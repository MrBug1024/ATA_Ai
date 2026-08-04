from fastapi.testclient import TestClient

from ai_hunter.app.main import create_app


def test_extract_correction_persists_annual_audit_fact(monkeypatch):
    from ai_hunter.app.graph.nodes import corrections as node
    from ai_hunter.app.graph.schemas import CorrectionModel
    import ai_hunter.app.services.correction_service as correction_service

    monkeypatch.setattr(
        node,
        "_extract_with_llm",
        lambda _query: CorrectionModel(
            target="2025年12月营业收入",
            instruction="以出库单日期重新执行截止性测试",
        ),
    )
    captured = {}

    class _Service:
        def add_correction(self, case_id, **kwargs):
            captured.update({"case_id": case_id, **kwargs})
            return {"id": 1}

    monkeypatch.setattr(correction_service, "get_correction_service", lambda: _Service())
    result = node.extract_correction(
        {
            "query": "12月收入应按出库单日期重测",
            "current_case_id": 7,
            "operator_id": "auditor-1",
            "operator_name": "审计员",
        }
    )
    assert "2025年12月营业收入" in result["user_corrections"][0]
    assert "截止性测试" in result["user_corrections"][0]
    assert captured["case_id"] == 7
    assert captured["operator_id"] == "auditor-1"
    assert captured["origin"] == "chat"


def test_extract_correction_storage_failure_keeps_conversation_overlay(monkeypatch):
    from ai_hunter.app.graph.nodes import corrections as node
    from ai_hunter.app.graph.schemas import CorrectionModel
    import ai_hunter.app.services.correction_service as correction_service

    monkeypatch.setattr(
        node,
        "_extract_with_llm",
        lambda _query: CorrectionModel(target="银行未达账项", instruction="按最新对账单复核"),
    )

    class _Unavailable:
        def add_correction(self, *_args, **_kwargs):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(correction_service, "get_correction_service", lambda: _Unavailable())
    result = node.extract_correction({"query": "复核银行未达账项", "current_case_id": 7})
    assert "银行未达账项" in result["user_corrections"][0]


def test_load_corrections_for_state_renders_annual_fact(monkeypatch):
    import ai_hunter.app.services.correction_service as correction_service

    class _Service:
        def list_corrections(self, case_id, *, include_history=False):
            assert case_id == 7
            return [
                {
                    "target": "应收账款账龄",
                    "instruction": "按期后回款日重新划分",
                    "source_query": "更新账龄",
                }
            ]

    monkeypatch.setattr(correction_service, "get_correction_service", lambda: _Service())
    result = correction_service.load_corrections_for_state(7)
    assert "应收账款账龄" in result["user_corrections"][0]
    assert result["correction_records"][0]["instruction"] == "按期后回款日重新划分"


class _FakeCorrectionService:
    def __init__(self):
        self.added = []

    def list_corrections(self, case_id, *, include_history=False):
        return [
            {
                "id": 1,
                "case_id": case_id,
                "target": "收入截止性",
                "instruction": "按出库单复核",
                "status": "active",
                "operator_meta": {},
            }
        ]

    def add_correction(self, case_id, **kwargs):
        self.added.append((case_id, kwargs))
        return {"id": 9, "case_id": case_id, "status": "active", "operator_meta": {}, **kwargs}

    def revoke_correction(self, case_id, correction_id):
        return None if correction_id == 404 else {
            "id": correction_id,
            "case_id": case_id,
            "status": "revoked",
            "operator_meta": {},
        }


def _client(monkeypatch):
    service = _FakeCorrectionService()
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_corrections.get_correction_service",
        lambda: service,
    )
    return TestClient(create_app()), service


def test_correction_routes_list_add_and_revoke(monkeypatch):
    client, service = _client(monkeypatch)
    listed = client.get("/cases/7/corrections")
    assert listed.status_code == 200
    assert listed.json()["corrections"][0]["target"] == "收入截止性"

    added = client.post(
        "/cases/7/corrections",
        json={"target": "银行未达账项", "instruction": "按最新对账单复核"},
    )
    assert added.status_code == 200
    assert service.added[0][1]["origin"] == "manual"

    missing = client.post("/cases/7/corrections/404/revoke")
    assert missing.status_code == 404
