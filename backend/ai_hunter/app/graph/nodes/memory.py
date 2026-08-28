import hashlib

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
    if not messages:
        return {"memory_context": memory_summary}

    recent_messages = trim_messages(
        messages,
        max_tokens=settings.langgraph_memory_max_tokens,
        token_counter="approximate",
        strategy="last",
        start_on="human",
        end_on=("human", "ai", "tool"),
        allow_partial=False,
    )
    recent_text = _render_recent_messages(recent_messages)
    parts = []
    if memory_summary:
        parts.append(f"[历史摘要]\n{memory_summary}")
    if recent_text:
        parts.append(f"[最近对话]\n{recent_text}")
    return {"memory_context": "\n\n".join(parts)}


def persist_conversation_memory(state: AuditGraphState) -> AuditGraphState:
    """Append the current turn, trim history safely, and roll overflow into memory_summary."""
    query = (state.get("query") or "").strip()
    if not query:
        return {}

    settings = get_settings()
    existing_messages = list(state.get("messages") or [])
    existing_summary = (state.get("memory_summary") or "").strip()
    current_case_id = state.get("current_case_id", 0)
    parse_summary = (state.get("parse_summary") or "").strip()
    final_report = resolve_final_report(state).strip()
    agent_output = (state.get("agent_output") or "").strip()
    intent = state.get("intent", "drilldown")

    if final_report:
        summary_line = "已生成本轮审计结果。"
    elif agent_output:
        summary_line = "已完成本轮分析并返回结果。"
    elif parse_summary:
        summary_line = "已完成本轮资料处理。"
    else:
        summary_line = "本轮未形成可展示的结果。"

    # ``summary_line`` is only the compact LLM-memory message.  It must never
    # be used as the display/history answer: doing so previously leaked values
    # such as ``intent=... | case_id=... | report_generated chars=...``.
    full_answer = sanitize_user_response(
        final_report or agent_output or state.get("final_report_summary", ""),
        fallback=friendly_no_result_response(state),
    )

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
        "audit_review_stage": str(state.get("audit_review_stage") or ""),
        "active_template_versions": dict(state.get("active_template_versions") or {}),
        # Persist only the user-facing attachment projection.  Storage refs
        # and template snapshots are server-side details; the chat history
        # needs the same preview/download actions after a page reload.
        "attachment_package": {
            "package_id": (state.get("attachment_package") or {}).get("package_id"),
            "package_version": (state.get("attachment_package") or {}).get("package_version"),
            "status": (state.get("attachment_package") or {}).get("status") or "",
            "errors": list((state.get("attachment_package") or {}).get("errors") or []),
            "artifacts": [
                {
                    key: item.get(key)
                    for key in (
                        "artifact_type",
                        "file_name",
                        "template_version",
                        "template_fill_status",
                        "output_file_ext",
                        "result_placement",
                        "format_validation",
                        "audit_result_included",
                        "download_url",
                        "preview_url",
                    )
                    if item.get(key) is not None
                }
                for item in ((state.get("attachment_package") or {}).get("artifacts") or [])
                if isinstance(item, dict)
            ],
        },
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
        new_messages = [AIMessage(content=summary_line)]
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
            AIMessage(content=summary_line),
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
        "conversation_log": existing_conv_log + conversation_log_entries,
        # The browser receives this exact persisted id in the SSE final event,
        # so it can attach the response-specific report reference to the
        # streaming assistant message without waiting for a refresh.
        "assistant_message_id": f"{turn_id}_assistant",
    }
