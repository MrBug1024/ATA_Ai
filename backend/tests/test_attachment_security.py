from __future__ import annotations

import hashlib
from datetime import timezone
from io import BytesIO

import pytest
from docx import Document

from ai_hunter.annual_audit.attachments.content_schemas import (
    AttachmentRenderError,
    BindingManifest,
    ResolvedDocumentPayload,
    ResolvedSlotPayload,
)
from ai_hunter.annual_audit.attachments.renderers.docx import render_docx
from ai_hunter.annual_audit.attachments.ticket_service import (
    ArtifactTicketError,
    issue_ticket,
    verify_ticket,
)
from ai_hunter.app.api import routes_artifacts
from ai_hunter.app.api.routes_artifacts import _resolve_range
from ai_hunter.app.auth.identity import Identity
from ai_hunter.app.middleware import access_log_path
from ai_hunter.app.settings import get_settings


def _docx_with_expression(expression: str) -> bytes:
    document = Document()
    document.add_paragraph(expression)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_docx_runtime_sandbox_rejects_undeclared_calls_and_filters() -> None:
    template = _docx_with_expression("{{ title }} / {{ range(2)|list }}")
    manifest = BindingManifest(
        document_code="audit_report",
        source_template_sha256=hashlib.sha256(template).hexdigest(),
        slots=[
            {
                "slot_id": "title",
                "target": "docx:jinja:title",
                "source": "document.report.title",
                "value_type": "scalar",
                "required": True,
                "missing_policy": "block",
            }
        ],
    )
    payload = ResolvedDocumentPayload(
        document_code="audit_report",
        slots=[ResolvedSlotPayload(slot_id="title", kind="scalar", value="Safe")],
    )

    with pytest.raises(AttachmentRenderError):
        render_docx(template, payload, manifest)


def test_artifact_ticket_is_opaque_expiring_and_bound_to_server_record(monkeypatch) -> None:
    from ai_hunter.annual_audit.attachments import ticket_service

    settings = get_settings().model_copy(update={"attachment_ticket_ttl_seconds": 60})
    recorded = {}
    monkeypatch.setattr(
        ticket_service.repository,
        "get_artifact",
        lambda **_kwargs: {"file_name": "审计报告.docx", "content_type": "application/docx"},
    )
    monkeypatch.setattr(
        ticket_service.repository,
        "record_ticket",
        lambda **kwargs: recorded.update(kwargs),
    )
    monkeypatch.setattr(
        ticket_service.repository,
        "get_ticket",
        lambda ticket_id, **_kwargs: (
            {
                "ticket_id": ticket_id,
                "artifact_id": recorded["artifact_id"],
                "engagement_id": recorded["engagement_id"],
                "purpose": recorded["purpose"],
                "actor_user_id": recorded["actor_user_id"],
                "expires_at": recorded["expires_at"],
            }
            if ticket_id == recorded.get("ticket_id")
            else None
        ),
    )

    ticket = issue_ticket(
        engagement_id=7,
        artifact_id="artifact-id",
        purpose="download",
        actor_user_id="user-id",
        settings=settings,
    )
    token = ticket["url"].rsplit("/", 1)[-1]
    claims = verify_ticket(token, settings=settings)

    assert claims["case"] == 7
    assert claims["artifact"] == "artifact-id"
    assert claims["user"] == "user-id"
    assert recorded["expires_at"].tzinfo is timezone.utc
    assert token == recorded["ticket_id"]
    assert "artifact-id" not in token
    assert "user-id" not in token
    with pytest.raises(ArtifactTicketError):
        verify_ticket("00000000-0000-4000-8000-000000000000", settings=settings)


def test_artifact_ticket_consumption_rechecks_ticket_user(monkeypatch) -> None:
    monkeypatch.setattr(routes_artifacts, "_case_identity", lambda *_args: None)
    monkeypatch.setattr(
        routes_artifacts,
        "verify_ticket",
        lambda _token: {
            "jti": "ticket-id",
            "case": 7,
            "artifact": "artifact-id",
            "purpose": "download",
            "user": "owner-id",
        },
    )

    with pytest.raises(Exception) as caught:
        routes_artifacts.consume_artifact_ticket(
            "opaque-token",
            type("RequestStub", (), {"headers": {}})(),
            Identity(user_id="other-id"),
        )

    assert getattr(caught.value, "status_code", None) == 403


def test_artifact_access_token_is_redacted_from_access_logs() -> None:
    assert (
        access_log_path("/api/artifact-access/0f41f88b-13e3-4fd7-a196-f1b7801b5d4f")
        == "/api/artifact-access/{token}"
    )
    assert access_log_path("/api/annual-audit/7/facts") == "/api/annual-audit/7/facts"


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 100, (0, 99, 200)),
        ("bytes=10-19", 100, (10, 19, 206)),
        ("bytes=90-", 100, (90, 99, 206)),
        ("bytes=-10", 100, (90, 99, 206)),
    ],
)
def test_range_resolution(header, size, expected) -> None:
    assert _resolve_range(header, size) == expected
