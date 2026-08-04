"""Deterministic read-only nodes used by annual-audit business-line routing."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from ..context_loader import resolve_trace_items
from ...services.case_evidence import rank_case_evidence
from ...services.kg_service import get_kg_service
from ....annual_audit.tools import (
    analyze_annual_data_readiness,
    get_annual_engagement,
    get_annual_material_status,
    list_annual_material_requirements,
    list_annual_tasks,
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
            "summary": f"{tool_name} 返回了无法解析的结果。",
            "key_facts": {"raw": str(raw or "")[:240]},
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
    lines = [str(item.get("summary") or f"{item['tool']} 查询完成。") for item in outputs]
    facts = {item["tool"]: item.get("key_facts") for item in outputs}
    lines.append(f"关键结果：{json.dumps(facts, ensure_ascii=False)}")
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

    facts = {
        "source_scope": "case_material",
        "case_binding": True,
        "reference_only": False,
        "case_id": case_id,
        "returned_count": len(evidence_items),
        "items": evidence_items,
    }
    return {
        "agent_output": (
            f"已从年审项目 {case_id} 中找到 {len(evidence_items)} 条可回源证据。\n"
            f"关键结果：{json.dumps(facts, ensure_ascii=False)}\n"
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


def query_tasks(state: AuditGraphState) -> dict[str, Any]:
    case_id = _case_id(state)
    if case_id <= 0:
        return _missing_case_result("task.query")
    raw = list_annual_tasks.invoke({"case_id": case_id})
    return _render_result("task.query", [_parse_tool_output("list_annual_tasks", raw)])


READ_ONLY_EXECUTOR_NODES: dict[str, ReadNode] = {
    "query_case_profile": query_case_profile,
    "query_material_status": query_material_status,
    "query_material_validation": query_material_validation,
    "query_evidence": query_evidence,
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
    "query_tasks": ("list_annual_tasks",),
}
