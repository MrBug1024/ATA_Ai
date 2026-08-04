"""Pure parsing and validation helpers for deterministic write commands."""

from __future__ import annotations

import re
from typing import Any, Mapping


DEFAULT_ENGAGEMENT_TYPE = "年度财务报表审计"
TASK_ACTION_ALIASES = {
    "create": "create",
    "创建": "create",
    "complete": "complete",
    "完成": "complete",
    "assign": "assign",
    "指派": "assign",
    "update": "update",
    "更新": "update",
}
TASK_STATUSES = ("待执行", "进行中", "已完成", "逾期", "已取消")


def command_dict(state: Mapping[str, Any]) -> dict[str, Any]:
    command = state.get("write_command") or {}
    if hasattr(command, "model_dump"):
        command = command.model_dump(exclude_none=True)
    return dict(command) if isinstance(command, Mapping) else {}


def explicit_write_capability(state: Mapping[str, Any]) -> str:
    return str(command_dict(state).get("capability") or "")


def _labeled_value(query: str, *labels: str) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})\s*[:：]\s*([^,，;；\n]+)",
        query,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def resolve_case_create_command(state: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    command = command_dict(state)
    query = str(state.get("query") or "")
    case_name = str(command.get("case_name") or "").strip() or _labeled_value(query, "项目名称", "审计项目")
    entity_name = str(command.get("entity_name") or "").strip() or _labeled_value(
        query, "被审计单位", "单位名称", "企业名称"
    )
    fiscal_year = command.get("fiscal_year")
    if not fiscal_year:
        year_match = re.search(r"(?<!\d)(20\d{2})(?:\s*年)?", query)
        fiscal_year = int(year_match.group(1)) if year_match else None
    payload = {
        "case_name": case_name,
        "entity_name": entity_name,
        "case_type": DEFAULT_ENGAGEMENT_TYPE,
        "entity_uscc": str(command.get("entity_uscc") or "").strip()
        or _labeled_value(query, "统一社会信用代码", "USCC"),
        "fiscal_year": fiscal_year,
    }
    missing = [field for field in ("case_name", "entity_name", "fiscal_year") if not payload[field]]
    return payload, missing


def resolve_task_write_command(
    state: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    command = command_dict(state)
    query = str(state.get("query") or "")
    raw_action = str(command.get("task_action") or decision.get("action") or "").strip()
    action = TASK_ACTION_ALIASES.get(raw_action.lower(), TASK_ACTION_ALIASES.get(raw_action, ""))
    raw_task_id = command.get("task_id") or decision.get("target_id")
    try:
        task_id = int(raw_task_id) if raw_task_id not in (None, "") else None
    except (TypeError, ValueError):
        task_id = None

    task_title = str(command.get("task_title") or "").strip()
    if not task_title and action == "create":
        match = re.search(r"(?:创建|新增|新建)(?:一个|一条)?任务\s*[:：]?\s*(.+)$", query)
        task_title = match.group(1).strip(" ，,；;") if match else ""

    assigned_to = str(command.get("assigned_to") or "").strip()
    if not assigned_to:
        match = re.search(r"(?:指派给|分配给|转给)\s*([^,，;；\s]+)", query)
        assigned_to = match.group(1).strip() if match else ""

    new_status = str(command.get("new_status") or "").strip()
    if action == "complete":
        new_status = "已完成"
    elif not new_status:
        new_status = next((status for status in TASK_STATUSES if status in query), "")

    payload = {
        "action": action,
        "task_id": task_id,
        "task_title": task_title,
        "task_detail": str(command.get("task_detail") or "").strip(),
        "assigned_to": assigned_to,
        "assigned_role": str(command.get("assigned_role") or "").strip(),
        "new_status": new_status,
        "completion_note": str(command.get("completion_note") or "").strip()
        or _labeled_value(query, "完成说明", "备注"),
        "deadline": str(command.get("deadline") or "").strip(),
        "deliverable": str(command.get("deliverable") or "").strip(),
        "priority": str(command.get("priority") or "中").strip(),
    }
    missing: list[str] = []
    if not action:
        missing.append("task_action")
    elif action == "create" and not task_title:
        missing.append("task_title")
    elif action in {"complete", "assign", "update"} and not task_id:
        missing.append("task_id")
    if action == "assign" and not assigned_to:
        missing.append("assigned_to")
    if action == "update" and (not new_status or new_status not in TASK_STATUSES):
        missing.append("new_status")
    return payload, missing


def write_clarification(capability: str, missing: list[str]) -> str:
    labels = {
        "case_name": "项目名称",
        "entity_name": "被审计单位",
        "fiscal_year": "会计年度",
        "task_action": "任务动作",
        "task_title": "任务内容",
        "task_id": "任务编号",
        "assigned_to": "被指派人",
        "new_status": "目标状态",
    }
    rendered = "、".join(labels.get(field, field) for field in missing)
    prefix = "创建年审项目" if capability == "case.create" else "执行任务操作"
    return f"{prefix}前请补充：{rendered}。"
