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
    artifact_status = str(artifacts.get("status") or "not_published")
    task_result = artifacts.get("tasks") or {}
    artifact_note = (
        f"\n\n---\n已保存报告草稿 v{report.get('version', '-')}；"
        f"工作底稿版本：{workpaper_versions or '-'}。"
    )
    artifact_note += (
        f"\n交付状态：{_delivery_status_label(artifact_status)}；"
        f"已生成后续复核任务 {int(task_result.get('created_count') or 0)} 项。"
        "\n说明：当前自动化范围主要覆盖 F1-2 营业收入、C5-2 应收账款和 "
        "C1-2 货币资金/银行流水，属于完整年审的一部分，不等同于正式审计报告。"
        "完成正式签发前，还需补齐全套资料、其余审计循环、函证或替代程序、"
        "差异与重大事项结论以及三级复核和签字。"
    )
    return {
        "agent_output": str(result.get("report_text") or "") + artifact_note,
        "artifacts": artifacts,
        "extracted_tasks": [],
    }


def _delivery_status_label(status: str) -> str:
    return {
        "published": "已生成可下载成果",
        "draft": "草稿，待复核",
        "not_published": "草稿，待复核",
    }.get(status, "草稿，待复核")


def build_annual_report_graph():
    graph = StateGraph(AuditGraphState)
    graph.add_node("generate_annual_report", generate_annual_report_node)
    graph.add_edge(START, "generate_annual_report")
    graph.add_edge("generate_annual_report", END)
    return graph.compile()


__all__ = ["build_annual_report_graph", "generate_annual_report_node"]
