import hashlib
import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, trim_messages
from langchain_core.messages.tool import ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from ...settings import get_settings
from ...response_safety import friendly_no_result_response, sanitize_user_response
from ..context_loader import (
    resolve_citation_coverage,
    resolve_final_report,
    resolve_trace_items,
    resolve_unresolved_graph_items,
)
from ..state import AuditGraphState
from ...repositories import get_conversation_message_repo


def _message_role(message: BaseMessage) -> str:
    """Map LangChain message objects to compact role labels."""
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, AIMessage):
        return "assistant"
    return "message"


def _message_line(message: BaseMessage) -> str:
    """Render one compact message line for memory summaries."""
    content = str(message.content).strip().replace("\n", " ")
    if len(content) > 160:
        content = f"{content[:160]}...(truncated)"
    return f"{_message_role(message)}: {content}"


def _merge_memory_summary(existing_summary: str, dropped_messages: list[BaseMessage]) -> str:
    """Fold dropped historical messages into a rolling plain-text summary."""
    settings = get_settings()
    new_lines = [_message_line(message) for message in dropped_messages if str(message.content).strip()]
    if not new_lines:
        return existing_summary

    parts = [part for part in (existing_summary.strip(), "\n".join(new_lines).strip()) if part]
    merged = "\n".join(parts)
    if len(merged) <= settings.langgraph_memory_summary_chars:
        return merged
    return f"...{merged[-settings.langgraph_memory_summary_chars + 3:]}"


def _render_recent_messages(messages: list[BaseMessage]) -> str:
    """Render the recent live message window as compact plain text."""
    return "\n".join(_message_line(message) for message in messages if str(message.content).strip())


def hydrate_memory_context(state: AuditGraphState) -> AuditGraphState:
    """Build memory_context from rolling summary plus a safe recent-message window."""
    settings = get_settings()
    messages = state.get("messages") or []
    memory_summary = (state.get("memory_summary") or "").strip()
    focus = dict(state.get("conversation_focus") or {})

    recent_messages = (
        trim_messages(
            messages,
            max_tokens=settings.langgraph_memory_max_tokens,
            token_counter="approximate",
            strategy="last",
            start_on="human",
            end_on=("human", "ai", "tool"),
            allow_partial=False,
        )
        if messages
        else []
    )
    recent_text = _render_recent_messages(recent_messages)
    parts = []
    if memory_summary:
        parts.append(f"[历史摘要]\n{memory_summary}")
    if focus:
        parts.append(
            "[当前会话焦点]\n"
            + json.dumps(focus, ensure_ascii=False, default=str)[:6000]
        )
    if recent_text:
        parts.append(f"[最近对话]\n{recent_text}")
    return {
        "memory_context": "\n\n".join(parts),
        "conversation_focus": focus,
    }


def persist_conversation_memory(state: AuditGraphState) -> AuditGraphState:
    """Append the current turn, trim history safely, and roll overflow into memory_summary."""
    query = (state.get("query") or "").strip()
    if not query:
        return {}

    settings = get_settings()
    existing_messages = list(state.get("messages") or [])
    existing_summary = (state.get("memory_summary") or "").strip()
    current_case_id = state.get("current_case_id", 0)
    final_report = resolve_final_report(state).strip()
    agent_output = (state.get("agent_output") or "").strip()
    intent = state.get("intent", "drilldown")

    full_answer = sanitize_user_response(
        final_report or agent_output or state.get("final_report_summary", ""),
        fallback=friendly_no_result_response(state),
    )
    # Keep the actual answer in model memory. A generic "analysis completed"
    # line destroys the object that a follow-up such as "这些结果" refers to.
    memory_answer = full_answer
    if len(memory_answer) > 2400:
        memory_answer = f"{memory_answer[:2400]}...(truncated)"

    # 本轮图谱关联快照：随 assistant 消息一起落库，使刷新历史会话时
    # 角标证据预览 / 覆盖率警告条 / 待补件 badge 不丢失（issue #8）。
    # 用与 /chat/invoke 同一批 resolver 取值，保证历史与首屏一致。
    unresolved_graph_items = resolve_unresolved_graph_items(state)
    assistant_graph_context = {
        "route_decision": state.get("route_decision") or {},
        "trace_items": resolve_trace_items(state),
        "citation_coverage": resolve_citation_coverage(state),
        # Keep the exact current-turn analysis scopes with the reply.  They
        # distinguish a response that deliberately found no data from legacy
        # prose that was generated before response-level evidence existed.
        "response_analysis_runs": list(state.get("response_analysis_runs") or []),
        "unresolved_relations": unresolved_graph_items.get("unresolved_relations", []),
        "unresolved_claims": unresolved_graph_items.get("unresolved_claims", []),
    }

    # Deterministic turn id.
    thread_id = state.get("thread_id", "")
    client_turn_id = (state.get("client_turn_id") or "").strip()
    if client_turn_id:
        turn_id = hashlib.sha256(
            f"{thread_id}:{client_turn_id}".encode()
        ).hexdigest()[:16]
    else:
        turn_id = hashlib.sha256(
            f"{query}:{current_case_id}:{intent}:{len(existing_messages)}".encode()
        ).hexdigest()[:16]

    regenerate = state.get("regenerate", False)
    repo = get_conversation_message_repo()

    if regenerate:
        # User clicked "regenerate": do NOT add another HumanMessage.
        # Replace the last AIMessage in the context so LLM memory stays clean.
        filtered_messages = list(existing_messages)
        if filtered_messages and isinstance(filtered_messages[-1], AIMessage):
            filtered_messages = filtered_messages[:-1]
        new_messages = [AIMessage(content=memory_answer)]
        complete_messages = filtered_messages + new_messages

        # Query current max version for this turn's assistant records
        assistant_version = repo.get_max_assistant_version(thread_id, f"{turn_id}_assistant") + 1

        # conversation_log keeps only the assistant entry (user is not duplicated)
        conversation_log_entries = [
            {
                "role": "assistant",
                "content": full_answer,
                "id": f"{turn_id}_assistant",
                "intent": intent,
                "case_id": current_case_id,
                "final_report_ref": state.get("final_report_ref", "") or "",
                "graph_context": assistant_graph_context,
                "version": assistant_version,
            },
        ]
    else:
        new_messages = [
            HumanMessage(content=query),
            AIMessage(content=memory_answer),
        ]
        complete_messages = existing_messages + new_messages
        conversation_log_entries = [
            {
                "role": "user",
                "content": query,
                "id": f"{turn_id}_user",
                "version": 1,
                "uploaded_files": list(state.get("uploaded_files") or []),
            },
            {
                "role": "assistant",
                "content": full_answer,
                "id": f"{turn_id}_assistant",
                "intent": intent,
                "case_id": current_case_id,
                "final_report_ref": state.get("final_report_ref", "") or "",
                "graph_context": assistant_graph_context,
                "version": 1,
            },
        ]
    trimmed_messages = trim_messages(
        complete_messages,
        max_tokens=settings.langgraph_memory_max_tokens,
        token_counter="approximate",
        strategy="last",
        start_on="human",
        end_on=("human", "ai", "tool"),
        allow_partial=False,
    )
    dropped_count = max(0, len(complete_messages) - len(trimmed_messages))
    dropped_messages = complete_messages[:dropped_count]
    memory_summary = _merge_memory_summary(existing_summary, dropped_messages)
    route_decision = state.get("route_decision") or {}
    if hasattr(route_decision, "model_dump"):
        route_decision = route_decision.model_dump()
    conversation_focus = {
        "case_id": current_case_id,
        "last_user_query": query[:1200],
        "last_assistant_answer": full_answer[:2400],
        "last_route_decision": route_decision if isinstance(route_decision, dict) else {},
        "last_capability": (
            str(route_decision.get("capability") or "")
            if isinstance(route_decision, dict)
            else ""
        ),
        "report_exists": bool(
            final_report
            or state.get("final_report_ref")
            or state.get("final_report_summary")
        ),
        "final_report_ref": str(state.get("final_report_ref") or ""),
        "citation_coverage": resolve_citation_coverage(state),
        "unresolved_item_count": (
            len(unresolved_graph_items.get("unresolved_relations", []))
            + len(unresolved_graph_items.get("unresolved_claims", []))
        ),
    }

    # Append to existing conversation_log instead of overwriting
    existing_conv_log = list(state.get("conversation_log") or [])

    # ------------------------------------------------------------------
    # Unified write to the dedicated conversation_messages table.
    # This happens *before* returning state so that a failure here raises
    # inside the node → LangGraph never merges this state update → the
    # checkpointer stays consistent.  ON CONFLICT DO NOTHING makes it safe
    # for retries.
    # ------------------------------------------------------------------
    thread_id = state.get("thread_id", "")
    if thread_id:
        get_conversation_message_repo().append_messages(
            thread_id,
            conversation_log_entries,
        )

    return {
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *trimmed_messages],
        "memory_summary": memory_summary,
        "conversation_focus": conversation_focus,
        "conversation_log": existing_conv_log + conversation_log_entries,
        # The browser receives this exact persisted id in the SSE final event,
        # so it can attach the response-specific report reference to the
        # streaming assistant message without waiting for a refresh.
        "assistant_message_id": f"{turn_id}_assistant",
    }
