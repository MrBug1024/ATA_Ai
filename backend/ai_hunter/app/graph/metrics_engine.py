"""确定性数值引擎（Tier1）。

定位（见 docs/design/01-确定性数值引擎.md）：消费上游 valuation_squeeze 去毒明细，
自己做"口径层"——本息回收率、NPV/折现/三层时间窗、极端归零、全参数化。
纯计算，无 LLM、无副作用、不抛错（数据缺失输出带标记的尽力结果）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..settings import get_settings

_LOGGER = logging.getLogger(__name__)


def _json_setting(name: str, raw: str, expect_type: type):
    """Parse one JSON settings value; invalid values return None and keep settings defaults."""
    if not raw:
        return None
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        _LOGGER.warning("metrics env %s 不是合法 JSON，已忽略：%s", name, raw[:120])
        return None
    if not isinstance(val, expect_type):
        _LOGGER.warning("metrics env %s 类型应为 %s，已忽略", name, expect_type.__name__)
        return None
    return val


def _json_setting_with_default(settings, field_name: str, expect_type: type):
    """Parse a JSON setting, falling back to the Settings field default when env is invalid."""
    raw = str(getattr(settings, field_name, "") or "")
    parsed = _json_setting(field_name, raw, expect_type)
    if parsed is not None:
        return parsed
    default_raw = str(settings.__class__.model_fields[field_name].default or "")
    return _json_setting(f"{field_name}.default", default_raw, expect_type)


def get_engine_params() -> dict[str, Any]:
    """Read deterministic valuation parameters from Settings / env.

    - METRICS_DISCOUNT_RATE=0.12
    - METRICS_AMOUNT_DECIMALS=4
    - METRICS_TRANCHE_YEARS={"T1":0.125,"T2":0.875,"T3":1.5}
    - METRICS_TRANCHE_ALLOCATION={"T1":0.2,"T2":0.5,"T3":0.3}
    - METRICS_TRANCHE_WEIGHT={"T1":0.95,"T2":0.85,"T3":0.7}
    - METRICS_ZEROING_REQUIRES=[["查封","案外异议"],["查封","强占"]]
    """
    settings = get_settings()
    params: dict[str, Any] = {
        "discount_rate": settings.metrics_discount_rate,
        "amount_decimals": settings.metrics_amount_decimals,
    }
    for key, env_name, typ in (
        ("tranche_years", "metrics_tranche_years", dict),
        ("tranche_allocation", "metrics_tranche_allocation", dict),
        ("tranche_weight", "metrics_tranche_weight", dict),
        ("zeroing_requires", "metrics_zeroing_requires", list),
    ):
        val = _json_setting_with_default(settings, env_name, typ)
        if val is not None:
            params[key] = val
    return params


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── 金额格式化（场景差异化）──────────────────────────────────────────────
def format_amount(value: Any, scene: str = "report", *, decimals: int | None = None) -> str:
    """report：万元、保留 decimals 位、无千分位；legal：元、加千分位。"""
    v = _num(value)
    if v is None:
        return ""
    if scene == "legal":
        return f"{v:,.2f}"  # 元 + 千分位
    dec = decimals if decimals is not None else get_settings().metrics_amount_decimals
    wan = v / 10000.0
    return f"{wan:.{dec}f}"  # 万元、无千分位


# ── 债权脱水（本息口径）──────────────────────────────────────────────────
def _compute_claims(claims: list, decimals: int) -> dict[str, Any]:
    recovery_base = 0.0
    subordinated = 0.0
    split = 0
    unsplittable_total = 0.0
    unsplittable_count = 0
    restructuring_rates: list[float] = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        p, i = _num(c.get("principal")), _num(c.get("interest"))
        pen, dly = _num(c.get("penalty")), _num(c.get("delayed_interest"))
        if p is not None or i is not None:
            recovery_base += (p or 0.0) + (i or 0.0)
            split += 1
        else:
            unsplittable_count += 1
            unsplittable_total += _num(c.get("total_claim")) or 0.0
        subordinated += (pen or 0.0) + (dly or 0.0)
        rate = _num(c.get("proposed_recovery_rate"))
        if rate is not None:
            restructuring_rates.append(rate)
    return {
        "recovery_base_principal_interest": round(recovery_base, decimals),
        "subordinated_total": round(subordinated, decimals),
        "split_claim_count": split,
        "unsplittable_claim_count": unsplittable_count,
        "unsplittable_total_claim": round(unsplittable_total, decimals),
        "restructuring_recovery_rates": restructuring_rates,
    }


# ── 资产去毒（消费上游 valuation_squeeze + 口径层归零）──────────────────────
def _zeroed_reason(item: dict, dehydrated: dict, params: dict) -> str | None:
    """按归零规则判定资产是否极端归零，返回原因或 None。

    上游 verdict='高风险' 且命中沙盘毒点的「叠加组合」时归零。毒点来自
    real_estate.drill_down_flags（含 risk_type 文本），按文本关键词匹配。
    """
    verdict = str(item.get("verdict") or "")
    if "高风险" not in verdict:
        return None
    flags_text = " ".join(
        str(f.get("risk_type", "")) + str(f.get("desc", ""))
        for f in (dehydrated.get("drill_down_flags") or [])
        if isinstance(f, dict)
    )
    for combo in params.get("zeroing_requires", []):
        if all(kw in flags_text for kw in combo):
            return f"极端风险归零（命中 {'+'.join(combo)}）"
    return None


def _compute_asset_block(valuation_items: list, dehydrated: dict, params: dict, decimals: int) -> dict[str, Any]:
    items_out = []
    gross_total = 0.0
    net_total = 0.0
    zeroed = []
    estimated = 0
    for it in valuation_items or []:
        if not isinstance(it, dict):
            continue
        gross = _num(it.get("gross_value")) or 0.0
        net = _num(it.get("net_value")) or 0.0
        name = it.get("property") or it.get("mine") or ""
        is_estimated = gross == 0.0  # 上游基数缺失
        if is_estimated:
            estimated += 1
        reason = _zeroed_reason(it, dehydrated, params)
        if reason:
            net = 0.0
            zeroed.append({"name": name, "reason": reason})
        gross_total += gross
        net_total += net
        items_out.append({
            "name": name,
            "gross_value": round(gross, decimals),
            "net_value": round(net, decimals),
            "discount_rate": _num(it.get("discount_rate")),
            "verdict": it.get("verdict"),
            "is_estimated": is_estimated,
            "zeroed": bool(reason),
        })
    avg_discount = round(net_total / gross_total, 4) if gross_total > 0 else None
    return {
        "items": items_out,
        "subtotal": {
            "count": len(items_out),
            "gross_total": round(gross_total, decimals),
            "net_total": round(net_total, decimals),
            "avg_discount": avg_discount,
        },
        "estimated_count": estimated,
        "zeroed": zeroed,
    }


# ── NPV / 回收率 ─────────────────────────────────────────────────────────
def _compute_npv(asset_net_total: float, recovery_base: float, params: dict, decimals: int) -> dict[str, Any]:
    r = params["discount_rate"]
    alloc = params["tranche_allocation"]
    weight = params["tranche_weight"]
    years = params["tranche_years"]
    tranche_forecast = {}
    v_rec = 0.0
    for t in ("T1", "T2", "T3"):
        p_n = asset_net_total * alloc.get(t, 0.0)          # 该档去毒净值
        pv = p_n * weight.get(t, 1.0) / ((1 + r) ** years.get(t, 1.0))  # 概率加权现值
        tranche_forecast[t] = round(pv, decimals)
        v_rec += pv
    v_net = round(v_rec, decimals)
    recovery_rate = round(v_net / recovery_base, 4) if recovery_base > 0 else None
    return {
        "V_rec": v_net,
        "V_net": v_net,
        "recovery_rate": recovery_rate,                    # 0-1 比值（本息分母）
        "recovery_rate_pct": round(recovery_rate * 100, 2) if recovery_rate is not None else None,
        "tranche_forecast": tranche_forecast,
        "asset_net_total": round(asset_net_total, decimals),
        "recovery_base_principal_interest": round(recovery_base, decimals),
    }


def _decorate_wan(metrics: dict[str, Any], dec: int) -> None:
    """给报告会引用的金额字段就地加『万元字符串』伴生字段 *_万元（已是万元/dec位/无千分位）。

    报告 LLM 直接照抄这些字段，避免自己换算大数 / 加千分位导致口径错。
    """
    def wan(v):
        return format_amount(v, "report", decimals=dec)

    claims = metrics.get("claims", {})
    for k in ("recovery_base_principal_interest", "subordinated_total", "unsplittable_total_claim"):
        if k in claims:
            claims[f"{k}_万元"] = wan(claims[k])

    for block in ("real_estate", "mining"):
        b = metrics.get(block, {})
        sub = b.get("subtotal", {})
        for k in ("gross_total", "net_total"):
            if k in sub:
                sub[f"{k}_万元"] = wan(sub[k])
        for it in b.get("items", []) or []:
            for k in ("gross_value", "net_value"):
                if k in it:
                    it[f"{k}_万元"] = wan(it[k])

    totals = metrics.get("totals", {})
    for k in ("gross_total", "net_total"):
        if k in totals:
            totals[f"{k}_万元"] = wan(totals[k])
    for row in totals.get("by_type", []) or []:
        for k in ("gross_total", "net_total"):
            if k in row:
                row[f"{k}_万元"] = wan(row[k])

    npv = metrics.get("npv", {})
    for k in ("V_rec", "V_net", "asset_net_total", "recovery_base_principal_interest"):
        if k in npv:
            npv[f"{k}_万元"] = wan(npv[k])
    tf = npv.get("tranche_forecast", {})
    if isinstance(tf, dict):
        npv["tranche_forecast_万元"] = {t: wan(v) for t, v in tf.items()}


def compute_metrics(full_context_data: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    """主入口：产出结构化 computed_metrics。纯计算、不抛错。"""
    params = params or get_engine_params()
    dec = int(params.get("amount_decimals", 4))
    data = full_context_data or {}
    engine = data.get("engine_results") or {}
    valuation = engine.get("valuation_squeeze") or {}

    claims = _compute_claims(data.get("claims") or [], dec)
    real_estate = _compute_asset_block(
        valuation.get("real_estate_valuations") or [], data.get("real_estate_dehydrated") or {}, params, dec)
    mining = _compute_asset_block(
        valuation.get("mining_valuations") or [], data.get("mining_dehydrated") or {}, params, dec)

    net_total = real_estate["subtotal"]["net_total"] + mining["subtotal"]["net_total"]
    gross_total = real_estate["subtotal"]["gross_total"] + mining["subtotal"]["gross_total"]
    npv = _compute_npv(net_total, claims["recovery_base_principal_interest"], params, dec)

    # 交叉校验：逐项 Σnet 与上游聚合 total_net_value（设计 §4.2，以逐项为准 + 记警告）
    upstream_net = _num(valuation.get("total_net_value"))
    cross_check = None
    if upstream_net is not None and abs(upstream_net - net_total) > max(1.0, 0.01 * abs(upstream_net)):
        cross_check = {
            "field": "valuation_squeeze.total_net_value",
            "upstream_aggregate": round(upstream_net, dec),
            "engine_item_sum": round(net_total, dec),
            "note": "上游聚合净值与逐项 Σnet 不一致，引擎以逐项为准（上游聚合疑似 bug）。",
        }

    metrics = {
        "case_id": data.get("case_id", 0),
        "params": params,
        "claims": claims,
        "real_estate": real_estate,
        "mining": mining,
        "totals": {
            "by_type": [
                {"type": "不动产", **real_estate["subtotal"]},
                {"type": "采矿权", **mining["subtotal"]},
            ],
            "gross_total": round(gross_total, dec),
            "net_total": round(net_total, dec),
            "avg_discount": round(net_total / gross_total, 4) if gross_total > 0 else None,
        },
        "npv": npv,
        "data_quality": {
            "is_estimated_count": real_estate["estimated_count"] + mining["estimated_count"],
            "unsplittable_claim_count": claims["unsplittable_claim_count"],
            "zeroed": real_estate["zeroed"] + mining["zeroed"],
            "cross_check": cross_check,
        },
        "note": (
            "口径：金额原值单位为【元】；报告金额请用同名 *_万元 字段（已换算为万元、保留小数位、无千分位）。"
            "回收率分母=本息(principal+interest)；资产净值消费上游 valuation_squeeze 去毒；"
            "NPV 三层时间窗/分配/权重为可配置默认；极端归零覆盖上游 5% 下限。"
        ),
    }
    _decorate_wan(metrics, dec)  # 加 *_万元 字符串伴生字段，供报告直接照抄
    return metrics
