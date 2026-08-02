"""Deterministic command nodes for Phase 2.5.4 write capabilities."""

from __future__ import annotations

from typing import Any

from ...auth.identity import Identity
from ...auth.permissions import has_module
from ...services.case_api import get_case_api_client
from ...services.task_api import get_task_api_client
from ..state import AuditGraphState
from ..write_contracts import (
    resolve_case_create_command,
    resolve_task_write_command,
    write_clarification,
)


def _decision(state: AuditGraphState) -> dict[str, Any]:
    value = state.get("route_decision") or {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return dict(value) if isinstance(value, dict) else {}


def _case_id(state: AuditGraphState) -> int:
    decision = _decision(state)
    try:
        return int(state.get("current_case_id") or decision.get("case_id") or 0)
    except (TypeError, ValueError):
        return 0


def _identity(state: AuditGraphState) -> Identity | None:
    context = state.get("identity_context") or {}
    if not isinstance(context, dict) or not context.get("user_id"):
        return None
    return Identity(
        user_id=str(context.get("user_id") or ""),
        username=str(context.get("username") or ""),
        roles=list(context.get("roles") or []),
        company_id=str(context.get("company_id") or ""),
        apps=list(context.get("apps") or []),
        is_company_admin=bool(context.get("is_company_admin")),
        is_super_admin=bool(context.get("is_super_admin")),
        authenticated=bool(context.get("authenticated")),
    )


def _identity_error(state: AuditGraphState, module: str) -> tuple[Identity | None, str]:
    identity = _identity(state)
    if identity is None:
        return None, "missing_identity_context"
    if not has_module(identity, module):
        return identity, "permission_denied"
    return identity, ""


def _command_result(
    capability: str,
    *,
    ok: bool,
    summary: str,
    command: dict[str, Any],
    response: dict[str, Any] | None = None,
    error: str = "",
    degraded: bool = False,
) -> dict[str, Any]:
    result = {
        "capability": capability,
        "read_only": False,
        "ok": ok,
        "degraded": degraded,
        "summary": summary,
        "command": command,
        "response": dict(response or {}),
    }
    if error:
        result["error"] = error
    return {"agent_output": summary, "business_line_result": result}


def create_case_command(state: AuditGraphState) -> dict[str, Any]:
    payload, missing = resolve_case_create_command(state)
    if missing:
        message = write_clarification("case.create", missing)
        return _command_result(
            "case.create", ok=False, summary=message, command=payload, error="missing_required_slots"
        )
    if _case_id(state) > 0:
        return _command_result(
            "case.create",
            ok=False,
            summary="当前会话已绑定案件，未创建新案件；请使用新的未绑定会话。",
            command=payload,
            error="thread_already_bound_to_case",
        )
    identity, identity_error = _identity_error(state, "report")
    if identity_error:
        return _command_result(
            "case.create",
            ok=False,
            summary=(
                "缺少可信身份上下文，未创建案件。"
                if identity_error == "missing_identity_context"
                else "当前身份无案件写入权限，未创建案件。"
            ),
            command=payload,
            error=identity_error,
        )
    try:
        response = get_case_api_client().create_case_sync(payload, identity=identity)
        case_id = int(response.get("case_id") or 0)
        debtor_id = int(response.get("debtor_id") or 0)
        if case_id <= 0 or debtor_id <= 0:
            raise ValueError("上游未返回有效 case_id/debtor_id")
    except Exception as exc:
        return _command_result(
            "case.create",
            ok=False,
            degraded=True,
            summary=f"案件创建失败，未继续执行后续写操作：{str(exc)[:180]}",
            command=payload,
            error="upstream_write_failed",
        )

    decision = _decision(state)
    decision["case_id"] = case_id
    summary = str(response.get("message") or f"案件已创建，case_id={case_id}。")
    result = _command_result("case.create", ok=True, summary=summary, command=payload, response=response)
    result.update(
        {
            "current_case_id": case_id,
            "current_debtor_id": debtor_id,
            "current_debtor_name": payload["debtor_name"],
            "route_decision": decision,
        }
    )
    return result


def record_material_upload(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    files = list(state.get("uploaded_files") or [])
    command = {
        "case_id": case_id,
        "upload_batch_id": str(state.get("upload_batch_id") or ""),
        "file_count": len(files),
        "doc_category": str(state.get("doc_category") or ""),
    }
    missing = []
    if case_id <= 0:
        missing.append("case_id")
    if not files:
        missing.append("uploaded_files")
    if missing:
        return _command_result(
            "material.upload",
            ok=False,
            summary="请先绑定案件并上传要处理的卷宗文件。",
            command=command,
            error="missing_required_slots",
        )
    _, identity_error = _identity_error(state, "report")
    if identity_error:
        return _command_result(
            "material.upload",
            ok=False,
            summary=(
                "缺少可信身份上下文，未确认材料摄入结果。"
                if identity_error == "missing_identity_context"
                else "当前身份无材料写入权限，未确认材料摄入结果。"
            ),
            command=command,
            error=identity_error,
        )

    errors = list(state.get("errors") or [])
    parse_summary = str(state.get("parse_summary") or "").strip()
    response = {
        "upload_batch_id": command["upload_batch_id"],
        "material_event_id": str(state.get("material_event_id") or ""),
        "records_inserted": int(state.get("records_inserted") or 0),
        "recognized_categories": list(state.get("recognized_categories") or []),
        "duplicate_files": list(state.get("duplicate_files") or []),
        "new_files": list(state.get("new_files") or []),
    }
    if errors:
        return _command_result(
            "material.upload",
            ok=False,
            degraded=True,
            summary=f"材料摄入未完成：{str(errors[-1])[:180]}",
            command=command,
            response=response,
            error="ingest_failed",
        )
    return _command_result(
        "material.upload",
        ok=True,
        summary=parse_summary or f"已完成 {len(files)} 个文件的摄入流程。",
        command=command,
        response=response,
    )


def _task_exists(response: dict[str, Any], task_id: int) -> bool:
    return any(int(item.get("task_id") or 0) == task_id for item in response.get("tasks") or [])


def write_task_command(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    command, missing = resolve_task_write_command(state, _decision(state))
    command["case_id"] = case_id
    if case_id <= 0:
        missing.insert(0, "case_id")
    if missing:
        message = write_clarification("task.write", list(dict.fromkeys(missing)))
        return _command_result(
            "task.write", ok=False, summary=message, command=command, error="missing_required_slots"
        )
    _, identity_error = _identity_error(state, "progress")
    if identity_error:
        return _command_result(
            "task.write",
            ok=False,
            summary=(
                "缺少可信身份上下文，未执行任务写入。"
                if identity_error == "missing_identity_context"
                else "当前身份无任务写入权限，未执行任务写入。"
            ),
            command=command,
            error=identity_error,
        )

    client = get_task_api_client()
    try:
        action = command["action"]
        if action == "create":
            task = {
                "action": command["task_title"],
                "detail": command["task_detail"],
                "assigned_role": command["assigned_role"],
                "deadline": command["deadline"] or None,
                "deliverable": command["deliverable"],
                "priority": command["priority"],
                "source_engine": "business_line",
            }
            response = client.create_batch_sync(case_id, [task])
        else:
            task_id = int(command["task_id"])
            tasks = client.manage_sync({"case_id": case_id, "action": "list"})
            if not _task_exists(tasks, task_id):
                return _command_result(
                    "task.write",
                    ok=False,
                    summary=f"案件 {case_id} 下不存在任务 {task_id}，未执行写入。",
                    command=command,
                    error="task_not_found_in_case",
                )
            if action in {"complete", "update"}:
                payload = {
                    "case_id": case_id,
                    "action": "update",
                    "task_id": task_id,
                    "new_status": command["new_status"],
                    "completion_note": command["completion_note"],
                }
            else:
                payload = {
                    "case_id": case_id,
                    "action": "assign",
                    "task_id": task_id,
                    "assigned_to": command["assigned_to"],
                }
            response = client.manage_sync(payload)
    except Exception as exc:
        return _command_result(
            "task.write",
            ok=False,
            degraded=True,
            summary=f"任务写入失败，未进行自动重试：{str(exc)[:180]}",
            command=command,
            error="upstream_write_failed",
        )

    summary = str(response.get("message") or "任务写操作已完成。")
    if command["action"] == "create":
        summary = (
            f"任务创建完成：新建 {int(response.get('tasks_created') or 0)} 条，"
            f"跳过 {int(response.get('tasks_skipped') or 0)} 条。"
        )
    return _command_result("task.write", ok=True, summary=summary, command=command, response=response)


WRITE_EXECUTOR_NODES = {
    "create_case_command": create_case_command,
    "record_material_upload_command": record_material_upload,
    "write_task_command": write_task_command,
}

WRITE_EXECUTOR_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "create_case_command": ("create_case",),
    "record_material_upload_command": (),
    "write_task_command": ("create_task_batch", "manage_tasks"),
}
