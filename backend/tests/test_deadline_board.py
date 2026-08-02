"""司法时效看板确定性引擎（Tier 2-5）：分级 / 倒计时 / 字段别名归一 / 接口。"""

import datetime

from fastapi.testclient import TestClient

from ai_hunter.app.graph.deadline_board import compute_deadline_board
from ai_hunter.app.main import create_app


TODAY = datetime.date(2026, 6, 17)


def test_grading_buckets_by_remaining_days():
    scan = {"alerts": [
        {"type": "查封", "due_date": "2026-05-01", "related_asset": "A房产", "action": "续封"},   # 过期
        {"type": "执行", "due_date": "2026-07-01", "related_asset": "B股权", "action": "申请执行"}, # +14 → 红
        {"type": "登记", "due_date": "2026-08-15", "related_asset": "C矿权", "action": "延续登记"}, # +59 → 黄
        {"type": "其它", "due_date": "2026-12-01", "related_asset": "D", "action": "关注"},        # +167 → 安全
    ]}
    board = compute_deadline_board(scan, today=TODAY, red_days=30, yellow_days=90)
    assert board["counts"] == {"expired": 1, "red": 1, "yellow": 1, "safe": 1, "unknown": 0, "total": 4}
    assert board["groups"]["expired"][0]["related_asset"] == "A房产"
    assert board["groups"]["red"][0]["remaining_days"] == 14
    assert board["groups"]["yellow"][0]["level"] == "黄"
    assert board["thresholds"] == {"red_days": 30, "yellow_days": 90}


def test_real_upstream_schema_parses():
    # 上游 /api/audit/deadline-scan 真实结构（NpaDemo deadline_alerts 表字段）
    scan = {
        "expired_alerts": [{"alert_type": "查封到期", "deadline_date": "2026-01-01",
                            "related_asset": "甲房产", "action_required": "续封",
                            "suggested_action": "已过期！需立即续封", "severity": "red", "days_remaining": -167}],
        "red_alerts": [{"alert_type": "采矿证到期", "deadline_date": "2026-06-30",
                        "related_asset": "乙矿权", "action_required": "延续登记", "severity": "red"}],
        "yellow_alerts": [],
        "green_alerts": [{"alert_type": "排污许可", "deadline_date": "2026-12-01", "related_asset": "丙"}],
        "risk_score": 80.0,
    }
    board = compute_deadline_board(scan, today=TODAY, red_days=30, yellow_days=90)
    exp = board["groups"]["expired"][0]
    assert exp["type"] == "查封到期" and exp["related_asset"] == "甲房产"
    assert exp["action"] == "已过期！需立即续封"   # 优先取 handler 增强的 suggested_action
    red = board["groups"]["red"][0]
    assert red["type"] == "采矿证到期" and red["due_date"] == "2026-06-30" and red["action"] == "延续登记"
    # green_alerts 数组键不再被丢（曾经的缺口）→ 进安全区
    assert board["counts"]["safe"] == 1 and board["groups"]["safe"][0]["related_asset"] == "丙"


def test_field_alias_fallback():
    # 兜底别名仍可解析（非上游标准名的历史/异构来源）
    scan = {"alerts": [{"category": "执行时效", "deadline": "2026-06-30", "target": "乙", "advice": "立即申请"}]}
    red = compute_deadline_board(scan, today=TODAY)["groups"]["red"][0]
    assert red["type"] == "执行时效" and red["related_asset"] == "乙" and red["action"] == "立即申请"


def test_missing_due_date_goes_unknown():
    board = compute_deadline_board({"alerts": [{"type": "无日期项", "related_asset": "X"}]}, today=TODAY)
    assert board["counts"]["unknown"] == 1
    assert board["groups"]["unknown"][0]["remaining_days"] is None


def test_remaining_days_sorted_most_urgent_first():
    scan = {"alerts": [
        {"due_date": "2026-07-10"},  # +23
        {"due_date": "2026-06-20"},  # +3
        {"due_date": "2026-07-01"},  # +14
    ]}
    board = compute_deadline_board(scan, today=TODAY, red_days=30, yellow_days=90)
    days = [e["remaining_days"] for e in board["groups"]["red"]]
    assert days == [3, 14, 23]  # 升序，最紧急在前


def test_empty_scan_safe():
    board = compute_deadline_board({}, today=TODAY)
    assert board["counts"]["total"] == 0
    assert board["groups"] == {"expired": [], "red": [], "yellow": [], "safe": [], "unknown": []}


def test_default_thresholds_read_from_settings(monkeypatch):
    import ai_hunter.app.graph.deadline_board as deadline_board

    class _Settings:
        deadline_red_days = 7
        deadline_yellow_days = 21

    monkeypatch.setattr(deadline_board, "get_settings", lambda: _Settings())
    board = compute_deadline_board({}, today=TODAY)

    assert board["thresholds"] == {"red_days": 7, "yellow_days": 21}


def test_deadline_threshold_settings_parse_comments_and_keep_individual_defaults():
    from ai_hunter.app.settings import Settings

    settings = Settings(
        _env_file=None,
        deadline_red_days="7 # red",
        deadline_yellow_days="bad value",
    )

    assert settings.deadline_red_days == 7
    assert settings.deadline_yellow_days == 90


# ── 接口 ────────────────────────────────────────────────────────────────
def test_route_deadline_board_ok(monkeypatch):
    class _Client:
        def audit_deadline_scan_sync(self, case_id):
            return {"alerts": [{"type": "查封", "due_date": "2026-05-01", "related_asset": "A"}]}

    import ai_hunter.app.services.audit_api as api
    monkeypatch.setattr(api, "get_audit_api_client", lambda: _Client())
    client = TestClient(create_app())
    r = client.get("/cases/116/deadline-board")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["counts"]["total"] == 1


def test_route_deadline_board_unavailable(monkeypatch):
    class _Boom:
        def audit_deadline_scan_sync(self, case_id):
            raise RuntimeError("audit api down")

    import ai_hunter.app.services.audit_api as api
    monkeypatch.setattr(api, "get_audit_api_client", lambda: _Boom())
    client = TestClient(create_app())
    r = client.get("/cases/116/deadline-board")
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert r.json()["counts"]["total"] == 0
