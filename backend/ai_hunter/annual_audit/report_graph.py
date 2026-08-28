"""Annual full-audit subgraph plugged into the original chat orchestrator."""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from ai_hunter.app.graph.state import AuditGraphState

from .attachment_service import generate_annual_attachment_package
from .file_attachment_service import plan_annual_attachment_package
from .report_service import generate_annual_report_draft
from .generic_template_repository import template_version_ref


LOGGER = logging.getLogger(__name__)


ATTACHMENT_TYPE_LABELS = {
    "annual_report": "年度审计报告",
    "financial_statements": "年度审计财务报表",
    "notes": "财务报表附注",
        "management_letter": "管理建议书（可选）",
    "audit_workpaper": "审计工作底稿",
    "confirmations": "函证",
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
    if action == "prepare_attachments":
        try:
            plan = plan_annual_attachment_package(case_id)
        except Exception:
            LOGGER.exception("annual_attachment_preflight_failed case_id=%s", case_id)
            return {
                "agent_output": (
                    "附件生成前置检查未能完成，原因可能是模板文件或项目资料暂时不可用。\n\n"
                    "系统尚未生成任何附件。请检查已激活的模板和项目资料后，再回复“确认生成附件”。"
                ),
                "audit_review_stage": "awaiting_artifact_confirmation",
                "attachment_preflight": {},
                "extracted_tasks": [],
            }
        summary = plan.get("summary") or {}
        template_lines = []
        for item in plan.get("templates") or []:
            status = "通过" if item.get("status") == "ready" else "阻断"
            template_lines.append(
                f"- {item.get('template_type')}：{item.get('file_name')}；"
                f"结构 {item.get('structure', {}).get('paragraph_count', item.get('structure', {}).get('sheet_count', '-'))} 段/表；"
                f"识别字段 {len(item.get('fields') or [])} 个，已映射 {sum(field.get('status') == 'mapped' for field in item.get('fields') or [])} 个；"
                f"主底稿标签命中 {item.get('matched_material_label_count', 0)}；门禁：{status}"
            )
        blockers = list(plan.get("blockers") or [])
        blocker_text = (
            "\n\n**当前阻断项**：\n" + "\n".join(f"- {item}" for item in blockers[:12])
            if blockers
            else ""
        )
        if blockers:
            return {
                "agent_output": (
                    "已完成附件生成前置检查，但当前模板/资料映射未通过，系统不会生成附件。\n\n"
                    f"主底稿读取：{summary.get('main_workpaper_sheet_count', 0)} 个工作表、"
                    f"{summary.get('main_workpaper_nonempty_rows', 0)} 行非空数据。\n\n"
                    + ("\n".join(template_lines) if template_lines else "未找到有效模板文件")
                    + blocker_text
                    + "\n\n请修正门禁后重新回复“确认生成附件”。"
                ),
                "audit_review_stage": "awaiting_artifact_confirmation",
                "attachment_preflight": plan,
                "active_template_versions": {
                    item.get("template_type"): item.get("template_version")
                    for item in plan.get("templates") or []
                    if item.get("template_type") and item.get("template_version")
                },
                "extracted_tasks": [],
            }
        return {
            "agent_output": (
                "已完成模板解析和资料映射，尚未生成附件。\n\n"
                f"主底稿读取：{summary.get('main_workpaper_sheet_count', 0)} 个工作表、"
                f"{summary.get('main_workpaper_nonempty_rows', 0)} 行非空数据。\n\n"
                + "\n".join(template_lines)
                + "\n\n系统将只把已映射的数据写入模板定义的段落/表格位置，并对生成文件执行格式、字段和分页校验。"
                "请回复“确认按映射生成附件”后，系统才开始生成三份文件。"
            ),
            "audit_review_stage": "awaiting_attachment_generation_confirmation",
            "attachment_preflight": plan,
            "active_template_versions": {
                item.get("template_type"): item.get("template_version")
                for item in plan.get("templates") or []
                if item.get("template_type") and item.get("template_version")
            },
            "extracted_tasks": [],
        }

    if action == "generate_attachments":
        try:
            package = generate_annual_attachment_package(
                case_id,
                created_by=str(state.get("operator_id") or "ai_agent"),
                preflight_plan=dict(state.get("attachment_preflight") or {}),
            )
        except ValueError:
            LOGGER.exception("annual_attachment_generation_blocked case_id=%s", case_id)
            return {
                "agent_output": (
                    "暂时无法生成附件，原因是当前模板或资料未通过生成校验。\n\n"
                    "请在「管理 → 模板管理」中为对应用途上传实际模板文件并激活；\n"
                    "文件格式不固定，系统会按每个已激活模板的实际扩展名和容器格式生成交付附件，\n"
                    "不会把 .xlsx/.xls/.md/.pdf 等模板统一转换成 .docx。\n\n"
                    "激活后回复“确认生成附件”即可重新生成。"
                ),
                "audit_review_stage": "awaiting_artifact_confirmation",
                "attachment_preflight": dict(state.get("attachment_preflight") or {}),
                "extracted_tasks": [],
            }
        versions = {
            key: str(value.get("version_label") or template_version_ref(value))
            for key, value in (package.get("template_snapshot") or {}).items()
            if isinstance(value, dict)
        }
        artifact_lines = [
            f"- {ATTACHMENT_TYPE_LABELS.get(str(item.get('artifact_type') or ''), item.get('artifact_type'))}: "
            f"`{item.get('file_name')}`（模板 {item.get('template_version')}；"
            f"格式校验：{'通过' if (item.get('format_validation') or {}).get('signature_valid') else '待核验'}）"
            for item in package.get("artifacts") or []
        ]
        errors = package.get("errors") or []
        error_line = (
            f"\n\n**生成提示**：有 {len(errors)} 个附件未完成生成或校验，"
            "请检查对应模板和项目资料后重试。"
            if errors
            else ""
        )
        success_count = len(package.get("artifacts") or [])
        return {
            "agent_output": (
                f"已基于当前已激活的模板版本生成附件包 v{package.get('package_version', '-')}。\n"
                f"附件包状态：{package.get('status', 'failed')}（共 {success_count} 个附件）。\n\n"
                "**交付附件清单**：\n"
                + ("\n".join(artifact_lines) if artifact_lines else "未成功上传任何附件。")
                + error_line
                + "\n\n---\n"
                "附件操作：请在本条回复下方对应文件点击“预览”或“下载”。\n\n"
                "**说明**：\n"
                "- 以上成果属于审计交付草稿，正式签发前仍需完成项目组复核、复核层级审批和签字。\n"
                "- 如需重新生成（例如修正了模板或补充了资料），请回复“重新生成附件”。\n"
                "- 如需补充生成审计工作底稿或函证等过程资料，请回复“生成工作底稿”或“生成函证”。"
            ),
            "attachment_package": package,
            "attachment_preflight": {},
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
        f"\n\n---\n**审计结果已保存**\n"
        f"- 报告草稿版本：v{report.get('version', '-')}；\n"
        f"- 工作底稿版本：{workpaper_versions or '-'}；\n"
        f"- 交付状态：{_delivery_status_label(artifact_status)}；\n"
        f"- 已生成后续复核任务 {int(task_result.get('created_count') or 0)} 项。"
    )
    case_pack_complete = "案例主底稿全量回放" in str(result.get("report_text") or "")
    artifact_note += (
        "\n\n**当前自动化审计范围说明**：\n"
        + (
            "本次为完整案例主底稿回放：系统已读取主底稿全部工作表，并将主底稿证据绑定到受控程序；"
            "F1-2、C5-2、C1-2 为结构化分析展示，不代表只执行了这三条线。正式签发仍须由有资格的项目组完成复核和签字。"
            if case_pack_complete
            else "当前自动化范围主要覆盖 F1-2 营业收入、C5-2 应收账款和 C1-2 货币资金/银行流水，属于完整年审的一部分，不等同于正式审计报告。"
        )
        + "\n\n---\n"
        "**请确认当前审计结果**：\n"
        "- ✅ 如果审计结果**没有问题**，请回复“**没有问题**”，我将询问是否基于当前已激活的模板版本生成年度审计报告、财务报表、"
        "财务报表附注等核心交付附件。管理建议书需单独配置模板后按需生成。\n"
        "- ❌ 如果审计结果**有问题**或需要补充审计，请直接描述问题、补充资料或调整要求，我会继续执行审计。"
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
