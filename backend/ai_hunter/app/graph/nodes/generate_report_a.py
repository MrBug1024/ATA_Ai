"""Generate the first half of the audit report as a Runnable chain."""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from ...settings import get_settings
from ..context_loader import build_inline_citation_catalog, resolve_report_full_context_json, resolve_kg_snapshot
from ..heavy_state import put_heavy_payload
from ..json_utils import json_dumps_safe
from ..llm import build_report_a_llm
from ..prompting import load_prompt
from ..state import AuditGraphState


def _prepare_messages_and_state(state: AuditGraphState) -> dict:
    """Build messages and pass original state through the chain."""
    case_id = state.get("current_case_id", 0)
    corrections = state.get("user_corrections", [])
    correction_text = "\n".join(corrections) if corrections else "无修正，按原始 JSON 执行。"
    full_context_json = resolve_report_full_context_json(state)
    kg_snapshot_json = json_dumps_safe(resolve_kg_snapshot(state))
    citation_catalog = build_inline_citation_catalog(state)
    prompt = load_prompt("report_part_a.txt")
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(
            content=(
                f"案件ID: {case_id}\n"
                f"用户修正台账:\n{correction_text}\n\n"
                f"底层脱水 JSON:\n{full_context_json}\n\n"
                f"知识图谱轻量摘要:\n{kg_snapshot_json}\n\n"
                f"可引用断言角标清单:\n{citation_catalog}"
            )
        ),
    ]
    return {"messages": messages, "state": state}


def _post_process_report_a(inputs: dict) -> dict:
    """Persist the LLM response to heavy payload store."""
    response = inputs["response"]
    report_part_a = str(response.content).strip()
    return {
        "report_part_a_ref": put_heavy_payload("report_part_a", {"text": report_part_a}),
        "report_part_a_summary": report_part_a[:240],
        "report_part_a": "",
    }


def _fallback_report_a(state: AuditGraphState) -> dict:
    """Deterministic placeholder when LLM is unavailable."""
    case_id = state.get("current_case_id", 0)
    corrections = state.get("user_corrections", [])
    correction_text = "\n".join(corrections) if corrections else "无修正，按原始 JSON 执行。"
    placeholder = (
        f"【报告前4段占位】\n案件ID: {case_id}\n"
        f"用户修正台账:\n{correction_text}\n"
        f"知识图谱摘要: {resolve_kg_snapshot(state).get('summary', '无')}\n"
        "这里将接入 report_part_a prompt 和模型。"
    )
    return {
        "report_part_a_ref": put_heavy_payload("report_part_a", {"text": placeholder}),
        "report_part_a_summary": placeholder[:240],
        "report_part_a": "",
    }


def build_report_part_a_node():
    """Build a Runnable node so astream_events can穿透 the LLM token stream."""
    settings = get_settings()
    if not settings.get_llm_config("report_a")["api_key"]:
        return RunnableLambda(_fallback_report_a)

    llm = build_report_a_llm()
    return (
        RunnableLambda(_prepare_messages_and_state)
        | RunnableLambda(lambda x: x["messages"])
        | llm
        | RunnableLambda(lambda response: {"response": response})
        | RunnableLambda(_post_process_report_a)
    )


# Legacy function kept for non-streaming invoke paths
def generate_report_part_a(state: AuditGraphState) -> AuditGraphState:
    """Render part A from prompt + full context, or fall back to a deterministic placeholder."""
    return build_report_part_a_node().invoke(state)
