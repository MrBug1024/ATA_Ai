from fastapi.testclient import TestClient

from ai_hunter.app.main import create_app


REQUIRED_AI_PATHS = {
    "/chat/invoke",
    "/files/health",
    "/evidence/resolve",
    "/cases/{case_id}/progress",
    "/auth/login",
}

REQUIRED_DOMAIN_METHODS = {
    "/api/ingest/case": {"post"},
    "/api/ingest/enterprise": {"post"},
    "/api/ingest/doc-categories": {"get"},
    "/api/case/{case_id}/doc-categories": {"get"},
    "/api/ingest/validate-doc-category": {"post"},
    "/api/ingest/parse-document": {"post"},
    "/api/ingest/structured-fields": {"post"},
    "/api/audit/delta-check": {"post"},
    "/api/audit/valuation-squeeze": {"post"},
    "/api/audit/deadline-scan": {"post"},
    "/api/audit/behavioral-scan": {"post"},
    "/api/cases": {"get"},
    "/api/cases/{case_id}/members": {"get"},
    "/api/cases/{case_id}/members/{member_user_id}": {"put"},
    "/api/cases/{case_id}/parties": {"get", "post"},
    "/api/case/{case_id}/profile": {"get"},
    "/api/case/{case_id}/legal-writ": {"get"},
    "/api/case/{case_id}/whiteglove": {"get"},
    "/api/case/{case_id}/fund-flow": {"get"},
    "/api/audit/get_full_context": {"post"},
    "/api/tasks/create-batch": {"post"},
    "/api/tasks/manage": {"post"},
    "/api/logs": {"get"},
    "/api/v1/check": {"get"},
    "/health": {"get"},
}


def test_unified_openapi_contains_ai_and_domain_contracts():
    schema_paths = create_app().openapi()["paths"]

    assert REQUIRED_AI_PATHS <= set(schema_paths)
    for path, required_methods in REQUIRED_DOMAIN_METHODS.items():
        assert path in schema_paths
        assert required_methods <= set(schema_paths[path])


def test_unified_health_routes_are_reachable():
    with TestClient(create_app()) as client:
        assert client.get("/files/health").status_code == 200
        assert client.get("/health").status_code == 200


def test_domain_health_uses_packaged_config(monkeypatch):
    monkeypatch.setattr("ai_hunter.domain_engine.api.db.query_one", lambda _sql: {"?column?": 1})

    with TestClient(create_app()) as client:
        payload = client.get("/health").json()

    assert payload["status"] == "ok"
    assert payload["db"] == "connected"
    assert payload["llm_provider"]
