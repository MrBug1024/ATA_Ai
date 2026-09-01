"""Celery tasks carrying only stable attachment job identifiers."""

from __future__ import annotations

from celery.exceptions import Retry

from .celery_app import celery_app


@celery_app.task(
    bind=True,
    name="annual_attachments.generate",
    autoretry_for=(),
    acks_late=True,
)
def generate_attachment_job(self, job_id: str) -> None:
    from ai_hunter.annual_audit.attachments.job_service import process_attachment_job
    from ai_hunter.app.settings import get_settings

    try:
        job_status = process_attachment_job(job_id)
        if job_status == "running":
            # A duplicate delivery may observe a live worker.  Recheck after
            # the durable stale lease so a worker-lost job is reclaimed rather
            # than acknowledged and abandoned.
            raise self.retry(
                countdown=max(65, get_settings().attachment_job_stale_seconds + 5),
                max_retries=5,
            )
    except Retry:
        raise
    except Exception as exc:
        # The durable job/item state records the focused error. Celery retry is
        # transport recovery and never becomes the business source of truth.
        raise self.retry(
            exc=exc,
            countdown=min(30 * (self.request.retries + 1), 300),
            max_retries=3,
        )


@celery_app.task(name="annual_attachments.dispatch_outbox")
def dispatch_attachment_outbox() -> int:
    from ai_hunter.annual_audit.attachments.job_service import dispatch_pending_outbox

    return dispatch_pending_outbox(limit=50)


__all__ = ["dispatch_attachment_outbox", "generate_attachment_job"]
