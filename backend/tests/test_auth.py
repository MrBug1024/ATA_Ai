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
