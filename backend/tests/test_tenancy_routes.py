from fastapi.testclient import TestClient

from ai_hunter.app.auth.identity import Identity, get_current_identity
from ai_hunter.app.main import create_app
from ai_hunter.app.settings import get_settings


def _identity() -> Identity:
    return Identity(
        user_id="auditor-1",
        company_id="audit-firm-1",
        roles=["project_manager"],
        authenticated=True,
    )


def _authenticated_app(monkeypatch, tenancy):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    monkeypatch.setattr("ai_hunter.app.auth.tenancy.get_tenancy_service", lambda: tenancy)
    app = create_app()
    app.dependency_overrides[get_current_identity] = _identity
    return app


def test_upload_batch_checks_project_access_before_returning(monkeypatch):
    class _Tenancy:
        def can_access_case(self, identity, case_id):
            assert case_id == 7
            return False

    class _KnowledgeGraph:
        def fetch_source_upload_batch(self, upload_batch_id):
            return {"upload_batch_id": upload_batch_id, "case_id": 7}

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: _KnowledgeGraph())
    response = TestClient(_authenticated_app(monkeypatch, _Tenancy())).get(
        "/files/upload-batches/annual-batch-1"
    )
    assert response.status_code == 403


def test_graph_request_checks_project_access_before_query(monkeypatch):
    called = {"graph": False}

    class _Tenancy:
        def can_access_case(self, identity, case_id):
            assert case_id == 7
            return False

    def _knowledge_graph():
        called["graph"] = True
        raise AssertionError("graph query must not run after access denial")

    monkeypatch.setattr("ai_hunter.app.api.routes_graph.get_kg_service", _knowledge_graph)
    response = TestClient(_authenticated_app(monkeypatch, _Tenancy())).post(
        "/graph/subgraph",
        json={"case_id": 7, "center_entity_id": 11, "depth": 1},
    )
    assert response.status_code == 403
    assert called["graph"] is False
