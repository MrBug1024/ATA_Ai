"""Dedicated Celery application for durable attachment work."""

from __future__ import annotations

from celery import Celery

from ai_hunter.app.settings import get_settings


settings = get_settings()
settings.require_runtime_storage()
broker_url = settings.attachment_celery_broker_url.strip()
if not broker_url:
    raise RuntimeError("Redis broker URL is required for attachment workers")
celery_app = Celery(
    "ai_hunter_annual_attachments",
    broker=broker_url,
    include=["ai_hunter.app.workers.attachment_tasks"],
)
celery_app.conf.update(
    task_default_queue=settings.attachment_celery_queue,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    task_ignore_result=True,
    task_always_eager=bool(settings.attachment_worker_eager),
    broker_transport_options={"visibility_timeout": 60 * 60},
    beat_schedule={
        "dispatch-annual-attachment-outbox": {
            "task": "annual_attachments.dispatch_outbox",
            "schedule": 10.0,
        }
    },
)


__all__ = ["celery_app"]
