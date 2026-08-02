"""下游对齐 1.1/1.2：报告上下文精选 + 本息口径回收率。"""

from ai_hunter.app.graph.context_loader import build_report_context, compute_recovery_metrics


def _sample_full_context():
    return {
        "case_id": 116,
        "case": {"case_name": "晨光煤矿"},
        "debtors": [{"debtor_id": 1}],
        "guarantors": [{"guarantor_id": 1}],
        "claims": [
            # 本息齐全（贷款合同型）
            {"claim_id": 1, "principal": 1000.0, "interest": 200.0, "penalty": 50.0, "delayed_interest": 10.0, "total_claim": 1260.0},
            {"claim_id": 2, "principal": 500.0, "interest": 100.0, "total_claim": 600.0},
            # 无本息拆分（重整方案型）：只有 total_claim + 清偿率
            {"claim_id": 3, "principal": None, "interest": None, "total_claim": 9000.0,
             "guarantee_type": "重整方案", "proposed_recovery_rate": 22.38},
        ],
        "financial_snapshots": [],
        # 战术沙盘（权威）
        "real_estate_dehydrated": {"_meta": {"total_count": 6, "total_net_value": 129219380.0},
                                   "core_assets_topN": [{"id": 1}], "bundled_assets": [{"bundle_type": "住宅", "count": 5}]},
        "mining_dehydrated": {"_meta": {"total_count": 3}, "core_assets_topN": [], "bundled_assets": []},
        # legacy 截断字段（应被剔除）
        "real_estate_evaluations": [{"id": 1}, {"id": 2}, {"id": 3}],
        "_real_estate_evaluations_total": 6,
        "mining_evaluations": [{"id": 1}],
        "engine_results": {
            "valuation_squeeze": {"total_net_value": 129219380.0, "recovery_rate": 0.76,
                                  "real_estate_valuations": [{"net_value": 100.0}]},
            "deadline_scan": {"expired_alerts": []},
            "behavioral_scan": {"whiteglove_suspects": []},
            "delta_check": {"verdict_summary": "正常"},
        },
        "whiteglove": {"score": 0.7},
        "fund_flow": [{"path": "A->B"}],
    }


def test_compute_recovery_metrics_principal_interest_base():
    m = compute_recovery_metrics(_sample_full_context())
    # 本息口径：仅 claim1(1000+200) + claim2(500+100) = 1800，排除罚息/迟延
    assert m["recovery_base_principal_interest"] == 1800.0
    # 劣后：penalty50 + delayed10 = 60
    assert m["subordinated_total"] == 60.0
    assert m["split_claim_count"] == 2
    # claim3 无本息 → unsplittable
    assert m["unsplittable_claim_count"] == 1
    assert m["unsplittable_total_claim"] == 9000.0
    assert m["restructuring_recovery_rates"] == [22.38]
    # asset_net / recovery_base
    assert m["asset_net_total"] == 129219380.0
    assert m["recovery_rate_principal_interest"] == round(129219380.0 / 1800.0, 4)
    assert m["recovery_rate_principal_interest_pct"] is not None


def test_compute_recovery_metrics_empty_base():
    m = compute_recovery_metrics({"claims": [{"principal": None, "interest": None, "total_claim": 5.0}],
                                  "engine_results": {"valuation_squeeze": {"total_net_value": 100.0}}})
    assert m["recovery_base_principal_interest"] == 0.0
    assert m["recovery_rate_principal_interest"] is None  # 分母为 0 → None，不崩


def test_build_report_context_uses_authoritative_drops_legacy():
    ctx = build_report_context(_sample_full_context())
    # 用权威沙盘
    assert ctx["real_estate"]["_meta"]["total_count"] == 6
    assert ctx["mining"]["_meta"]["total_count"] == 3
    # 去毒明细
    assert ctx["valuation_detail"]["total_net_value"] == 129219380.0
    # 时效/行为/轧差
    assert "deadline_board" in ctx and "behavioral" in ctx and "delta" in ctx
    # 数值引擎结果注入（含本息回收率）
    assert ctx["computed_metrics"]["claims"]["recovery_base_principal_interest"] == 1800.0
    assert "npv" in ctx["computed_metrics"]
    # legacy 截断字段被剔除
    assert "real_estate_evaluations" not in ctx
    assert "mining_evaluations" not in ctx
    assert "_real_estate_evaluations_total" not in ctx
