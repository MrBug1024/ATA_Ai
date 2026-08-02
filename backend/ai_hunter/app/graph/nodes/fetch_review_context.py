"""复盘子图入口：拉回款数据 + 确定性对账（Tier1-3 Phase 2-A）。

读 recovery_forecast / recovery_record(仅 confirmed) / case_progress，
跑 review_metrics 三视角对账，把结果 + 原始数据存进 state.review_context，
供复盘段子 agent 解读、reconcile_review 拼接。纯读 + 纯算，不改任何库表。
"""

from __future__ import annotations

import logging

from ..review_metrics import compute_review_metrics
from ..state import AuditGraphState

LOGGER = logging.getLogger(__name__)


def fetch_review_context(state: AuditGraphState) -> AuditGraphState:
    case_id = state.get("current_case_id", 0) or 0
    forecasts: list[dict] = []
    records: list[dict] = []
    progress: dict = {"case_id": case_id}

    try:
        from ...services.progress_service import get_progress_service

        svc = get_progress_service()
        forecasts = svc.list_forecast(case_id)
        # 复盘只认已确认实收（pending 待确认不计入，防核心 KPI 被自动抽取污染）
        records = [r for r in svc.list_recovery(case_id) if str(r.get("status", "confirmed")) == "confirmed"]
        progress = svc.get_progress(case_id)
    except Exception as exc:  # noqa: BLE001 — 库不可达时降级为空对账，仍能出占位复盘
        LOGGER.warning("fetch_review_context db failed case=%s: %s", case_id, str(exc)[:160])

    # 原报告 NPV 口径（预期的"出处"，差异归因要引用）：本会话内若已算过则带上
    try:
        from ..context_loader import resolve_computed_metrics

        cm = resolve_computed_metrics(state)
        if isinstance(cm, dict) and cm:
            progress = {**progress, "computed_metrics": cm}
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("review computed_metrics unavailable case=%s: %s", case_id, str(exc)[:120])

    metrics = compute_review_metrics(forecasts, records, progress)

    return {
        "review_context": {
            "case_id": case_id,
            "forecasts": forecasts,
            "records": records,
            "metrics": metrics,
        }
    }
