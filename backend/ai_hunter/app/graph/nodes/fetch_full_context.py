"""Fetch or synthesize the audit context consumed by downstream report nodes."""

from ...services.audit_api import get_audit_api_client
from ...services.correction_service import load_corrections_for_state
from ..json_utils import json_dumps_safe
from ..heavy_state import put_heavy_payload
from ..schemas import FullContextResultModel
from ..state import AuditGraphState


def _merge_corrections(state: AuditGraphState) -> dict:
    """决策三：加载期应用权威订正。

    从 case_correction 表加载该案 active 订正，与本轮会话叠加（extract_correction
    刚写入的 overlay）并集去重，作为 user_corrections / correction_records 返回给下游。
    - 库有订正 → DB 权威优先，**任何 full_audit、任何会话/人都自动应用**；
    - 库不可达（返回 {}）→ 返回 {} 不覆盖，保留纯会话叠加（离线/降级仍可用）；
    - 并集去重保证：即便本轮写库失败、订正只在 overlay，也不丢。
    """
    case_id = int(state.get("current_case_id", 0) or 0)
    db = load_corrections_for_state(case_id) if case_id > 0 else {}
    if not db:
        return {}
    db_pairs = list(zip(db.get("user_corrections", []), db.get("correction_records", [])))
    overlay_pairs = list(zip(state.get("user_corrections") or [], state.get("correction_records") or []))
    seen: set[str] = set()
    user_corrections: list[str] = []
    correction_records: list = []
    for line, record in db_pairs + overlay_pairs:
        if line in seen:
            continue
        seen.add(line)
        user_corrections.append(line)
        correction_records.append(record)
    return {"user_corrections": user_corrections, "correction_records": correction_records}


def _build_full_context_summary(payload: dict) -> str:
    """Build a compact summary that can safely live in the persisted state."""
    return json_dumps_safe(
        {
            "case_id": payload.get("case_id", 0),
            "top_level_keys": list(payload.keys())[:12],
            "debtors_count": len(payload.get("debtors", [])) if isinstance(payload.get("debtors"), list) else 0,
            "claims_count": len(payload.get("claims", [])) if isinstance(payload.get("claims"), list) else 0,
            "guarantors_count": len(payload.get("guarantors", []))
            if isinstance(payload.get("guarantors"), list)
            else 0,
            "real_estate_count": len(payload.get("real_estate_evaluations", []))
            if isinstance(payload.get("real_estate_evaluations"), list)
            else 0,
            "mining_count": len(payload.get("mining_evaluations", []))
            if isinstance(payload.get("mining_evaluations"), list)
            else 0,
            "has_whiteglove": bool(payload.get("whiteglove")),
            "has_fund_flow": bool(payload.get("fund_flow")),
        },
        ensure_ascii=False,
    )


def fetch_full_context(state: AuditGraphState) -> AuditGraphState:
    """Prefer the live audit API but keep a stable mock fallback for offline work.

    加载期会应用权威订正（决策三）：把 case_correction 表里该案的 active 订正
    合并进 user_corrections / correction_records，下游报告段/下钻照常消费。
    """
    case_id = state.get("current_case_id", 0)
    corrections_update = _merge_corrections(state)

    if case_id > 0:
        try:
            payload = FullContextResultModel.model_validate(
                get_audit_api_client().get_full_context_sync(case_id)
            )
            payload_dict = payload.model_dump()
            payload_json = payload.model_dump_json(ensure_ascii=False)
            payload_ref = put_heavy_payload("full_context", {"data": payload_dict, "json": payload_json})
            return {
                "full_context_ref": payload_ref,
                "full_context_summary": _build_full_context_summary(payload_dict),
                "full_context_data": {},
                "full_context_json": "",
                **corrections_update,
            }
        except Exception:
            pass

    payload = {
        "case_id": case_id,
        "summary": "TODO: call /api/audit/get_full_context",
        "correction_records": corrections_update.get("correction_records", state.get("correction_records", [])),
    }
    payload_json = json_dumps_safe(payload)
    payload_ref = put_heavy_payload("full_context", {"data": payload, "json": payload_json})
    return {
        "full_context_ref": payload_ref,
        "full_context_summary": _build_full_context_summary(payload),
        "full_context_data": {},
        "full_context_json": "",
        **corrections_update,
    }
