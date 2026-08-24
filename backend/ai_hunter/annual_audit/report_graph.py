"""Annual full-audit subgraph plugged into the original chat orchestrator."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ai_hunter.app.graph.state import AuditGraphState

from .attachment_service import generate_annual_attachment_package
from .report_service import generate_annual_report_draft
from .generic_template_repository import get_active_template_catalog, template_version_ref


ATTACHMENT_TYPE_LABELS = {
    "annual_report": "年度审计报告",
    "financial_statements": "经审计的财务报表",
    "notes": "会计报表附注",
    "management_letter": "管理建议书",
}


def generate_annual_report_node(state: AuditGraphState) -> AuditGraphState:
    case_id = int(state.get("current_case_id") or 0)
    if case_id <= 0:
        return {
            "agent_output": "请先在当前对话中选择或创建一个年审项目，再生成完整年审报告。",
            "extracted_tasks": [],
        }
    route_decision = state.get("route_decision") or {}
    action = route_decision.get("action") if isinstance(route_decision, dict) else ""
    if action == "generate_attachments":
        try:
            package = generate_annual_attachment_package(
                case_id,
                created_by=str(state.get("operator_id") or "ai_agent"),
            )
        except ValueError as exc:
            return {
                "agent_output": f"暂时无法生成附件：{exc}。请先在年审模板管理中为相应模板版本上传实际文件并激活，然后回复“确认生成附件”。",
                "audit_review_stage": "awaiting_artifact_confirmation",
                "extracted_tasks": [],
            }
        versions = {
            key: str(value.get("version_label") or template_version_ref(value))
            for key, value in get_active_template_catalog().items()
        }
        artifact_lines = [
            f"- {ATTACHMENT_TYPE_LABELS.get(str(item.get('artifact_type') or ''), item.get('artifact_type'))}: "
            f"`{item.get('file_name')}`（模板 {item.get('template_version')}）"
            for item in package.get("artifacts") or []
        ]
        errors = package.get("errors") or []
        error_line = f"\n生成异常：{'；'.join(str(item) for item in errors)}" if errors else ""
        return {
            "agent_output": (
                f"已基于当前已激活的模板版本生成附件包 v{package.get('package_version', '-')}。\n"
                f"附件包状态：{package.get('status', 'failed')}。\n"
                + ("\n".join(artifact_lines) if artifact_lines else "未成功上传任何附件。")
                + error_line
                + "\n\n附件操作：请在本条回复下方对应文件点击“预览”或“下载”。"
                + "\n\n说明：以上成果仍属于审计交付草稿，正式签发前仍需完成项目组复核、复核层级审批和签字。"
            ),
            "attachment_package": package,
            "active_template_versions": versions,
            "audit_review_stage": "attachments_generated",
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
        "\n\n请先确认当前审计结果是否有问题：如有问题，请直接描述问题、补充资料或调整要求，我会继续执行审计；"
        "如没有问题，请回复“没有问题”，随后我会询问是否基于当前已激活的模板版本生成年度审计报告、财务报表、"
        "财务报表附注和管理建议书等交付附件。底稿、函证属于过程资料，不会随标准年审交付包自动生成。"
    )
    active_template_versions = dict(result.get("active_template_versions") or {})
    return {
        "agent_output": str(result.get("report_text") or "") + artifact_note,
        "artifacts": artifacts,
        "response_trace_candidates": list(result.get("response_trace_candidates") or []),
        "response_citation_coverage": dict(result.get("response_citation_coverage") or {}),
        "citation_entries": list(result.get("citation_entries") or []),
        "annual_report_manifest": dict(result.get("annual_report_manifest") or {}),
        "audit_review_stage": "awaiting_result_review",
        "active_template_versions": active_template_versions,
        "extracted_tasks": [],
    }


def _delivery_status_label(status: str) -> str:
    return {
        "draft_saved": "已保存可下载草稿，待复核和签发",
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
