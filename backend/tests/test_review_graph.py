"""复盘子图（Tier1-3 Phase 2-A）：注册表 + fetch_review_context + reconcile_review。"""

import datetime

from ai_hunter.app.graph.heavy_state import get_heavy_payload, put_heavy_payload
from ai_hunter.app.graph.nodes.fetch_review_context import fetch_review_context
from ai_hunter.app.graph.nodes.reconcile_review import reconcile_review
from ai_hunter.app.graph.review_sections import (
    REVIEW_SECTION_BY_NODE,
    REVIEW_SECTIONS,
    review_section_id_from_node,
    review_section_node_name,
)


def test_review_registry_and_node_roundtrip():
    assert [s["id"] for s in REVIEW_SECTIONS] == ["R1", "R2", "R3"]
    for s in REVIEW_SECTIONS:
        assert s["title"] and s["prompt"].startswith("review_s")
    assert review_section_node_name("R1") == "generate_review_section_R1"
    assert review_section_id_from_node("generate_review_section_R2") == "R2"
    # 不与审计段冲突
    assert review_section_id_from_node("generate_section_2") is None
    assert review_section_id_from_node("") is None
    assert set(REVIEW_SECTION_BY_NODE) == {f"generate_review_section_{i}" for i in ("R1", "R2", "R3")}


class _FakeProgressService:
    def list_forecast(self, case_id):
        return [
            {"tranche": "T1", "expected_amount": 6000000.0, "expected_date": datetime.date(2026, 3, 1), "basis": "报告NPV"},
            {"tranche": "T2", "expected_amount": 4000000.0, "expected_date": datetime.date(2026, 12, 1), "basis": "报告NPV"},
        ]

    def list_recovery(self, case_id):
        return [
            {"amount": 5000000.0, "disposal_path": "清算拍卖", "status": "confirmed"},
            {"amount": 2000000.0, "disposal_path": "执行", "status": "pending"},  # 待确认，复盘不计入
        ]

    def get_progress(self, case_id):
        return {"case_id": case_id, "expected_recovery_total": 10000000.0, "risk_alerts": []}


def test_fetch_review_context_aggregates_confirmed_only(monkeypatch):
    import ai_hunter.app.services.progress_service as ps
    monkeypatch.setattr(ps, "get_progress_service", lambda: _FakeProgressService())

    out = fetch_review_context({"current_case_id": 116})
    ctx = out["review_context"]
    assert ctx["case_id"] == 116
    # pending 不计入实收：仅 500 万元（清算拍卖）confirmed
    assert ctx["metrics"]["overall"]["actual_total"] == 5000000.0
    assert ctx["metrics"]["overall"]["expected_total"] == 10000000.0
    assert ctx["metrics"]["overall"]["achievement_rate_pct"] == 50.0
    # 记录数也只保留 confirmed
    assert len(ctx["records"]) == 1


def test_reconcile_review_stitches_sections():
    # 直接放三段 heavy ref，验证拼接 + 标题 + 去千分位（不依赖 LLM）
    refs = {
        "R1": put_heavy_payload("report_section", {"text": "对账总览：实收 600 万元，达成率 60%。"}),
        "R2": put_heavy_payload("report_section", {"text": "差异归因：T2 尚未到期，金额 1,234,567 元口径。"}),
        "R3": put_heavy_payload("report_section", {"text": "经验：清算拍卖兑现最佳。"}),
    }
    state = {"current_case_id": 116, "report_section_refs": refs,
             "review_context": {"metrics": {"today": "2026-06-17"}}}
    out = reconcile_review(state)
    ref = out["final_report_ref"]
    text = get_heavy_payload(ref)["text"]
    assert "案件 116 回款复盘报告" in text and "复盘日 2026-06-17" in text
    assert "对账总览" in text and "差异归因" in text and "经验" in text
    # 千分位被清洗（1,234,567 → 1234567）
    assert "1,234,567" not in text and "1234567" in text
    assert out["final_report"] == ""  # 落 heavy，state 清空


def test_reconcile_review_empty_when_no_sections():
    out = reconcile_review({"current_case_id": 9, "report_section_refs": {}, "review_context": {}})
    text = get_heavy_payload(out["final_report_ref"])["text"]
    assert "案件 9 回款复盘报告" in text and "暂无可对账的回款数据" in text
