"""Authorization boundaries for direct annual-audit HTTP APIs."""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from ai_hunter.annual_audit import api as annual_api
from ai_hunter.app.auth.identity import Identity, get_current_identity
from ai_hunter.app.main import create_app
from ai_hunter.app.settings import get_settings


def _identity(*, roles: list[str] | None = None) -> Identity:
    return Identity(
        user_id="auditor-1",
        username="Auditor One",
        company_id="audit-firm-1",
        roles=roles or ["annual_api_user"],
        authenticated=True,
    )


def _authenticated_app(monkeypatch, identity: Identity):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    monkeypatch.setattr(
        "ai_hunter.app.auth.permissions._role_permissions",
        lambda: {
            "annual_api_user": {
                "modules": ["report", "materials", "tasks", "drilldown"],
            }
        },
    )
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: identity
    return app


def test_health_remains_public_when_auth_is_enabled(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, *_):
            pass

        def fetchone(self):
            return {"ok": 1}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor()

    @contextmanager
    def mysql_connection():
        yield Connection()

    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    monkeypatch.setattr(annual_api, "mysql_connection", mysql_connection)

    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_non_case_annual_api_routes_require_module_permission(monkeypatch):
    app = _authenticated_app(monkeypatch, _identity(roles=["unprivileged"]))
    client = TestClient(app)

    assert client.get("/api/cases").status_code == 403
    assert client.get("/api/ingest/doc-categories").status_code == 403


def test_list_cases_derives_tenant_scope_from_identity(monkeypatch):
    captured = {}

    def list_engagements(**kwargs):
        captured.update(kwargs)
        return {"page": 1, "page_size": 20, "total": 0, "cases": []}

    monkeypatch.setattr(annual_api.engagements, "list_engagements", list_engagements)
    client = TestClient(_authenticated_app(monkeypatch, _identity()))

    response = client.get(
        "/api/cases?company_id=other-company&user_id=other-user&"
        "is_company_admin=true&is_super_admin=true"
    )

    assert response.status_code == 200
    assert captured["company_id"] == "audit-firm-1"
    assert captured["user_id"] == "auditor-1"
    assert captured["is_company_admin"] is False
    assert captured["is_super_admin"] is False


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/case/7/profile", None),
        ("get", "/api/case/7/doc-categories", None),
        ("post", "/api/ingest/validate-doc-category", {"case_id": 7, "doc_category": "contracts"}),
        ("post", "/api/tasks/create-batch", {"case_id": 7, "tasks": []}),
        ("post", "/api/tasks/manage", {"case_id": 7, "action": "list"}),
        ("post", "/api/audit/get_full_context", {"case_id": 7}),
        ("post", "/api/annual-audit/readiness", {"case_id": 7}),
        ("post", "/api/annual-audit/sales-receivables", {"case_id": 7}),
        ("post", "/api/annual-audit/cash-and-bank", {"case_id": 7}),
        ("post", "/api/annual-audit/report", {"case_id": 7}),
        ("get", "/api/annual-audit/7/artifacts", None),
        ("get", "/api/annual-audit/7/execution", None),
        ("put", "/api/annual-audit/7/profile", {"profile": {}}),
        ("put", "/api/annual-audit/7/program/F1", {"status": "in_progress"}),
        (
            "post",
            "/api/annual-audit/7/reviews",
            {"review_level": "project_manager", "decision": "approved"},
        ),
        (
            "put",
            "/api/annual-audit/7/findings/5/resolution",
            {"resolution_status": "closed"},
        ),
        (
            "put",
            "/api/annual-audit/7/confirmations",
            {
                "procedure_code": "C1",
                "counterparty_name": "示例银行",
                "confirmation_type": "bank",
            },
        ),
        (
            "post",
            "/api/annual-audit/7/policy-binding",
            {"knowledge_release_id": 1, "ruleset_id": 1},
        ),
        ("get", "/api/annual-audit/7/release-gate", None),
        ("post", "/api/annual-audit/7/release-gate", {}),
        (
            "post",
            "/api/annual-audit/7/issue",
            {
                "report_artifact_ref": "minio://annual/formal-signed.docx",
                "report_artifact_sha256": "a" * 64,
                "opinion_type": "unmodified",
                "signing_attestation": True,
            },
        ),
        (
            "post",
            "/api/annual-audit/7/archive",
            {
                "archive_manifest_ref": "minio://annual/archive-manifest.json",
                "archive_manifest_sha256": "a" * 64,
            },
        ),
    ],
)
def test_case_scoped_annual_api_routes_check_acl_before_work(monkeypatch, method, path, payload):
    checked_case_ids = []

    class DeniedTenancy:
        def can_access_case(self, identity, case_id):
            checked_case_ids.append((identity.user_id, case_id))
            return False

    monkeypatch.setattr(
        "ai_hunter.app.auth.tenancy.get_tenancy_service",
        lambda: DeniedTenancy(),
    )
    client = TestClient(_authenticated_app(monkeypatch, _identity()))

    if method == "get":
        response = client.get(path)
    elif method == "put":
        response = client.put(path, json=payload)
    else:
        response = client.post(path, json=payload)

    assert response.status_code == 403
    assert checked_case_ids == [("auditor-1", 7)]


def test_create_case_binds_tenant_and_actor_to_identity(monkeypatch):
    created_payloads = []

    def create_engagement(payload):
        created_payloads.append(payload)
        return {"case_id": 7, "deduplicated": False}

    monkeypatch.setattr(annual_api.engagements, "create_engagement", create_engagement)
    client = TestClient(_authenticated_app(monkeypatch, _identity()))

    rejected = client.post(
        "/api/ingest/case",
        json={"case_name": "FY2025", "entity_name": "Client", "company_id": "other-company"},
    )
    accepted = client.post(
        "/api/ingest/case",
        json={
            "case_name": "FY2025",
            "entity_name": "Client",
            "owner_id": "attacker",
            "created_by": "attacker",
        },
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert created_payloads == [
        {
            "case_name": "FY2025",
            "case_type": "年度财务报表审计",
            "entity_name": "Client",
            "entity_uscc": None,
            "fiscal_year": None,
            "company_id": "audit-firm-1",
            "owner_id": "auditor-1",
            "created_by": "auditor-1",
        }
    ]


def test_report_generation_uses_authenticated_actor(monkeypatch):
    captured = {}

    class AllowedTenancy:
        def can_access_case(self, identity, case_id):
            return True

    def generate(case_id, **kwargs):
        captured["case_id"] = case_id
        captured.update(kwargs)
        return {"case_id": case_id}

    monkeypatch.setattr(
        "ai_hunter.app.auth.tenancy.get_tenancy_service",
        lambda: AllowedTenancy(),
    )
    monkeypatch.setattr(annual_api, "generate_annual_report_draft", generate)
    client = TestClient(_authenticated_app(monkeypatch, _identity()))

    response = client.post(
        "/api/annual-audit/report",
        json={"case_id": 7, "created_by": "attacker"},
    )

    assert response.status_code == 200
    assert captured["case_id"] == 7
    assert captured["created_by"] == "auditor-1"
