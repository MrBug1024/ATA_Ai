from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_hunter.annual_audit.attachments import job_service
from ai_hunter.app.api import routes_artifacts
from ai_hunter.app.api.routes_artifacts import (
    CreateAttachmentJobRequest,
    FactUpsertRequest,
)
from ai_hunter.app.auth.identity import Identity


def _identity(role: str) -> Identity:
    return Identity(user_id=f"{role}-user", roles=[role])


@pytest.fixture(autouse=True)
def bypass_case_lookup(monkeypatch):
    monkeypatch.setattr(routes_artifacts, "_case_identity", lambda _case, identity: identity)


@pytest.mark.parametrize("role", ["auditor", "audit_assistant", "company_admin"])
def test_fact_confirmation_requires_existing_project_control_role(monkeypatch, role) -> None:
    monkeypatch.setattr(
        routes_artifacts.repository,
        "upsert_fact_version",
        lambda **_kwargs: pytest.fail("unauthorized fact was persisted"),
    )

    with pytest.raises(HTTPException) as caught:
        routes_artifacts.put_engagement_fact(
            7,
            "entity.registered_capital",
            FactUpsertRequest(value=500, status="confirmed"),
            _identity(role),
        )

    assert caught.value.status_code == 403


def test_candidate_fact_remains_available_to_case_report_user(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        routes_artifacts.repository,
        "upsert_fact_version",
        lambda **kwargs: captured.update(kwargs) or {"id": 1},
    )

    result = routes_artifacts.put_engagement_fact(
        7,
        "entity.registered_capital",
        FactUpsertRequest(
            value=500,
            status="candidate",
            source_kind="material_extraction",
        ),
        _identity("audit_assistant"),
    )

    assert result == {"id": 1}
    assert captured["reviewed"] is False


@pytest.mark.parametrize(
    ("role", "fact_status"),
    [
        ("engagement_manager", "confirmed"),
        ("reviewer", "conflicted"),
        ("engagement_partner", "rejected"),
    ],
)
def test_existing_project_control_roles_can_review_fact(
    monkeypatch, role, fact_status
) -> None:
    captured = {}
    monkeypatch.setattr(
        routes_artifacts.repository,
        "upsert_fact_version",
        lambda **kwargs: captured.update(kwargs) or {"id": 2},
    )

    routes_artifacts.put_engagement_fact(
        7,
        "entity.registered_capital",
        FactUpsertRequest(value=500, status=fact_status),
        _identity(role),
    )

    assert captured["reviewed"] is True
    assert captured["actor_user_id"] == f"{role}-user"


def test_final_candidate_requires_project_control_but_review_draft_does_not(
    monkeypatch,
) -> None:
    created: list[str] = []
    monkeypatch.setattr(
        job_service,
        "create_attachment_job",
        lambda **kwargs: created.append(kwargs["delivery_level"]) or {"id": "job"},
    )
    monkeypatch.setattr(job_service, "dispatch_pending_outbox", lambda **_kwargs: 1)
    auditor = _identity("auditor")

    routes_artifacts.create_attachment_job(
        7,
        CreateAttachmentJobRequest(report_id=3, delivery_level="review_draft"),
        auditor,
    )
    with pytest.raises(HTTPException) as caught:
        routes_artifacts.create_attachment_job(
            7,
            CreateAttachmentJobRequest(report_id=3, delivery_level="final_candidate"),
            auditor,
        )
    routes_artifacts.create_attachment_job(
        7,
        CreateAttachmentJobRequest(report_id=3, delivery_level="final_candidate"),
        _identity("reviewer"),
    )

    assert caught.value.status_code == 403
    assert created == ["review_draft", "final_candidate"]


def test_issued_level_uses_existing_engagement_partner_boundary(monkeypatch) -> None:
    monkeypatch.setattr(
        job_service,
        "create_attachment_job",
        lambda **_kwargs: {"id": "job"},
    )
    monkeypatch.setattr(job_service, "dispatch_pending_outbox", lambda **_kwargs: 1)

    with pytest.raises(HTTPException) as caught:
        routes_artifacts.create_attachment_job(
            7,
            CreateAttachmentJobRequest(report_id=3, delivery_level="issued"),
            _identity("reviewer"),
        )
    allowed = routes_artifacts.create_attachment_job(
        7,
        CreateAttachmentJobRequest(report_id=3, delivery_level="issued"),
        _identity("engagement_partner"),
    )

    assert caught.value.status_code == 403
    assert allowed == {"id": "job"}


def test_ticket_requires_visibility_of_every_report_section(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_artifacts, "all_report_section_codes", lambda: {"scope", "opinion"}
    )
    monkeypatch.setattr(
        routes_artifacts,
        "visible_report_sections",
        lambda identity: {"scope", "opinion"}
        if "reviewer" in identity.roles
        else {"scope"},
    )
    monkeypatch.setattr(
        routes_artifacts,
        "issue_ticket",
        lambda **kwargs: {"artifact_id": kwargs["artifact_id"]},
    )

    with pytest.raises(HTTPException) as caught:
        routes_artifacts._ticket_response(7, "artifact", "download", _identity("auditor"))
    allowed = routes_artifacts._ticket_response(
        7, "artifact", "download", _identity("reviewer")
    )

    assert caught.value.status_code == 403
    assert allowed == {"artifact_id": "artifact"}


def test_old_preview_ticket_is_denied_after_report_section_role_downgrade(
    monkeypatch,
) -> None:
    identity = _identity("auditor")
    visible_sections = {"scope", "opinion"}
    monkeypatch.setattr(
        routes_artifacts, "all_report_section_codes", lambda: {"scope", "opinion"}
    )
    monkeypatch.setattr(
        routes_artifacts,
        "visible_report_sections",
        lambda _identity: set(visible_sections),
    )
    monkeypatch.setattr(
        routes_artifacts,
        "issue_ticket",
        lambda **_kwargs: {"url": "/api/artifact-access/old-preview-ticket"},
    )
    issued = routes_artifacts._ticket_response(
        7, "artifact", "preview", identity
    )

    visible_sections.remove("opinion")
    monkeypatch.setattr(
        routes_artifacts,
        "verify_ticket",
        lambda _token: {
            "jti": "ticket",
            "case": 7,
            "artifact": "artifact",
            "purpose": "preview",
            "user": identity.user_id,
        },
    )
    monkeypatch.setattr(
        routes_artifacts.repository,
        "get_artifact",
        lambda **_kwargs: pytest.fail("artifact read happened before ACL recheck"),
    )

    with pytest.raises(HTTPException) as caught:
        routes_artifacts.consume_artifact_ticket(
            "opaque-ticket",
            SimpleNamespace(headers={}),
            identity,
        )

    assert issued["url"].endswith("old-preview-ticket")
    assert caught.value.status_code == 403
