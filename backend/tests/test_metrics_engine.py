"""确定性数值引擎（Tier1）测试。"""

from ai_hunter.app.graph.metrics_engine import (
    compute_metrics,
    format_amount,
    get_engine_params,
)
from ai_hunter.app.settings import get_settings


def _ctx():
    return {
        "case_id": 116,
        "claims": [
            {"claim_id": 1, "principal": 1000.0, "interest": 200.0, "penalty": 50.0, "delayed_interest": 10.0, "total_claim": 1260.0},
            {"claim_id": 2, "principal": 500.0, "interest": 100.0, "total_claim": 600.0},
            {"claim_id": 3, "principal": None, "interest": None, "total_claim": 9000.0, "proposed_recovery_rate": 22.38},
        ],
        "real_estate_dehydrated": {"drill_down_flags": [{"risk_type": "物理抗辩", "desc": "存在案外人执行异议"}]},
        "mining_dehydrated": {"drill_down_flags": []},
        "engine_results": {
            "valuation_squeeze": {
                "real_estate_valuations": [
                    {"property": "楼A", "gross_value": 1000.0, "net_value": 900.0, "discount_rate": 0.9, "verdict": "低风险"},
                    # 高风险 + 沙盘命中 查封? 这里 flags 是"物理抗辩"，需"查封+物理抗辩"才归零→构造一个查封flag
                    {"property": "楼B", "gross_value": 2000.0, "net_value": 1000.0, "discount_rate": 0.5, "verdict": "高风险"},
                ],
                "mining_valuations": [
                    {"mine": "矿1", "gross_value": 0.0, "net_value": 0.0, "verdict": "低风险"},  # gross=0 → is_estimated
                ],
            },
        },
    }


def test_compute_metrics_claims_principal_interest():
    m = compute_metrics(_ctx())
    c = m["claims"]
    assert c["recovery_base_principal_interest"] == 1800.0
    assert c["subordinated_total"] == 60.0
    assert c["split_claim_count"] == 2
    assert c["unsplittable_claim_count"] == 1
    assert c["restructuring_recovery_rates"] == [22.38]


def test_compute_metrics_asset_totals_and_estimated():
    m = compute_metrics(_ctx())
    # 不动产 net = 900 + 1000 = 1900（楼B 高风险但 flags 只有"物理抗辩"无"查封"，不满足归零组合）
    assert m["real_estate"]["subtotal"]["net_total"] == 1900.0
    # 矿 gross=0 → is_estimated
    assert m["data_quality"]["is_estimated_count"] == 1
    assert m["totals"]["net_total"] == 1900.0


def test_compute_metrics_zeroing_on_stacked_risk():
    ctx = _ctx()
    # 给沙盘加"查封"毒点 → 楼B(高风险) 命中 查封+物理抗辩 → 归零
    ctx["real_estate_dehydrated"]["drill_down_flags"].append({"risk_type": "查封", "desc": "已查封"})
    m = compute_metrics(ctx)
    assert any("归零" in z["reason"] for z in m["data_quality"]["zeroed"])
    # 楼B 净值归零 → 不动产 net = 900
    assert m["real_estate"]["subtotal"]["net_total"] == 900.0


def test_compute_metrics_npv_uses_params():
    m = compute_metrics(_ctx())
    npv = m["npv"]
    assert npv["asset_net_total"] == 1900.0
    # 回收率 = V_net / 本息基数(1800)
    assert npv["recovery_base_principal_interest"] == 1800.0
    assert npv["recovery_rate"] is not None
    # 三档预测齐全且为正
    assert set(npv["tranche_forecast"].keys()) == {"T1", "T2", "T3"}
    assert all(v >= 0 for v in npv["tranche_forecast"].values())
    # 参数回显
    assert m["params"]["discount_rate"] == get_engine_params()["discount_rate"]


def test_compute_metrics_empty_is_safe():
    m = compute_metrics({})
    assert m["claims"]["recovery_base_principal_interest"] == 0.0
    assert m["npv"]["recovery_rate"] is None  # 分母 0 → None，不崩
    assert m["totals"]["net_total"] == 0.0


def test_format_amount_scenes():
    # 报告：万元、4 位、无千分位
    assert format_amount(188283103.12, "report") == "18828.3103"
    # 法律文书：元、千分位
    assert format_amount(188283103.12, "legal") == "188,283,103.12"
    assert format_amount(None) == ""


def test_get_engine_params_env_override(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("METRICS_DISCOUNT_RATE", "0.08")
    monkeypatch.setenv("METRICS_AMOUNT_DECIMALS", "2")
    p = get_engine_params()
    assert p["discount_rate"] == 0.08
    assert p["amount_decimals"] == 2
    get_settings.cache_clear()


def test_get_engine_params_json_env_override(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("METRICS_TRANCHE_ALLOCATION", '{"T1":0.1,"T2":0.6,"T3":0.3}')
    monkeypatch.setenv("METRICS_TRANCHE_WEIGHT", '{"T1":0.9,"T2":0.8,"T3":0.6}')
    monkeypatch.setenv("METRICS_TRANCHE_YEARS", '{"T1":0.25,"T2":1.0,"T3":2.0}')
    monkeypatch.setenv("METRICS_ZEROING_REQUIRES", '[["查封","强占"]]')
    p = get_engine_params()
    assert p["tranche_allocation"] == {"T1": 0.1, "T2": 0.6, "T3": 0.3}
    assert p["tranche_weight"] == {"T1": 0.9, "T2": 0.8, "T3": 0.6}
    assert p["tranche_years"] == {"T1": 0.25, "T2": 1.0, "T3": 2.0}
    assert p["zeroing_requires"] == [["查封", "强占"]]
    get_settings.cache_clear()


def test_get_engine_params_bad_json_env_keeps_default(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("METRICS_TRANCHE_ALLOCATION", "not-json")
    p = get_engine_params()
    assert p["tranche_allocation"] == {"T1": 0.20, "T2": 0.50, "T3": 0.30}  # 回退默认
    get_settings.cache_clear()
