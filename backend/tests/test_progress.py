"""回款闭环与进度看板（Tier1-3 Phase 1）：看板聚合纯逻辑 + 路由。"""

import datetime

from fastapi.testclient import TestClient

from ai_hunter.app.main import create_app
from ai_hunter.app.services.progress_service import build_board_view


def test_board_view_collection_reminder():
    today = datetime.date(2026, 6, 17)
    progress = {"stage": "执行处置", "status": "进行中",
                "expected_recovery_total": 1000.0, "actual_recovery_total": 300.0}
    forecasts = [
        {"tranche": "T1", "expected_amount": 500.0, "expected_date": datetime.date(2026, 5, 1)},  # 已到期
        {"tranche": "T2", "expected_amount": 500.0, "expected_date": datetime.date(2026, 12, 1)},  # 未到期
    ]
    view = build_board_view(116, progress, forecasts, [], today=today, overdue_days=0, profit_threshold_pct=80)
    # 已到期预期 500，实收 300 → 待催收 200（元）→ 文案用万元：0.0200 万元
    cobranza = [a for a in view["reminders"] if a["type"] == "催收"]
    assert cobranza and "0.0200" in cobranza[0]["message"] and "万元" in cobranza[0]["message"]
    # 实收/预期 = 30% < 80% → 无利润提醒
    assert not [a for a in view["reminders"] if a["type"] == "利润分配"]
    assert view["recovery_ratio_pct"] == 30.0
    # 万元伴生字段
    assert view["actual_recovery_total_wan"] == "0.0300"
    assert view["expected_recovery_total_wan"] == "0.1000"
    assert view["forecasts"][0]["expected_amount_wan"] == "0.0500"


def test_board_view_profit_reminder():
    today = datetime.date(2026, 6, 17)
    progress = {"expected_recovery_total": 1000.0, "actual_recovery_total": 900.0}
    view = build_board_view(1, progress, [], [], today=today, overdue_days=0, profit_threshold_pct=80)
    profit = [a for a in view["reminders"] if a["type"] == "利润分配"]
    assert profit and "90.0%" in profit[0]["message"]


def test_board_view_no_expected_no_reminders():
    view = build_board_view(1, {"expected_recovery_total": 0, "actual_recovery_total": 0}, [], [],
                            today=datetime.date(2026, 6, 17))
    assert view["reminders"] == []
    assert view["recovery_ratio_pct"] == 0.0


class _FakeProgressService:
    def __init__(self):
        self.recorded = []

    def build_board(self, case_id):
        return {"case_id": case_id, "stage": "执行处置", "reminders": [], "forecasts": [], "records": []}

    def upsert_progress(self, case_id, **fields):
        if fields.get("stage") == "无效阶段":
            raise ValueError("invalid stage: 无效阶段")
        return {"case_id": case_id, **fields}

    def add_recovery(self, case_id, **kw):
        self.recorded.append((case_id, kw))
        return {"id": 1, "case_id": case_id, **kw}

    def list_recovery(self, case_id):
        return []

    def seed_forecast(self, case_id, *, report_ref, tranches):
        return len(tranches)

    def list_forecast(self, case_id):
        return []


def _client(monkeypatch):
    fake = _FakeProgressService()
    monkeypatch.setattr("ai_hunter.app.api.routes_progress.get_progress_service", lambda: fake)
    return TestClient(create_app()), fake


def test_route_get_board(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get("/cases/116/progress")
    assert r.status_code == 200 and r.json()["case_id"] == 116


def test_route_add_recovery_parses_date(monkeypatch):
    client, fake = _client(monkeypatch)
    r = client.post("/cases/116/recovery", json={"amount": 5000.0, "recovered_at": "2026-06-01", "disposal_path": "执行"})
    assert r.status_code == 200
    assert fake.recorded[0][1]["recovered_at"] == datetime.date(2026, 6, 1)


def test_route_bad_date_422(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post("/cases/116/recovery", json={"amount": 1.0, "recovered_at": "06/01/2026"})
    assert r.status_code == 422


def test_route_invalid_stage_422(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.put("/cases/116/progress", json={"stage": "无效阶段"})
    assert r.status_code == 422


# ── 实收自动捕获 ──────────────────────────────────────────────────────────
def test_recovery_signal_prefilter():
    from ai_hunter.app.services.recovery_capture import has_recovery_signal
    assert has_recovery_signal("水西南路房产已回款800万")
    assert has_recovery_signal("收到分红120万元")
    assert not has_recovery_signal("请分析该案件的资产结构")


def test_extract_recovery_skips_without_signal(monkeypatch):
    # 无信号词 → 不调 LLM，直接空
    from ai_hunter.app.services import recovery_capture as rc
    called = {"n": 0}
    monkeypatch.setattr(rc, "build_zero_temp_router_llm", lambda: called.__setitem__("n", called["n"] + 1), raising=False)
    assert rc.extract_recovery_records("分析资产结构，无回款") == []
    assert called["n"] == 0


def test_coerce_records_robust_parsing():
    from ai_hunter.app.services.recovery_capture import _coerce_records
    # 带 ```json 围栏 + 多余文本
    raw = '```json\n{"records":[{"amount":8000000,"recovered_at":"2026-05-20","source_desc":"房产","disposal_path":"清算拍卖"},{"amount":0,"source_desc":"忽略零额"},{"amount":"x"}]}\n```'
    recs = _coerce_records(raw)
    assert len(recs) == 1 and recs[0]["amount"] == 8000000.0  # 零额/非数字被剔除
    assert _coerce_records("没有 JSON 的纯文本") == []
    assert _coerce_records('{"records":[]}') == []


def test_capture_writes_pending(monkeypatch):
    from ai_hunter.app.services import recovery_capture as rc
    monkeypatch.setattr(rc, "extract_recovery_records",
                        lambda text: [{"amount": 8000000, "recovered_at": "2026-06-01", "source_desc": "水西南路房产拍卖款", "disposal_path": "清算拍卖"}])
    captured = {}

    class _Svc:
        def add_recovery(self, case_id, **kw):
            captured.update({"case_id": case_id, **kw})
            return {"id": 1}

    import ai_hunter.app.services.progress_service as ps
    monkeypatch.setattr(ps, "get_progress_service", lambda: _Svc())
    n = rc.capture_recovery_to_db("水西南路房产已回款800万", 116, origin="chat")
    assert n == 1
    assert captured["status"] == "pending" and captured["origin"] == "chat"
    assert captured["amount"] == 8000000
