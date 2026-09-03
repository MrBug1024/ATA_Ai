"""PostgreSQL repository for immutable platform document templates."""

from __future__ import annotations

import json
import hashlib
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ai_hunter.app.settings import Settings, get_settings


_STORAGE_RETENTION_DAYS = 30


def _storage_ref_hash(storage_ref: str) -> str:
    return hashlib.sha256(storage_ref.encode("utf-8")).hexdigest()


def _register_template_storage_reference(
    cursor: Any,
    *,
    storage_ref: str,
    object_kind: str,
    content_sha256: str,
    owner_id: UUID | str,
    owner_field: str,
    actor: str,
    managed_exclusive: bool,
) -> None:
    """Register an object and one live owner without ever promoting legacy scope."""

    normalized_ref = str(storage_ref or "").strip()
    if not normalized_ref:
        return
    ref_hash = _storage_ref_hash(normalized_ref)
    cursor.execute(
        """
        INSERT INTO public.document_template_storage_object (
          storage_ref_hash, storage_ref, object_kind, content_sha256,
          management_scope, retention_state
        ) VALUES (%s, %s, %s, %s, %s, 'active')
        ON CONFLICT (storage_ref_hash) DO UPDATE
        SET last_seen_at = now(),
            retention_state = CASE
              WHEN public.document_template_storage_object.retention_state = 'legal_hold'
              THEN 'legal_hold' ELSE 'active'
            END,
            retention_until = CASE
              WHEN public.document_template_storage_object.retention_state = 'legal_hold'
              THEN public.document_template_storage_object.retention_until ELSE NULL
            END,
            unreferenced_at = CASE
              WHEN public.document_template_storage_object.retention_state = 'legal_hold'
              THEN public.document_template_storage_object.unreferenced_at ELSE NULL
            END,
            content_sha256 = COALESCE(
              public.document_template_storage_object.content_sha256,
              EXCLUDED.content_sha256
            )
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
        INSERT INTO public.document_template_storage_reference (
          storage_ref_hash, owner_type, owner_id, owner_field, acquired_by
        ) VALUES (%s, 'template_file', %s, %s, %s)
        ON CONFLICT (storage_ref_hash, owner_type, owner_id, owner_field) DO UPDATE
        SET released_by = NULL, release_reason = NULL, released_at = NULL,
            acquired_by = EXCLUDED.acquired_by, acquired_at = now()
        """,
        (ref_hash, str(owner_id), owner_field, actor or "system"),
    )


def _release_template_storage_references(
    cursor: Any,
    *,
    owner_id: UUID | str,
    references: tuple[tuple[str, str, str, str], ...],
    actor: str,
    reason: str,
) -> None:
    """Release owner links while retaining every object for at least 30 days."""

    for owner_field, storage_ref, content_sha256, object_kind in references:
        normalized_ref = str(storage_ref or "").strip()
        if not normalized_ref:
            continue
        # If a pre-ledger object reaches a release path before backfill, record
        # it as legacy_unknown first.  This deliberately prevents auto-reclaim.
        _register_template_storage_reference(
            cursor,
            storage_ref=normalized_ref,
            object_kind=object_kind,
            content_sha256=content_sha256,
            owner_id=owner_id,
            owner_field=owner_field,
            actor=actor,
            managed_exclusive=False,
        )
        ref_hash = _storage_ref_hash(normalized_ref)
        cursor.execute(
            """
            UPDATE public.document_template_storage_reference
            SET released_by = %s, release_reason = %s,
                released_at = COALESCE(released_at, now())
            WHERE storage_ref_hash = %s AND owner_type = 'template_file'
              AND owner_id = %s AND owner_field = %s
            """,
            (actor or "system", reason[:128], ref_hash, str(owner_id), owner_field),
        )
        cursor.execute(
            f"""
            UPDATE public.document_template_storage_object AS storage_object
            SET retention_state = 'retained',
                unreferenced_at = COALESCE(unreferenced_at, now()),
                retention_until = GREATEST(
                  COALESCE(retention_until, now()),
                  now() + INTERVAL '{_STORAGE_RETENTION_DAYS} days'
                )
            WHERE storage_ref_hash = %s
              AND retention_state <> 'legal_hold'
              AND NOT EXISTS (
                SELECT 1
                FROM public.document_template_storage_reference AS owner_ref
                WHERE owner_ref.storage_ref_hash = storage_object.storage_ref_hash
                  AND owner_ref.released_at IS NULL
              )
            """,
            (ref_hash,),
        )


class TemplateRepositoryError(RuntimeError):
    code = "TEMPLATE_REPOSITORY_ERROR"


class TemplateNotFoundError(TemplateRepositoryError):
    code = "TEMPLATE_NOT_FOUND"


class TemplateConflictError(TemplateRepositoryError):
    code = "TEMPLATE_CONFLICT"


class TemplateImmutableError(TemplateConflictError):
    code = "TEMPLATE_VERSION_IMMUTABLE"


class TemplateRevisionConflictError(TemplateConflictError):
    code = "TEMPLATE_REVISION_CONFLICT"


class TemplateValidationStateError(TemplateConflictError):
    code = "TEMPLATE_VALIDATION_REQUIRED"


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _file_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "compiled_sha256": str(row.get("compiled_sha256") or ""),
        "renderer_profile": str(row.get("renderer_profile") or ""),
        "binding_manifest": _loads(row.get("binding_manifest_json"), {}),
        "inspection_report": _loads(row.get("inspection_report_json"), {}),
        "preview_available": bool(row.get("preview_object_ref")),
        "preview_sha256": str(row.get("preview_sha256") or ""),
    }


def _version_dict(row: dict[str, Any], *, files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    normalized = {
        **row,
        "manifest": _loads(row.get("manifest_json"), {}),
        "validation_report": _loads(row.get("validation_report_json"), {}),
        "content_sha256": str(row.get("content_sha256") or ""),
        "activated_by": str(row.get("activated_by") or ""),
        "active": bool(row.get("active")),
        "file_count": int(row.get("file_count") or 0),
        "ready_file_count": int(row.get("ready_file_count") or 0),
    }
    if files is not None:
        normalized["files"] = files
    return normalized


class DocumentTemplateRepository:
    def __init__(self, settings: Settings | None = None, *, dsn: str | None = None) -> None:
        resolved = settings or get_settings()
        self.dsn = dsn or resolved.postgres_checkpointer_dsn

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as connection:
            yield connection

    @staticmethod
    def _audit(
        cursor: Any,
        *,
        event_type: str,
        actor: str,
        family_id: Any = None,
        version_id: Any = None,
        file_id: Any = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO public.document_template_audit_event (
              family_id, version_id, file_id, event_type,
              before_json, after_json, actor_user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                family_id,
                version_id,
                file_id,
                event_type,
                Jsonb(before) if before is not None else None,
                Jsonb(after) if after is not None else None,
                actor or "system",
            ),
        )

    @staticmethod
    def _version_select(*, for_update: bool = False) -> str:
        lock = " FOR UPDATE OF v" if for_update else ""
        return f"""
            SELECT v.*, f.business_type, f.scope_type, f.scope_key,
                   f.revision AS family_revision, f.active_version_id,
                   (f.active_version_id = v.id) AS active,
                   (SELECT COUNT(*) FROM public.document_template_file tf
                    WHERE tf.template_version_id = v.id) AS file_count,
                   (SELECT COUNT(*) FROM public.document_template_file tf
                    WHERE tf.template_version_id = v.id AND tf.status = 'ready') AS ready_file_count
            FROM public.document_template_version v
            JOIN public.document_template_family f ON f.id = v.family_id
            WHERE v.id = %s{lock}
        """

    @staticmethod
    def _check_revision(row: dict[str, Any], revision: int) -> None:
        if int(row.get("revision") or 0) != int(revision):
            raise TemplateRevisionConflictError("template revision has changed; refresh and retry")

    def list_versions(
        self,
        *,
        business_type: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 20,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        conditions = ["TRUE"]
        params: list[Any] = []
        if business_type:
            conditions.append("f.business_type = %s")
            params.append(business_type)
        if status:
            conditions.append("v.status = %s")
            params.append(status)
        elif not include_archived:
            conditions.append("v.status <> 'archived'")
        where = " AND ".join(conditions)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*) AS total
                    FROM public.document_template_version v
                    JOIN public.document_template_family f ON f.id = v.family_id
                    WHERE {where}
                    """,
                    tuple(params),
                )
                total = int((cursor.fetchone() or {}).get("total") or 0)
                cursor.execute(
                    f"""
                    SELECT v.*, f.business_type, f.scope_type, f.scope_key,
                           f.revision AS family_revision,
                           (f.active_version_id = v.id) AS active,
                           COUNT(tf.id) AS file_count,
                           COUNT(tf.id) FILTER (WHERE tf.status = 'ready') AS ready_file_count
                    FROM public.document_template_version v
                    JOIN public.document_template_family f ON f.id = v.family_id
                    LEFT JOIN public.document_template_file tf ON tf.template_version_id = v.id
                    WHERE {where}
                    GROUP BY v.id, f.id
                    ORDER BY v.updated_at DESC, v.version_no DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*params, page_size, (page - 1) * page_size),
                )
                items = [_version_dict(dict(row)) for row in cursor.fetchall()]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_version(self, version_id: UUID | str, *, include_files: bool = True) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._version_select(), (str(version_id),))
                row = cursor.fetchone()
                if not row:
                    raise TemplateNotFoundError("template version was not found")
                files: list[dict[str, Any]] | None = None
                if include_files:
                    cursor.execute(
                        """
                        SELECT * FROM public.document_template_file
                        WHERE template_version_id = %s
                        ORDER BY sort_order, created_at, id
                        """,
                        (str(version_id),),
                    )
                    files = [_file_dict(dict(item)) for item in cursor.fetchall()]
        return _version_dict(dict(row), files=files)

    def get_file(self, file_id: UUID | str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM public.document_template_file WHERE id = %s",
                (str(file_id),),
            ).fetchone()
        if not row:
            raise TemplateNotFoundError("template file was not found")
        return _file_dict(dict(row))

    def create_version(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.document_template_family (
                      business_type, scope_type, scope_key, created_by, updated_by
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (scope_type, scope_key, business_type) DO NOTHING
                    """,
                    (
                        payload["business_type"],
                        payload.get("scope_type") or "system",
                        payload.get("scope_key") or "system",
                        actor,
                        actor,
                    ),
                )
                cursor.execute(
                    """
                    SELECT * FROM public.document_template_family
                    WHERE scope_type = %s AND scope_key = %s AND business_type = %s
                    FOR UPDATE
                    """,
                    (
                        payload.get("scope_type") or "system",
                        payload.get("scope_key") or "system",
                        payload["business_type"],
                    ),
                )
                family = dict(cursor.fetchone() or {})
                if not family:
                    raise TemplateRepositoryError("template family could not be created")
                version_no = int(family["next_version_no"])
                cursor.execute(
                    """
                    UPDATE public.document_template_family
                    SET next_version_no = next_version_no + 1,
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (actor, family["id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO public.document_template_version (
                      family_id, version_no, version_label, name, description,
                      status, contract_version, manifest_json, created_by, updated_by
                    ) VALUES (%s, %s, %s, %s, %s, 'draft', '1.0', '{}'::jsonb, %s, %s)
                    RETURNING id
                    """,
                    (
                        family["id"],
                        version_no,
                        f"v{version_no}",
                        payload["name"],
                        payload.get("description") or "",
                        actor,
                        actor,
                    ),
                )
                version_id = cursor.fetchone()["id"]
                self._audit(
                    cursor,
                    event_type="version_created",
                    actor=actor,
                    family_id=family["id"],
                    version_id=version_id,
                    after={"version_no": version_no, "name": payload["name"], "status": "draft"},
                )
        return self.get_version(version_id)

    def update_version(
        self, version_id: UUID | str, changes: dict[str, Any], *, revision: int, actor: str
    ) -> dict[str, Any]:
        allowed = {key: changes[key] for key in ("name", "description", "manifest") if key in changes}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._version_select(for_update=True), (str(version_id),))
                row = dict(cursor.fetchone() or {})
                if not row:
                    raise TemplateNotFoundError("template version was not found")
                self._check_revision(row, revision)
                if row["status"] != "draft":
                    raise TemplateImmutableError("only draft template versions can be edited")
                assignments: list[str] = []
                params: list[Any] = []
                for field, value in allowed.items():
                    column = "manifest_json" if field == "manifest" else field
                    assignments.append(f"{column} = %s")
                    params.append(Jsonb(value) if field == "manifest" else value)
                if not assignments:
                    return self.get_version(version_id)
                before = {key: row.get("manifest_json" if key == "manifest" else key) for key in allowed}
                cursor.execute(
                    f"""
                    UPDATE public.document_template_version
                    SET {', '.join(assignments)}, content_sha256 = NULL,
                        validation_report_json = '{{}}'::jsonb,
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (*params, actor, str(version_id)),
                )
                self._audit(
                    cursor,
                    event_type="version_updated",
                    actor=actor,
                    family_id=row["family_id"],
                    version_id=row["id"],
                    before=before,
                    after=allowed,
                )
        return self.get_version(version_id)

    def clone_version(
        self,
        version_id: UUID | str,
        *,
        actor: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT family_id FROM public.document_template_version WHERE id = %s",
                    (str(version_id),),
                )
                identity = cursor.fetchone()
                if not identity:
                    raise TemplateNotFoundError("template version was not found")
                cursor.execute(
                    "SELECT * FROM public.document_template_family WHERE id = %s FOR UPDATE",
                    (identity["family_id"],),
                )
                family = dict(cursor.fetchone())
                cursor.execute(self._version_select(for_update=True), (str(version_id),))
                source = dict(cursor.fetchone())
                version_no = int(family["next_version_no"])
                cursor.execute(
                    """
                    UPDATE public.document_template_family
                    SET next_version_no = next_version_no + 1,
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (actor, family["id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO public.document_template_version (
                      family_id, version_no, version_label, name, description, status,
                      contract_version, manifest_json, created_by, updated_by
                    ) VALUES (%s, %s, %s, %s, %s, 'draft', %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        family["id"],
                        version_no,
                        f"v{version_no}",
                        name or f"{source['name']} (copy)",
                        source["description"] if description is None else description,
                        source["contract_version"],
                        Jsonb(_loads(source.get("manifest_json"), {})),
                        actor,
                        actor,
                    ),
                )
                clone_id = cursor.fetchone()["id"]
                cursor.execute(
                    """
                    INSERT INTO public.document_template_file (
                      id, template_version_id, document_code, display_name,
                      source_file_name, extension, content_type, size_bytes,
                      source_object_ref, source_sha256, compiled_object_ref,
                      compiled_sha256, renderer_profile, binding_manifest_json,
                      inspection_report_json, preview_object_ref, preview_sha256,
                      status, sort_order, created_by, updated_by
                    )
                    SELECT gen_random_uuid(), %s, document_code, display_name,
                           source_file_name, extension, content_type, size_bytes,
                           source_object_ref, source_sha256, NULL,
                           NULL, NULL, binding_manifest_json,
                           inspection_report_json, NULL, NULL,
                           'mapping', sort_order, %s, %s
                    FROM public.document_template_file
                    WHERE template_version_id = %s
                    """,
                    (clone_id, actor, actor, source["id"]),
                )
                cursor.execute(
                    """
                    SELECT id, source_object_ref, source_sha256
                    FROM public.document_template_file
                    WHERE template_version_id = %s
                    """,
                    (clone_id,),
                )
                for cloned_file in cursor.fetchall():
                    _register_template_storage_reference(
                        cursor,
                        storage_ref=str(cloned_file.get("source_object_ref") or ""),
                        object_kind="source",
                        content_sha256=str(cloned_file.get("source_sha256") or ""),
                        owner_id=cloned_file["id"],
                        owner_field="source",
                        actor=actor,
                        managed_exclusive=False,
                    )
                self._audit(
                    cursor,
                    event_type="version_cloned",
                    actor=actor,
                    family_id=family["id"],
                    version_id=clone_id,
                    before={"source_version_id": str(source["id"])},
                    after={"version_no": version_no, "status": "draft"},
                )
        return self.get_version(clone_id)

    def delete_version(
        self, version_id: UUID | str, *, revision: int, actor: str
    ) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT family_id FROM public.document_template_version WHERE id = %s",
                    (str(version_id),),
                )
                identity = cursor.fetchone()
                if not identity:
                    raise TemplateNotFoundError("template version was not found")
                cursor.execute(
                    "SELECT * FROM public.document_template_family WHERE id = %s FOR UPDATE",
                    (identity["family_id"],),
                )
                family = dict(cursor.fetchone())
                cursor.execute(self._version_select(for_update=True), (str(version_id),))
                row = dict(cursor.fetchone() or {})
                if not row:
                    raise TemplateNotFoundError("template version was not found")
                self._check_revision(row, revision)
                if (
                    row["status"] not in {"draft", "retired"}
                    or family.get("active_version_id") == row["id"]
                ):
                    raise TemplateImmutableError(
                        "only inactive draft or retired template versions can be deleted"
                    )
                cursor.execute(
                    """
                    SELECT
                      EXISTS (
                        SELECT 1
                        FROM public.annual_attachment_generation_job
                        WHERE template_version_id = %s
                      )
                      OR EXISTS (
                        SELECT 1
                        FROM public.annual_generated_artifact
                        WHERE template_version_id = %s
                           OR template_file_id IN (
                             SELECT id::text
                             FROM public.document_template_file
                             WHERE template_version_id = %s
                           )
                      ) AS has_attachment_history
                    """,
                    (str(row["id"]), str(row["id"]), str(row["id"])),
                )
                history = dict(cursor.fetchone() or {})
                if bool(history.get("has_attachment_history")):
                    raise TemplateImmutableError(
                        "该模板版本已用于生成附件，为保留审计追溯无法删除"
                    )
                cursor.execute(
                    """
                    SELECT id, source_object_ref, source_sha256,
                           compiled_object_ref, compiled_sha256,
                           preview_object_ref, preview_sha256
                    FROM public.document_template_file
                    WHERE template_version_id = %s
                    """,
                    (row["id"],),
                )
                for template_file in cursor.fetchall():
                    _release_template_storage_references(
                        cursor,
                        owner_id=template_file["id"],
                        references=(
                            (
                                "source",
                                str(template_file.get("source_object_ref") or ""),
                                str(template_file.get("source_sha256") or ""),
                                "source",
                            ),
                            (
                                "compiled",
                                str(template_file.get("compiled_object_ref") or ""),
                                str(template_file.get("compiled_sha256") or ""),
                                "compiled",
                            ),
                            (
                                "preview",
                                str(template_file.get("preview_object_ref") or ""),
                                str(template_file.get("preview_sha256") or ""),
                                "preview",
                            ),
                        ),
                        actor=actor,
                        reason="template_version_deleted",
                    )
                cursor.execute(
                    """
                    UPDATE public.document_template_audit_event SET file_id = NULL
                    WHERE file_id IN (
                      SELECT id FROM public.document_template_file WHERE template_version_id = %s
                    )
                    """,
                    (row["id"],),
                )
                cursor.execute(
                    "UPDATE public.document_template_audit_event SET version_id = NULL WHERE version_id = %s",
                    (row["id"],),
                )
                self._audit(
                    cursor,
                    event_type="version_deleted",
                    actor=actor,
                    family_id=family["id"],
                    before={
                        "version_id": str(row["id"]),
                        "version_no": row["version_no"],
                        "name": row["name"],
                    },
                )
                cursor.execute("DELETE FROM public.document_template_version WHERE id = %s", (row["id"],))
                cursor.execute(
                    """
                    UPDATE public.document_template_family
                    SET revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (actor, family["id"]),
                )
        return {"deleted": True, "id": row["id"]}

    def add_file(self, record: dict[str, Any], *, actor: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(self._version_select(for_update=True), (str(record["template_version_id"]),))
                    version = dict(cursor.fetchone() or {})
                    if not version:
                        raise TemplateNotFoundError("template version was not found")
                    if version["status"] != "draft":
                        raise TemplateImmutableError("files can only be added to a draft template version")
                    cursor.execute(
                        """
                        INSERT INTO public.document_template_file (
                          id, template_version_id, document_code, display_name,
                          source_file_name, extension, content_type, size_bytes,
                          source_object_ref, source_sha256, binding_manifest_json,
                          inspection_report_json, status, sort_order, created_by, updated_by
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                  '{}'::jsonb, %s, %s, %s, %s, %s)
                        """,
                        (
                            record["id"],
                            record["template_version_id"],
                            record["document_code"],
                            record["display_name"],
                            record["source_file_name"],
                            record["extension"],
                            record["content_type"],
                            record["size_bytes"],
                            record["source_object_ref"],
                            record["source_sha256"],
                            Jsonb(record.get("inspection_report") or {}),
                            record.get("status") or "mapping",
                            int(record.get("sort_order") or 0),
                            actor,
                            actor,
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE public.document_template_version
                        SET content_sha256 = NULL, validation_report_json = '{}'::jsonb,
                            revision = revision + 1, updated_by = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (actor, version["id"]),
                    )
                    _register_template_storage_reference(
                        cursor,
                        storage_ref=str(record["source_object_ref"]),
                        object_kind="source",
                        content_sha256=str(record["source_sha256"]),
                        owner_id=record["id"],
                        owner_field="source",
                        actor=actor,
                        managed_exclusive=True,
                    )
                    self._audit(
                        cursor,
                        event_type="file_uploaded",
                        actor=actor,
                        family_id=version["family_id"],
                        version_id=version["id"],
                        file_id=record["id"],
                        after={
                            "document_code": record["document_code"],
                            "source_sha256": record["source_sha256"],
                            "status": record.get("status") or "mapping",
                        },
                    )
        except psycopg.errors.UniqueViolation as exc:
            raise TemplateConflictError("document_code must be unique within a template version") from exc
        return self.get_file(record["id"])

    def update_file(
        self, file_id: UUID | str, changes: dict[str, Any], *, revision: int, actor: str
    ) -> dict[str, Any]:
        allowed = {
            key: changes[key]
            for key in ("document_code", "display_name", "sort_order", "binding_manifest")
            if key in changes
        }
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT tf.*, v.status AS version_status, v.family_id
                        FROM public.document_template_file tf
                        JOIN public.document_template_version v ON v.id = tf.template_version_id
                        WHERE tf.id = %s FOR UPDATE OF tf, v
                        """,
                        (str(file_id),),
                    )
                    row = dict(cursor.fetchone() or {})
                    if not row:
                        raise TemplateNotFoundError("template file was not found")
                    self._check_revision(row, revision)
                    if row["version_status"] != "draft":
                        raise TemplateImmutableError("files in active or retired versions are immutable")
                    assignments: list[str] = []
                    params: list[Any] = []
                    invalidate = "document_code" in allowed or "binding_manifest" in allowed
                    for field, value in allowed.items():
                        column = "binding_manifest_json" if field == "binding_manifest" else field
                        assignments.append(f"{column} = %s")
                        params.append(Jsonb(value) if field == "binding_manifest" else value)
                    if invalidate:
                        _release_template_storage_references(
                            cursor,
                            owner_id=row["id"],
                            references=(
                                (
                                    "compiled",
                                    str(row.get("compiled_object_ref") or ""),
                                    str(row.get("compiled_sha256") or ""),
                                    "compiled",
                                ),
                                (
                                    "preview",
                                    str(row.get("preview_object_ref") or ""),
                                    str(row.get("preview_sha256") or ""),
                                    "preview",
                                ),
                            ),
                            actor=actor,
                            reason="template_mapping_changed",
                        )
                        assignments.extend(
                            [
                                "compiled_object_ref = NULL",
                                "compiled_sha256 = NULL",
                                "renderer_profile = NULL",
                                "preview_object_ref = NULL",
                                "preview_sha256 = NULL",
                                "status = 'mapping'",
                            ]
                        )
                    cursor.execute(
                        f"""
                        UPDATE public.document_template_file
                        SET {', '.join(assignments)}, revision = revision + 1,
                            updated_by = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (*params, actor, row["id"]),
                    )
                    cursor.execute(
                        """
                        UPDATE public.document_template_version
                        SET content_sha256 = NULL, validation_report_json = '{}'::jsonb,
                            revision = revision + 1, updated_by = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (actor, row["template_version_id"]),
                    )
                    self._audit(
                        cursor,
                        event_type="file_updated",
                        actor=actor,
                        family_id=row["family_id"],
                        version_id=row["template_version_id"],
                        file_id=row["id"],
                        before={key: row.get(f"{key}_json" if key == "binding_manifest" else key) for key in allowed},
                        after=allowed,
                    )
        except psycopg.errors.UniqueViolation as exc:
            raise TemplateConflictError("document_code must be unique within a template version") from exc
        return self.get_file(file_id)

    def delete_file(self, file_id: UUID | str, *, revision: int, actor: str) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tf.*, v.status AS version_status, v.family_id
                    FROM public.document_template_file tf
                    JOIN public.document_template_version v ON v.id = tf.template_version_id
                    WHERE tf.id = %s FOR UPDATE OF tf, v
                    """,
                    (str(file_id),),
                )
                row = dict(cursor.fetchone() or {})
                if not row:
                    raise TemplateNotFoundError("template file was not found")
                self._check_revision(row, revision)
                if row["version_status"] != "draft":
                    raise TemplateImmutableError("files in active or retired versions are immutable")
                _release_template_storage_references(
                    cursor,
                    owner_id=row["id"],
                    references=(
                        (
                            "source",
                            str(row.get("source_object_ref") or ""),
                            str(row.get("source_sha256") or ""),
                            "source",
                        ),
                        (
                            "compiled",
                            str(row.get("compiled_object_ref") or ""),
                            str(row.get("compiled_sha256") or ""),
                            "compiled",
                        ),
                        (
                            "preview",
                            str(row.get("preview_object_ref") or ""),
                            str(row.get("preview_sha256") or ""),
                            "preview",
                        ),
                    ),
                    actor=actor,
                    reason="template_file_deleted",
                )
                cursor.execute(
                    "UPDATE public.document_template_audit_event SET file_id = NULL WHERE file_id = %s",
                    (row["id"],),
                )
                self._audit(
                    cursor,
                    event_type="file_deleted",
                    actor=actor,
                    family_id=row["family_id"],
                    version_id=row["template_version_id"],
                    before={
                        "file_id": str(row["id"]),
                        "document_code": row["document_code"],
                        "source_sha256": row["source_sha256"],
                    },
                )
                cursor.execute("DELETE FROM public.document_template_file WHERE id = %s", (row["id"],))
                cursor.execute(
                    """
                    UPDATE public.document_template_version
                    SET content_sha256 = NULL, validation_report_json = '{}'::jsonb,
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (actor, row["template_version_id"]),
                )
        return {"deleted": True, "id": row["id"]}

    def record_inspection(
        self,
        file_id: UUID | str,
        *,
        revision: int,
        inspection_report: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        status = "mapping" if inspection_report.get("ok") else "invalid"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tf.*, v.status AS version_status, v.family_id
                    FROM public.document_template_file tf
                    JOIN public.document_template_version v ON v.id = tf.template_version_id
                    WHERE tf.id = %s FOR UPDATE OF tf, v
                    """,
                    (str(file_id),),
                )
                row = dict(cursor.fetchone() or {})
                if not row:
                    raise TemplateNotFoundError("template file was not found")
                self._check_revision(row, revision)
                if row["version_status"] != "draft":
                    raise TemplateImmutableError("files in active or retired versions are immutable")
                _release_template_storage_references(
                    cursor,
                    owner_id=row["id"],
                    references=(
                        (
                            "compiled",
                            str(row.get("compiled_object_ref") or ""),
                            str(row.get("compiled_sha256") or ""),
                            "compiled",
                        ),
                        (
                            "preview",
                            str(row.get("preview_object_ref") or ""),
                            str(row.get("preview_sha256") or ""),
                            "preview",
                        ),
                    ),
                    actor=actor,
                    reason="template_reinspection",
                )
                cursor.execute(
                    """
                    UPDATE public.document_template_file
                    SET inspection_report_json = %s, status = %s,
                        compiled_object_ref = NULL, compiled_sha256 = NULL,
                        renderer_profile = NULL, preview_object_ref = NULL,
                        preview_sha256 = NULL,
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (Jsonb(inspection_report), status, actor, row["id"]),
                )
                cursor.execute(
                    """
                    UPDATE public.document_template_version
                    SET content_sha256 = NULL, validation_report_json = '{}'::jsonb,
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (actor, row["template_version_id"]),
                )
                self._audit(
                    cursor,
                    event_type="file_inspected",
                    actor=actor,
                    family_id=row["family_id"],
                    version_id=row["template_version_id"],
                    file_id=row["id"],
                    after={"status": status, "inspection": inspection_report},
                )
        return self.get_file(file_id)

    def record_compilation(
        self,
        file_id: UUID | str,
        *,
        revision: int,
        binding_manifest: dict[str, Any],
        compiled_object_ref: str,
        compiled_sha256: str,
        renderer_profile: str,
        inspection_report: dict[str, Any],
        preview_object_ref: str = "",
        preview_sha256: str = "",
        actor: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tf.*, v.status AS version_status, v.family_id
                    FROM public.document_template_file tf
                    JOIN public.document_template_version v ON v.id = tf.template_version_id
                    WHERE tf.id = %s FOR UPDATE OF tf, v
                    """,
                    (str(file_id),),
                )
                row = dict(cursor.fetchone() or {})
                if not row:
                    raise TemplateNotFoundError("template file was not found")
                self._check_revision(row, revision)
                if row["version_status"] != "draft":
                    raise TemplateImmutableError("files in active or retired versions are immutable")
                _release_template_storage_references(
                    cursor,
                    owner_id=row["id"],
                    references=(
                        (
                            "compiled",
                            str(row.get("compiled_object_ref") or ""),
                            str(row.get("compiled_sha256") or ""),
                            "compiled",
                        ),
                        (
                            "preview",
                            str(row.get("preview_object_ref") or ""),
                            str(row.get("preview_sha256") or ""),
                            "preview",
                        ),
                    ),
                    actor=actor,
                    reason="template_recompiled",
                )
                cursor.execute(
                    """
                    UPDATE public.document_template_file
                    SET binding_manifest_json = %s, compiled_object_ref = %s,
                        compiled_sha256 = %s, renderer_profile = %s,
                        inspection_report_json = %s, preview_object_ref = %s,
                        preview_sha256 = %s, status = 'ready',
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        Jsonb(binding_manifest),
                        compiled_object_ref,
                        compiled_sha256,
                        renderer_profile,
                        Jsonb(inspection_report),
                        preview_object_ref or None,
                        preview_sha256 or None,
                        actor,
                        row["id"],
                    ),
                )
                _register_template_storage_reference(
                    cursor,
                    storage_ref=compiled_object_ref,
                    object_kind="compiled",
                    content_sha256=compiled_sha256,
                    owner_id=row["id"],
                    owner_field="compiled",
                    actor=actor,
                    managed_exclusive=True,
                )
                _register_template_storage_reference(
                    cursor,
                    storage_ref=preview_object_ref,
                    object_kind="preview",
                    content_sha256=preview_sha256,
                    owner_id=row["id"],
                    owner_field="preview",
                    actor=actor,
                    managed_exclusive=True,
                )
                cursor.execute(
                    """
                    UPDATE public.document_template_version
                    SET content_sha256 = NULL, validation_report_json = '{}'::jsonb,
                        revision = revision + 1, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (actor, row["template_version_id"]),
                )
                self._audit(
                    cursor,
                    event_type="file_compiled",
                    actor=actor,
                    family_id=row["family_id"],
                    version_id=row["template_version_id"],
                    file_id=row["id"],
                    after={
                        "compiled_sha256": compiled_sha256,
                        "renderer_profile": renderer_profile,
                        "preview_sha256": preview_sha256,
                    },
                )
        return self.get_file(file_id)

    def record_validation(
        self,
        version_id: UUID | str,
        *,
        revision: int,
        validation_report: dict[str, Any],
        content_sha256: str,
        passed: bool,
        actor: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._version_select(for_update=True), (str(version_id),))
                row = dict(cursor.fetchone() or {})
                if not row:
                    raise TemplateNotFoundError("template version was not found")
                self._check_revision(row, revision)
                if row["status"] in {"active", "archived"}:
                    raise TemplateImmutableError("active or archived template versions cannot be revalidated")
                next_status = row["status"] if row["status"] == "retired" else ("ready" if passed else "draft")
                cursor.execute(
                    """
                    UPDATE public.document_template_version
                    SET status = %s, validation_report_json = %s,
                        content_sha256 = %s, revision = revision + 1,
                        updated_by = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        next_status,
                        Jsonb(validation_report),
                        content_sha256 if passed else None,
                        actor,
                        row["id"],
                    ),
                )
                self._audit(
                    cursor,
                    event_type="version_validated",
                    actor=actor,
                    family_id=row["family_id"],
                    version_id=row["id"],
                    before={"status": row["status"]},
                    after={
                        "status": next_status,
                        "passed": passed,
                        "content_sha256": content_sha256 if passed else "",
                    },
                )
        return self.get_version(version_id)

    def set_activation(
        self,
        version_id: UUID | str,
        *,
        revision: int,
        active: bool,
        actor: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT family_id FROM public.document_template_version WHERE id = %s",
                    (str(version_id),),
                )
                identity = cursor.fetchone()
                if not identity:
                    raise TemplateNotFoundError("template version was not found")
                cursor.execute(
                    "SELECT * FROM public.document_template_family WHERE id = %s FOR UPDATE",
                    (identity["family_id"],),
                )
                family = dict(cursor.fetchone())
                cursor.execute(self._version_select(for_update=True), (str(version_id),))
                target = dict(cursor.fetchone() or {})
                if not target:
                    raise TemplateNotFoundError("template version was not found")
                self._check_revision(target, revision)
                current_active_id = family.get("active_version_id")
                if active:
                    if current_active_id == target["id"] and target["status"] == "active":
                        return self.get_version(version_id)
                    report = _loads(target.get("validation_report_json"), {})
                    if target["status"] not in {"ready", "retired"}:
                        raise TemplateValidationStateError("template version is not ready for activation")
                    if (
                        not report.get("passed")
                        or not target.get("content_sha256")
                        or report.get("content_sha256") != target.get("content_sha256")
                    ):
                        raise TemplateValidationStateError("template validation is missing or stale")
                    if int(target.get("file_count") or 0) <= 0 or int(target.get("ready_file_count") or 0) != int(
                        target.get("file_count") or 0
                    ):
                        raise TemplateValidationStateError("all template files must be ready before activation")
                    if current_active_id and current_active_id != target["id"]:
                        cursor.execute(
                            "SELECT id FROM public.document_template_version WHERE id = %s FOR UPDATE",
                            (current_active_id,),
                        )
                        cursor.execute(
                            """
                            UPDATE public.document_template_version
                            SET status = 'retired', validation_report_json = '{}'::jsonb,
                                revision = revision + 1,
                                updated_by = %s, updated_at = now()
                            WHERE id = %s
                            """,
                            (actor, current_active_id),
                        )
                        self._audit(
                            cursor,
                            event_type="version_retired",
                            actor=actor,
                            family_id=family["id"],
                            version_id=current_active_id,
                            before={"status": "active"},
                            after={
                                "status": "retired",
                                "superseded_by_version_id": str(target["id"]),
                                "requires_revalidation": True,
                            },
                        )
                    cursor.execute(
                        """
                        UPDATE public.document_template_version
                        SET status = 'active', activated_by = %s, activated_at = now(),
                            revision = revision + 1, updated_by = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (actor, actor, target["id"]),
                    )
                    cursor.execute(
                        """
                        UPDATE public.document_template_family
                        SET active_version_id = %s, revision = revision + 1,
                            updated_by = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (target["id"], actor, family["id"]),
                    )
                    event_type = "version_activated"
                else:
                    if current_active_id != target["id"] or target["status"] != "active":
                        raise TemplateConflictError("template version is not currently active")
                    cursor.execute(
                        """
                        UPDATE public.document_template_version
                        SET status = 'retired', validation_report_json = '{}'::jsonb,
                            revision = revision + 1,
                            updated_by = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (actor, target["id"]),
                    )
                    cursor.execute(
                        """
                        UPDATE public.document_template_family
                        SET active_version_id = NULL, revision = revision + 1,
                            updated_by = %s, updated_at = now()
                        WHERE id = %s
                        """,
                        (actor, family["id"]),
                    )
                    event_type = "version_deactivated"
                self._audit(
                    cursor,
                    event_type=event_type,
                    actor=actor,
                    family_id=family["id"],
                    version_id=target["id"],
                    before={"active_version_id": str(current_active_id or "")},
                    after={
                        "active_version_id": str(target["id"]) if active else "",
                    },
                )
        return self.get_version(version_id)

    def plan_storage_reclamation(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Mark provably unreferenced managed objects; never delete object bytes."""

        bounded_limit = min(max(int(limit), 1), 1_000)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH candidates AS (
                      SELECT storage_object.storage_ref_hash
                      FROM public.document_template_storage_object AS storage_object
                      WHERE storage_object.management_scope = 'managed_exclusive'
                        AND storage_object.retention_state = 'retained'
                        AND storage_object.retention_until <= now()
                        AND NOT EXISTS (
                          SELECT 1
                          FROM public.document_template_storage_reference AS owner_ref
                          WHERE owner_ref.storage_ref_hash = storage_object.storage_ref_hash
                            AND owner_ref.released_at IS NULL
                        )
                      ORDER BY storage_object.retention_until, storage_object.storage_ref_hash
                      FOR UPDATE OF storage_object SKIP LOCKED
                      LIMIT %s
                    )
                    UPDATE public.document_template_storage_object AS storage_object
                    SET retention_state = 'reclaim_candidate', last_seen_at = now()
                    FROM candidates
                    WHERE storage_object.storage_ref_hash = candidates.storage_ref_hash
                      AND storage_object.management_scope = 'managed_exclusive'
                      AND storage_object.retention_state = 'retained'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM public.document_template_storage_reference AS owner_ref
                        WHERE owner_ref.storage_ref_hash = storage_object.storage_ref_hash
                          AND owner_ref.released_at IS NULL
                      )
                    RETURNING storage_object.storage_ref_hash,
                              storage_object.storage_ref,
                              storage_object.object_kind,
                              storage_object.content_sha256,
                              storage_object.unreferenced_at,
                              storage_object.retention_until,
                              storage_object.retention_state
                    """,
                    (bounded_limit,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_active_template_snapshot(self, business_type: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT f.id AS family_id, f.business_type, f.scope_type, f.scope_key,
                           f.revision AS family_revision,
                           v.id AS version_id, v.version_no, v.version_label,
                           v.contract_version, v.content_sha256, v.revision AS version_revision,
                           v.manifest_json, v.validation_report_json
                    FROM public.document_template_family f
                    JOIN public.document_template_version v ON v.id = f.active_version_id
                    WHERE f.scope_type = 'system' AND f.scope_key = 'system'
                      AND f.business_type = %s AND v.status = 'active'
                    """,
                    (business_type,),
                )
                version = cursor.fetchone()
                if not version:
                    return None
                cursor.execute(
                    """
                    SELECT * FROM public.document_template_file
                    WHERE template_version_id = %s AND status = 'ready'
                    ORDER BY sort_order, created_at, id
                    """,
                    (version["version_id"],),
                )
                files = [_file_dict(dict(row)) for row in cursor.fetchall()]
        return {
            **dict(version),
            "manifest": _loads(version.get("manifest_json"), {}),
            "validation_report": _loads(version.get("validation_report_json"), {}),
            "files": files,
        }


__all__ = [
    "DocumentTemplateRepository",
    "TemplateConflictError",
    "TemplateImmutableError",
    "TemplateNotFoundError",
    "TemplateRepositoryError",
    "TemplateRevisionConflictError",
    "TemplateValidationStateError",
]
