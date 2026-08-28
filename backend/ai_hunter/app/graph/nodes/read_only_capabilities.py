"""Deterministic read-only nodes used by annual-audit business-line routing."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from ....annual_audit.engagement_repository import get_engagement_profile
from ....annual_audit.task_repository import manage_tasks
from ....annual_audit.workflow_guide import render_annual_workflow_guide
from ..context_loader import resolve_trace_items
from ...services.case_evidence import rank_case_evidence
from ...services.kg_service import get_kg_service
from ....annual_audit.tools import (
    analyze_annual_data_readiness,
    get_annual_engagement,
    get_annual_material_status,
    list_annual_material_requirements,
)
from ..state import AuditGraphState


ReadNode = Callable[[AuditGraphState], dict[str, Any]]


def _case_id(state: AuditGraphState) -> int:
    decision = state.get("route_decision") or {}
    decision_case_id = decision.get("case_id") if isinstance(decision, dict) else None
    try:
        return int(state.get("current_case_id") or decision_case_id or 0)
    except (TypeError, ValueError):
        return 0


def _parse_tool_output(tool_name: str, raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        payload = {
            "summary": "系统返回了无法解析的审计数据。",
            "key_facts": {},
            "truncated": True,
            "next_hint": "请稍后重试。",
        }
    return {"tool": tool_name, **payload}


def _missing_case_result(capability: str) -> dict[str, Any]:
    message = "请先提供要查询的年审项目编号。"
    return {
        "agent_output": message,
        "business_line_result": {
            "capability": capability,
            "read_only": True,
            "ok": False,
            "error": "missing_case_id",
            "tool_calls": [],
        },
    }


def _render_result(capability: str, outputs: list[dict[str, Any]]) -> dict[str, Any]:
    ok = all(not isinstance(item.get("key_facts"), dict) or "error" not in item["key_facts"] for item in outputs)
    summary_by_capability = {
        "case.profile": "已读取年审项目画像。",
        "material.status": "已读取年审资料处理状态。",
        "material.validate": "已完成年审资料类别、完整性和数据就绪度校验。",
    }
    lines = [summary_by_capability.get(capability, "已完成年审查询。")]
    for item in outputs:
        facts = item.get("key_facts")
        if not isinstance(facts, dict):
            continue
        labels = (
            ("case_id", "项目编号"),
            ("entity_name", "被审计单位"),
            ("period_start", "审计期间起"),
            ("period_end", "审计期间止"),
            ("status", "状态"),
            ("total", "总数"),
            ("uploaded_count", "已上传"),
            ("missing_count", "缺失"),
            ("ready_count", "已就绪"),
            ("blocking_count", "阻断项"),
        )
        for key, label in labels:
            value = facts.get(key)
            if value not in (None, "", [], {}):
                lines.append(f"- {label}：{value}")
    hints = [str(item.get("next_hint") or "") for item in outputs if item.get("next_hint")]
    if hints:
        lines.append("下一步：" + " ".join(dict.fromkeys(hints)))
    return {
        "agent_output": "\n".join(lines),
        "business_line_result": {
            "capability": capability,
            "read_only": True,
            "ok": ok,
            "tool_calls": outputs,
        },
    }


def query_case_profile(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    if case_id <= 0:
        return _missing_case_result("case.profile")
    raw = get_annual_engagement.invoke({"case_id": case_id})
    return _render_result("case.profile", [_parse_tool_output("get_annual_engagement", raw)])


def query_material_status(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    if case_id <= 0:
        return _missing_case_result("material.status")
    raw = get_annual_material_status.invoke({"case_id": case_id})
    return _render_result("material.status", [_parse_tool_output("get_annual_material_status", raw)])


def query_material_validation(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    if case_id <= 0:
        return _missing_case_result("material.validate")
    catalog = list_annual_material_requirements.invoke({})
    status = get_annual_material_status.invoke({"case_id": case_id})
    readiness = analyze_annual_data_readiness.invoke({"case_id": case_id})
    return _render_result(
        "material.validate",
        [
            _parse_tool_output("list_annual_material_requirements", catalog),
            _parse_tool_output("get_annual_material_status", status),
            _parse_tool_output("analyze_annual_data_readiness", readiness),
        ],
    )


def query_evidence(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    if case_id <= 0:
        return _missing_case_result("evidence.resolve")
    query = str(state.get("query") or "")
    state_traces = resolve_trace_items(state)
    has_explicit_reference = bool(
        re.search(r"(?:角标|引用|citation|claim|断言|\[)\s*[编号#:]?\s*\d+", query, re.IGNORECASE)
    )
    if has_explicit_reference and state_traces:
        traces = state_traces
    else:
        try:
            traces = get_kg_service().fetch_case_evidence_traces(case_id, query_text=query, limit=5)
        except Exception:
            traces = state_traces
    evidence_items = rank_case_evidence(traces or state_traces, query, limit=5)
    if not evidence_items:
        return {
            "agent_output": "当前年审项目尚无可回源证据，请先上传并解析审计资料。",
            "business_line_result": {
                "capability": "evidence.resolve",
                "read_only": True,
                "ok": False,
                "error": "case_evidence_not_found",
                "source_scope": "case_material",
                "case_binding": True,
                "reference_only": False,
                "tool_calls": [],
                "evidence_items": [],
            },
        }

    return {
        "agent_output": (
            f"已从年审项目 {case_id} 中找到 {len(evidence_items)} 条可回源证据。\n"
            "每条证据均保留项目范围、来源文件和定位信息，可继续按角标、断言或关键词缩小范围。\n"
            "下一步：可按角标、断言或关键词继续缩小范围。"
        ),
        "business_line_result": {
            "capability": "evidence.resolve",
            "read_only": True,
            "ok": True,
            "source_scope": "case_material",
            "case_binding": True,
            "reference_only": False,
            "tool_calls": [],
            "evidence_items": evidence_items,
        },
    }


_PRIORITY_LABELS = {
    "urgent": "紧急",
    "high": "高",
    "medium": "中",
    "low": "低",
}
_STATUS_LABELS = {
    "pending": "待执行",
    "in_progress": "进行中",
    "completed": "已完成",
    "overdue": "逾期",
}


def _render_task_list(payload: dict[str, Any]) -> str:
    tasks_value = payload.get("tasks") or []
    if isinstance(tasks_value, dict):
        tasks = tasks_value.get("items") or []
    else:
        tasks = tasks_value
    if not isinstance(tasks, list):
        tasks = []
    case_id = payload.get("case_id") or 0
    lines = [f"年审项目 {case_id} 当前共有 {len(tasks)} 项任务。"]
    if not tasks:
        lines.append("当前没有已生成的待办任务，可先完成资料完整性校验或启动年审分析。")
        return "\n".join(lines)

    status_counts: dict[str, int] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = _STATUS_LABELS.get(str(task.get("status") or ""), str(task.get("status") or "未标记"))
        status_counts[status] = status_counts.get(status, 0) + 1
    if status_counts:
        lines.append("状态概览：" + "、".join(f"{status} {count} 项" for status, count in status_counts.items()) + "。")

    lines.append("\n任务明细：")
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            continue
        task_no = str(task.get("task_no") or f"任务 {index}")
        action = str(task.get("action") or "未填写任务事项")
        status = _STATUS_LABELS.get(str(task.get("status") or ""), str(task.get("status") or "未标记"))
        priority = _PRIORITY_LABELS.get(str(task.get("priority") or ""), str(task.get("priority") or "未标记"))
        lines.append(f"- **{task_no}：{action}**（状态：{status}；优先级：{priority}）")
        detail = str(task.get("detail") or "").strip()
        if detail:
            lines.append(f"  - 说明：{detail}")
        owner = task.get("assigned_to") or task.get("assigned_role")
        if owner:
            lines.append(f"  - 责任人/角色：{owner}")
        if task.get("deadline"):
            lines.append(f"  - 截止日期：{task['deadline']}")
        if task.get("deliverable"):
            lines.append(f"  - 应形成：{task['deliverable']}")
    return "\n".join(lines)


def query_workflow_guide(state: AuditGraphState) -> dict[str, Any]:
    """Explain the complete annual-audit workflow and its delivery boundary."""

    case_id = _case_id(state)
    engagement: dict[str, Any] | None = None
    task_summary: dict[str, Any] | None = None
    warnings: list[str] = []
    if case_id > 0:
        try:
            engagement = get_engagement_profile(case_id)
        except Exception:
            warnings.append("项目画像暂时不可用")
        try:
            task_summary = manage_tasks({"case_id": case_id, "action": "summary"})
        except Exception:
            warnings.append("任务统计暂时不可用")
    output = render_annual_workflow_guide(
        case_id=case_id,
        engagement=engagement,
        task_summary=task_summary,
    )
    if warnings:
        output += "\n\n提示：" + "、".join(warnings) + "；以上流程和交付清单仍可作为本项目的完整验收标准。"
    return {
        "agent_output": output,
        "business_line_result": {
            "capability": "audit.workflow",
            "read_only": True,
            "ok": not warnings,
            "case_binding": case_id > 0,
            "tool_calls": [],
            "warnings": warnings,
        },
    }


def query_tasks(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    if case_id <= 0:
        return _missing_case_result("task.query")
    payload = manage_tasks({"case_id": case_id, "action": "list"})
    return {
        "agent_output": _render_task_list(payload),
        "business_line_result": {
            "capability": "task.query",
            "read_only": True,
            "ok": True,
            "tool_calls": [{"tool": "list_annual_tasks", "payload": payload}],
        },
    }


READ_ONLY_EXECUTOR_NODES: dict[str, ReadNode] = {
    "query_case_profile": query_case_profile,
    "query_material_status": query_material_status,
    "query_material_validation": query_material_validation,
    "query_evidence": query_evidence,
    "query_workflow_guide": query_workflow_guide,
    "query_tasks": query_tasks,
}

READ_ONLY_EXECUTOR_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "query_case_profile": ("get_annual_engagement",),
    "query_material_status": ("get_annual_material_status",),
    "query_material_validation": (
        "list_annual_material_requirements",
        "get_annual_material_status",
        "analyze_annual_data_readiness",
    ),
    "query_evidence": (),
    "query_workflow_guide": (),
    "query_tasks": ("list_annual_tasks",),
}
