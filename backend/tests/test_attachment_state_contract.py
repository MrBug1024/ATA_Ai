from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from ai_hunter.annual_audit.attachments import job_service, repository
from ai_hunter.app.workers import attachment_tasks
from ai_hunter.app.services import minio_service


class _Cursor:
    def __init__(self, *, job=None, items=None, artifacts=None, rowcounts=None):
        self.job = job
        self.items = items or []
        self.artifacts = artifacts or []
        self.rowcounts = list(rowcounts or [])
        self.rowcount = 0
        self.execute_count = 0
        self.statements: list[str] = []
        self.parameters: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=()):
        self.statements.append(" ".join(str(statement).split()))
        self.parameters.append(tuple(_params))
        if self.rowcounts:
            self.rowcount = self.rowcounts.pop(0)
        self.execute_count += 1

    def fetchone(self):
        return self.job

    def fetchall(self):
        if self.execute_count == 2:
            return self.items
        if self.execute_count == 3:
            return self.artifacts
        return []


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


def _postgres_context(connection):
    @contextmanager
    def factory(_settings=None):
        yield connection

    return factory


def test_public_job_snapshot_strips_internal_storage_and_lease_fields(monkeypatch) -> None:
    cursor = _Cursor(
        job={
            "id": "job-id",
            "engagement_id": 7,
            "status": "running",
            "template_snapshot_json": '{"version_label":"v3","business_type":"annual_audit"}',
            "fact_snapshot_ref": "minio://private/context.json",
            "fact_snapshot_sha256": "a" * 64,
            "input_fingerprint": "b" * 64,
            "dedupe_fingerprint": "b" * 64,
            "request_idempotency_key_hash": "c" * 64,
            "model_manifest_json": '{"provider":"internal","api_key":"must-not-leak"}',
            "renderer_manifest_json": '{"image_digest":"private"}',
            "lease_token": "lease-secret",
            "lease_expires_at": None,
            "requested_by": "internal-user-id",
            "thread_id": "internal-thread-id",
            "assistant_turn_id": "public-turn-id",
        },
        items=[
            {
                "id": "item-id",
                "status": "running",
                "binding_manifest_json": '{"slots":[{"slot_id":"x"}]}',
                "payload_ref": "minio://private/payload.json",
                "payload_sha256": "d" * 64,
                "quality_report_json": '{"passed":true}',
                "source_template_sha256": "e" * 64,
                "compiled_template_sha256": "f" * 64,
                "lease_token": "lease-secret",
            }
        ],
        artifacts=[
            {
                "id": "artifact-id",
                "status": "validated",
                "delivery_approved": False,
                "object_ref": "minio://private/artifact.docx",
                "preview_ref": "minio://private/artifact.pdf",
                "preview_sha256": "1" * 64,
                "provenance_manifest_ref": "minio://private/provenance.json",
                "provenance_sha256": "2" * 64,
                "created_by": "internal-user-id",
                "published_by": "internal-reviewer-id",
                "quality_report_json": '{"passed":true,"issues":[]}',
            }
        ],
    )
    connection = _Connection(cursor)
    monkeypatch.setattr(repository, "postgres_connection", _postgres_context(connection))

    snapshot = repository.get_job(job_id="job-id", engagement_id=7, settings=SimpleNamespace())

    assert snapshot is not None
    assert snapshot["template_version_label"] == "v3"
    for field in {
        "template_snapshot",
        "fact_snapshot_ref",
        "fact_snapshot_sha256",
        "input_fingerprint",
        "dedupe_fingerprint",
        "request_idempotency_key_hash",
        "model_manifest",
        "renderer_manifest",
        "lease_token",
        "lease_expires_at",
        "requested_by",
        "thread_id",
    }:
        assert field not in snapshot
    assert snapshot["assistant_turn_id"] == "public-turn-id"
    for field in {
        "binding_manifest",
        "payload_ref",
        "payload_sha256",
        "quality_report",
        "source_template_sha256",
        "compiled_template_sha256",
        "lease_token",
    }:
        assert field not in snapshot["items"][0]
    assert snapshot["artifacts"][0]["quality_status"] == "passed"
    assert snapshot["artifacts"][0]["preview_available"] is True
    assert "等待完整附件包原子发布" in snapshot["artifacts"][0]["quality_summary"]
    for field in {
        "quality_report",
        "object_ref",
        "preview_ref",
        "preview_sha256",
        "provenance_manifest_ref",
        "provenance_sha256",
        "created_by",
        "published_by",
    }:
        assert field not in snapshot["artifacts"][0]
    assert "artifact.preview_ref" in cursor.statements[2]


def test_job_level_failure_without_failed_item_is_retryable(monkeypatch) -> None:
    cursor = _Cursor(
        job={"id": "job-id", "engagement_id": 7, "status": "failed"},
        items=[{"id": "item-id", "status": "queued"}],
    )
    monkeypatch.setattr(
        repository,
        "postgres_connection",
        _postgres_context(_Connection(cursor)),
    )

    snapshot = repository.get_job(job_id="job-id", engagement_id=7, settings=SimpleNamespace())

    assert snapshot is not None
    assert snapshot["retryable"] is True


def test_retry_failed_job_requeues_job_level_and_lost_worker_failures(monkeypatch) -> None:
    cursor = _Cursor(job={"status": "failed"})
    connection = _Connection(cursor)
    monkeypatch.setattr(repository, "postgres_connection", _postgres_context(connection))

    changed = repository.retry_failed_job("job-id", settings=SimpleNamespace())

    assert changed is True
    assert connection.commits == 1
    assert any("status IN ('failed','running')" in statement for statement in cursor.statements)
    assert any("INSERT INTO annual_attachment_outbox" in statement for statement in cursor.statements)


def test_lost_item_lease_cannot_mark_whole_job_failed(monkeypatch) -> None:
    cursor = _Cursor(rowcounts=[0])
    connection = _Connection(cursor)
    monkeypatch.setattr(repository, "postgres_connection", _postgres_context(connection))

    changed = repository.fail_item(
        job_id="job-id",
        item_id="item-id",
        stage="rendering",
        error_code="ERROR",
        error_summary="focused",
        lease_token="old-lease",
        settings=SimpleNamespace(),
    )

    assert changed is False
    assert len(cursor.statements) == 1
    assert "job.lease_token = %s" in cursor.statements[0]


def test_outbox_batch_claim_is_locked_and_moves_events_to_publishing(monkeypatch) -> None:
    class OutboxCursor(_Cursor):
        def __init__(self):
            super().__init__()
            self.rows = [
                {
                    "id": 11,
                    "job_id": "job-11",
                    "event_type": "attachment.generate",
                    "attempt_count": 2,
                },
                {
                    "id": 12,
                    "job_id": "job-12",
                    "event_type": "attachment.generate",
                    "attempt_count": 0,
                },
            ]

        def execute(self, statement, params=()):
            super().execute(statement, params)
            if self.execute_count == 2:
                self.rowcount = len(self.rows)

        def fetchall(self):
            return self.rows

    cursor = OutboxCursor()
    connection = _Connection(cursor)
    monkeypatch.setattr(repository, "postgres_connection", _postgres_context(connection))

    events = repository.claim_pending_outbox(
        limit=500,
        stale_after_seconds=15,
        settings=SimpleNamespace(),
    )

    assert connection.commits == 1
    assert [event["status"] for event in events] == ["publishing", "publishing"]
    assert [event["attempt_count"] for event in events] == [3, 1]
    assert "status IN ('pending','failed')" in cursor.statements[0]
    assert "status = 'publishing'" in cursor.statements[0]
    assert "FOR UPDATE SKIP LOCKED" in cursor.statements[0]
    assert cursor.parameters[0] == (60, 100)
    assert "SET status = 'publishing'" in cursor.statements[1]
    assert "attempt_count = attempt_count + 1" in cursor.statements[1]
    assert cursor.parameters[1] == (11, 12)


def test_outbox_result_uses_status_and_attempt_cas(monkeypatch) -> None:
    successful_cursor = _Cursor(rowcounts=[1])
    successful_connection = _Connection(successful_cursor)
    monkeypatch.setattr(
        repository,
        "postgres_connection",
        _postgres_context(successful_connection),
    )

    assert repository.mark_outbox_result(
        11,
        attempt_count=3,
        published=True,
        settings=SimpleNamespace(),
    ) is True
    assert "status = 'publishing'" in successful_cursor.statements[0]
    assert "attempt_count = %s" in successful_cursor.statements[0]
    assert successful_cursor.parameters[0][-2:] == (11, 3)

    late_cursor = _Cursor(rowcounts=[0])
    late_connection = _Connection(late_cursor)
    monkeypatch.setattr(
        repository,
        "postgres_connection",
        _postgres_context(late_connection),
    )

    assert repository.mark_outbox_result(
        11,
        attempt_count=2,
        published=False,
        error="late failure",
        settings=SimpleNamespace(),
    ) is False
    assert late_connection.commits == 1


def test_dispatch_marks_the_exact_claim_attempt(monkeypatch) -> None:
    settings = SimpleNamespace(
        attachment_worker_eager=False,
        attachment_celery_broker_url="redis://broker",
        attachment_celery_queue="attachment-generation",
        attachment_job_stale_seconds=321,
    )
    claimed: list[dict] = []
    marked: list[dict] = []
    published_jobs: list[tuple[list[str], str]] = []

    def fake_claim(**kwargs):
        claimed.append(kwargs)
        return [{"id": 11, "job_id": "job-11", "attempt_count": 4}]

    def fake_mark(outbox_id, **kwargs):
        marked.append({"outbox_id": outbox_id, **kwargs})
        return True

    monkeypatch.setattr(job_service.repository, "claim_pending_outbox", fake_claim)
    monkeypatch.setattr(job_service.repository, "mark_outbox_result", fake_mark)
    monkeypatch.setattr(
        attachment_tasks.generate_attachment_job,
        "apply_async",
        lambda *, args, queue: published_jobs.append((args, queue)),
    )

    assert job_service.dispatch_pending_outbox(limit=7, settings=settings) == 1
    assert claimed == [
        {"limit": 7, "stale_after_seconds": 321, "settings": settings}
    ]
    assert published_jobs == [(["job-11"], "attachment-generation")]
    assert marked == [
        {
            "outbox_id": 11,
            "attempt_count": 4,
            "published": True,
            "settings": settings,
        }
    ]


def test_postgres_baseline_uses_lease_cas_and_cancel_releases_fingerprint() -> None:
    sql = (
        Path(__file__).resolve().parents[1] / "sql" / "annual_audit_postgres_v3.sql"
    ).read_text(encoding="utf-8")

    assert "lease_token varchar(36)" in sql
    assert "lease_expires_at timestamptz" in sql
    assert "dedupe_fingerprint char(64) GENERATED ALWAYS AS" in sql
    assert "UNIQUE (dedupe_fingerprint)" in sql
    assert "UNIQUE (engagement_id, request_idempotency_key_hash)" in sql


def test_create_job_rejects_concurrent_reuse_of_one_idempotency_key(monkeypatch) -> None:
    class ConflictCursor:
        def __init__(self) -> None:
            self.query = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, _params=()):
            self.query = " ".join(str(statement).split())

        def fetchone(self):
            if "INSERT INTO annual_attachment_generation_job" in self.query:
                return None
            if "request_idempotency_key_hash" in self.query:
                return {"id": "existing", "input_fingerprint": "different"}
            return None

    cursor = ConflictCursor()
    connection = _Connection(cursor)
    monkeypatch.setattr(repository, "postgres_connection", _postgres_context(connection))

    with pytest.raises(repository.AttachmentIdempotencyConflictError):
        repository.create_job_with_outbox(
            job={
                "id": "new-job",
                "engagement_id": 7,
                "report_id": 8,
                "report_version": 1,
                "template_family_id": "family",
                "template_version_id": "version",
                "template_snapshot": {},
                "template_content_sha256": "a" * 64,
                "fact_snapshot_ref": "minio://artifacts/context",
                "fact_snapshot_sha256": "b" * 64,
                "input_fingerprint": "c" * 64,
                "request_idempotency_key_hash": "d" * 64,
                "requested_by": "tester",
            },
            items=[],
            settings=SimpleNamespace(),
        )


def test_cancelling_queued_job_releases_only_to_retention(monkeypatch) -> None:
    class CancelCursor(_Cursor):
        def execute(self, statement, params=()):
            super().execute(statement, params)
            if "UPDATE annual_attachment_generation_job" in self.statements[-1]:
                self.rowcount = 1

    cursor = CancelCursor()
    connection = _Connection(cursor)
    monkeypatch.setattr(repository, "postgres_connection", _postgres_context(connection))

    assert repository.cancel_queued_job("job-id", settings=SimpleNamespace()) is True

    sql = "\n".join(cursor.statements)
    assert "UPDATE annual_attachment_storage_reference" in sql
    assert "retention_state = 'retained'" in sql
    assert "DELETE FROM" not in sql.upper()


def test_attachment_object_keys_are_content_addressed(monkeypatch) -> None:
    service = object.__new__(minio_service.MinioService)
    service.enabled = True
    service.bucket_artifacts = "artifacts"
    captured: list[str] = []

    def fake_put(self, *, bucket, object_key, content_type, file_bytes, metadata=None):
        captured.append(object_key)
        return SimpleNamespace(storage_ref=f"minio://{bucket}/{object_key}")

    service._put_bytes = MethodType(fake_put, service)
    monkeypatch.setattr(
        minio_service,
        "scoped_object_key",
        lambda _settings, *, project_id, category, parts: "/".join(
            (str(project_id), category, *parts)
        ),
    )

    values = (b"same", b"same", b"different")
    for value in values:
        service.upload_attachment_blob(
            project_id=7,
            blob_id="123e4567-e89b-12d3-a456-426614174000",
            category="artifacts",
            file_name="result.docx",
            content_type="application/octet-stream",
            file_bytes=value,
        )

    assert captured[0] == captured[1]
    assert captured[0] != captured[2]
