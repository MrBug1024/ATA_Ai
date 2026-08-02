"""In-process upload ingest job runner used to decouple HTTP upload from long ingest work."""

from __future__ import annotations

import atexit
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable


LOGGER = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="upload-ingest")


def enqueue_upload_ingest_job(job_payload: dict, handler: Callable[[dict], None]) -> Future:
    """Submit one upload-ingest job to the shared executor."""
    if not isinstance(job_payload, dict):
        raise TypeError("job_payload must be a dict")
    return _EXECUTOR.submit(_run_job, dict(job_payload), handler)


def _run_job(job_payload: dict, handler: Callable[[dict], None]) -> None:
    """Wrap one background job so unexpected failures are always logged."""
    upload_batch_id = str(job_payload.get("upload_batch_id", "") or "")
    material_event_id = str(job_payload.get("material_event_id", "") or "")
    try:
        handler(job_payload)
    except Exception:
        LOGGER.exception(
            "upload_ingest_job_unhandled_failure upload_batch_id=%s material_event_id=%s",
            upload_batch_id,
            material_event_id,
        )
        raise


def shutdown_upload_ingest_jobs() -> None:
    """Best-effort executor shutdown on interpreter exit."""
    _EXECUTOR.shutdown(wait=False, cancel_futures=False)


atexit.register(shutdown_upload_ingest_jobs)
