from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_hunter.app.api import routes_templates
from ai_hunter.app.auth.identity import Identity, get_current_identity
from ai_hunter.document_templates.repository import (
    DocumentTemplateRepository,
    TemplateImmutableError,
)
from ai_hunter.document_templates.service import TemplateServiceValidationError


class ScriptedCursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql: str, params=()):
        self.executed.append((" ".join(sql.split()), tuple(params)))
        return self

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        result = self.rows
        self.rows = []
        return result


class ScriptedConnection:
    def __init__(self, cursor: ScriptedCursor) -> None:
        self.scripted_cursor = cursor

    def cursor(self):
        return self.scripted_cursor


def _repository_with_rows(rows: list[dict]):
    repository = DocumentTemplateRepository(
        settings=SimpleNamespace(postgres_checkpointer_dsn="postgresql://unused")
    )
    cursor = ScriptedCursor(rows)

    @contextmanager
    def connect():
        yield ScriptedConnection(cursor)

    repository._connect = connect
    return repository, cursor


def test_create_version_allocates_next_number_under_family_row_lock() -> None:
    family_id = uuid4()
    version_id = uuid4()
    repository, cursor = _repository_with_rows(
        [
            {"id": family_id, "next_version_no": 4},
            {"id": version_id},
        ]
    )
    repository.get_version = lambda value: {"id": value}
    created = repository.create_version(
        {
            "business_type": "annual_audit",
            "scope_type": "system",
            "scope_key": "system",
            "name": "Version four",
            "description": "",
        },
        actor="superadmin",
    )
    sql = "\n".join(statement for statement, _ in cursor.executed)
    assert "FOR UPDATE" in sql
    assert "next_version_no = next_version_no + 1" in sql
    assert "MAX(" not in sql.upper()
    assert any("v4" in params for _, params in cursor.executed)
    assert created["id"] == version_id


def test_active_version_is_immutable() -> None:
    version_id = uuid4()
    repository, _ = _repository_with_rows(
        [
            {
                "id": version_id,
                "family_id": uuid4(),
                "status": "active",
                "revision": 3,
            }
        ]
    )
    with pytest.raises(TemplateImmutableError):
        repository.update_version(
            version_id,
            {"name": "changed"},
            revision=3,
            actor="superadmin",
        )


def test_activation_locks_family_retires_old_and_invalidates_old_gate() -> None:
    family_id = uuid4()
    old_id = uuid4()
    target_id = uuid4()
    content_sha = "a" * 64
    repository, cursor = _repository_with_rows(
        [
            {"family_id": family_id},
            {"id": family_id, "active_version_id": old_id},
            {
                "id": target_id,
                "family_id": family_id,
                "status": "ready",
                "revision": 5,
                "file_count": 2,
                "ready_file_count": 2,
                "content_sha256": content_sha,
                "validation_report_json": {
                    "passed": True,
                    "content_sha256": content_sha,
                },
            },
        ]
    )
    repository.get_version = lambda value: {"id": value, "status": "active"}
    activated = repository.set_activation(
        target_id,
        revision=5,
        active=True,
        actor="superadmin",
        visual_confirmation={
            "confirmation_version": "template-preview-confirmation-v1",
            "confirmed_by": "superadmin",
            "confirmed_at": "2026-09-01T00:00:00+00:00",
            "files": [
                {"file_id": str(uuid4()), "preview_sha256": "b" * 64},
                {"file_id": str(uuid4()), "preview_sha256": "c" * 64},
            ],
        },
    )
    sql = "\n".join(statement for statement, _ in cursor.executed)
    assert "document_template_family WHERE id = %s FOR UPDATE" in sql
    assert "SET status = 'retired', validation_report_json = '{}'::jsonb" in sql
    assert "SET active_version_id = %s" in sql
    assert "version_retired" in [
        params[3] for _, params in cursor.executed if len(params) == 7
    ]
    assert activated["id"] == target_id


def test_reinspection_invalidates_compiled_file_and_parent_version() -> None:
    file_id = uuid4()
    version_id = uuid4()
    repository, cursor = _repository_with_rows(
        [
            {
                "id": file_id,
                "template_version_id": version_id,
                "family_id": uuid4(),
                "version_status": "draft",
                "revision": 2,
            }
        ]
    )
    repository.get_file = lambda value: {"id": value, "status": "mapping"}
    repository.record_inspection(
        file_id,
        revision=2,
        inspection_report={"ok": True},
        actor="superadmin",
    )
    sql = "\n".join(statement for statement, _ in cursor.executed)
    assert "compiled_object_ref = NULL" in sql
    assert "preview_object_ref = NULL" in sql
    assert "UPDATE public.document_template_version" in sql
    assert "validation_report_json = '{}'::jsonb" in sql


def _version_response() -> dict:
    family_id = uuid4()
    version_id = uuid4()
    file_id = uuid4()
    return {
        "id": version_id,
        "family_id": family_id,
        "business_type": "annual_audit",
        "scope_type": "system",
        "scope_key": "system",
        "version_no": 1,
        "version_label": "v1",
        "name": "Annual audit",
        "description": "",
        "status": "draft",
        "contract_version": "1.0",
        "manifest": {},
        "content_sha256": "",
        "validation_report": {},
        "revision": 1,
        "family_revision": 1,
        "active": False,
        "file_count": 1,
        "ready_file_count": 0,
        "source_object_ref": "minio://must-not-leak/version",
        "files": [
            {
                "id": file_id,
                "template_version_id": version_id,
                "document_code": "audit_report",
                "display_name": "Audit report",
                "source_file_name": "audit.md",
                "extension": ".md",
                "content_type": "text/markdown",
                "size_bytes": 20,
                "source_sha256": "a" * 64,
                "compiled_sha256": "",
                "renderer_profile": "",
                "binding_manifest": {},
                "inspection_report": {},
                "preview_available": False,
                "preview_sha256": "",
                "status": "mapping",
                "sort_order": 0,
                "revision": 1,
                "source_object_ref": "minio://must-not-leak/source",
                "compiled_object_ref": "minio://must-not-leak/compiled",
                "preview_object_ref": "minio://must-not-leak/preview",
            }
        ],
    }


def _test_app(identity: Identity) -> FastAPI:
    app = FastAPI()
    app.include_router(routes_templates.router)
    app.dependency_overrides[get_current_identity] = lambda: identity
    return app


def test_template_write_requires_explicit_superadmin() -> None:
    company_admin = Identity(
        user_id="company-admin",
        roles=["admin"],
        is_company_admin=True,
        is_super_admin=False,
    )
    client = TestClient(_test_app(company_admin))
    response = client.post(
        "/api/admin/template-versions",
        json={"business_type": "annual_audit", "name": "v1"},
    )
    assert response.status_code == 403


def test_create_request_rejects_server_owned_fields() -> None:
    client = TestClient(_test_app(Identity.admin()))
    response = client.post(
        "/api/admin/template-versions",
        json={
            "business_type": "annual_audit",
            "name": "v1",
            "version_no": 99,
        },
    )
    assert response.status_code == 422


def test_activation_request_requires_explicit_preview_confirmations() -> None:
    client = TestClient(_test_app(Identity.admin()))
    response = client.put(
        f"/api/admin/template-versions/{uuid4()}/activation",
        json={"active": True, "revision": 1},
    )
    assert response.status_code == 422


def test_template_http_response_never_exposes_object_references(monkeypatch) -> None:
    version = _version_response()
    fake_service = SimpleNamespace(get_version=lambda _: version)
    monkeypatch.setattr(
        routes_templates, "get_document_template_service", lambda: fake_service
    )
    client = TestClient(_test_app(Identity.admin()))
    response = client.get(f"/api/admin/template-versions/{version['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "object_ref" not in str(body)
    assert body["files"][0]["source_sha256"] == "a" * 64
    assert body["files"][0]["preview_available"] is False


def test_template_http_error_omits_internal_exception_details(monkeypatch) -> None:
    version_id = uuid4()

    def fail_get_version(_version_id):
        raise TemplateServiceValidationError(
            "template failed the synthetic render gate",
            details={
                "code": "SYNTHETIC_RENDER_FAILED",
                "error_type": "RuntimeError",
                "message": "failed at minio://private/templates/source.docx",
                "source_object_ref": "minio://private/templates/source.docx",
                "errors": [{"code": "SAFE_DIAGNOSTIC", "message": "invalid slot"}],
            },
        )

    fake_service = SimpleNamespace(get_version=fail_get_version)
    monkeypatch.setattr(
        routes_templates, "get_document_template_service", lambda: fake_service
    )

    response = TestClient(_test_app(Identity.admin())).get(
        f"/api/admin/template-versions/{version_id}"
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "TEMPLATE_VALIDATION_FAILED"
    assert detail["details"] == {
        "code": "SYNTHETIC_RENDER_FAILED",
        "errors": [{"code": "SAFE_DIAGNOSTIC", "message": "invalid slot"}],
    }
    assert "RuntimeError" not in response.text
    assert "minio://" not in response.text


def test_router_exposes_the_documented_management_contract() -> None:
    routes = {
        (method, route.path)
        for route in routes_templates.router.routes
        for method in route.methods
    }
    expected = {
        ("GET", "/api/admin/template-business-types"),
        ("GET", "/api/admin/template-versions"),
        ("POST", "/api/admin/template-versions"),
        ("GET", "/api/admin/template-versions/{version_id}"),
        ("PATCH", "/api/admin/template-versions/{version_id}"),
        ("POST", "/api/admin/template-versions/{version_id}/clone"),
        ("DELETE", "/api/admin/template-versions/{version_id}"),
        ("POST", "/api/admin/template-versions/{version_id}/files"),
        ("PATCH", "/api/admin/template-files/{file_id}"),
        ("DELETE", "/api/admin/template-files/{file_id}"),
        ("POST", "/api/admin/template-files/{file_id}/inspect"),
        ("POST", "/api/admin/template-files/{file_id}/compile"),
        ("GET", "/api/admin/template-files/{file_id}/preview"),
        ("POST", "/api/admin/template-versions/{version_id}/validate"),
        ("PUT", "/api/admin/template-versions/{version_id}/activation"),
    }
    assert routes == expected
