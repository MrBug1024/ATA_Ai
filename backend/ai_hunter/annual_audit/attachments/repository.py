"""PostgreSQL persistence for immutable attachment facts, jobs, and artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

from ai_hunter.app.settings import Settings, get_settings
from ai_hunter.annual_audit.storage import postgres_connection


TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
RUNNING_STAGES = frozenset(
    {
        "freezing_context",
        "loading_template",
        "composing_payload",
        "rendering",
        "validating",
        "previewing",
        "publishing",
    }
)
FACT_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\[\])?(?:\.[a-z][a-z0-9_]*(?:\[\])?)*$"
)


class AttachmentStateError(RuntimeError):
    """Raised when a durable attachment state transition is invalid."""


class AttachmentIdempotencyConflictError(AttachmentStateError):
    """Raised when one client idempotency key is reused for different input."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _fact_candidate_key(
    *,
    source_kind: str,
    source_ref: dict[str, Any] | None,
    evidence_refs: list[dict[str, Any]],
    actor_user_id: str,
) -> str:
    """Return the stable identity of one independently current fact source."""

    normalized_source_kind = str(source_kind or "").strip()
    normalized_source_ref = source_ref or {}
    source_identity: dict[str, Any]
    if normalized_source_kind == "manual_review":
        source_identity = {"actor_user_id": str(actor_user_id or "system")}
    elif normalized_source_ref:
        source_identity = {"source_ref": normalized_source_ref}
    elif evidence_refs:
        source_identity = {
            "evidence_refs": sorted(
                evidence_refs,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=_json_default,
                ),
            )
        }
    else:
        source_identity = {"actor_user_id": str(actor_user_id or "system")}
    encoded = json.dumps(
        {
            "source_kind": normalized_source_kind,
            **source_identity,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decode_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
        elif key.endswith("_json"):
            result[key.removesuffix("_json")] = _decode_json(value, {} if "snapshot" in key or "manifest" in key or "report" in key else [])
            result.pop(key, None)
        elif isinstance(value, (bytes, bytearray)) and len(value) == 1:
            result[key] = bool(value[0])
    for key in ("delivery_approved", "is_current"):
        if key in result:
            result[key] = bool(result[key])
    return result


def _storage_ref_hash(storage_ref: str) -> str:
    return hashlib.sha256(storage_ref.encode("utf-8")).hexdigest()


def _register_attachment_storage_reference(
    cursor: Any,
    *,
    storage_ref: str,
    object_kind: str,
    content_sha256: str,
    owner_type: str,
    owner_id: str,
    owner_field: str,
    actor: str,
    managed_exclusive: bool,
) -> None:
    """Register one immutable object owner without promoting legacy objects."""

    normalized_ref = str(storage_ref or "").strip()
    if not normalized_ref:
        return
    ref_hash = _storage_ref_hash(normalized_ref)
    cursor.execute(
        """
        INSERT INTO annual_attachment_storage_object (
          storage_ref_hash, storage_ref, object_kind, content_sha256,
          management_scope, retention_state
        ) VALUES (%s, %s, %s, %s, %s, 'active')
        ON CONFLICT (storage_ref_hash) DO UPDATE SET
          last_seen_at = now(),
          retention_state = CASE WHEN annual_attachment_storage_object.retention_state = 'legal_hold' THEN 'legal_hold' ELSE 'active' END,
          retention_until = CASE WHEN annual_attachment_storage_object.retention_state = 'legal_hold' THEN annual_attachment_storage_object.retention_until ELSE NULL END,
          unreferenced_at = CASE WHEN annual_attachment_storage_object.retention_state = 'legal_hold' THEN annual_attachment_storage_object.unreferenced_at ELSE NULL END,
          content_sha256 = COALESCE(annual_attachment_storage_object.content_sha256, EXCLUDED.content_sha256)
        """,
        (
            ref_hash,
            normalized_ref,
            object_kind,
            content_sha256 or None,
            "managed_exclusive" if managed_exclusive else "legacy_unknown",
        ),
    )
    cursor.execute(
        """
        INSERT INTO annual_attachment_storage_reference (
          storage_ref_hash, owner_type, owner_id, owner_field, acquired_by
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (storage_ref_hash, owner_type, owner_id, owner_field) DO UPDATE SET
          released_by = NULL, release_reason = NULL, released_at = NULL,
          acquired_by = EXCLUDED.acquired_by, acquired_at = now()
        """,
        (ref_hash, owner_type, owner_id, owner_field, actor or "system"),
    )


def _release_attachment_storage_references(
    cursor: Any,
    *,
    owner_type: str,
    owner_id: str,
    actor: str,
    reason: str,
) -> None:
    """Release an owner's managed objects into the retention window.

    The planner only ever marks candidates; this transition never deletes
    MinIO bytes. Objects shared by another live owner remain active.
    """

    cursor.execute(
        """
        UPDATE annual_attachment_storage_reference
        SET released_at = now(), released_by = %s, release_reason = %s
        WHERE owner_type = %s AND owner_id = %s AND released_at IS NULL
        """,
        (actor or "system", reason, owner_type, owner_id),
    )
    cursor.execute(
        """
        UPDATE annual_attachment_storage_object AS storage_object
        SET retention_state = 'retained',
            unreferenced_at = COALESCE(storage_object.unreferenced_at, now()),
            retention_until = COALESCE(
                storage_object.retention_until,
                now() + INTERVAL '30 days'
            ),
            last_seen_at = now()
        WHERE storage_object.management_scope = 'managed_exclusive'
          AND storage_object.storage_ref_hash IN (
            SELECT owner_ref.storage_ref_hash
            FROM annual_attachment_storage_reference AS owner_ref
            WHERE owner_ref.owner_type = %s AND owner_ref.owner_id = %s
          )
          AND NOT EXISTS (
            SELECT 1
            FROM annual_attachment_storage_reference AS live_owner
            WHERE live_owner.storage_ref_hash = storage_object.storage_ref_hash
              AND live_owner.released_at IS NULL
          )
        """,
        (owner_type, owner_id),
    )


def list_current_facts(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, engagement_id, fact_key, value_json, display_value,
                       data_type, status, source_kind, source_ref_json,
                       evidence_refs_json, revision, is_current, reviewed_by,
                       reviewed_at, created_by, created_at
                FROM annual_engagement_fact
                WHERE engagement_id = %s AND is_current = TRUE
                ORDER BY fact_key, source_kind, revision
                """,
                (engagement_id,),
            )
            rows = cursor.fetchall()
    facts: list[dict[str, Any]] = []
    for row in rows:
        item = _serialize_row(dict(row))
        item["value"] = item.pop("value", _decode_json(row.get("value_json"), None))
        item["source_ref"] = _decode_json(row.get("source_ref_json"), {})
        item["evidence_refs"] = _decode_json(row.get("evidence_refs_json"), [])
        facts.append(item)
    return facts


def upsert_fact_version(
    *,
    engagement_id: int,
    fact_key: str,
    value: Any,
    display_value: str | None,
    data_type: str,
    status: str,
    source_kind: str,
    source_ref: dict[str, Any] | None,
    evidence_refs: list[dict[str, Any]],
    actor_user_id: str,
    reviewed: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if status not in {"candidate", "confirmed", "conflicted", "rejected"}:
        raise ValueError("unsupported fact status")
    normalized_key = str(fact_key or "").strip()
    if not FACT_KEY_PATTERN.fullmatch(normalized_key):
        raise ValueError("fact_key must be a canonical dotted identifier")
    normalized_source_kind = str(source_kind or "").strip()
    if not normalized_source_kind:
        raise ValueError("source_kind must not be blank")
    candidate_key = _fact_candidate_key(
        source_kind=normalized_source_kind,
        source_ref=source_ref,
        evidence_refs=evidence_refs,
        actor_user_id=actor_user_id,
    )
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM audit_engagement
                WHERE id = %s
                FOR UPDATE
                """,
                (engagement_id,),
            )
            if cursor.fetchone() is None:
                raise LookupError("annual audit engagement not found")
            cursor.execute(
                """
                SELECT COALESCE(MAX(revision), 0) AS max_revision
                FROM annual_engagement_fact
                WHERE engagement_id = %s AND fact_key = %s
                """,
                (engagement_id, normalized_key),
            )
            revision_row = cursor.fetchone() or {}
            revision = int(revision_row.get("max_revision") or 0) + 1
            cursor.execute(
                """
                SELECT id
                FROM annual_engagement_fact
                WHERE engagement_id = %s
                  AND fact_key = %s
                  AND is_current = TRUE
                  AND (
                    candidate_key = %s
                    OR (
                      candidate_key LIKE 'legacy:%%'
                      AND source_kind = %s
                      AND created_by = %s
                    )
                  )
                FOR UPDATE
                """,
                (
                    engagement_id,
                    normalized_key,
                    candidate_key,
                    normalized_source_kind,
                    actor_user_id,
                ),
            )
            current = cursor.fetchall()
            if current:
                cursor.execute(
                    """
                    UPDATE annual_engagement_fact
                    SET is_current = FALSE
                    WHERE engagement_id = %s
                      AND fact_key = %s
                      AND is_current = TRUE
                      AND (
                        candidate_key = %s
                        OR (
                          candidate_key LIKE 'legacy:%%'
                          AND source_kind = %s
                          AND created_by = %s
                        )
                      )
                    """,
                    (
                        engagement_id,
                        normalized_key,
                        candidate_key,
                        normalized_source_kind,
                        actor_user_id,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO annual_engagement_fact (
                  engagement_id, fact_key, candidate_key, value_json,
                  display_value, data_type,
                  status, source_kind, source_ref_json, evidence_refs_json,
                  revision, is_current, reviewed_by, reviewed_at, created_by
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE,
                  %s, CASE WHEN %s THEN now() ELSE NULL END, %s
                )
                RETURNING id
                """,
                (
                    engagement_id,
                    normalized_key,
                    candidate_key,
                    _json(value),
                    display_value,
                    data_type,
                    status,
                    normalized_source_kind,
                    _json(source_ref or {}),
                    _json(evidence_refs),
                    revision,
                    actor_user_id if reviewed else None,
                    reviewed,
                    actor_user_id,
                ),
            )
            inserted = cursor.fetchone()
            if not inserted:
                raise AttachmentStateError("attachment fact insert did not return an id")
            fact_id = int(inserted["id"])
        connection.commit()
    return {
        "id": fact_id,
        "engagement_id": engagement_id,
        "fact_key": normalized_key,
        "value": value,
        "display_value": display_value,
        "data_type": data_type,
        "status": status,
        "source_kind": normalized_source_kind,
        "source_ref": source_ref or {},
        "evidence_refs": evidence_refs,
        "revision": revision,
        "is_current": True,
        "reviewed_by": actor_user_id if reviewed else None,
    }


def get_report_version(
    engagement_id: int,
    report_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, engagement_id, report_type, report_version, status,
                       fact_snapshot_json, created_at
                FROM audit_report
                WHERE id = %s AND engagement_id = %s
                """,
                (report_id, engagement_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                """
                SELECT id, report_version
                FROM audit_report
                WHERE engagement_id = %s AND report_type = %s
                ORDER BY report_version DESC LIMIT 1
                """,
                (engagement_id, row["report_type"]),
            )
            latest = cursor.fetchone()
    result = _serialize_row(dict(row))
    result["fact_snapshot"] = _decode_json(row.get("fact_snapshot_json"), {})
    result["is_latest"] = bool(latest and int(latest["id"]) == int(row["id"]))
    return result


def get_latest_report_version(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM audit_report
                WHERE engagement_id = %s AND report_type = 'annual_audit_draft'
                ORDER BY report_version DESC LIMIT 1
                """,
                (engagement_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return get_report_version(
        engagement_id,
        int(row["id"]),
        settings=resolved,
    )


def create_job_with_outbox(
    *,
    job: dict[str, Any],
    items: list[dict[str, Any]],
    settings: Settings | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create a job, its per-template items, and its outbox event atomically."""

    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO annual_attachment_generation_job (
                  id, engagement_id, report_id, report_version, thread_id,
                  assistant_turn_id, template_family_id, template_version_id,
                  template_snapshot_json, template_content_sha256,
                  fact_snapshot_ref, fact_snapshot_sha256, input_fingerprint,
                  request_idempotency_key_hash,
                  request_scope, delivery_level, status, stage, progress,
                  expected_item_count, succeeded_item_count, model_manifest_json,
                  renderer_manifest_json, requested_by
                ) VALUES (
                  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                  'queued','queued',0,%s,0,%s,%s,%s
                )
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    job["id"],
                    job["engagement_id"],
                    job["report_id"],
                    job["report_version"],
                    job.get("thread_id"),
                    job.get("assistant_turn_id"),
                    job["template_family_id"],
                    job["template_version_id"],
                    _json(job["template_snapshot"]),
                    job["template_content_sha256"],
                    job["fact_snapshot_ref"],
                    job["fact_snapshot_sha256"],
                    job["input_fingerprint"],
                    job.get("request_idempotency_key_hash") or None,
                    job.get("request_scope") or "all_active_template_files",
                    job.get("delivery_level") or "review_draft",
                    len(items),
                    _json(job.get("model_manifest") or {}),
                    _json(job.get("renderer_manifest") or {}),
                    job["requested_by"],
                ),
            )
            inserted = cursor.fetchone()
            if not inserted:
                existing = None
                request_key_hash = str(job.get("request_idempotency_key_hash") or "")
                if request_key_hash:
                    cursor.execute(
                        """
                        SELECT id, input_fingerprint
                        FROM annual_attachment_generation_job
                        WHERE engagement_id = %s AND request_idempotency_key_hash = %s
                        """,
                        (job["engagement_id"], request_key_hash),
                    )
                    existing = cursor.fetchone()
                    if (
                        existing is not None
                        and str(existing.get("input_fingerprint") or "")
                        != str(job["input_fingerprint"])
                    ):
                        raise AttachmentIdempotencyConflictError(
                            "attachment idempotency key was reused for different frozen input"
                        )
                if existing is None:
                    cursor.execute(
                        """
                        SELECT id FROM annual_attachment_generation_job
                        WHERE input_fingerprint = %s AND status <> 'cancelled'
                        """,
                        (job["input_fingerprint"],),
                    )
                    existing = cursor.fetchone()
                if not existing:
                    raise AttachmentStateError("idempotent attachment job disappeared")
                connection.commit()
                snapshot = get_job(
                    job_id=str(existing["id"]),
                    engagement_id=int(job["engagement_id"]),
                    settings=resolved,
                )
                if snapshot is None:
                    raise AttachmentStateError("idempotent attachment job disappeared")
                return snapshot, False
            _register_attachment_storage_reference(
                cursor,
                storage_ref=str(job["fact_snapshot_ref"]),
                object_kind="context",
                content_sha256=str(job["fact_snapshot_sha256"]),
                owner_type="generation_job",
                owner_id=str(job["id"]),
                owner_field="context",
                actor=str(job["requested_by"]),
                managed_exclusive=True,
            )
            for item in items:
                cursor.execute(
                    """
                    INSERT INTO annual_attachment_generation_item (
                      id, job_id, template_file_id, document_code, display_name,
                      extension, source_template_sha256, compiled_template_sha256,
                      binding_manifest_json, status, stage
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued','queued')
                    """,
                    (
                        item["id"],
                        job["id"],
                        item["template_file_id"],
                        item["document_code"],
                        item["display_name"],
                        item["extension"],
                        item["source_template_sha256"],
                        item["compiled_template_sha256"],
                        _json(item["binding_manifest"]),
                    ),
                )
            cursor.execute(
                "INSERT INTO annual_attachment_outbox (job_id) VALUES (%s)",
                (job["id"],),
            )
        connection.commit()
    snapshot = get_job(job_id=str(job["id"]), engagement_id=int(job["engagement_id"]), settings=resolved)
    if snapshot is None:
        raise AttachmentStateError("created attachment job could not be read")
    return snapshot, True


def get_job(
    *,
    job_id: str,
    engagement_id: int,
    include_internal: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM annual_attachment_generation_job
                WHERE id = %s AND engagement_id = %s
                """,
                (job_id, engagement_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                """
                SELECT * FROM annual_attachment_generation_item
                WHERE job_id = %s ORDER BY created_at, id
                """,
                (job_id,),
            )
            items = [_serialize_row(dict(item)) for item in cursor.fetchall()]
            cursor.execute(
                """
                SELECT artifact.id, artifact.job_id, artifact.item_id,
                       artifact.document_code, artifact.display_name,
                       artifact.file_name, artifact.extension,
                       artifact.content_type, artifact.file_size, artifact.sha256,
                       artifact.preview_ref, artifact.preview_sha256, artifact.status,
                       artifact.delivery_approved, artifact.delivery_level,
                       artifact.created_at, artifact.published_at,
                       item.quality_report_json
                FROM annual_generated_artifact AS artifact
                JOIN annual_attachment_generation_item AS item
                  ON item.id = artifact.item_id
                WHERE artifact.job_id = %s
                ORDER BY artifact.created_at, artifact.id
                """,
                (job_id,),
            )
            artifacts = []
            for artifact_row in cursor.fetchall():
                artifact = _serialize_row(dict(artifact_row))
                quality_report = artifact.pop("quality_report", {})
                artifact["preview_available"] = bool(artifact.get("preview_ref"))
                quality_passed = (
                    quality_report.get("passed")
                    if isinstance(quality_report, dict)
                    else None
                )
                if artifact.get("status") == "rejected" or quality_passed is False:
                    artifact["quality_status"] = "failed"
                elif quality_passed is True or artifact.get("status") == "published":
                    artifact["quality_status"] = "passed"
                else:
                    artifact["quality_status"] = "pending"
                issue_messages = [
                    str(issue.get("message") or "").strip()
                    for issue in (
                        quality_report.get("issues") or []
                        if isinstance(quality_report, dict)
                        else []
                    )
                    if isinstance(issue, dict) and str(issue.get("message") or "").strip()
                ]
                if issue_messages:
                    artifact["quality_summary"] = "; ".join(issue_messages[:3])[:1024]
                elif quality_passed is True and not artifact.get("delivery_approved"):
                    artifact["quality_summary"] = "单文件质量门禁通过，等待完整附件包原子发布"
                elif quality_passed is True:
                    artifact["quality_summary"] = "质量门禁通过"
                else:
                    artifact["quality_summary"] = None
                artifacts.append(artifact)
    result = _serialize_row(dict(row))
    result["items"] = items
    result["artifacts"] = artifacts
    # Job-level failures can happen before an item is claimed (for example a
    # transient context/object-store read) or after every item succeeds while
    # the atomic publication check is running. Both states must be retryable.
    result["retryable"] = result.get("status") == "failed"
    if not include_internal:
        template_snapshot = result.pop("template_snapshot", {})
        if isinstance(template_snapshot, dict):
            result["template_version_label"] = str(
                template_snapshot.get("version_label") or ""
            )
            result["business_type"] = str(
                template_snapshot.get("business_type") or "annual_audit"
            )
        for key in (
            "fact_snapshot_ref",
            "fact_snapshot_sha256",
            "template_content_sha256",
            "input_fingerprint",
            "dedupe_fingerprint",
            "request_idempotency_key_hash",
            "model_manifest",
            "renderer_manifest",
            "lease_token",
            "lease_expires_at",
            "requested_by",
            "thread_id",
        ):
            result.pop(key, None)
        for item in result["items"]:
            for key in (
                "binding_manifest",
                "payload_ref",
                "payload_sha256",
                "source_template_sha256",
                "compiled_template_sha256",
                "quality_report",
                "lease_token",
            ):
                item.pop(key, None)
        for artifact in result["artifacts"]:
            for key in (
                "object_ref",
                "preview_ref",
                "preview_sha256",
                "provenance_manifest_ref",
                "provenance_sha256",
                "created_by",
                "published_by",
            ):
                artifact.pop(key, None)
    return result


def list_jobs(
    engagement_id: int,
    *,
    limit: int = 50,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM annual_attachment_generation_job
                WHERE engagement_id = %s
                ORDER BY queued_at DESC LIMIT %s
                """,
                (engagement_id, min(max(limit, 1), 100)),
            )
            ids = [str(row["id"]) for row in cursor.fetchall()]
    return [
        snapshot
        for job_id in ids
        if (snapshot := get_job(job_id=job_id, engagement_id=engagement_id, settings=resolved))
    ]


def get_job_by_id(
    job_id: str,
    *,
    include_internal: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT engagement_id FROM annual_attachment_generation_job WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return get_job(
        job_id=job_id,
        engagement_id=int(row["engagement_id"]),
        include_internal=include_internal,
        settings=resolved,
    )


def get_job_by_fingerprint(
    *,
    engagement_id: int,
    input_fingerprint: str,
    include_internal: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM annual_attachment_generation_job
                WHERE engagement_id = %s AND input_fingerprint = %s
                  AND status <> 'cancelled'
                ORDER BY queued_at DESC LIMIT 1
                """,
                (engagement_id, input_fingerprint),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return get_job(
        job_id=str(row["id"]),
        engagement_id=engagement_id,
        include_internal=include_internal,
        settings=resolved,
    )


def get_job_by_request_key(
    *,
    engagement_id: int,
    request_idempotency_key_hash: str,
    include_internal: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    if not request_idempotency_key_hash:
        return None
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM annual_attachment_generation_job
                WHERE engagement_id = %s AND request_idempotency_key_hash = %s
                LIMIT 1
                """,
                (engagement_id, request_idempotency_key_hash),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return get_job(
        job_id=str(row["id"]),
        engagement_id=engagement_id,
        include_internal=include_internal,
        settings=resolved,
    )


def transition_job(
    *,
    job_id: str,
    expected_statuses: set[str],
    status: str,
    stage: str,
    progress: int,
    error_code: str | None = None,
    error_summary: str | None = None,
    lease_token: str | None = None,
    lease_seconds: int = 900,
    settings: Settings | None = None,
) -> bool:
    if status not in {"queued", "running", "succeeded", "failed", "cancelled"}:
        raise ValueError("unsupported job status")
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            placeholders = ",".join(["%s"] * len(expected_statuses))
            lease_filter = (
                " AND lease_token = %s AND lease_expires_at >= now()"
                if lease_token
                else ""
            )
            cursor.execute(
                f"""
                UPDATE annual_attachment_generation_job
                SET status = %s, stage = %s, progress = %s,
                    error_code = %s, error_summary = %s,
                    started_at = CASE WHEN %s = 'running' AND started_at IS NULL THEN now() ELSE started_at END,
                    completed_at = CASE WHEN %s IN ('succeeded','failed') THEN now() ELSE completed_at END,
                    cancelled_at = CASE WHEN %s = 'cancelled' THEN now() ELSE cancelled_at END,
                    lease_expires_at = CASE
                      WHEN %s IS NOT NULL AND %s = 'running' THEN now() + (%s * INTERVAL '1 second')
                      WHEN %s IN ('succeeded','failed','cancelled') THEN NULL ELSE lease_expires_at END,
                    lease_token = CASE WHEN %s IN ('succeeded','failed','cancelled') THEN NULL ELSE lease_token END
                WHERE id = %s AND status IN ({placeholders}){lease_filter}
                """,
                (
                    status,
                    stage,
                    min(max(progress, 0), 100),
                    error_code,
                    (error_summary or "")[:1024] or None,
                    status,
                    status,
                    status,
                    lease_token,
                    status,
                    max(60, lease_seconds),
                    status,
                    status,
                    job_id,
                    *sorted(expected_statuses),
                    *((lease_token,) if lease_token else ()),
                ),
            )
            changed = cursor.rowcount == 1
        connection.commit()
    return changed


def claim_job_for_processing(
    job_id: str,
    *,
    lease_token: str,
    stale_after_seconds: int = 900,
    settings: Settings | None = None,
) -> bool:
    """Claim a queued job or recover a worker-lost stale running job."""

    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status,
                       lease_expires_at IS NULL OR lease_expires_at < now() AS stale
                FROM annual_attachment_generation_job
                WHERE id = %s FOR UPDATE
                """,
                (job_id,),
            )
            job = cursor.fetchone()
            if not job:
                return False
            status = str(job["status"])
            stale = bool(job.get("stale"))
            if status == "queued":
                cursor.execute(
                    """
                    UPDATE annual_attachment_generation_job
                    SET status = 'running', stage = 'freezing_context', progress = 5,
                        started_at = COALESCE(started_at, now()),
                        error_code = NULL, error_summary = NULL,
                        lease_token = %s,
                        lease_expires_at = now() + (%s * INTERVAL '1 second')
                    WHERE id = %s
                    """,
                    (lease_token, max(stale_after_seconds, 60), job_id),
                )
            elif status == "running" and stale:
                cursor.execute(
                    """
                    UPDATE annual_attachment_generation_item
                    SET status = 'queued', stage = 'queued', lease_token = NULL
                    WHERE job_id = %s AND status = 'running'
                    """,
                    (job_id,),
                )
                cursor.execute(
                    """
                    UPDATE annual_attachment_generation_job
                    SET stage = 'freezing_context', progress = 5,
                        error_code = NULL, error_summary = NULL,
                        lease_token = %s,
                        lease_expires_at = now() + (%s * INTERVAL '1 second')
                    WHERE id = %s
                    """,
                    (lease_token, max(stale_after_seconds, 60), job_id),
                )
            else:
                return False
        connection.commit()
    return True


def claim_item(
    *,
    job_id: str,
    item_id: str,
    stage: str,
    lease_token: str,
    settings: Settings | None = None,
) -> bool:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE annual_attachment_generation_item AS item
                SET status = 'running', stage = %s,
                    attempt_count = item.attempt_count + 1,
                    error_code = NULL, error_summary = NULL, lease_token = %s
                FROM annual_attachment_generation_job AS job
                WHERE item.id = %s AND item.job_id = %s
                  AND job.id = item.job_id
                  AND item.status IN ('queued','failed')
                  AND job.status = 'running' AND job.lease_token = %s
                  AND job.lease_expires_at >= now()
                """,
                (stage, lease_token, item_id, job_id, lease_token),
            )
            changed = cursor.rowcount == 1
        connection.commit()
    return changed


def fail_item(
    *,
    job_id: str,
    item_id: str,
    stage: str,
    error_code: str,
    error_summary: str,
    lease_token: str,
    settings: Settings | None = None,
) -> bool:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE annual_attachment_generation_item AS item
                SET status = 'failed', stage = %s, error_code = %s,
                    error_summary = %s, lease_token = NULL
                FROM annual_attachment_generation_job AS job
                WHERE item.id = %s AND item.job_id = %s AND item.status = 'running'
                  AND job.id = item.job_id
                  AND item.lease_token = %s AND job.lease_token = %s
                  AND job.lease_expires_at >= now()
                """,
                (
                    stage,
                    error_code[:64],
                    error_summary[:1024],
                    item_id,
                    job_id,
                    lease_token,
                    lease_token,
                ),
            )
            changed = cursor.rowcount == 1
            if changed:
                cursor.execute(
                    """
                    UPDATE annual_attachment_generation_job
                    SET status = 'failed', stage = %s, error_code = %s,
                        error_summary = %s, completed_at = now(),
                        lease_token = NULL, lease_expires_at = NULL
                    WHERE id = %s AND status = 'running' AND lease_token = %s
                    """,
                    (stage, error_code[:64], error_summary[:1024], job_id, lease_token),
                )
        connection.commit()
    return changed


def complete_item(
    *,
    job_id: str,
    item_id: str,
    payload_ref: str,
    payload_sha256: str,
    quality_report: dict[str, Any],
    artifact: dict[str, Any],
    lease_token: str,
    settings: Settings | None = None,
) -> None:
    """Persist an internal artifact and complete its item in one transaction."""

    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT item.status, item.lease_token, job.lease_token AS job_lease_token,
                       job.lease_expires_at >= now() AS lease_valid
                FROM annual_attachment_generation_item AS item
                JOIN annual_attachment_generation_job AS job ON job.id = item.job_id
                WHERE item.id = %s AND item.job_id = %s FOR UPDATE
                """,
                (item_id, job_id),
            )
            item = cursor.fetchone()
            if (
                not item
                or item["status"] != "running"
                or str(item.get("lease_token") or "") != lease_token
                or str(item.get("job_lease_token") or "") != lease_token
                or not bool(item.get("lease_valid"))
            ):
                raise AttachmentStateError("attachment item lease is no longer owned")
            cursor.execute(
                """
                INSERT INTO annual_generated_artifact (
                  id, job_id, item_id, engagement_id, report_id,
                  template_version_id, template_file_id, document_code,
                  display_name, file_name, extension, content_type, file_size,
                  sha256, object_ref, preview_ref, preview_sha256,
                  provenance_manifest_ref, provenance_sha256, status,
                  delivery_approved, delivery_level, created_by
                ) VALUES (
                  %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                  'validated',FALSE,%s,%s
                )
                """,
                (
                    artifact["id"],
                    job_id,
                    item_id,
                    artifact["engagement_id"],
                    artifact["report_id"],
                    artifact["template_version_id"],
                    artifact["template_file_id"],
                    artifact["document_code"],
                    artifact["display_name"],
                    artifact["file_name"],
                    artifact["extension"],
                    artifact["content_type"],
                    artifact["file_size"],
                    artifact["sha256"],
                    artifact["object_ref"],
                    artifact.get("preview_ref"),
                    artifact.get("preview_sha256"),
                    artifact["provenance_manifest_ref"],
                    artifact["provenance_sha256"],
                    artifact["delivery_level"],
                    artifact["created_by"],
                ),
            )
            cursor.execute(
                """
                UPDATE annual_attachment_generation_item
                SET status = 'succeeded', stage = 'validated', payload_ref = %s,
                    payload_sha256 = %s, quality_report_json = %s,
                    error_code = NULL, error_summary = NULL, lease_token = NULL
                WHERE id = %s AND job_id = %s AND lease_token = %s
                """,
                (
                    payload_ref,
                    payload_sha256,
                    _json(quality_report),
                    item_id,
                    job_id,
                    lease_token,
                ),
            )
            _register_attachment_storage_reference(
                cursor,
                storage_ref=payload_ref,
                object_kind="payload",
                content_sha256=payload_sha256,
                owner_type="generation_item",
                owner_id=item_id,
                owner_field="payload",
                actor=str(artifact["created_by"]),
                managed_exclusive=True,
            )
            _register_attachment_storage_reference(
                cursor,
                storage_ref=str(artifact["object_ref"]),
                object_kind="artifact",
                content_sha256=str(artifact["sha256"]),
                owner_type="generated_artifact",
                owner_id=str(artifact["id"]),
                owner_field="artifact",
                actor=str(artifact["created_by"]),
                managed_exclusive=True,
            )
            _register_attachment_storage_reference(
                cursor,
                storage_ref=str(artifact.get("preview_ref") or ""),
                object_kind="preview",
                content_sha256=str(artifact.get("preview_sha256") or ""),
                owner_type="generated_artifact",
                owner_id=str(artifact["id"]),
                owner_field="preview",
                actor=str(artifact["created_by"]),
                managed_exclusive=True,
            )
            _register_attachment_storage_reference(
                cursor,
                storage_ref=str(artifact["provenance_manifest_ref"]),
                object_kind="provenance",
                content_sha256=str(artifact["provenance_sha256"]),
                owner_type="generated_artifact",
                owner_id=str(artifact["id"]),
                owner_field="provenance",
                actor=str(artifact["created_by"]),
                managed_exclusive=True,
            )
            cursor.execute(
                """
                UPDATE annual_attachment_generation_job
                SET succeeded_item_count = (
                  SELECT COUNT(*) FROM annual_attachment_generation_item
                  WHERE job_id = %s AND status = 'succeeded'
                )
                WHERE id = %s AND lease_token = %s
                """,
                (job_id, job_id, lease_token),
            )
        connection.commit()


def publish_job_if_complete(
    *,
    job_id: str,
    actor_user_id: str,
    lease_token: str,
    settings: Settings | None = None,
) -> bool:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, expected_item_count
                FROM annual_attachment_generation_job
                WHERE id = %s AND lease_token = %s
                  AND lease_expires_at >= now()
                FOR UPDATE
                """,
                (job_id, lease_token),
            )
            job = cursor.fetchone()
            if not job or job["status"] != "running":
                return False
            cursor.execute(
                """
                SELECT COUNT(*) AS item_count,
                       COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded_count
                FROM annual_attachment_generation_item WHERE job_id = %s
                """,
                (job_id,),
            )
            counts = cursor.fetchone()
            expected = int(job["expected_item_count"])
            if int(counts.get("item_count") or 0) != expected or int(counts.get("succeeded_count") or 0) != expected:
                return False
            cursor.execute(
                "SELECT COUNT(*) AS artifact_count FROM annual_generated_artifact WHERE job_id = %s AND status = 'validated'",
                (job_id,),
            )
            if int(cursor.fetchone()["artifact_count"]) != expected:
                return False
            cursor.execute(
                """
                UPDATE annual_generated_artifact
                SET status = 'published', delivery_approved = TRUE,
                    published_by = %s, published_at = now()
                WHERE job_id = %s AND status = 'validated'
                """,
                (actor_user_id, job_id),
            )
            cursor.execute(
                """
                UPDATE annual_attachment_generation_job
                SET status = 'succeeded', stage = 'published', progress = 100,
                    succeeded_item_count = expected_item_count,
                    completed_at = now(), error_code = NULL,
                    error_summary = NULL, lease_token = NULL,
                    lease_expires_at = NULL
                WHERE id = %s AND lease_token = %s
                """,
                (job_id, lease_token),
            )
        connection.commit()
    return True


def retry_failed_job(job_id: str, *, settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM annual_attachment_generation_job WHERE id = %s FOR UPDATE",
                (job_id,),
            )
            job = cursor.fetchone()
            if not job or job["status"] != "failed":
                return False
            cursor.execute(
                """
                UPDATE annual_attachment_generation_item
                SET status = 'queued', stage = 'queued', error_code = NULL,
                    error_summary = NULL, lease_token = NULL
                WHERE job_id = %s AND status IN ('failed','running')
                """,
                (job_id,),
            )
            cursor.execute(
                """
                UPDATE annual_attachment_generation_job
                SET status = 'queued', stage = 'queued', progress = 0,
                    error_code = NULL, error_summary = NULL, completed_at = NULL,
                    cancelled_at = NULL, lease_token = NULL, lease_expires_at = NULL
                WHERE id = %s
                """,
                (job_id,),
            )
            cursor.execute(
                """
                INSERT INTO annual_attachment_outbox (job_id, status)
                VALUES (%s, 'pending')
                ON CONFLICT (job_id, event_type) DO UPDATE SET
                  status = 'pending', available_at = now(), published_at = NULL, last_error = NULL
                """,
                (job_id,),
            )
        connection.commit()
    return True


def cancel_queued_job(job_id: str, *, settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE annual_attachment_generation_job
                SET status = 'cancelled', stage = 'cancelled',
                    cancelled_at = now(), lease_token = NULL,
                    lease_expires_at = NULL
                WHERE id = %s AND status = 'queued'
                """,
                (job_id,),
            )
            changed = cursor.rowcount == 1
            if changed:
                cursor.execute(
                    "UPDATE annual_attachment_generation_item SET status = 'cancelled', stage = 'cancelled', lease_token = NULL WHERE job_id = %s AND status = 'queued'",
                    (job_id,),
                )
                cursor.execute(
                    "UPDATE annual_attachment_outbox SET status = 'failed', last_error = 'job cancelled' WHERE job_id = %s AND status = 'pending'",
                    (job_id,),
                )
                _release_attachment_storage_references(
                    cursor,
                    owner_type="generation_job",
                    owner_id=job_id,
                    actor="system",
                    reason="job_cancelled",
                )
        connection.commit()
    return changed


def claim_pending_outbox(
    *,
    limit: int = 50,
    stale_after_seconds: int = 900,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Atomically lease a bounded batch of dispatchable outbox events."""

    bounded_limit = min(max(int(limit), 1), 100)
    bounded_stale_seconds = max(int(stale_after_seconds), 60)
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, job_id, event_type, attempt_count
                FROM annual_attachment_outbox
                WHERE (
                    status IN ('pending','failed')
                    AND available_at <= now()
                  ) OR (
                    status = 'publishing'
                    AND updated_at <= now() - (%s * INTERVAL '1 second')
                  )
                ORDER BY available_at, id
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (bounded_stale_seconds, bounded_limit),
            )
            events = [_serialize_row(dict(row)) for row in cursor.fetchall()]
            if events:
                placeholders = ",".join("%s" for _ in events)
                cursor.execute(
                    f"""
                    UPDATE annual_attachment_outbox
                    SET status = 'publishing',
                        attempt_count = attempt_count + 1,
                        published_at = NULL,
                        last_error = NULL
                    WHERE id IN ({placeholders})
                    """,
                    tuple(int(event["id"]) for event in events),
                )
                if cursor.rowcount != len(events):
                    raise AttachmentStateError(
                        "claimed attachment outbox batch changed unexpectedly"
                    )
                for event in events:
                    event["status"] = "publishing"
                    event["attempt_count"] = int(event.get("attempt_count") or 0) + 1
        connection.commit()
    return events


def mark_outbox_result(
    outbox_id: int,
    *,
    attempt_count: int,
    published: bool,
    error: str = "",
    settings: Settings | None = None,
) -> bool:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE annual_attachment_outbox
                SET status = %s,
                    published_at = CASE WHEN %s THEN now() ELSE NULL END,
                    available_at = CASE WHEN %s THEN available_at ELSE now() + INTERVAL '30 seconds' END,
                    last_error = %s
                WHERE id = %s
                  AND status = 'publishing'
                  AND attempt_count = %s
                """,
                (
                    "published" if published else "failed",
                    published,
                    published,
                    error[:1024] or None,
                    outbox_id,
                    int(attempt_count),
                ),
            )
            changed = cursor.rowcount == 1
        connection.commit()
    return changed


def get_artifact(
    *,
    engagement_id: int,
    artifact_id: str,
    purpose: str,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    if purpose not in {"download", "preview"}:
        raise ValueError("unsupported artifact purpose")
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM annual_generated_artifact
                WHERE id = %s AND engagement_id = %s
                  AND status = 'published' AND delivery_approved = TRUE
                """,
                (artifact_id, engagement_id),
            )
            row = cursor.fetchone()
    if not row:
        return None
    result = _serialize_row(dict(row))
    result["access_ref"] = row.get("preview_ref") if purpose == "preview" else row.get("object_ref")
    if purpose == "preview" and not result["access_ref"]:
        return None
    return result


def record_ticket(
    *,
    artifact_id: str,
    engagement_id: int,
    purpose: str,
    actor_user_id: str,
    ticket_id: str,
    expires_at: datetime,
    settings: Settings | None = None,
) -> None:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO annual_artifact_access_event (
                  artifact_id, engagement_id, purpose, actor_user_id, ticket_id, expires_at
                ) VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (artifact_id, engagement_id, purpose, actor_user_id, ticket_id, expires_at),
            )
        connection.commit()


def get_ticket(
    ticket_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ticket_id, artifact_id, engagement_id, purpose,
                       actor_user_id, expires_at, redeemed_at
                FROM annual_artifact_access_event
                WHERE ticket_id = %s AND expires_at >= now()
                """,
                (ticket_id,),
            )
            row = cursor.fetchone()
    return _serialize_row(dict(row)) if row else None


def redeem_ticket(
    ticket_id: str,
    *,
    purpose: str,
    settings: Settings | None = None,
) -> bool:
    if purpose not in {"download", "preview"}:
        return False
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            if purpose == "download":
                cursor.execute(
                    """
                    UPDATE annual_artifact_access_event
                    SET redeemed_at = now()
                    WHERE ticket_id = %s AND purpose = 'download'
                      AND expires_at >= now() AND redeemed_at IS NULL
                    """,
                    (ticket_id,),
                )
                valid = cursor.rowcount == 1
            else:
                cursor.execute(
                    """
                    UPDATE annual_artifact_access_event
                    SET redeemed_at = COALESCE(redeemed_at, now())
                    WHERE ticket_id = %s AND purpose = 'preview'
                      AND expires_at >= now()
                    """,
                    (ticket_id,),
                )
                cursor.execute(
                    """
                    SELECT 1 FROM annual_artifact_access_event
                    WHERE ticket_id = %s AND purpose = 'preview'
                      AND expires_at >= now()
                    """,
                    (ticket_id,),
                )
                # PDF.js issues several Range requests for one preview.
                valid = cursor.fetchone() is not None
        connection.commit()
    return valid


def plan_storage_reclamation(
    *,
    limit: int = 100,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Mark provably unreferenced managed objects; never delete object bytes."""

    bounded_limit = min(max(int(limit), 1), 1_000)
    resolved = settings or get_settings()
    planned: list[dict[str, Any]] = []
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT storage_object.storage_ref_hash,
                       storage_object.storage_ref,
                       storage_object.object_kind,
                       storage_object.content_sha256,
                       storage_object.unreferenced_at,
                       storage_object.retention_until
                FROM annual_attachment_storage_object AS storage_object
                WHERE storage_object.management_scope = 'managed_exclusive'
                  AND storage_object.retention_state = 'retained'
                  AND storage_object.retention_until <= now()
                  AND NOT EXISTS (
                    SELECT 1
                    FROM annual_attachment_storage_reference AS owner_ref
                    WHERE owner_ref.storage_ref_hash = storage_object.storage_ref_hash
                      AND owner_ref.released_at IS NULL
                  )
                ORDER BY storage_object.retention_until, storage_object.storage_ref_hash
                LIMIT %s FOR UPDATE SKIP LOCKED
                """,
                (bounded_limit,),
            )
            candidates = [dict(row) for row in cursor.fetchall()]
            for candidate in candidates:
                cursor.execute(
                    """
                    UPDATE annual_attachment_storage_object AS storage_object
                    SET retention_state = 'reclaim_candidate',
                        last_seen_at = now()
                    WHERE storage_ref_hash = %s
                      AND management_scope = 'managed_exclusive'
                      AND retention_state = 'retained'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM annual_attachment_storage_reference AS owner_ref
                        WHERE owner_ref.storage_ref_hash = storage_object.storage_ref_hash
                          AND owner_ref.released_at IS NULL
                      )
                    """,
                    (candidate["storage_ref_hash"],),
                )
                if cursor.rowcount == 1:
                    candidate["retention_state"] = "reclaim_candidate"
                    planned.append(_serialize_row(candidate))
        connection.commit()
    return planned


__all__ = [
    "AttachmentStateError",
    "AttachmentIdempotencyConflictError",
    "FACT_KEY_PATTERN",
    "TERMINAL_JOB_STATUSES",
    "cancel_queued_job",
    "claim_job_for_processing",
    "claim_item",
    "complete_item",
    "create_job_with_outbox",
    "fail_item",
    "get_artifact",
    "get_job",
    "get_job_by_id",
    "get_job_by_fingerprint",
    "get_job_by_request_key",
    "get_report_version",
    "get_ticket",
    "get_latest_report_version",
    "list_current_facts",
    "list_jobs",
    "claim_pending_outbox",
    "mark_outbox_result",
    "plan_storage_reclamation",
    "publish_job_if_complete",
    "record_ticket",
    "redeem_ticket",
    "retry_failed_job",
    "transition_job",
    "upsert_fact_version",
]
