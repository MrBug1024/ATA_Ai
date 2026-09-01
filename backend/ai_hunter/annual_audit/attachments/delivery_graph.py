"""Chat capability that creates a durable attachment job for the latest report."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ai_hunter.app.graph.state import AuditGraphState
from ai_hunter.app.graph.turn_identity import derive_assistant_message_id

from . import repository


def enqueue_delivery_node(state: AuditGraphState) -> dict:
    case_id = int(state.get("current_case_id") or 0)
    if case_id <= 0:
        return {"agent_output": "请先选择需要生成附件的年度审计项目。"}
    report = repository.get_latest_report_version(case_id)
    if report is None:
        return {"agent_output": "当前项目还没有冻结的年审报告版本，请先完成年度审计报告草稿。"}
    from .job_service import AttachmentJobError, create_attachment_job, dispatch_pending_outbox

    thread_id = str(state.get("thread_id") or "")
    assistant_turn_id = derive_assistant_message_id(
        thread_id=thread_id,
        client_turn_id=str(state.get("client_turn_id") or ""),
        query=str(state.get("query") or ""),
        case_id=case_id,
        intent=str(state.get("intent") or "drilldown"),
        message_count=len(list(state.get("messages") or [])),
    )
    try:
        job = create_attachment_job(
            engagement_id=case_id,
            report_id=int(report["id"]),
            thread_id=thread_id,
            assistant_turn_id=assistant_turn_id,
            request_scope="all_active_template_files",
            delivery_level="review_draft",
            client_idempotency_key=str(state.get("client_turn_id") or ""),
            requested_by=str(state.get("operator_id") or "ai_agent"),
        )
        dispatch_pending_outbox(limit=1)
    except AttachmentJobError as exc:
        return {
            "agent_output": f"附件生成未受理：{exc}",
            "attachment_job": {},
        }
    job_ref = dict(job.get("attachment_job") or {})
    return {
        "agent_output": (
            f"已创建附件生成任务，绑定报告 v{job_ref.get('report_version', report.get('report_version', '-'))} "
            f"和模板 {job_ref.get('template_version_label') or '-'}。附件为待复核草稿，"
            "全部模板文件通过质量门禁后才会开放预览与下载。"
        ),
        "attachment_job": job_ref,
    }


def build_attachment_delivery_graph():
    graph = StateGraph(AuditGraphState)
    graph.add_node("enqueue_attachment_delivery", enqueue_delivery_node)
    graph.add_edge(START, "enqueue_attachment_delivery")
    graph.add_edge("enqueue_attachment_delivery", END)
    return graph.compile()


__all__ = ["build_attachment_delivery_graph", "enqueue_delivery_node"]
