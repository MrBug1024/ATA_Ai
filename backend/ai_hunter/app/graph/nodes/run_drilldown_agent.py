"""Run the drilldown/task agent as a Runnable so token streams are visible to astream_events."""

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.tool import ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.managed.is_last_step import RemainingSteps
from langgraph.prebuilt import create_react_agent
from typing_extensions import TypedDict

from ..context_loader import resolve_full_context_data, resolve_kg_snapshot, resolve_report_part_b
from ..json_utils import json_dumps_safe
from ..llm import build_agent_llm, has_api_key
from ..prompting import load_prompt
from ..state import AuditGraphState
from ...settings import get_settings
from ...tools.registry import tools_for_capability


LOGGER = logging.getLogger(__name__)


# These are deliberately explicit rather than inferred from an assistant's
# prose.  A citation/evidence resolver must only see analysis runs that this
# ReAct invocation actually executed.
_ANALYSIS_TOOL_TYPES = {
    "analyze_sales_receivables": "sales_receivables",
    "analyze_cash_and_bank": "cash_and_bank",
}
_EVIDENCE_TOOL_NAMES = frozenset({"search_annual_evidence"})


class DrilldownAgentState(AuditGraphState, total=False):
    """Agent-only state adds LangGraph's managed recursion budget."""

    remaining_steps: RemainingSteps


def _agent_recursion_limit() -> int:
    """Bound one ReAct subgraph independently from the top-level graph."""
    return max(4, int(get_settings().agent_recursion_limit))


def _truncate_text(text: str, max_chars: int = 800) -> str:
    """Clip long prompt fragments so drilldown context stays compact."""
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars]}...(truncated)"


def _list_count(value: object) -> int:
    """Return list length for common array-like values."""
    if isinstance(value, list):
        return len(value)
    return 0


def _build_case_snapshot(state: AuditGraphState) -> str:
    """Build a compact engagement snapshot for the annual-audit agent."""
    full_context = resolve_full_context_data(state)
    if not isinstance(full_context, dict):
        return _truncate_text(str(state.get("full_context_summary") or "{}"), max_chars=600)

    return json_dumps_safe(
        {
            "engagement_id": state.get("current_case_id", 0),
            "engagement": full_context.get("annual_audit")
            or full_context.get("case")
            or full_context,
            "data_completeness": full_context.get("data_completeness") or {},
            "available_analysis_results": list(
                (full_context.get("engine_results") or {}).keys()
            )[:8]
            if isinstance(full_context.get("engine_results"), dict)
            else [],
        }
    )


def _build_correction_block(state: AuditGraphState) -> str:
    """Render corrections in a compact but high-priority prompt block."""
    correction_records = state.get("correction_records") or []
    if not correction_records:
        return "无修正台账。"

    lines: list[str] = []
    for item in correction_records[:8]:
        if isinstance(item, dict):
            target = item.get("target", "")
            instruction = item.get("instruction", "")
            source_query = item.get("source_query", "")
            lines.append(
                f"- 标的: {target or '未标注'} | 指令: {instruction or '未标注'} | 来源: {source_query or '未标注'}"
            )
        else:
            lines.append(f"- {str(item)}")
    if len(correction_records) > 8:
        lines.append(f"- 其余 {len(correction_records) - 8} 条修正已省略，请按最新修正优先。")
    return "\n".join(lines)


def _build_system_prompt(
    state: AuditGraphState,
    *,
    prompt_name: str = "annual_audit_drilldown_agent.txt",
) -> list:
    """Assemble the lightweight drilldown system prompt with correction priority last.

    Returns a list of messages used directly as the prompt callable for
    create_react_agent: a SystemMessage carrying instructions + case context,
    followed by the conversation messages (history + the current user turn,
    injected by ``_inject_current_query`` before the agent runs).

    NOTE: create_react_agent's callable-prompt path (``_get_prompt_runnable``)
    does NOT auto-append ``state["messages"]`` — whatever this returns IS the
    full message list sent to the model. So we must append them ourselves,
    otherwise the agent never sees the user's actual question and falls back to
    emitting a generic drilldown menu.
    """
    prompt = load_prompt(prompt_name)
    case_id = state.get("current_case_id", 0)
    memory_context = _truncate_text(state.get("memory_context", ""), max_chars=1200) or "无"
    case_snapshot = _build_case_snapshot(state) or "{}"
    kg_snapshot = _truncate_text(
        json_dumps_safe(resolve_kg_snapshot(state)),
        max_chars=1400,
    ) or "无"
    report_part_b = _truncate_text(resolve_report_part_b(state), max_chars=1600) or "无"
    correction_block = _build_correction_block(state)
    parse_summary = _truncate_text(state.get("parse_summary", ""), max_chars=300) or "无"
    route_decision = state.get("route_decision") or {}

    content = (
        f"{prompt}\n\n"
        f"当前年审项目编号: {case_id}\n"
        f"最近资料解析摘要:\n{parse_summary}\n\n"
        f"本轮路由约束:\n{json_dumps_safe(route_decision)}\n"
        "只能处理该 capability 范围内的请求；信息不足时直接询问，不得猜测。\n\n"
        f"历史轻量记忆:\n{memory_context}\n\n"
        f"当前年审项目摘要:\n{case_snapshot}\n\n"
        f"当前证据与关系图谱摘要:\n{kg_snapshot}\n\n"
        f"已有年审报告/底稿下钻索引:\n{report_part_b}\n\n"
        f"用户更正记录（最高优先级）:\n{correction_block}"
    )
    return [SystemMessage(content=content), *(state.get("messages") or [])]


def _inject_current_query(state: AuditGraphState) -> AuditGraphState:
    """Append the current-turn query to ``messages`` before the ReAct agent runs.

    The query lives only in ``state["query"]`` during the turn — it is not added
    to ``messages`` until ``persist_conversation_memory`` at the very end. Without
    this, the drilldown agent's prompt would carry case context but not the actual
    question. Injecting it into the persistent message list (rather than appending
    in the per-loop prompt callable) keeps it positioned before the agent's
    tool-call/tool-result messages across ReAct iterations, so it is not
    re-presented after tool results and does not trigger duplicate tool calls.

    Dedup / regenerate: on a "regenerate" turn the same query is already the most
    recent HumanMessage in history (followed by the stale assistant turn being
    regenerated). Rather than appending a duplicate, drop everything after that
    HumanMessage so the query stays the effective last turn for the agent to
    re-answer. Only the agent's input view is affected — the node still returns
    just ``agent_output``, so main-graph ``messages`` are untouched.
    """
    query = (state.get("query") or "").strip()
    if not query:
        return state
    messages = list(state.get("messages") or [])

    last_human_idx = next(
        (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
        None,
    )
    if last_human_idx is not None and str(messages[last_human_idx].content).strip() == query:
        return {**state, "messages": messages[: last_human_idx + 1]}

    messages.append(HumanMessage(content=query))
    return {**state, "messages": messages}


def _current_turn_tool_messages(messages: list[Any]) -> list[ToolMessage]:
    """Return ToolMessages emitted after the current query in this agent run.

    The prompt contains compact conversation history.  Retaining a historical
    ToolMessage here would make the next answer appear to have executed an old
    analysis run, so the last HumanMessage is the strict current-turn boundary.
    A direct unit invocation may not include a HumanMessage; in that case its
    supplied ToolMessages are the complete response scope.
    """

    last_human_index = max(
        (index for index, message in enumerate(messages) if isinstance(message, HumanMessage)),
        default=-1,
    )
    return [
        message
        for message in messages[last_human_index + 1 :]
        if isinstance(message, ToolMessage)
    ]


def _tool_name(message: ToolMessage) -> str:
    """Read the exact registered tool name without inspecting result prose."""

    name = getattr(message, "name", "")
    if isinstance(name, str) and name.strip():
        return name.strip()
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    fallback_name = additional_kwargs.get("name") if isinstance(additional_kwargs, dict) else ""
    return fallback_name.strip() if isinstance(fallback_name, str) else ""


def _successful_tool_envelope(message: ToolMessage) -> dict[str, Any] | None:
    """Parse a successful ``build_tool_result`` envelope from one ToolMessage.

    Tool errors use the same envelope shape but place ``error`` in
    ``key_facts``.  They are intentionally excluded: a failed tool call is not
    an evidence or analysis scope for the visible answer.
    """

    if not isinstance(message.content, str):
        return None
    try:
        envelope = json.loads(message.content)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, dict):
        return None
    key_facts = envelope.get("key_facts")
    if not isinstance(key_facts, dict):
        return None
    if envelope.get("error") or envelope.get("success") is False or key_facts.get("error"):
        return None
    return envelope


def _positive_int(value: Any) -> int | None:
    """Accept only a positive integral JSON value for a persisted run id."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _extract_agent_output(response: dict, *, capability: str = "") -> dict:
    """Pull final output and exact current-tool execution scope from an agent run."""

    messages = list(response.get("messages") or [])
    current_tool_messages = _current_turn_tool_messages(messages)
    analysis_runs: list[dict[str, Any]] = []
    evidence_tool_results: list[dict[str, Any]] = []

    for message in current_tool_messages:
        tool_name = _tool_name(message)
        envelope = _successful_tool_envelope(message)
        if not tool_name or envelope is None:
            continue
        key_facts = envelope["key_facts"]

        expected_analysis_type = _ANALYSIS_TOOL_TYPES.get(tool_name)
        if expected_analysis_type:
            analysis_type = key_facts.get("analysis_type")
            analysis_run_id = _positive_int(key_facts.get("analysis_run_id"))
            # The tool name and the type returned by its structured result must
            # agree.  Do not infer either value from the assistant response.
            if analysis_type == expected_analysis_type and analysis_run_id is not None:
                analysis_runs.append(
                    {
                        "tool_name": tool_name,
                        "analysis_type": analysis_type,
                        "analysis_run_id": analysis_run_id,
                    }
                )
            continue

        if tool_name in _EVIDENCE_TOOL_NAMES:
            # Keep the direct, de-hydrated tool result as-is for a downstream
            # evidence resolver.  This is distinct from a graph-wide/latest
            # lookup and cannot inherit evidence from another turn.
            evidence_tool_results.append(
                {
                    "tool_name": tool_name,
                    "key_facts": key_facts,
                    "truncated": bool(envelope.get("truncated")),
                }
            )

    if capability == "audit.drilldown":
        successful_tool_count = sum(
            _successful_tool_envelope(message) is not None
            for message in current_tool_messages
        )
        if successful_tool_count == 0:
            return {
                "agent_output": (
                    "本轮未取得可核验的项目资料或分析结果，因此不能形成审计事实、风险结论或金额判断。"
                    "请先确认年审项目存在且已导入相应资料后，再执行下钻分析。"
                ),
                "business_line_result": {
                    "capability": capability,
                    "ok": False,
                    "error": "no_successful_audit_tool_result",
                },
                "response_analysis_runs": [],
                "response_evidence_tool_results": [],
            }

    if messages:
        return {
            "agent_output": str(messages[-1].content).strip(),
            "response_analysis_runs": analysis_runs,
            "response_evidence_tool_results": evidence_tool_results,
        }
    LOGGER.warning("drilldown_agent_empty_response")
    return {
        "agent_output": "",
        "response_analysis_runs": [],
        "response_evidence_tool_results": [],
    }


def _fallback_agent_output(state: AuditGraphState) -> dict:
    """Placeholder when the agent cannot run."""
    case_id = state.get("current_case_id", 0)
    query = state.get("query", "")
    memory_context = state.get("memory_context", "")
    report_part_b = resolve_report_part_b(state)
    return {
        "agent_output": (
            f"【年审分析暂不可用】\n项目编号={case_id}\n问题={query}\n"
            f"memory_context={memory_context[:200]}\n"
            f"case_snapshot={_build_case_snapshot(state)[:200]}\n"
            f"kg_summary={resolve_kg_snapshot(state).get('summary', '')[:200]}\n"
            f"report_part_b={report_part_b[:200]}\n"
            "当前模型不可用，请稍后重试；本轮未写入任何分析结论。"
        )
    }


DOMAIN_AGENT_PROMPTS = {
    "audit.drilldown": "annual_audit_drilldown_agent.txt",
    "graph.query": "annual_audit_graph_agent.txt",
}


def _fallback_domain_agent_output(state: AuditGraphState, capability: str) -> dict:
    labels = {
        "audit.drilldown": "审计下钻",
        "graph.query": "图谱查询",
    }
    label = labels.get(capability, "领域分析")
    return {
        "agent_output": (
            f"【{label}降级结果】\n"
            f"年审项目编号：{state.get('current_case_id', 0)}\n"
            f"问题：{state.get('query', '')}\n"
            "当前领域模型不可用，未执行工具调用，请稍后重试。"
        ),
        "business_line_result": {
            "capability": capability,
            "ok": False,
            "degraded": True,
            "error": "agent_model_unavailable",
            "tool_calls": [],
        },
    }


def _runtime_fallback_domain_agent_output(state: AuditGraphState, capability: str) -> dict:
    """Return a fact-grounded result when a configured model fails at runtime.

    A valid API key only proves that an agent can be constructed.  The provider
    can still be unreachable when the request is executed.  Annual-audit
    drilldown has deterministic implementations for the same core cycles, so
    keep the business route usable and make the degraded nature explicit.
    """
    if capability != "audit.drilldown":
        return _fallback_domain_agent_output(state, capability)

    case_id = int(state.get("current_case_id") or 0)
    if case_id <= 0:
        return _fallback_domain_agent_output(state, capability)

    try:
        from ....annual_audit.analysis_service import (
            data_readiness,
            run_cash_and_bank,
            run_sales_receivables,
        )
        from ....annual_audit.engagement_repository import get_engagement
        from ....annual_audit.report_service import render_annual_report_draft

        engagement = get_engagement(case_id)
        readiness = data_readiness(case_id)
        sales = run_sales_receivables(case_id)
        cash = run_cash_and_bank(case_id)
        report = render_annual_report_draft(
            engagement=engagement,
            readiness=readiness,
            sales_receivables=sales,
            cash_and_bank=cash,
            material_sources=list(state.get("case_material_sources") or []),
        )
        output = (
            "> 当前模型服务不可连接；以下内容由本地结构化数据与确定性规则生成，"
            "未使用模型推断。模型恢复后可重新生成补充语义分析。\n\n"
            f"{report}"
        )
    except Exception as exc:
        LOGGER.exception(
            "domain_agent_runtime_fallback_failed capability=%s case_id=%s error=%s",
            capability,
            case_id,
            exc,
        )
        return _fallback_domain_agent_output(state, capability)

    return {
        "agent_output": output,
        "business_line_result": {
            "capability": capability,
            "ok": False,
            "degraded": True,
            "error": "agent_model_runtime_unavailable",
            "tool_calls": [
                "get_annual_engagement",
                "analyze_annual_data_readiness",
                "analyze_sales_receivables",
                "analyze_cash_and_bank",
            ],
        },
    }


def _build_scoped_agent(
    llm,
    capability: str,
    *,
    prompt_name: str = "annual_audit_drilldown_agent.txt",
):
    def prompt(state: AuditGraphState) -> list:
        return _build_system_prompt(state, prompt_name=prompt_name)

    agent = create_react_agent(
        llm,
        tools_for_capability(capability),
        prompt=prompt,
        state_schema=DrilldownAgentState,
    ).with_config({"recursion_limit": _agent_recursion_limit()})
    return RunnableLambda(_inject_current_query) | agent | RunnableLambda(
        lambda response: _extract_agent_output(response, capability=capability)
    )


def build_capability_agent_node(capability: str):
    """Build one fixed-capability domain agent for a business-line subgraph."""
    prompt_name = DOMAIN_AGENT_PROMPTS.get(capability)
    if not prompt_name:
        raise ValueError(f"unsupported domain agent capability: {capability}")
    try:
        llm = build_agent_llm()
        if not has_api_key(llm):
            LOGGER.warning("domain_agent_no_api_key capability=%s; falling back", capability)
            return RunnableLambda(lambda state: _fallback_domain_agent_output(state, capability))
    except Exception as exc:
        LOGGER.warning("domain_agent_build_failed capability=%s error=%s; falling back", capability, exc)
        return RunnableLambda(lambda state: _fallback_domain_agent_output(state, capability))
    agent = _build_scoped_agent(llm, capability, prompt_name=prompt_name)
    return agent.with_fallbacks(
        [RunnableLambda(lambda state: _runtime_fallback_domain_agent_output(state, capability))]
    )
