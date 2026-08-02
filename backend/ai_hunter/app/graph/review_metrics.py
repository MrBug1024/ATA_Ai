"""复盘对账确定性引擎（Tier1-3 Phase 2-A）。

预期(recovery_forecast，按 T1/T2/T3 时间分档) vs 实际(recovery_record，按处置路径)
没有天然对应键，故对账分三视角：
- 总量：预期总额 vs 已确认实收总额 → 达成率/差异额/差异率。
- 时点：按 forecast.expected_date 累计"截至今日应收" vs "已收"，算时点缺口（催收口径）。
- 路径：实收按 disposal_path 分组（预期侧无路径分档则仅展示，不强配对）。

纯函数、不调 LLM、不读库；金额内部存元，输出补 `*_万元` 字符串（万元/4位/无千分位）。
复盘报告段子 agent 只解读这里算好的数，禁止自行重算。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .metrics_engine import format_amount


def _num(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _wan(v: Any) -> str:
    return format_amount(v, "report")  # 万元 / 4 位 / 无千分位


def _as_ordinal(d: Any) -> int | None:
    """expected_date 可能是 date 或 ISO 字符串；取不到返回 None（视为无到期日）。"""
    if isinstance(d, date):
        return d.toordinal()
    if isinstance(d, str) and d.strip():
        try:
            return date.fromisoformat(d.strip()[:10]).toordinal()
        except ValueError:
            return None
    return None


def _ratio_pct(numer: float, denom: float) -> float:
    return round(numer / denom * 100, 2) if denom > 0 else 0.0


def compute_review_metrics(
    forecasts: list[dict[str, Any]],
    records: list[dict[str, Any]],
    progress: dict[str, Any] | None = None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """三视角对账。records 只传已确认(confirmed)实收；progress 提供原报告 NPV 口径参考。"""
    today = today or date.today()
    today_ord = today.toordinal()
    progress = progress or {}

    forecasts = list(forecasts or [])
    records = list(records or [])

    expected_total = round(sum(_num(f.get("expected_amount")) for f in forecasts), 2)
    # 预期总额优先用 forecast 汇总；forecast 空时回退 progress 缓存值
    if expected_total == 0:
        expected_total = round(_num(progress.get("expected_recovery_total")), 2)
    actual_total = round(sum(_num(r.get("amount")) for r in records), 2)

    # ── 视角一：总量对账 ──────────────────────────────────────────────
    overall = {
        "expected_total": expected_total,
        "expected_total_万元": _wan(expected_total),
        "actual_total": actual_total,
        "actual_total_万元": _wan(actual_total),
        "achievement_rate_pct": _ratio_pct(actual_total, expected_total),
        "variance": round(actual_total - expected_total, 2),
        "variance_万元": _wan(round(actual_total - expected_total, 2)),
        "variance_pct": round((actual_total - expected_total) / expected_total * 100, 2) if expected_total > 0 else 0.0,
        "forecast_count": len(forecasts),
        "record_count": len(records),
    }

    # ── 视角二：时点对账（按到期日累计应收 vs 已收）─────────────────────
    due_total = round(
        sum(_num(f.get("expected_amount")) for f in forecasts
            if (o := _as_ordinal(f.get("expected_date"))) is not None and o <= today_ord),
        2,
    )
    not_due_total = round(expected_total - due_total, 2)
    timeline_gap = round(due_total - actual_total, 2)  # >0 表示到期应收未收齐（催收缺口）
    tranches: list[dict[str, Any]] = []
    for f in forecasts:
        exp = round(_num(f.get("expected_amount")), 2)
        o = _as_ordinal(f.get("expected_date"))
        is_due = o is not None and o <= today_ord
        tranches.append({
            "tranche": str(f.get("tranche", "") or ""),
            "expected_amount": exp,
            "expected_amount_万元": _wan(exp),
            "expected_date": (f.get("expected_date").isoformat() if isinstance(f.get("expected_date"), date)
                              else (str(f.get("expected_date")) if f.get("expected_date") else "")),
            "basis": str(f.get("basis", "") or ""),
            "is_due": is_due,
            "status": "已到期" if is_due else ("未到期" if o is not None else "无到期日"),
        })
    timeline = {
        "due_total": due_total,
        "due_total_万元": _wan(due_total),
        "not_due_total": not_due_total,
        "not_due_total_万元": _wan(not_due_total),
        "actual_total": actual_total,
        "actual_total_万元": _wan(actual_total),
        "timeline_gap": timeline_gap,
        "timeline_gap_万元": _wan(timeline_gap),
        "due_achievement_rate_pct": _ratio_pct(actual_total, due_total),
        "tranches": tranches,
    }

    # ── 视角三：按处置路径分组实收（展示用，不与预期强配对）──────────────
    by_path: dict[str, dict[str, Any]] = {}
    for r in records:
        path = str(r.get("disposal_path", "") or "").strip() or "未标注"
        slot = by_path.setdefault(path, {"disposal_path": path, "amount": 0.0, "count": 0})
        slot["amount"] = round(slot["amount"] + _num(r.get("amount")), 2)
        slot["count"] += 1
    paths = sorted(by_path.values(), key=lambda x: x["amount"], reverse=True)
    for p in paths:
        p["amount_万元"] = _wan(p["amount"])
        p["share_pct"] = _ratio_pct(p["amount"], actual_total)
    by_disposal_path = {"paths": paths, "actual_total": actual_total, "actual_total_万元": _wan(actual_total)}

    # ── 原报告 NPV 口径参考（预期的"出处"，供差异归因引用）──────────────
    npv_ref = {}
    cm = (progress.get("computed_metrics") or {}) if isinstance(progress.get("computed_metrics"), dict) else {}
    npv = cm.get("npv", {}) if isinstance(cm.get("npv"), dict) else {}
    if npv:
        npv_ref = {
            "V_rec_万元": npv.get("V_rec_万元", ""),
            "V_net_万元": npv.get("V_net_万元", ""),
            "recovery_rate_pct": npv.get("recovery_rate_pct", npv.get("recovery_rate", "")),
        }

    return {
        "case_id": progress.get("case_id", 0),
        "today": today.isoformat(),
        "overall": overall,
        "timeline": timeline,
        "by_disposal_path": by_disposal_path,
        "npv_ref": npv_ref,
        "risk_alerts": progress.get("risk_alerts") or [],
    }
