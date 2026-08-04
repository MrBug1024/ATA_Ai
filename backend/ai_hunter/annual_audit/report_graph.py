"""Annual full-audit subgraph plugged into the original chat orchestrator."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ai_hunter.app.graph.state import AuditGraphState

from .report_service import generate_annual_report_draft


def generate_annual_report_node(state: AuditGraphState) -> AuditGraphState:
    case_id = int(state.get("current_case_id") or 0)
    if case_id <= 0:
        return {
            "agent_output": "请先在当前对话中选择或创建一个年审项目，再生成完整年审报告。",
            "extracted_tasks": [],
        }
    corrections = [str(item) for item in (state.get("user_corrections") or []) if str(item).strip()]
    result = generate_annual_report_draft(
        case_id,
        recompute=bool(corrections or state.get("regenerate")),
        corrections=corrections,
        material_sources=list(state.get("case_material_sources") or []),
        created_by=str(state.get("operator_id") or "ai_agent"),
    )
    artifacts = result.get("artifacts") or {}
    report = artifacts.get("report") or {}
    workpapers = artifacts.get("workpapers") or []
    workpaper_versions = ", ".join(
        f"{item.get('code')} v{item.get('version')}" for item in workpapers
    )
    artifact_note = (
        f"\n\n---\n已保存报告草稿 v{report.get('version', '-')}；"
        f"工作底稿版本：{workpaper_versions or '-'}。"
    )
    return {
        "agent_output": str(result.get("report_text") or "") + artifact_note,
        "extracted_tasks": [],
    }


def build_annual_report_graph():
    graph = StateGraph(AuditGraphState)
    graph.add_node("generate_annual_report", generate_annual_report_node)
    graph.add_edge(START, "generate_annual_report")
    graph.add_edge("generate_annual_report", END)
    return graph.compile()


__all__ = ["build_annual_report_graph", "generate_annual_report_node"]
