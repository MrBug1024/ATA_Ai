"""Short-lived opaque tickets for artifact preview and download."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from ai_hunter.app.settings import Settings, get_settings

from . import repository


class ArtifactTicketError(ValueError):
    pass


def issue_ticket(
    *,
    engagement_id: int,
    artifact_id: str,
    purpose: str,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if purpose not in {"download", "preview"}:
        raise ArtifactTicketError("unsupported ticket purpose")
    resolved = settings or get_settings()
    artifact = repository.get_artifact(
        engagement_id=engagement_id,
        artifact_id=artifact_id,
        purpose=purpose,
        settings=resolved,
    )
    if artifact is None:
        raise LookupError("artifact is not available for this purpose")
    now = datetime.now(timezone.utc)
    ttl_seconds = min(max(30, int(resolved.attachment_ticket_ttl_seconds)), 15 * 60)
    expires_at = now + timedelta(seconds=ttl_seconds)
    ticket_id = str(uuid4())
    repository.record_ticket(
        artifact_id=artifact_id,
        engagement_id=engagement_id,
        purpose=purpose,
        actor_user_id=actor_user_id,
        ticket_id=ticket_id,
        expires_at=expires_at,
        settings=resolved,
    )
    file_name = str(artifact.get("file_name") or "attachment")
    if purpose == "preview":
        file_name = file_name.rsplit(".", 1)[0] + ".pdf"
    return {
        "url": f"/api/artifact-access/{ticket_id}",
        "expires_at": expires_at.isoformat(),
        "content_type": "application/pdf" if purpose == "preview" else artifact.get("content_type"),
        "file_name": file_name,
    }


def verify_ticket(token: str, *, settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    try:
        ticket_id = str(UUID(str(token or "")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ArtifactTicketError("malformed artifact ticket") from exc
    record = repository.get_ticket(ticket_id, settings=resolved)
    if record is None:
        raise ArtifactTicketError("artifact ticket is invalid or expired")
    purpose = str(record.get("purpose") or "")
    if purpose not in {"download", "preview"}:
        raise ArtifactTicketError("invalid artifact ticket purpose")
    artifact_id = str(record.get("artifact_id") or "").strip()
    actor_user_id = str(record.get("actor_user_id") or "").strip()
    engagement_id = int(record.get("engagement_id") or 0)
    if not artifact_id or not actor_user_id:
        raise ArtifactTicketError("artifact ticket is incomplete")
    if engagement_id <= 0:
        raise ArtifactTicketError("artifact ticket case is invalid")
    return {
        "jti": ticket_id,
        "case": engagement_id,
        "artifact": artifact_id,
        "purpose": purpose,
        "user": actor_user_id,
        "expires_at": record.get("expires_at"),
    }


__all__ = ["ArtifactTicketError", "issue_ticket", "verify_ticket"]
