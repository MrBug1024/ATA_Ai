"""Annual full-audit subgraph plugged into the original chat orchestrator."""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from ai_hunter.app.graph.state import AuditGraphState
from ai_hunter.app.graph.turn_identity import derive_assistant_message_id
from ai_hunter.app.user_facing import attachment_failure_message

from .report_service import generate_annual_report_draft


LOGGER = logging.getLogger(__name__)


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
    task_result = artifacts.get("tasks") or {}
    attachment_job: dict = {}
    attachment_acceptance_note = ""
    report_id = int(report.get("id") or 0)
    if report_id > 0:
        from .attachments.job_service import (
            AttachmentJobError,
            create_attachment_job,
            dispatch_pending_outbox,
        )

        thread_id = str(state.get("thread_id") or "")
        assistant_turn_id = derive_assistant_message_id(
            thread_id=thread_id,
            client_turn_id=str(state.get("client_turn_id") or ""),
            query=str(state.get("query") or ""),
            case_id=case_id,
            intent=str(state.get("intent") or "full_audit"),
            message_count=len(list(state.get("messages") or [])),
        )
        try:
            attachment_result = create_attachment_job(
                engagement_id=case_id,
                report_id=report_id,
                thread_id=thread_id,
                assistant_turn_id=assistant_turn_id,
                request_scope="all_active_template_files",
                delivery_level="review_draft",
                client_idempotency_key=str(state.get("client_turn_id") or ""),
                requested_by=str(state.get("operator_id") or "ai_agent"),
            )
            attachment_job = dict(attachment_result.get("attachment_job") or {})
            if not attachment_job.get("job_id"):
                raise RuntimeError("attachment service returned no durable job reference")
        except AttachmentJobError as exc:
            attachment_acceptance_note = (
                f"\n\n**附件暂未生成**：{attachment_failure_message(exc.code)}"
                "报告草稿已保存；请按上述提示处理后，在当前项目重新生成附件。"
            )
            LOGGER.info(
                "automatic_attachment_job_not_created case_id=%s report_id=%s code=%s",
                case_id,
                report_id,
                exc.code,
            )
        except Exception:
            attachment_acceptance_note = (
                "\n\n**附件暂未生成**：附件任务服务当前不可用。"
                "报告草稿已保存；请稍后在当前项目重新生成附件；若持续失败，"
                "请联系平台管理员检查附件 worker 和 outbox。"
            )
            LOGGER.exception(
                "automatic_attachment_job_failed case_id=%s report_id=%s",
                case_id,
                report_id,
            )
        else:
            try:
                dispatch_pending_outbox(limit=1)
            except Exception:
                # The durable job and outbox event already exist. Keep the real
                # job reference so the UI can poll it while beat retries dispatch.
                LOGGER.exception(
                    "automatic_attachment_dispatch_delayed case_id=%s report_id=%s",
                    case_id,
                    report_id,
                )
    else:
        attachment_acceptance_note = (
            "\n\n**附件暂未生成**：报告草稿未返回可冻结的报告版本。"
            "请先确认报告已成功保存，再在当前项目重新生成附件。"
        )
    artifact_note = (
        f"\n\n---\n**审计结果已保存**\n"
        f"- 报告草稿版本：v{report.get('version', '-')}；\n"
        f"- 工作底稿版本：{workpaper_versions or '-'}；\n"
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
        "如需调整报告草稿、补充资料或继续执行审计，请直接描述要求。"
    )
    return {
        "agent_output": (
            str(result.get("report_text") or "")
            + artifact_note
            + attachment_acceptance_note
        ),
        "artifacts": artifacts,
        "response_trace_candidates": list(result.get("response_trace_candidates") or []),
        "response_citation_coverage": dict(result.get("response_citation_coverage") or {}),
        "citation_entries": list(result.get("citation_entries") or []),
        "annual_report_manifest": dict(result.get("annual_report_manifest") or {}),
        "attachment_job": attachment_job,
        "extracted_tasks": [],
    }


def build_annual_report_graph():
    graph = StateGraph(AuditGraphState)
    graph.add_node("generate_annual_report", generate_annual_report_node)
    graph.add_edge(START, "generate_annual_report")
    graph.add_edge("generate_annual_report", END)
    return graph.compile()


__all__ = ["build_annual_report_graph", "generate_annual_report_node"]
