"""Structured extraction for user-issued correction commands.

决策三：抽出的订正除随会话叠加外，**写入权威订正表**（case_correction），
使其跨会话/跨人生效、可追溯。写库 best-effort：库不可达时回退纯会话叠加，
不影响本轮重审（随后 fetch_full_context 会从库加载 active 订正覆盖 state）。
"""

import logging

from ..llm import build_zero_temp_router_llm
from ..schemas import CorrectionLedgerItemModel, CorrectionModel
from ..state import AuditGraphState

LOGGER = logging.getLogger(__name__)


def _extract_with_llm(query: str) -> CorrectionModel | None:
    try:
        llm = build_zero_temp_router_llm()
        extractor = llm.with_structured_output(CorrectionModel)
        return extractor.invoke(f"从这句话中提取修正对象和修正指令：{query}")
    except Exception:
        return None


def _persist_correction(state: AuditGraphState, *, target: str, instruction: str, source_query: str) -> None:
    """写权威订正表（best-effort）。操作人取自 state（账号体系上线前可空，预留 meta）。"""
    case_id = int(state.get("current_case_id", 0) or 0)
    if case_id <= 0:
        return
    try:
        from ...services.correction_service import get_correction_service

        get_correction_service().add_correction(
            case_id,
            target=target,
            instruction=instruction,
            source_query=source_query,
            operator_id=str(state.get("operator_id", "") or ""),
            operator_name=str(state.get("operator_name", "") or ""),
            origin="chat",
        )
    except Exception as exc:  # noqa: BLE001 — 库不可达不应拖垮重审
        LOGGER.warning("persist_correction_failed case=%s error=%s", case_id, str(exc)[:160])


def extract_correction(state: AuditGraphState) -> AuditGraphState:
    """Append a normalized correction record, its prompt-friendly ledger line, and persist it."""
    query = (state.get("query") or "").strip()
    corrections = list(state.get("user_corrections", []))
    records = list(state.get("correction_records", []))
    if not query:
        return {"user_corrections": corrections, "correction_records": records}

    correction = _extract_with_llm(query)
    if correction:
        target, instruction = correction.target, correction.instruction
    else:
        target, instruction = "待人工确认", query

    record = CorrectionLedgerItemModel(target=target, instruction=instruction, source_query=query)
    corrections.append(f"标的：{record.target} -> 强制指令：{record.instruction}")
    records.append(record.model_dump())
    _persist_correction(state, target=target, instruction=instruction, source_query=query)
    return {"user_corrections": corrections, "correction_records": records}
