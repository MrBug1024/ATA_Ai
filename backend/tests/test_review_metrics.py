"""复盘对账确定性引擎单测（Tier1-3 Phase 2-A）：三视角对账纯逻辑。"""

import datetime

from ai_hunter.app.graph.review_metrics import compute_review_metrics


def test_overall_achievement_and_variance():
    today = datetime.date(2026, 6, 17)
    forecasts = [
        {"tranche": "T1", "expected_amount": 6000000.0, "expected_date": datetime.date(2026, 3, 1)},
        {"tranche": "T2", "expected_amount": 4000000.0, "expected_date": datetime.date(2026, 12, 1)},
    ]
    records = [
        {"amount": 5000000.0, "disposal_path": "清算拍卖"},
        {"amount": 1000000.0, "disposal_path": "执行"},
    ]
    m = compute_review_metrics(forecasts, records, {"case_id": 116}, today=today)
    o = m["overall"]
    assert o["expected_total"] == 10000000.0
    assert o["actual_total"] == 6000000.0
    assert o["achievement_rate_pct"] == 60.0
    assert o["variance"] == -4000000.0  # 欠收 400 万元
    # 万元口径：1000 万元 / 600 万元 / 欠收 400 万元
    assert o["expected_total_万元"] == "1000.0000"
    assert o["actual_total_万元"] == "600.0000"
    assert o["variance_万元"] == "-400.0000"


def test_timeline_due_vs_actual():
    today = datetime.date(2026, 6, 17)
    forecasts = [
        {"tranche": "T1", "expected_amount": 6000000.0, "expected_date": datetime.date(2026, 3, 1)},  # 已到期
        {"tranche": "T2", "expected_amount": 4000000.0, "expected_date": datetime.date(2026, 12, 1)},  # 未到期
    ]
    records = [{"amount": 5000000.0, "disposal_path": "清算拍卖"}]
    m = compute_review_metrics(forecasts, records, {"case_id": 116}, today=today)
    t = m["timeline"]
    assert t["due_total"] == 6000000.0       # 仅 T1 到期
    assert t["not_due_total"] == 4000000.0
    assert t["timeline_gap"] == 1000000.0    # 到期应收 600 万元 − 实收 500 万元 = 缺口 100 万元
    assert t["due_achievement_rate_pct"] == round(5000000.0 / 6000000.0 * 100, 2)
    statuses = {tr["tranche"]: tr["status"] for tr in t["tranches"]}
    assert statuses == {"T1": "已到期", "T2": "未到期"}


def test_by_disposal_path_grouping_and_share():
    today = datetime.date(2026, 6, 17)
    records = [
        {"amount": 3000000.0, "disposal_path": "清算拍卖"},
        {"amount": 1000000.0, "disposal_path": "清算拍卖"},
        {"amount": 1000000.0, "disposal_path": "执行"},
        {"amount": 500000.0, "disposal_path": ""},  # 未标注
    ]
    m = compute_review_metrics([], records, {"case_id": 1}, today=today)
    paths = m["by_disposal_path"]["paths"]
    assert paths[0]["disposal_path"] == "清算拍卖" and paths[0]["amount"] == 4000000.0
    assert paths[0]["count"] == 2
    assert paths[0]["amount_万元"] == "400.0000"
    # 占比基于实收总额 550 万元
    assert paths[0]["share_pct"] == round(4000000.0 / 5500000.0 * 100, 2)
    assert any(p["disposal_path"] == "未标注" for p in paths)


def test_iso_string_date_and_empty_inputs():
    today = datetime.date(2026, 6, 17)
    # expected_date 为 ISO 字符串也能解析为已到期
    m = compute_review_metrics(
        [{"tranche": "T1", "expected_amount": 1000000.0, "expected_date": "2026-01-01"}],
        [], {"case_id": 1}, today=today,
    )
    assert m["timeline"]["due_total"] == 1000000.0
    assert m["overall"]["achievement_rate_pct"] == 0.0

    # 全空输入不报错，达成率为 0
    empty = compute_review_metrics([], [], None, today=today)
    assert empty["overall"]["expected_total"] == 0.0
    assert empty["overall"]["achievement_rate_pct"] == 0.0
    assert empty["by_disposal_path"]["paths"] == []


def test_expected_total_falls_back_to_progress_cache():
    today = datetime.date(2026, 6, 17)
    # forecast 为空时，预期总额回退 progress 缓存值
    m = compute_review_metrics([], [{"amount": 2000000.0}],
                               {"case_id": 1, "expected_recovery_total": 8000000.0}, today=today)
    assert m["overall"]["expected_total"] == 8000000.0
    assert m["overall"]["achievement_rate_pct"] == 25.0


def test_npv_ref_passthrough():
    today = datetime.date(2026, 6, 17)
    progress = {"case_id": 1, "computed_metrics": {"npv": {"V_net_万元": "1234.5678", "recovery_rate_pct": 42.0}}}
    m = compute_review_metrics([], [], progress, today=today)
    assert m["npv_ref"]["V_net_万元"] == "1234.5678"
    assert m["npv_ref"]["recovery_rate_pct"] == 42.0
