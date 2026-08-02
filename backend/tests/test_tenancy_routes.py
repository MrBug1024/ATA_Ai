"""Route-level object access enforcement for auth v2-B.4."""

from fastapi.testclient import TestClient

from ai_hunter.app.auth.identity import Identity, get_current_identity
from ai_hunter.app.main import create_app
from ai_hunter.app.settings import get_settings


def _identity() -> Identity:
    return Identity(
        user_id="u_member",
        company_id="co_1",
        roles=["project_manager"],
        authenticated=True,
    )


def _authenticated_app(monkeypatch, tenancy):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    monkeypatch.setattr("ai_hunter.app.auth.tenancy.get_tenancy_service", lambda: tenancy)
    monkeypatch.setattr("ai_hunter.app.api.routes_review.get_tenancy_service", lambda: tenancy)
    app = create_app()
    app.dependency_overrides[get_current_identity] = _identity
    return app


def test_progress_rejects_module_user_without_case_access(monkeypatch):
    class _Tenancy:
        def can_access_case(self, identity, case_id):
            return False

    response = TestClient(_authenticated_app(monkeypatch, _Tenancy())).get("/cases/116/progress")

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该案件"


def test_upload_batch_checks_resolved_case_before_returning(monkeypatch):
    class _Tenancy:
        def can_access_case(self, identity, case_id):
            assert case_id == 116
            return False

    class _KG:
        def fetch_source_upload_batch(self, upload_batch_id):
            return {"upload_batch_id": upload_batch_id, "case_id": 116}

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: _KG())
    response = TestClient(_authenticated_app(monkeypatch, _Tenancy())).get(
        "/files/upload-batches/batch-1"
    )

    assert response.status_code == 403


def test_graph_payload_rejects_case_before_kg_lookup(monkeypatch):
    called = {"kg": False}

    class _Tenancy:
        def can_access_case(self, identity, case_id):
            return False

    def _kg():
        called["kg"] = True
        raise AssertionError("KG lookup must not run after tenancy denial")

    monkeypatch.setattr("ai_hunter.app.api.routes_graph.get_kg_service", _kg)
    response = TestClient(_authenticated_app(monkeypatch, _Tenancy())).post(
        "/graph/subgraph",
        json={"case_id": 116, "center_entity_id": 11, "depth": 1},
    )

    assert response.status_code == 403
    assert called["kg"] is False


def test_review_registers_case_bound_thread_metadata(monkeypatch):
    calls = []

    class _Tenancy:
        def can_access_case(self, identity, case_id):
            return True

        def ensure_thread_for_invoke(self, identity, thread_id, case_id):
            calls.append(("ensure", identity.user_id, thread_id, case_id))

        def update_thread_metadata(self, thread_id, *, last_intent="", title=""):
            calls.append(("update", thread_id, last_intent, title))

    monkeypatch.setattr(
        "ai_hunter.app.api.routes_review._invoke_review",
        lambda case_id, thread_id, query: {
            "intent": "review",
            "final_report": "复盘报告",
            "review_context": {"metrics": {}},
        },
    )
    response = TestClient(_authenticated_app(monkeypatch, _Tenancy())).post(
        "/cases/116/review",
        json={"thread_id": "review-116", "query": "复盘案件116"},
    )

    assert response.status_code == 200
    assert calls == [
        ("ensure", "u_member", "review-116", 116),
        ("update", "review-116", "review", "复盘案件116"),
    ]
