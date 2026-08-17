"""Annual-audit authentication and authorization contracts."""

import jwt
import pytest

from ai_hunter.app.auth.identity import Identity, get_current_identity
from ai_hunter.app.auth.permissions import (
    MODULES,
    allowed_modules,
    clear_role_permissions_cache,
    visible_report_sections,
)
from ai_hunter.app.auth.report_filter import filter_report_text_by_sections
from ai_hunter.app.settings import get_settings


def test_annual_modules_do_not_expose_removed_business_lines():
    assert MODULES == {"report", "drilldown", "materials", "tasks", "corrections", "graph", "admin"}
    assert allowed_modules(Identity.admin()) == MODULES


def test_auditor_permissions_come_from_annual_seed(monkeypatch):
    class UnavailableService:
        def list_role_permissions(self):
            raise RuntimeError("database unavailable")

        def list_report_sections(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "ai_hunter.app.services.user_service.get_user_service",
        lambda: UnavailableService(),
    )
    clear_role_permissions_cache()
    try:
        identity = Identity(roles=["auditor"])
        assert {"report", "drilldown", "materials", "tasks", "corrections", "graph"} <= allowed_modules(identity)
        assert visible_report_sections(identity) == {
            "engagement_scope",
            "revenue_audit",
            "receivables_audit",
            "cash_audit",
            "evidence_index",
        }
    finally:
        clear_role_permissions_cache()


def test_report_filter_uses_annual_section_catalog():
    report = (
        "# 2025 年度审计报告\n\n"
        "### 1. 项目范围\n范围正文\n\n"
        "### 5. 风险事项\n管理层正文\n\n"
        "### 6. 证据索引\n证据正文"
    )
    filtered = filter_report_text_by_sections(report, {"engagement_scope", "evidence_index"})
    assert "范围正文" in filtered
    assert "证据正文" in filtered
    assert "管理层正文" not in filtered


def test_verified_jwt_builds_identity(monkeypatch):
    settings = get_settings()
    secret = "test-secret-key-at-least-32-bytes-long!!"
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_identity_mode", "platform")
    monkeypatch.setattr(settings, "auth_legacy_roles_enabled", True)
    monkeypatch.setattr(settings, "user_center_jwt_alg", "HS256")
    monkeypatch.setattr(settings, "auth_local_jwt_secret", "")
    monkeypatch.setattr(settings, "user_center_jwt_secret", secret)
    token = jwt.encode(
        {"sub": "u-annual", "name": "审计人员", "roles": ["auditor"]},
        secret,
        algorithm="HS256",
    )
    request = type("Request", (), {"headers": {"authorization": f"Bearer {token}"}})()
    identity = get_current_identity(request)
    assert identity.user_id == "u-annual"
    assert identity.roles == ["auditor"]
    assert identity.authenticated is True


def test_invalid_jwt_is_rejected_when_auth_enabled(monkeypatch):
    from fastapi import HTTPException

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_identity_mode", "platform")
    monkeypatch.setattr(settings, "user_center_jwt_alg", "HS256")
    monkeypatch.setattr(settings, "user_center_jwt_secret", "test-secret-key-at-least-32-bytes-long!!")
    request = type("Request", (), {"headers": {"authorization": "Bearer invalid.token.value"}})()
    with pytest.raises(HTTPException) as error:
        get_current_identity(request)
    assert error.value.status_code == 401


def test_private_valid_signature_unknown_local_principal_is_rejected(monkeypatch):
    from fastapi import HTTPException

    class LocalUsers:
        def get_active_local_user(self, user_id):
            assert user_id == "stale-user"
            return None

    settings = get_settings()
    secret = "local-test-secret-key-at-least-32-bytes!!"
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_identity_mode", "private")
    monkeypatch.setattr(settings, "user_center_jwt_alg", "HS256")
    monkeypatch.setattr(settings, "auth_local_jwt_secret", secret)
    monkeypatch.setattr(settings, "user_center_jwt_secret", "")
    monkeypatch.setattr(
        "ai_hunter.app.services.user_service.get_user_service",
        lambda: LocalUsers(),
    )
    token = jwt.encode(
        {"sub": "stale-user", "name": "旧会话用户", "auth_source": "local"},
        secret,
        algorithm="HS256",
    )
    request = type("Request", (), {"headers": {"authorization": f"Bearer {token}"}})()

    with pytest.raises(HTTPException) as error:
        get_current_identity(request)

    assert error.value.status_code == 401
    assert "重新登录" in str(error.value.detail)


def test_private_known_active_superadmin_uses_local_principal(monkeypatch):
    class LocalUsers:
        def get_active_local_user(self, user_id):
            assert user_id == "local_super_admin"
            return {
                "user_id": user_id,
                "username": "本地超级管理员",
                "company_id": "",
                "auth_source": "local",
                "status": "active",
                "is_super_admin": True,
            }

        def list_user_roles(self, user_id, *, company_id=""):
            assert user_id == "local_super_admin"
            assert company_id == ""
            return ["super_admin"]

    settings = get_settings()
    secret = "local-test-secret-key-at-least-32-bytes!!"
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_identity_mode", "private")
    monkeypatch.setattr(settings, "auth_legacy_roles_enabled", False)
    monkeypatch.setattr(settings, "user_center_jwt_alg", "HS256")
    monkeypatch.setattr(settings, "auth_local_jwt_secret", secret)
    monkeypatch.setattr(settings, "user_center_jwt_secret", "")
    monkeypatch.setattr(
        "ai_hunter.app.services.user_service.get_user_service",
        lambda: LocalUsers(),
    )
    token = jwt.encode(
        {
            "sub": "local_super_admin",
            "name": "过期显示名",
            "company": "untrusted-company",
            "is_super_admin": False,
            "auth_source": "local",
        },
        secret,
        algorithm="HS256",
    )
    request = type("Request", (), {"headers": {"authorization": f"Bearer {token}"}})()

    identity = get_current_identity(request)

    assert identity.user_id == "local_super_admin"
    assert identity.username == "本地超级管理员"
    assert identity.company_id == ""
    assert identity.roles == ["super_admin"]
    assert identity.is_super_admin is True
    assert identity.is_admin is True


def test_private_development_headers_do_not_require_local_jwt_principal(monkeypatch):
    class LocalUsers:
        def get_active_local_user(self, _user_id):
            raise AssertionError("development headers must not use the local JWT lookup")

        def list_user_roles(self, _user_id, *, company_id=""):
            assert company_id == "co-dev"
            return []

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_identity_mode", "private")
    monkeypatch.setattr(settings, "auth_dev_trust_headers", True)
    monkeypatch.setattr(settings, "auth_legacy_roles_enabled", True)
    monkeypatch.setattr(settings, "auth_local_jwt_secret", "")
    monkeypatch.setattr(settings, "user_center_jwt_secret", "")
    monkeypatch.setattr(settings, "user_center_jwt_public_key", "")
    monkeypatch.setattr(
        "ai_hunter.app.services.user_service.get_user_service",
        lambda: LocalUsers(),
    )
    request = type(
        "Request",
        (),
        {
            "headers": {
                "x-user-id": "dev-user",
                "x-user-name": "开发用户",
                "x-user-roles": "auditor",
                "x-company-id": "co-dev",
            }
        },
    )()

    identity = get_current_identity(request)

    assert identity.user_id == "dev-user"
    assert identity.roles == ["auditor"]
    assert identity.authenticated is False
