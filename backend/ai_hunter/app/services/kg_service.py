"""Database service layer for knowledge graph persistence and retrieval."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

import psycopg
from psycopg.errors import UndefinedTable
from psycopg.rows import dict_row
from psycopg.types.json import Json

from ..graph.json_utils import make_json_safe
from ..graph.schemas import (
    EvidenceItemModel,
    ExtractedEntityModel,
    ExtractedRelationModel,
    ExtractionClaimModel,
    GraphEdgeModel,
    GraphNodeModel,
    ReconciliationLedgerItemModel,
    SourceChunkModel,
)
from .minio_service import resolve_minio_reference_url
from .graph_identity import (
    DEFAULT_GRAPH_STATUS,
    map_graph_status_to_claim_review_status,
    normalize_entity_name,
    normalize_graph_status,
)
from ..settings import get_settings


LOGGER = logging.getLogger(__name__)


class KnowledgeGraphService:
    """Encapsulate PostgreSQL reads and writes for the traceable knowledge graph."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._source_file_columns_cache: set[str] | None = None
        self._kg_claim_columns_cache: set[str] | None = None

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """Yield a psycopg connection with dict rows for service-level operations."""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    def _get_source_file_columns(self, cur: psycopg.Cursor) -> set[str]:
        """Cache the current source_file column set so inserts survive rolling migrations."""
        if self._source_file_columns_cache is not None:
            return self._source_file_columns_cache
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'source_file'
            """
        )
        self._source_file_columns_cache = {str(row["column_name"]) for row in cur.fetchall()}
        return self._source_file_columns_cache

    def _build_source_file_upsert_query(self, columns: set[str]) -> str:
        """Build an upsert query that only touches columns present in the live database."""
        preferred_columns = [
            "case_id",
            "debtor_id",
            "file_name",
            "file_type",
            "content_type",
            "file_sha256",
            "file_size_bytes",
            "storage_ref",
            "storage_provider",
            "storage_bucket",
            "storage_key",
            "storage_etag",
            "storage_version",
            "ingest_payload_ref",
            "ocr_provider",
            "ocr_version",
            "parser_version",
            "status",
        ]
        active_columns = [column for column in preferred_columns if column in columns]
        insert_columns = ", ".join(active_columns)
        insert_values = ", ".join(f"%({column})s" for column in active_columns)
        update_columns = [column for column in active_columns if column not in {"case_id", "file_sha256"}]
        update_clause = ",\n            ".join(
            [f"{column} = EXCLUDED.{column}" for column in update_columns] + ["updated_at = NOW()"]
        )
        return f"""
        INSERT INTO public.source_file (
            {insert_columns}
        ) VALUES (
            {insert_values}
        )
        ON CONFLICT (case_id, file_sha256) DO UPDATE
        SET {update_clause}
        RETURNING id, case_id, file_sha256, file_name
        """

    def _get_kg_claim_columns(self, cur: psycopg.Cursor) -> set[str]:
        """Cache the current kg_claim column set so claim writes survive rolling migrations."""
        if self._kg_claim_columns_cache is not None:
            return self._kg_claim_columns_cache
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'kg_claim'
            """
        )
        self._kg_claim_columns_cache = {str(row["column_name"]) for row in cur.fetchall()}
        return self._kg_claim_columns_cache

    def _build_insert_claims_query(self, columns: set[str]) -> str:
        """Build an insert query that can write both legacy and upgraded kg_claim schemas."""
        preferred_columns = [
            "case_id",
            "extraction_run_id",
            "entity_id",
            "relation_id",
            "claim_type",
            "claim_text",
            "claim_value",
            "confidence",
            "prompt_version",
            "model_provider",
            "model_name",
            "parser_version",
            "status",
            "review_status",
        ]
        active_columns = [column for column in preferred_columns if column in columns]
        insert_columns = ", ".join(active_columns)
        insert_values = ", ".join(f"%({column})s" for column in active_columns)
        return f"""
        INSERT INTO public.kg_claim (
            {insert_columns}
        ) VALUES (
            {insert_values}
        )
        RETURNING id, entity_id, relation_id, claim_type, claim_text, confidence
        """

    def _normalize_claim_payload(self, row: dict[str, Any], columns: set[str]) -> dict[str, Any]:
        """Fill one claim payload for either upgraded status schema or legacy review_status schema."""
        normalized_status = normalize_graph_status(str(row.get("status", DEFAULT_GRAPH_STATUS) or ""))
        review_status = map_graph_status_to_claim_review_status(
            normalized_status,
            str(row.get("review_status", "pending") or "pending"),
        )
        defaults = {
            "case_id": 0,
            "extraction_run_id": 0,
            "entity_id": None,
            "relation_id": None,
            "claim_type": "",
            "claim_text": "",
            "claim_value": {},
            "confidence": 0,
            "prompt_version": "",
            "model_provider": "",
            "model_name": "",
            "parser_version": "",
            "status": normalized_status,
            "review_status": review_status,
        }
        return {column: row.get(column, defaults.get(column)) if column not in {"status", "review_status"} else defaults[column] for column in columns if column in defaults}

    def _normalize_source_file_payload(self, row: dict[str, Any], columns: set[str]) -> dict[str, Any]:
        """Fill missing source_file columns with harmless defaults for dynamic upserts."""
        defaults = {
            "case_id": 0,
            "debtor_id": 0,
            "file_name": "",
            "file_type": "",
            "content_type": "",
            "file_sha256": "",
            "file_size_bytes": 0,
            "storage_ref": "",
            "storage_provider": "",
            "storage_bucket": "",
            "storage_key": "",
            "storage_etag": "",
            "storage_version": "",
            "ingest_payload_ref": "",
            "ocr_provider": "",
            "ocr_version": "",
            "parser_version": "",
            "status": "active",
        }
        payload = {column: row.get(column, defaults.get(column)) for column in columns if column in defaults}
        return payload

    def create_extraction_run(
        self,
        *,
        case_id: int,
        run_type: str = "ingest",
        trigger_source: str = "system",
        source_file_ids: list[int] | None = None,
        chunk_count: int = 0,
        prompt_version: str = "",
        model_provider: str = "",
        model_name: str = "",
        status: str = "running",
    ) -> int:
        """Insert one extraction run record and return its primary key."""
        query = """
        INSERT INTO public.kg_extraction_run (
            case_id, run_type, trigger_source, source_file_ids, chunk_count,
            prompt_version, model_provider, model_name, status
        ) VALUES (
            %(case_id)s, %(run_type)s, %(trigger_source)s, %(source_file_ids)s, %(chunk_count)s,
            %(prompt_version)s, %(model_provider)s, %(model_name)s, %(status)s
        )
        RETURNING id
        """
        payload = {
            "case_id": case_id,
            "run_type": run_type,
            "trigger_source": trigger_source,
            "source_file_ids": Json(make_json_safe(source_file_ids or [])),
            "chunk_count": chunk_count,
            "prompt_version": prompt_version,
            "model_provider": model_provider,
            "model_name": model_name,
            "status": status,
        }
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, payload)
            run_id = int(cur.fetchone()["id"])
            conn.commit()
            return run_id

    def complete_extraction_run(self, run_id: int, *, status: str = "completed") -> None:
        """Mark one extraction run as completed."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.kg_extraction_run
                SET status = %(status)s,
                    finished_at = NOW()
                WHERE id = %(run_id)s
                """,
                {"run_id": run_id, "status": status},
            )
            conn.commit()

    def fail_extraction_run(self, run_id: int, error_message: str) -> None:
        """Mark one extraction run as failed and store its error message."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.kg_extraction_run
                SET status = 'failed',
                    error_message = %(error_message)s,
                    finished_at = NOW()
                WHERE id = %(run_id)s
                """,
                {"run_id": run_id, "error_message": error_message},
            )
            conn.commit()

    def insert_source_files(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert source files and return inserted identifiers."""
        if not rows:
            return []
        with self.connect() as conn, conn.cursor() as cur:
            columns = self._get_source_file_columns(cur)
            query = self._build_source_file_upsert_query(columns)
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = self._normalize_source_file_payload(row, columns)
                cur.execute(query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def upsert_source_upload_batch(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Create or update one upload batch metadata row."""
        upload_batch_id = str(summary.get("upload_batch_id", "") or "").strip()
        case_id = int(summary.get("case_id", 0) or 0)
        if not upload_batch_id or case_id <= 0:
            return {}
        query = """
        INSERT INTO public.source_upload_batch (
            upload_batch_id, case_id, debtor_id, batch_name, doc_category,
            operator_id, operator_name, status, file_count, new_file_count,
            duplicate_file_count, suspected_mismatch_file_count, records_inserted, metadata
        ) VALUES (
            %(upload_batch_id)s, %(case_id)s, %(debtor_id)s, %(batch_name)s, %(doc_category)s,
            %(operator_id)s, %(operator_name)s, %(status)s, %(file_count)s, %(new_file_count)s,
            %(duplicate_file_count)s, %(suspected_mismatch_file_count)s, %(records_inserted)s, %(metadata)s
        )
        ON CONFLICT (upload_batch_id) DO UPDATE
        SET case_id = EXCLUDED.case_id,
            debtor_id = EXCLUDED.debtor_id,
            batch_name = EXCLUDED.batch_name,
            doc_category = EXCLUDED.doc_category,
            operator_id = EXCLUDED.operator_id,
            operator_name = EXCLUDED.operator_name,
            status = EXCLUDED.status,
            file_count = EXCLUDED.file_count,
            new_file_count = EXCLUDED.new_file_count,
            duplicate_file_count = EXCLUDED.duplicate_file_count,
            suspected_mismatch_file_count = EXCLUDED.suspected_mismatch_file_count,
            records_inserted = EXCLUDED.records_inserted,
            metadata = EXCLUDED.metadata,
            updated_at = NOW()
        RETURNING
            upload_batch_id, case_id, debtor_id, batch_name, doc_category,
            operator_id, operator_name, status, file_count, new_file_count,
            duplicate_file_count, suspected_mismatch_file_count, records_inserted, metadata
        """
        payload = {
            "upload_batch_id": upload_batch_id,
            "case_id": case_id,
            "debtor_id": int(summary.get("debtor_id", 0) or 0),
            "batch_name": str(summary.get("batch_name", "") or ""),
            "doc_category": str(summary.get("doc_category", "") or "") or None,
            "operator_id": str(summary.get("operator_id", "") or ""),
            "operator_name": str(summary.get("operator_name", "") or ""),
            "status": str(summary.get("status", "") or "received"),
            "file_count": int(summary.get("file_count", 0) or 0),
            "new_file_count": int(summary.get("new_file_count", 0) or 0),
            "duplicate_file_count": int(summary.get("duplicate_file_count", 0) or 0),
            "suspected_mismatch_file_count": int(summary.get("suspected_mismatch_file_count", 0) or 0),
            "records_inserted": int(summary.get("records_inserted", 0) or 0),
            "metadata": Json(make_json_safe(summary.get("metadata", {}) or {})),
        }
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, payload)
            returned = dict(cur.fetchone())
            conn.commit()
            return returned

    def fetch_source_upload_batch(self, upload_batch_id: str) -> dict[str, Any]:
        """Return one upload batch with file/category/page/chunk verification details."""
        normalized_batch_id = str(upload_batch_id or "").strip()
        if not normalized_batch_id:
            return {}
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        upload_batch_id, case_id, debtor_id, batch_name, doc_category,
                        operator_id, operator_name, status, file_count, new_file_count,
                        duplicate_file_count, suspected_mismatch_file_count,
                        records_inserted, metadata, created_at, updated_at
                    FROM public.source_upload_batch
                    WHERE upload_batch_id = %(upload_batch_id)s
                    """,
                    {"upload_batch_id": normalized_batch_id},
                )
                batch = cur.fetchone()
                if not batch:
                    return {}
                cur.execute(
                    """
                    SELECT
                        link.id AS upload_batch_link_id,
                        link.file_id,
                        link.file_name,
                        link.file_sha256,
                        link.duplicate_of,
                        sf.file_type,
                        sf.content_type,
                        sf.file_size_bytes,
                        sf.storage_provider,
                        sf.storage_bucket,
                        sf.storage_key,
                        sf.storage_ref,
                        sf.created_at,
                        COALESCE(page_counts.page_count, 0) AS page_count,
                        COALESCE(chunk_counts.chunk_count, 0) AS chunk_count,
                        COALESCE(
                            ARRAY_REMOVE(ARRAY_AGG(DISTINCT category.category_code), NULL),
                            ARRAY[]::TEXT[]
                        ) AS doc_categories
                    FROM public.source_file_upload_batch link
                    JOIN public.source_file sf ON sf.id = link.file_id
                    LEFT JOIN public.source_file_doc_category category ON category.file_id = link.file_id
                    LEFT JOIN (
                        SELECT file_id, COUNT(*) AS page_count
                        FROM public.source_page
                        GROUP BY file_id
                    ) page_counts ON page_counts.file_id = link.file_id
                    LEFT JOIN (
                        SELECT file_id, COUNT(*) AS chunk_count
                        FROM public.source_chunk
                        GROUP BY file_id
                    ) chunk_counts ON chunk_counts.file_id = link.file_id
                    WHERE link.upload_batch_id = %(upload_batch_id)s
                    GROUP BY
                        link.id, link.file_id, link.file_name, link.file_sha256, link.duplicate_of,
                        sf.file_type, sf.content_type, sf.file_size_bytes, sf.storage_provider, sf.storage_bucket,
                        sf.storage_key, sf.storage_ref, sf.created_at,
                        page_counts.page_count, chunk_counts.chunk_count
                    ORDER BY link.id
                    """,
                    {"upload_batch_id": normalized_batch_id},
                )
                files = [dict(row) for row in cur.fetchall()]
        except UndefinedTable:
            LOGGER.warning("fetch_source_upload_batch_skipped_missing_tables upload_batch_id=%s", normalized_batch_id)
            return {}
        return {
            **dict(batch),
            "files": files,
            "persistence_checks": _build_upload_batch_persistence_checks(dict(batch), files),
        }

    def list_source_upload_batches_by_case(self, case_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """List recent upload batches for one case."""
        normalized_case_id = int(case_id or 0)
        if normalized_case_id <= 0:
            return []
        normalized_limit = max(1, min(int(limit or 50), 200))
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        upload_batch_id, case_id, debtor_id, batch_name, doc_category,
                        operator_id, operator_name, status, file_count, new_file_count,
                        duplicate_file_count, suspected_mismatch_file_count,
                        records_inserted, metadata, created_at, updated_at
                    FROM public.source_upload_batch
                    WHERE case_id = %(case_id)s
                    ORDER BY created_at DESC
                    LIMIT %(limit)s
                    """,
                    {"case_id": normalized_case_id, "limit": normalized_limit},
                )
                return [dict(row) for row in cur.fetchall()]
        except UndefinedTable:
            LOGGER.warning("list_source_upload_batches_skipped_missing_table case_id=%s", normalized_case_id)
            return []

    def link_source_files_to_upload_batch(
        self,
        *,
        upload_batch_id: str,
        files: list[dict[str, Any]],
        duplicate_by_sha256: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Link inserted source files to an upload batch."""
        if not upload_batch_id or not files:
            return []
        query = """
        INSERT INTO public.source_file_upload_batch (
            upload_batch_id, file_id, file_name, file_sha256, duplicate_of
        ) VALUES (
            %(upload_batch_id)s, %(file_id)s, %(file_name)s, %(file_sha256)s, %(duplicate_of)s
        )
        ON CONFLICT (upload_batch_id, file_id) DO UPDATE
        SET file_name = EXCLUDED.file_name,
            file_sha256 = EXCLUDED.file_sha256,
            duplicate_of = EXCLUDED.duplicate_of
        RETURNING id, upload_batch_id, file_id, file_name, duplicate_of
        """
        duplicate_by_sha256 = duplicate_by_sha256 or {}
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for file_row in files:
                file_sha256 = str(file_row.get("file_sha256", "") or "")
                cur.execute(
                    query,
                    {
                        "upload_batch_id": upload_batch_id,
                        "file_id": int(file_row["id"]),
                        "file_name": str(file_row.get("file_name", "") or ""),
                        "file_sha256": file_sha256,
                        "duplicate_of": duplicate_by_sha256.get(file_sha256, ""),
                    },
                )
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def upsert_material_event(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Create or update one material event row."""
        material_event_id = str(summary.get("material_event_id", "") or "").strip()
        case_id = int(summary.get("case_id", 0) or 0)
        if not material_event_id or case_id <= 0:
            return {}
        status = str(summary.get("status", "") or "received")
        query = """
        INSERT INTO public.material_event (
            material_event_id, case_id, debtor_id, upload_batch_id, event_type, status,
            batch_name, doc_category, operator_id, operator_name,
            file_count, records_inserted, event_payload, error_message,
            started_at, completed_at, failed_at
        ) VALUES (
            %(material_event_id)s, %(case_id)s, %(debtor_id)s, %(upload_batch_id)s, %(event_type)s, %(status)s,
            %(batch_name)s, %(doc_category)s, %(operator_id)s, %(operator_name)s,
            %(file_count)s, %(records_inserted)s, %(event_payload)s, %(error_message)s,
            %(started_at)s, %(completed_at)s, %(failed_at)s
        )
        ON CONFLICT (material_event_id) DO UPDATE
        SET case_id = EXCLUDED.case_id,
            debtor_id = EXCLUDED.debtor_id,
            upload_batch_id = EXCLUDED.upload_batch_id,
            event_type = EXCLUDED.event_type,
            status = EXCLUDED.status,
            batch_name = EXCLUDED.batch_name,
            doc_category = EXCLUDED.doc_category,
            operator_id = EXCLUDED.operator_id,
            operator_name = EXCLUDED.operator_name,
            file_count = EXCLUDED.file_count,
            records_inserted = EXCLUDED.records_inserted,
            event_payload = EXCLUDED.event_payload,
            error_message = EXCLUDED.error_message,
            started_at = COALESCE(EXCLUDED.started_at, public.material_event.started_at),
            completed_at = COALESCE(EXCLUDED.completed_at, public.material_event.completed_at),
            failed_at = COALESCE(EXCLUDED.failed_at, public.material_event.failed_at),
            updated_at = NOW()
        RETURNING
            material_event_id, case_id, debtor_id, upload_batch_id, event_type, status,
            batch_name, doc_category, operator_id, operator_name,
            file_count, records_inserted, event_payload, error_message,
            started_at, completed_at, failed_at, created_at, updated_at
        """
        payload = {
            "material_event_id": material_event_id,
            "case_id": case_id,
            "debtor_id": int(summary.get("debtor_id", 0) or 0),
            "upload_batch_id": str(summary.get("upload_batch_id", "") or ""),
            "event_type": str(summary.get("event_type", "") or "supplement_upload"),
            "status": status,
            "batch_name": str(summary.get("batch_name", "") or ""),
            "doc_category": str(summary.get("doc_category", "") or ""),
            "operator_id": str(summary.get("operator_id", "") or ""),
            "operator_name": str(summary.get("operator_name", "") or ""),
            "file_count": int(summary.get("file_count", 0) or 0),
            "records_inserted": int(summary.get("records_inserted", 0) or 0),
            "event_payload": Json(make_json_safe(summary.get("event_payload", {}) or {})),
            "error_message": str(summary.get("error_message", "") or ""),
            "started_at": "NOW()" if status == "processing" else None,
            "completed_at": "NOW()" if status == "completed" else None,
            "failed_at": "NOW()" if status == "failed" else None,
        }
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                query.replace("%(started_at)s", "NOW()" if payload["started_at"] == "NOW()" else "NULL")
                .replace("%(completed_at)s", "NOW()" if payload["completed_at"] == "NOW()" else "NULL")
                .replace("%(failed_at)s", "NOW()" if payload["failed_at"] == "NOW()" else "NULL"),
                {key: value for key, value in payload.items() if key not in {"started_at", "completed_at", "failed_at"}},
            )
            returned = dict(cur.fetchone())
            conn.commit()
            return returned

    def fetch_material_event(self, material_event_id: str) -> dict[str, Any]:
        """Fetch one material event by ID."""
        normalized_id = str(material_event_id or "").strip()
        if not normalized_id:
            return {}
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        material_event_id, case_id, debtor_id, upload_batch_id, event_type, status,
                        batch_name, doc_category, operator_id, operator_name,
                        file_count, records_inserted, event_payload, error_message,
                        started_at, completed_at, failed_at, created_at, updated_at
                    FROM public.material_event
                    WHERE material_event_id = %(material_event_id)s
                    """,
                    {"material_event_id": normalized_id},
                )
                row = cur.fetchone()
                return dict(row) if row else {}
        except UndefinedTable:
            LOGGER.warning("fetch_material_event_skipped_missing_table material_event_id=%s", normalized_id)
            return {}

    def list_material_events_by_case(self, case_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        """List recent material events for one case."""
        normalized_case_id = int(case_id or 0)
        if normalized_case_id <= 0:
            return []
        normalized_limit = max(1, min(int(limit or 50), 200))
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        material_event_id, case_id, debtor_id, upload_batch_id, event_type, status,
                        batch_name, doc_category, operator_id, operator_name,
                        file_count, records_inserted, event_payload, error_message,
                        started_at, completed_at, failed_at, created_at, updated_at
                    FROM public.material_event
                    WHERE case_id = %(case_id)s
                    ORDER BY created_at DESC
                    LIMIT %(limit)s
                    """,
                    {"case_id": normalized_case_id, "limit": normalized_limit},
                )
                return [dict(row) for row in cur.fetchall()]
        except UndefinedTable:
            LOGGER.warning("list_material_events_by_case_skipped_missing_table case_id=%s", normalized_case_id)
            return []

    def upsert_source_file_doc_categories(
        self,
        *,
        case_id: int,
        category_code: str,
        files: list[dict[str, Any]],
        match_source: str = "manual",
        confidence: float | None = None,
        notes: str = "",
    ) -> list[dict[str, Any]]:
        """Maintain source_file -> doc_category relation rows."""
        normalized_category = str(category_code or "").strip()
        if int(case_id or 0) <= 0 or not normalized_category or not files:
            return []
        query = """
        INSERT INTO public.source_file_doc_category (
            file_id, case_id, category_code, match_source, confidence, notes
        ) VALUES (
            %(file_id)s, %(case_id)s, %(category_code)s, %(match_source)s, %(confidence)s, %(notes)s
        )
        ON CONFLICT (file_id, category_code) DO UPDATE
        SET case_id = EXCLUDED.case_id,
            match_source = EXCLUDED.match_source,
            confidence = EXCLUDED.confidence,
            notes = EXCLUDED.notes,
            updated_at = NOW()
        RETURNING id, file_id, case_id, category_code, match_source
        """
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for file_row in files:
                cur.execute(
                    query,
                    {
                        "file_id": int(file_row["id"]),
                        "case_id": int(case_id),
                        "category_code": normalized_category,
                        "match_source": match_source,
                        "confidence": confidence,
                        "notes": notes,
                    },
                )
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def insert_source_pages(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert page records and return inserted identifiers."""
        if not rows:
            return []
        query = """
        INSERT INTO public.source_page (
            file_id, page_no, page_text, page_image_ref, page_width, page_height, ocr_blocks
        ) VALUES (
            %(file_id)s, %(page_no)s, %(page_text)s, %(page_image_ref)s, %(page_width)s, %(page_height)s, %(ocr_blocks)s
        )
        ON CONFLICT (file_id, page_no) DO UPDATE
        SET page_text = EXCLUDED.page_text,
            page_image_ref = EXCLUDED.page_image_ref,
            page_width = EXCLUDED.page_width,
            page_height = EXCLUDED.page_height,
            ocr_blocks = EXCLUDED.ocr_blocks
        RETURNING id, file_id, page_no
        """
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = dict(row)
                payload["ocr_blocks"] = Json(make_json_safe(payload.get("ocr_blocks", [])))
                cur.execute(query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def insert_source_chunks(self, rows: list[SourceChunkModel | dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert chunk records and return identifiers."""
        if not rows:
            return []
        query = """
        INSERT INTO public.source_chunk (
            chunk_id, case_id, file_id, page_id, page_no, chunk_index, chunk_type,
            chunk_text, chunk_text_sha256, anchor_text, bbox_list, span_start, span_end,
            token_count, metadata
        ) VALUES (
            %(chunk_id)s, %(case_id)s, %(file_id)s, %(page_id)s, %(page_no)s, %(chunk_index)s, %(chunk_type)s,
            %(chunk_text)s, %(chunk_text_sha256)s, %(anchor_text)s, %(bbox_list)s, %(span_start)s, %(span_end)s,
            %(token_count)s, %(metadata)s
        )
        ON CONFLICT (chunk_id) DO UPDATE
        SET chunk_text = EXCLUDED.chunk_text,
            anchor_text = EXCLUDED.anchor_text,
            bbox_list = EXCLUDED.bbox_list,
            span_start = EXCLUDED.span_start,
            span_end = EXCLUDED.span_end,
            token_count = EXCLUDED.token_count,
            metadata = EXCLUDED.metadata
        RETURNING id, chunk_id, case_id, file_id, page_id, page_no
        """
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = row.model_dump() if isinstance(row, SourceChunkModel) else row
                payload = dict(payload)
                payload["bbox_list"] = Json(make_json_safe(payload.get("bbox_list", [])))
                payload["metadata"] = Json(make_json_safe(payload.get("metadata", {})))
                cur.execute(query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def upsert_entities(
        self,
        *,
        case_id: int,
        rows: list[ExtractedEntityModel | dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Upsert entities by their stable entity_key."""
        if not rows:
            return []
        query = """
        INSERT INTO public.kg_entity (
            case_id, entity_key, entity_type, canonical_name, aliases, normalized_name,
            attributes, first_seen_chunk_id, confidence, source_count, human_verified, status
        ) VALUES (
            %(case_id)s, %(entity_key)s, %(entity_type)s, %(canonical_name)s, %(aliases)s, %(normalized_name)s,
            %(attributes)s, %(first_seen_chunk_id)s, %(confidence)s, %(source_count)s, %(human_verified)s, %(status)s
        )
        ON CONFLICT (case_id, entity_key) DO UPDATE
        SET canonical_name = EXCLUDED.canonical_name,
            aliases = EXCLUDED.aliases,
            normalized_name = EXCLUDED.normalized_name,
            attributes = EXCLUDED.attributes,
            first_seen_chunk_id = EXCLUDED.first_seen_chunk_id,
            confidence = EXCLUDED.confidence,
            source_count = EXCLUDED.source_count,
            human_verified = EXCLUDED.human_verified,
            status = EXCLUDED.status,
            updated_at = NOW()
        RETURNING id, case_id, entity_key, canonical_name
        """
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = row.model_dump() if isinstance(row, ExtractedEntityModel) else dict(row)
                payload["case_id"] = case_id
                payload["aliases"] = Json(make_json_safe(payload.get("aliases", [])))
                payload["attributes"] = Json(make_json_safe(payload.get("attributes", {})))
                cur.execute(query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def upsert_relations(
        self,
        *,
        case_id: int,
        rows: list[ExtractedRelationModel | dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Upsert graph relations by their stable relation_key."""
        if not rows:
            return []
        query = """
        INSERT INTO public.kg_relation (
            case_id, relation_key, from_entity_id, to_entity_id, relation_type, relation_label,
            direction, amount, amount_currency, event_date, attributes, confidence, source_count,
            human_verified, status
        ) VALUES (
            %(case_id)s, %(relation_key)s, %(from_entity_id)s, %(to_entity_id)s, %(relation_type)s, %(relation_label)s,
            %(direction)s, %(amount)s, %(amount_currency)s, %(event_date)s, %(attributes)s, %(confidence)s, %(source_count)s,
            %(human_verified)s, %(status)s
        )
        ON CONFLICT (case_id, relation_key) DO UPDATE
        SET from_entity_id = EXCLUDED.from_entity_id,
            to_entity_id = EXCLUDED.to_entity_id,
            relation_type = EXCLUDED.relation_type,
            relation_label = EXCLUDED.relation_label,
            direction = EXCLUDED.direction,
            amount = EXCLUDED.amount,
            amount_currency = EXCLUDED.amount_currency,
            event_date = EXCLUDED.event_date,
            attributes = EXCLUDED.attributes,
            confidence = EXCLUDED.confidence,
            source_count = EXCLUDED.source_count,
            human_verified = EXCLUDED.human_verified,
            status = EXCLUDED.status,
            updated_at = NOW()
        RETURNING id, case_id, relation_key, from_entity_id, to_entity_id
        """
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = row.model_dump() if isinstance(row, ExtractedRelationModel) else dict(row)
                payload["case_id"] = case_id
                payload["attributes"] = Json(make_json_safe(payload.get("attributes", {})))
                cur.execute(query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def insert_claims(
        self,
        *,
        case_id: int,
        extraction_run_id: int,
        rows: list[ExtractionClaimModel | dict[str, Any]],
        prompt_version: str = "",
        model_provider: str = "",
        model_name: str = "",
        parser_version: str = "",
    ) -> list[dict[str, Any]]:
        """Insert extraction claims and return their identifiers."""
        if not rows:
            return []
        with self.connect() as conn, conn.cursor() as cur:
            columns = self._get_kg_claim_columns(cur)
            query = self._build_insert_claims_query(columns)
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = row.model_dump() if isinstance(row, ExtractionClaimModel) else dict(row)
                payload.update(
                    {
                        "case_id": case_id,
                        "extraction_run_id": extraction_run_id,
                        "prompt_version": prompt_version,
                        "model_provider": model_provider,
                        "model_name": model_name,
                        "parser_version": parser_version,
                        "entity_id": payload.get("entity_id"),
                        "relation_id": payload.get("relation_id"),
                    }
                )
                normalized_payload = self._normalize_claim_payload(payload, columns)
                normalized_payload["claim_value"] = Json(
                    make_json_safe(normalized_payload.get("claim_value", {}))
                )
                cur.execute(query, normalized_payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def mark_claims_superseded(self, claim_ids: list[int]) -> int:
        """Soft-supersede claims so later evidence can replace them without hard deletion."""
        normalized_ids = [int(claim_id) for claim_id in claim_ids if int(claim_id) > 0]
        if not normalized_ids:
            return 0
        with self.connect() as conn, conn.cursor() as cur:
            columns = self._get_kg_claim_columns(cur)
            if "status" in columns:
                cur.execute(
                    """
                    UPDATE public.kg_claim
                    SET status = 'superseded'
                    WHERE id = ANY(%(claim_ids)s::bigint[])
                    """,
                    {"claim_ids": normalized_ids},
                )
            else:
                cur.execute(
                    """
                    UPDATE public.kg_claim
                    SET review_status = 'corrected'
                    WHERE id = ANY(%(claim_ids)s::bigint[])
                    """,
                    {"claim_ids": normalized_ids},
                )
            conn.commit()
            return cur.rowcount or 0

    def mark_relations_superseded(self, relation_ids: list[int]) -> int:
        """Soft-supersede relations so new evidence can replace them without hard deletion."""
        normalized_ids = [int(relation_id) for relation_id in relation_ids if int(relation_id) > 0]
        if not normalized_ids:
            return 0
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.kg_relation
                SET status = 'superseded',
                    updated_at = NOW()
                WHERE id = ANY(%(relation_ids)s::bigint[])
                """,
                {"relation_ids": normalized_ids},
            )
            conn.commit()
            return cur.rowcount or 0

    def insert_evidence_links(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert claim-to-evidence mappings."""
        if not rows:
            return []
        query = """
        INSERT INTO public.kg_evidence_link (
            claim_id, chunk_id, file_id, page_no, quote_text, bbox_list, score
        ) VALUES (
            %(claim_id)s, %(chunk_id)s, %(file_id)s, %(page_no)s, %(quote_text)s, %(bbox_list)s, %(score)s
        )
        RETURNING id, claim_id, chunk_id
        """
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = dict(row)
                payload["bbox_list"] = Json(make_json_safe(payload.get("bbox_list", [])))
                cur.execute(query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def insert_reconciliation_ledger(
        self,
        *,
        case_id: int,
        rows: list[ReconciliationLedgerItemModel | dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Persist incremental reconciliation rows for later audit and frontend explanation."""
        if case_id <= 0 or not rows:
            return []
        query = """
        INSERT INTO public.kg_reconciliation_ledger (
            case_id,
            action,
            new_claim_id,
            superseded_claim_id,
            new_relation_id,
            superseded_relation_id,
            rationale,
            evidence_chunk_ids,
            decision_payload
        ) VALUES (
            %(case_id)s,
            %(action)s,
            %(new_claim_id)s,
            %(superseded_claim_id)s,
            %(new_relation_id)s,
            %(superseded_relation_id)s,
            %(rationale)s,
            %(evidence_chunk_ids)s,
            %(decision_payload)s
        )
        RETURNING
            id,
            case_id,
            action,
            new_claim_id,
            superseded_claim_id,
            new_relation_id,
            superseded_relation_id,
            rationale,
            evidence_chunk_ids,
            decision_payload,
            created_at
        """
        with self.connect() as conn, conn.cursor() as cur:
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = row.model_dump() if isinstance(row, ReconciliationLedgerItemModel) else dict(row)
                payload["case_id"] = case_id
                payload["action"] = str(payload.get("action", "ADD") or "ADD").upper()
                payload["new_relation_id"] = _normalize_optional_fk(payload.get("new_relation_id"))
                payload["superseded_relation_id"] = _normalize_optional_fk(payload.get("superseded_relation_id"))
                payload["evidence_chunk_ids"] = Json(
                    make_json_safe(payload.get("evidence_chunk_ids", []))
                )
                payload["decision_payload"] = Json(
                    make_json_safe(payload.get("decision_payload", {}))
                )
                cur.execute(query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def fetch_reconciliation_ledger(self, *, case_id: int, limit: int = 12) -> list[dict[str, Any]]:
        """Fetch recent reconciliation rows with enough context for frontend drilldown."""
        if case_id <= 0:
            return []
        query = """
        SELECT
            l.id,
            l.case_id,
            l.action,
            l.new_claim_id,
            nc.claim_text AS new_claim_text,
            l.superseded_claim_id,
            oc.claim_text AS superseded_claim_text,
            l.new_relation_id,
            l.superseded_relation_id,
            l.rationale,
            l.evidence_chunk_ids,
            l.decision_payload,
            l.created_at
        FROM public.kg_reconciliation_ledger l
        JOIN public.kg_claim nc ON nc.id = l.new_claim_id
        LEFT JOIN public.kg_claim oc ON oc.id = l.superseded_claim_id
        WHERE l.case_id = %(case_id)s
        ORDER BY l.created_at DESC, l.id DESC
        LIMIT %(limit)s
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"case_id": case_id, "limit": max(int(limit or 0), 1)})
            return [dict(row) for row in cur.fetchall()]

    def fetch_case_evolution_items(
        self,
        *,
        case_id: int,
        action: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch frontend-friendly claim evolution rows with event and evidence context."""
        if case_id <= 0:
            return []
        normalized_action = str(action or "").strip().upper()
        query = """
        SELECT
            l.id,
            l.case_id,
            l.action,
            l.new_claim_id,
            nc.claim_text AS new_claim_text,
            nc.claim_type AS new_claim_type,
            l.superseded_claim_id,
            oc.claim_text AS superseded_claim_text,
            oc.claim_type AS superseded_claim_type,
            l.new_relation_id,
            l.superseded_relation_id,
            l.rationale,
            l.evidence_chunk_ids,
            l.decision_payload,
            l.created_at,
            batch.upload_batch_id,
            COALESCE(batch.batch_name, '') AS batch_name,
            COALESCE(batch.doc_category, '') AS doc_category,
            COALESCE(me.material_event_id, '') AS material_event_id,
            COALESCE(me.status, '') AS material_event_status,
            COALESCE(me.event_type, '') AS material_event_type
        FROM public.kg_reconciliation_ledger l
        JOIN public.kg_claim nc ON nc.id = l.new_claim_id
        LEFT JOIN public.kg_claim oc ON oc.id = l.superseded_claim_id
        LEFT JOIN LATERAL (
            SELECT
                link.upload_batch_id,
                sb.batch_name,
                sb.doc_category
            FROM public.kg_evidence_link e
            JOIN public.source_chunk sc ON sc.chunk_id = e.chunk_id
            JOIN public.source_file_upload_batch link ON link.file_id = sc.file_id
            LEFT JOIN public.source_upload_batch sb ON sb.upload_batch_id = link.upload_batch_id
            WHERE e.claim_id = l.new_claim_id
            ORDER BY link.id DESC
            LIMIT 1
        ) batch ON TRUE
        LEFT JOIN public.material_event me ON me.upload_batch_id = batch.upload_batch_id
        WHERE l.case_id = %(case_id)s
          AND (%(action)s = '' OR l.action = %(action)s)
        ORDER BY l.created_at DESC, l.id DESC
        LIMIT %(limit)s
        """
        evidence_query = """
        SELECT
            e.claim_id,
            e.chunk_id,
            e.file_id,
            sf.file_name,
            e.page_no,
            e.quote_text,
            e.bbox_list,
            sc.page_id AS source_page_id,
            sp.page_image_ref,
            sf.storage_ref,
            sf.content_type,
            c.entity_id
        FROM public.kg_evidence_link e
        LEFT JOIN public.kg_claim c ON c.id = e.claim_id
        LEFT JOIN public.source_file sf ON sf.id = e.file_id
        LEFT JOIN public.source_chunk sc ON sc.chunk_id = e.chunk_id
        LEFT JOIN public.source_page sp ON sp.id = sc.page_id
        WHERE e.claim_id = ANY(%(claim_ids)s::bigint[])
        ORDER BY e.claim_id, e.id
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                query,
                {
                    "case_id": case_id,
                    "action": normalized_action,
                    "limit": max(int(limit or 0), 1),
                },
            )
            rows = [dict(row) for row in cur.fetchall()]
            claim_ids = [int(row.get("new_claim_id", 0) or 0) for row in rows if int(row.get("new_claim_id", 0) or 0) > 0]
            evidence_rows: list[dict[str, Any]] = []
            if claim_ids:
                cur.execute(evidence_query, {"claim_ids": claim_ids})
                evidence_rows = [dict(row) for row in cur.fetchall()]

        evidence_by_claim_id: dict[int, list[dict[str, Any]]] = {}
        for row in evidence_rows:
            claim_id = int(row.get("claim_id", 0) or 0)
            if claim_id <= 0:
                continue
            evidence_by_claim_id.setdefault(claim_id, []).append(
                {
                    "chunk_id": str(row.get("chunk_id", "") or ""),
                    "file_id": int(row.get("file_id", 0) or 0),
                    "file_name": str(row.get("file_name", "") or ""),
                    "page_no": int(row.get("page_no", 0) or 0),
                    "quote_text": str(row.get("quote_text", "") or ""),
                    "bbox_list": row.get("bbox_list") or [],
                    "source_page_id": int(row.get("source_page_id", 0) or 0),
                    "page_image_ref": resolve_minio_reference_url(str(row.get("page_image_ref", "") or "")),
                    "source_file_url": resolve_minio_reference_url(str(row.get("storage_ref", "") or "")),
                    "content_type": str(row.get("content_type", "") or ""),
                    "entity_id": int(row.get("entity_id", 0) or 0),
                }
            )

        items: list[dict[str, Any]] = []
        for row in rows:
            new_claim_id = int(row.get("new_claim_id", 0) or 0)
            items.append(
                {
                    **row,
                    "upload_batch_id": str(row.get("upload_batch_id", "") or ""),
                    "batch_name": str(row.get("batch_name", "") or ""),
                    "doc_category": str(row.get("doc_category", "") or ""),
                    "material_event_id": str(row.get("material_event_id", "") or ""),
                    "material_event_status": str(row.get("material_event_status", "") or ""),
                    "material_event_type": str(row.get("material_event_type", "") or ""),
                    "evidences": evidence_by_claim_id.get(new_claim_id, []),
                }
            )
        return items

    def insert_unresolved_graph_items(
        self,
        *,
        case_id: int,
        extraction_run_id: int,
        upload_batch_id: str = "",
        material_event_id: str = "",
        relation_rows: list[dict[str, Any]] | None = None,
        claim_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Persist unresolved relation/claim items so later batches can replay them."""
        normalized_relation_rows = [dict(row) for row in (relation_rows or []) if isinstance(row, dict)]
        normalized_claim_rows = [dict(row) for row in (claim_rows or []) if isinstance(row, dict)]
        if case_id <= 0 or extraction_run_id <= 0 or (not normalized_relation_rows and not normalized_claim_rows):
            return {"unresolved_relations": [], "unresolved_claims": []}

        query = """
        INSERT INTO public.kg_unresolved_item (
            case_id,
            extraction_run_id,
            upload_batch_id,
            material_event_id,
            item_type,
            entity_name,
            entity_key,
            relation_key,
            entity_temp_id,
            relation_temp_id,
            claim_type,
            claim_text,
            relation_type,
            relation_label,
            missing_dependencies,
            reason,
            status,
            payload
        ) VALUES (
            %(case_id)s,
            %(extraction_run_id)s,
            %(upload_batch_id)s,
            %(material_event_id)s,
            %(item_type)s,
            %(entity_name)s,
            %(entity_key)s,
            %(relation_key)s,
            %(entity_temp_id)s,
            %(relation_temp_id)s,
            %(claim_type)s,
            %(claim_text)s,
            %(relation_type)s,
            %(relation_label)s,
            %(missing_dependencies)s,
            %(reason)s,
            %(status)s,
            %(payload)s
        )
        RETURNING
            id,
            case_id,
            extraction_run_id,
            upload_batch_id,
            material_event_id,
            item_type,
            entity_name,
            entity_key,
            relation_key,
            entity_temp_id,
            relation_temp_id,
            claim_type,
            claim_text,
            relation_type,
            relation_label,
            missing_dependencies,
            reason,
            status,
            payload,
            created_at
        """
        returned_relations: list[dict[str, Any]] = []
        returned_claims: list[dict[str, Any]] = []
        with self.connect() as conn, conn.cursor() as cur:
            for row in normalized_relation_rows:
                payload = {
                    "case_id": case_id,
                    "extraction_run_id": extraction_run_id,
                    "upload_batch_id": str(upload_batch_id or ""),
                    "material_event_id": str(material_event_id or ""),
                    "item_type": "relation",
                    "entity_name": "",
                    "entity_key": "",
                    "relation_key": str(row.get("relation_key", "") or ""),
                    "entity_temp_id": str(row.get("from_entity_temp_id", "") or ""),
                    "relation_temp_id": str(row.get("relation_temp_id", "") or ""),
                    "claim_type": "",
                    "claim_text": "",
                    "relation_type": str(row.get("relation_type", "") or ""),
                    "relation_label": str(row.get("relation_label", "") or ""),
                    "missing_dependencies": Json(
                        make_json_safe(row.get("missing_dependencies", []))
                    ),
                    "reason": str(row.get("reason", "") or ""),
                    "status": "pending",
                    "payload": Json(make_json_safe(row)),
                }
                cur.execute(query, payload)
                returned_relations.append(dict(cur.fetchone()))
            for row in normalized_claim_rows:
                payload = {
                    "case_id": case_id,
                    "extraction_run_id": extraction_run_id,
                    "upload_batch_id": str(upload_batch_id or ""),
                    "material_event_id": str(material_event_id or ""),
                    "item_type": "claim",
                    "entity_name": str(row.get("entity_name", "") or ""),
                    "entity_key": str(row.get("entity_key", "") or ""),
                    "relation_key": str(row.get("relation_key", "") or ""),
                    "entity_temp_id": str(row.get("entity_temp_id", "") or ""),
                    "relation_temp_id": str(row.get("relation_temp_id", "") or ""),
                    "claim_type": str(row.get("claim_type", "") or ""),
                    "claim_text": str(row.get("claim_text", "") or ""),
                    "relation_type": "",
                    "relation_label": "",
                    "missing_dependencies": Json(
                        make_json_safe(row.get("missing_dependencies", []))
                    ),
                    "reason": str(row.get("reason", "") or ""),
                    "status": "pending",
                    "payload": Json(make_json_safe(row)),
                }
                cur.execute(query, payload)
                returned_claims.append(dict(cur.fetchone()))
            conn.commit()
        return {
            "unresolved_relations": returned_relations,
            "unresolved_claims": returned_claims,
        }

    def fetch_unresolved_graph_items(
        self,
        *,
        case_id: int,
        upload_batch_id: str = "",
        status: str = "pending",
        limit: int = 50,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch unresolved relation/claim items for one case, optionally scoped to one batch."""
        if case_id <= 0:
            return {"unresolved_relations": [], "unresolved_claims": []}
        query = """
        SELECT
            id,
            case_id,
            extraction_run_id,
            upload_batch_id,
            material_event_id,
            item_type,
            entity_name,
            entity_key,
            relation_key,
            entity_temp_id,
            relation_temp_id,
            claim_type,
            claim_text,
            relation_type,
            relation_label,
            missing_dependencies,
            reason,
            status,
            payload,
            created_at
        FROM public.kg_unresolved_item
        WHERE case_id = %(case_id)s
          AND (%(upload_batch_id)s = '' OR upload_batch_id = %(upload_batch_id)s)
          AND (%(status)s = '' OR status = %(status)s)
        ORDER BY created_at DESC, id DESC
        LIMIT %(limit)s
        """
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    query,
                    {
                        "case_id": case_id,
                        "upload_batch_id": str(upload_batch_id or ""),
                        "status": str(status or ""),
                        "limit": max(int(limit or 0), 1),
                    },
                )
                rows = [dict(row) for row in cur.fetchall()]
        except UndefinedTable:
            LOGGER.warning("fetch_unresolved_graph_items_skipped_missing_table case_id=%s", case_id)
            return {"unresolved_relations": [], "unresolved_claims": []}
        return {
            "unresolved_relations": [row for row in rows if str(row.get("item_type", "")) == "relation"],
            "unresolved_claims": [row for row in rows if str(row.get("item_type", "")) == "claim"],
        }

    def fetch_active_entities(
        self,
        *,
        case_id: int,
        entity_keys: list[str] | None = None,
        entity_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch active entities by stable keys or normalized names for cross-batch replay."""
        normalized_keys = [str(item).strip() for item in (entity_keys or []) if str(item).strip()]
        normalized_names = [normalize_entity_name(str(item)) for item in (entity_names or []) if str(item).strip()]
        normalized_names = [item for item in normalized_names if item]
        if case_id <= 0 or (not normalized_keys and not normalized_names):
            return []
        query = """
        SELECT id, case_id, entity_key, canonical_name, normalized_name, entity_type
        FROM public.kg_entity
        WHERE case_id = %(case_id)s
          AND COALESCE(status, 'active') = 'active'
          AND (
                (%(entity_keys)s::text[] IS NOT NULL AND entity_key = ANY(%(entity_keys)s::text[]))
                OR (%(entity_names)s::text[] IS NOT NULL AND normalized_name = ANY(%(entity_names)s::text[]))
          )
        ORDER BY id DESC
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                query,
                {
                    "case_id": case_id,
                    "entity_keys": normalized_keys or None,
                    "entity_names": normalized_names or None,
                },
            )
            return [dict(row) for row in cur.fetchall()]

    def fetch_active_relations(
        self,
        *,
        case_id: int,
        relation_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch active relations by stable relation keys for cross-batch replay."""
        normalized_keys = [str(item).strip() for item in (relation_keys or []) if str(item).strip()]
        if case_id <= 0 or not normalized_keys:
            return []
        query = """
        SELECT id, case_id, relation_key, from_entity_id, to_entity_id, relation_type, relation_label
        FROM public.kg_relation
        WHERE case_id = %(case_id)s
          AND COALESCE(status, 'active') = 'active'
          AND relation_key = ANY(%(relation_keys)s::text[])
        ORDER BY id DESC
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"case_id": case_id, "relation_keys": normalized_keys})
            return [dict(row) for row in cur.fetchall()]

    def fetch_source_chunks_by_ids(self, *, case_id: int, chunk_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch persisted chunk details needed to rebuild evidence links during replay."""
        normalized_ids = [str(item).strip() for item in chunk_ids if str(item).strip()]
        if case_id <= 0 or not normalized_ids:
            return []
        query = """
        SELECT
            sc.chunk_id,
            sc.file_id,
            sc.page_id,
            sc.page_no,
            sc.chunk_text,
            sc.anchor_text,
            sc.bbox_list,
            sp.page_image_ref
        FROM public.source_chunk sc
        LEFT JOIN public.source_page sp ON sp.id = sc.page_id
        WHERE sc.case_id = %(case_id)s
          AND sc.chunk_id = ANY(%(chunk_ids)s::text[])
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"case_id": case_id, "chunk_ids": normalized_ids})
            return [dict(row) for row in cur.fetchall()]

    def mark_unresolved_items_resolved(self, rows: list[dict[str, Any]]) -> int:
        """Mark unresolved rows as resolved and backfill the graph IDs they eventually mapped to."""
        normalized_rows = [dict(row) for row in rows if int(row.get("id", 0) or 0) > 0]
        if not normalized_rows:
            return 0
        query = """
        UPDATE public.kg_unresolved_item
        SET status = 'resolved',
            resolved_entity_id = %(resolved_entity_id)s,
            resolved_relation_id = %(resolved_relation_id)s,
            resolved_claim_id = %(resolved_claim_id)s,
            resolved_at = NOW(),
            updated_at = NOW()
        WHERE id = %(id)s
        """
        try:
            with self.connect() as conn, conn.cursor() as cur:
                for row in normalized_rows:
                    cur.execute(
                        query,
                        {
                            "id": int(row.get("id", 0) or 0),
                            "resolved_entity_id": _normalize_optional_fk(row.get("resolved_entity_id")),
                            "resolved_relation_id": _normalize_optional_fk(row.get("resolved_relation_id")),
                            "resolved_claim_id": _normalize_optional_fk(row.get("resolved_claim_id")),
                        },
                    )
                conn.commit()
        except UndefinedTable:
            LOGGER.warning("mark_unresolved_items_resolved_skipped_missing_table row_count=%s", len(normalized_rows))
            return 0
        return len(normalized_rows)

    def fetch_subgraph_by_entity(
        self,
        *,
        case_id: int,
        center_entity_id: int,
        depth: int = 2,
        relation_types: list[str] | None = None,
    ) -> dict[str, list[GraphNodeModel | GraphEdgeModel]]:
        """Fetch a depth-bounded subgraph via BFS, centered on one entity, for frontend rendering."""
        relation_types = relation_types or []
        depth = max(1, min(int(depth or 1), 2))  # clamp 1..2: 二跳以上易指数膨胀，前端可视化也不需要
        edge_query = """
        SELECT
            r.id AS relation_id,
            r.relation_type,
            r.relation_label,
            r.confidence,
            r.from_entity_id,
            r.to_entity_id,
            fe.canonical_name AS from_name,
            fe.entity_type AS from_type,
            te.canonical_name AS to_name,
            te.entity_type AS to_type
        FROM public.kg_relation r
        JOIN public.kg_entity fe ON fe.id = r.from_entity_id
        JOIN public.kg_entity te ON te.id = r.to_entity_id
        WHERE r.case_id = %(case_id)s
          AND (
                r.from_entity_id = ANY(%(frontier)s::bigint[])
                OR r.to_entity_id = ANY(%(frontier)s::bigint[])
          )
          AND (
                %(relation_types)s = '{}'::text[]
                OR r.relation_type = ANY(%(relation_types)s)
          )
        LIMIT %(limit)s
        """
        per_level_limit = 200 if depth > 1 else 100
        nodes: dict[int, GraphNodeModel] = {}
        edges_by_id: dict[int, GraphEdgeModel] = {}
        visited_entities: set[int] = {int(center_entity_id)}
        frontier: list[int] = [int(center_entity_id)]
        with self.connect() as conn, conn.cursor() as cur:
            for _ in range(depth):
                if not frontier:
                    break
                cur.execute(
                    edge_query,
                    {
                        "case_id": case_id,
                        "frontier": frontier,
                        "relation_types": relation_types,
                        "limit": per_level_limit,
                    },
                )
                rows = cur.fetchall()
                next_frontier: list[int] = []
                for row in rows:
                    from_id = int(row["from_entity_id"])
                    to_id = int(row["to_entity_id"])
                    nodes[from_id] = GraphNodeModel(
                        id=f"entity_{from_id}",
                        entity_id=from_id,
                        label=row["from_name"],
                        entity_type=row["from_type"],
                    )
                    nodes[to_id] = GraphNodeModel(
                        id=f"entity_{to_id}",
                        entity_id=to_id,
                        label=row["to_name"],
                        entity_type=row["to_type"],
                    )
                    relation_id = int(row["relation_id"])
                    if relation_id not in edges_by_id:
                        edges_by_id[relation_id] = GraphEdgeModel(
                            id=f"relation_{relation_id}",
                            relation_id=relation_id,
                            source=f"entity_{from_id}",
                            target=f"entity_{to_id}",
                            label=row["relation_label"] or row["relation_type"],
                            relation_type=row["relation_type"],
                            confidence=float(row["confidence"] or 0),
                        )
                    for nid in (from_id, to_id):
                        if nid not in visited_entities:
                            visited_entities.add(nid)
                            next_frontier.append(nid)
                frontier = next_frontier
        return {"nodes": list(nodes.values()), "edges": list(edges_by_id.values())}

    def list_entities_by_case(self, case_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        """List a case's entities with relation degree, for the frontend graph entity picker."""
        query = """
        SELECT
            e.id AS entity_id,
            e.canonical_name AS label,
            e.entity_type,
            COALESCE(d.degree, 0) AS degree
        FROM public.kg_entity e
        LEFT JOIN (
            SELECT eid, count(*) AS degree FROM (
                SELECT from_entity_id AS eid FROM public.kg_relation WHERE case_id = %(case_id)s
                UNION ALL
                SELECT to_entity_id AS eid FROM public.kg_relation WHERE case_id = %(case_id)s
            ) t GROUP BY eid
        ) d ON d.eid = e.id
        WHERE e.case_id = %(case_id)s
          AND COALESCE(e.status, 'active') = 'active'
        ORDER BY degree DESC, e.id
        LIMIT %(limit)s
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"case_id": case_id, "limit": max(int(limit or 0), 1)})
            return [
                {
                    "entity_id": int(row["entity_id"]),
                    "label": str(row.get("label") or ""),
                    "entity_type": str(row.get("entity_type") or ""),
                    "degree": int(row.get("degree") or 0),
                }
                for row in cur.fetchall()
            ]

    def fetch_relation_evidence(self, relation_id: int, *, case_id: int | None = None) -> list[dict[str, Any]]:
        """Fetch claims and evidence items for one relation."""
        query = """
        SELECT
            c.id AS claim_id,
            c.claim_type,
            c.claim_text,
            c.confidence,
            e.chunk_id,
            e.file_id,
            sf.file_name,
            e.page_no,
            e.quote_text,
            e.bbox_list,
            sc.page_id AS source_page_id,
            sp.page_image_ref,
            sf.storage_ref,
            sf.content_type,
            c.entity_id,
            cm.citation_id
        FROM public.kg_claim c
        LEFT JOIN public.kg_evidence_link e ON e.claim_id = c.id
        LEFT JOIN public.source_file sf ON sf.id = e.file_id
        LEFT JOIN public.source_chunk sc ON sc.chunk_id = e.chunk_id
        LEFT JOIN public.source_page sp ON sp.id = sc.page_id
        LEFT JOIN LATERAL (
            SELECT m.citation_id
            FROM public.report_citation_map m
            WHERE m.case_id = c.case_id AND m.claim_id = c.id
            ORDER BY m.id DESC
            LIMIT 1
        ) cm ON TRUE
        WHERE c.relation_id = %(relation_id)s
          AND (%(case_id)s::bigint IS NULL OR c.case_id = %(case_id)s)
        ORDER BY c.id, e.id
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"relation_id": relation_id, "case_id": case_id})
            return [dict(row) for row in cur.fetchall()]

    def replace_report_citations(
        self,
        *,
        case_id: int,
        report_ref: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Replace citation mappings for one concrete report version."""
        if case_id <= 0 or not report_ref.strip():
            return []

        delete_query = """
        DELETE FROM public.report_citation_map
        WHERE case_id = %(case_id)s
          AND report_ref = %(report_ref)s
        """
        insert_query = """
        INSERT INTO public.report_citation_map (
            case_id, report_ref, citation_id, claim_id, report_section, ordinal, paragraph_index
        ) VALUES (
            %(case_id)s, %(report_ref)s, %(citation_id)s, %(claim_id)s, %(report_section)s, %(ordinal)s, %(paragraph_index)s
        )
        RETURNING id, citation_id, claim_id, report_section, ordinal, paragraph_index
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(delete_query, {"case_id": case_id, "report_ref": report_ref})
            returned: list[dict[str, Any]] = []
            for row in rows:
                payload = {
                    "case_id": case_id,
                    "report_ref": report_ref,
                    "citation_id": str(row.get("citation_id", "") or ""),
                    "claim_id": int(row.get("claim_id", 0) or 0),
                    "report_section": str(row.get("report_section", "") or ""),
                    "ordinal": int(row.get("ordinal", 0) or 0),
                    "paragraph_index": int(row.get("paragraph_index", 0) or 0),
                }
                if payload["claim_id"] <= 0 or not payload["citation_id"]:
                    continue
                cur.execute(insert_query, payload)
                returned.append(dict(cur.fetchone()))
            conn.commit()
            return returned

    def resolve_claim_by_citation(
        self,
        *,
        case_id: int,
        report_ref: str,
        citation_id: str,
    ) -> dict[str, Any]:
        """Resolve one report citation into its claim row."""
        query = """
        SELECT
            m.claim_id,
            c.claim_text
        FROM public.report_citation_map m
        JOIN public.kg_claim c ON c.id = m.claim_id
        WHERE m.case_id = %(case_id)s
          AND m.report_ref = %(report_ref)s
          AND m.citation_id = %(citation_id)s
        ORDER BY m.id DESC
        LIMIT 1
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                query,
                {
                    "case_id": case_id,
                    "report_ref": report_ref,
                    "citation_id": citation_id,
                },
            )
            row = cur.fetchone()
        return dict(row) if row else {}

    def fetch_claim_text(self, claim_id: int, *, case_id: int | None = None) -> str:
        """Return one claim's text by id.

        The ``citation_id`` resolve path gets ``claim_text`` from
        ``report_citation_map`` join, but the direct ``claim_id`` path (the
        recommended "most stable" graph entry, see issue #9) skipped it. This
        lets the API backfill the drawer title for both paths consistently.
        """
        if claim_id <= 0:
            return ""
        query = """
        SELECT claim_text FROM public.kg_claim
        WHERE id = %(claim_id)s
          AND (%(case_id)s::bigint IS NULL OR case_id = %(case_id)s)
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"claim_id": claim_id, "case_id": case_id})
            row = cur.fetchone()
        return str(row.get("claim_text") or "") if row else ""

    def report_ref_exists(self, *, case_id: int, report_ref: str) -> bool:
        """Return True when any citation mapping exists for this (case_id, report_ref).

        Lets the API tell a wrong/typo'd report_ref (no rows at all) apart from a
        valid report whose specific citation simply has no mapping — so callers can
        report ``ref_not_found`` vs ``citation_not_found`` instead of an ambiguous
        empty result.
        """
        if case_id <= 0 or not report_ref.strip():
            return False
        query = """
        SELECT 1 FROM public.report_citation_map
        WHERE case_id = %(case_id)s AND report_ref = %(report_ref)s
        LIMIT 1
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"case_id": case_id, "report_ref": report_ref})
            return cur.fetchone() is not None

    def list_report_citations(
        self,
        *,
        case_id: int,
        report_ref: str,
        citation_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List claim mappings for one concrete report version."""
        normalized_ids = [str(item).strip() for item in (citation_ids or []) if str(item).strip()]
        query = """
        SELECT
            m.citation_id,
            m.claim_id,
            c.claim_text
        FROM public.report_citation_map m
        JOIN public.kg_claim c ON c.id = m.claim_id
        WHERE m.case_id = %(case_id)s
          AND m.report_ref = %(report_ref)s
          AND (%(citation_ids)s::text[] IS NULL OR m.citation_id = ANY(%(citation_ids)s::text[]))
        ORDER BY m.ordinal, m.id
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                query,
                {
                    "case_id": case_id,
                    "report_ref": report_ref,
                    "citation_ids": normalized_ids or None,
                },
            )
            return [dict(row) for row in cur.fetchall()]

    def fetch_claim_evidence(self, claim_id: int, *, case_id: int | None = None) -> list[EvidenceItemModel]:
        """Fetch evidence items for one claim."""
        query = """
        SELECT
            e.chunk_id,
            e.file_id,
            sf.file_name,
            e.page_no,
            e.quote_text,
            e.bbox_list,
            sc.page_id AS source_page_id,
            sp.page_image_ref,
            sf.storage_ref,
            sf.content_type,
            c.entity_id
        FROM public.kg_evidence_link e
        LEFT JOIN public.kg_claim c ON c.id = e.claim_id
        LEFT JOIN public.source_file sf ON sf.id = e.file_id
        LEFT JOIN public.source_chunk sc ON sc.chunk_id = e.chunk_id
        LEFT JOIN public.source_page sp ON sp.id = sc.page_id
        WHERE e.claim_id = %(claim_id)s
          AND (%(case_id)s::bigint IS NULL OR c.case_id = %(case_id)s)
        ORDER BY e.id
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"claim_id": claim_id, "case_id": case_id})
            rows = cur.fetchall()
        return [
            EvidenceItemModel(
                chunk_id=row["chunk_id"],
                file_id=int(row["file_id"]),
                file_name=row.get("file_name") or "",
                page_no=int(row["page_no"]),
                quote_text=row.get("quote_text") or "",
                bbox_list=row.get("bbox_list") or [],
                page_image_ref=resolve_minio_reference_url(row.get("page_image_ref") or ""),
                source_page_id=int(row.get("source_page_id") or 0),
                source_file_url=resolve_minio_reference_url(row.get("storage_ref") or ""),
                content_type=row.get("content_type") or "",
                entity_id=int(row.get("entity_id") or 0),
            )
            for row in rows
        ]

    def fetch_case_evidence_traces(
        self,
        case_id: int,
        *,
        query_text: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch case-bound evidence candidates without expanding the main graph snapshot."""
        from .case_evidence import evidence_query_terms

        patterns = [f"%{term}%" for term in evidence_query_terms(query_text)] or None
        query = """
        SELECT
            c.id AS claim_id,
            c.claim_type,
            c.claim_text,
            c.confidence,
            e.chunk_id,
            e.file_id,
            sf.file_name,
            e.page_no,
            e.quote_text,
            e.bbox_list,
            sc.page_id AS source_page_id,
            sp.page_image_ref,
            sf.storage_ref,
            sf.content_type
        FROM public.kg_claim c
        JOIN public.kg_evidence_link e ON e.claim_id = c.id
        LEFT JOIN public.source_file sf ON sf.id = e.file_id
        LEFT JOIN public.source_chunk sc ON sc.chunk_id = e.chunk_id
        LEFT JOIN public.source_page sp ON sp.id = sc.page_id
        WHERE c.case_id = %(case_id)s
          AND COALESCE(c.status, 'active') = 'active'
          AND (
                %(patterns)s::text[] IS NULL
                OR c.claim_text ILIKE ANY(%(patterns)s::text[])
                OR e.quote_text ILIKE ANY(%(patterns)s::text[])
                OR sf.file_name ILIKE ANY(%(patterns)s::text[])
          )
        ORDER BY c.confidence DESC, c.id DESC, e.id
        LIMIT %(query_limit)s
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                query,
                {
                    "case_id": case_id,
                    "patterns": patterns,
                    "query_limit": max(limit * 10, 50),
                },
            )
            rows = [dict(row) for row in cur.fetchall()]

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            claim_id = int(row.get("claim_id", 0) or 0)
            trace = grouped.setdefault(
                claim_id,
                {
                    "citation_id": "",
                    "claim_id": claim_id,
                    "claim_type": str(row.get("claim_type", "") or ""),
                    "claim_text": str(row.get("claim_text", "") or ""),
                    "confidence": float(row.get("confidence", 0) or 0),
                    "evidences": [],
                },
            )
            trace["evidences"].append(
                {
                    "chunk_id": str(row.get("chunk_id", "") or ""),
                    "file_id": int(row.get("file_id", 0) or 0),
                    "file_name": str(row.get("file_name", "") or ""),
                    "page_no": int(row.get("page_no", 0) or 0),
                    "quote_text": str(row.get("quote_text", "") or ""),
                    "bbox_list": row.get("bbox_list") or [],
                    "page_image_ref": resolve_minio_reference_url(str(row.get("page_image_ref", "") or "")),
                    "source_page_id": int(row.get("source_page_id", 0) or 0),
                    "source_file_url": resolve_minio_reference_url(str(row.get("storage_ref", "") or "")),
                    "content_type": str(row.get("content_type", "") or ""),
                }
            )
        return list(grouped.values())

    def fetch_page_anchors(self, *, file_id: int, page_no: int, chunk_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch page anchors for PDF/image highlighter rendering."""
        query = """
        SELECT
            sc.chunk_id,
            sc.anchor_text AS quote_text,
            sc.bbox_list,
            sc.page_id AS source_page_id,
            sp.page_image_ref,
            sp.page_width,
            sp.page_height,
            sf.storage_ref,
            sf.file_name,
            sf.content_type
        FROM public.source_chunk sc
        JOIN public.source_page sp ON sp.id = sc.page_id
        LEFT JOIN public.source_file sf ON sf.id = sc.file_id
        WHERE sc.file_id = %(file_id)s
          AND sc.page_no = %(page_no)s
          AND (%(chunk_id)s::text IS NULL OR sc.chunk_id = %(chunk_id)s::text)
        ORDER BY sc.chunk_index
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(query, {"file_id": file_id, "page_no": page_no, "chunk_id": chunk_id})
            return [dict(row) for row in cur.fetchall()]

    def get_source_file_case_id(self, file_id: int) -> int | None:
        """Resolve a source file to its owning case before serving file-scoped data."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT case_id FROM public.source_file WHERE id = %s", (file_id,))
            row = cur.fetchone()
        return int(row["case_id"]) if row and row.get("case_id") is not None else None

    def fetch_candidate_conflicts_by_chunks(
        self,
        *,
        case_id: int,
        chunk_ids: list[str],
        entity_keys: list[str] | None = None,
        relation_keys: list[str] | None = None,
        claim_texts: list[str] | None = None,
        exclude_claim_ids: list[int] | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Shrink historical claims down to a small candidate set for incremental reconciliation."""
        normalized_chunk_ids = [str(chunk_id).strip() for chunk_id in chunk_ids if str(chunk_id).strip()]
        normalized_entity_keys = [str(key).strip() for key in (entity_keys or []) if str(key).strip()]
        normalized_relation_keys = [str(key).strip() for key in (relation_keys or []) if str(key).strip()]
        normalized_claim_texts = [str(text).strip() for text in (claim_texts or []) if str(text).strip()]
        normalized_exclude_claim_ids = [int(claim_id) for claim_id in (exclude_claim_ids or []) if int(claim_id) > 0]
        if case_id <= 0 or not normalized_chunk_ids:
            return {
                "chunk_ids": normalized_chunk_ids,
                "entity_keys": normalized_entity_keys,
                "relation_keys": normalized_relation_keys,
                "claim_texts": normalized_claim_texts,
                "exclude_claim_ids": normalized_exclude_claim_ids,
                "candidates": [],
            }

        chunk_signal_query = """
        SELECT chunk_id, chunk_text, anchor_text
        FROM public.source_chunk
        WHERE case_id = %(case_id)s
          AND chunk_id = ANY(%(chunk_ids)s::text[])
        ORDER BY page_no, chunk_index
        """
        with self.connect() as conn, conn.cursor() as cur:
            claim_columns = self._get_kg_claim_columns(cur)
            cur.execute(chunk_signal_query, {"case_id": case_id, "chunk_ids": normalized_chunk_ids})
            chunk_rows = [dict(row) for row in cur.fetchall()]

            chunk_text_signals = _build_chunk_text_signals(chunk_rows)
            effective_claim_texts = _dedupe_text_list([*normalized_claim_texts, *chunk_text_signals])
            search_patterns = _build_claim_search_patterns(effective_claim_texts)
            if not normalized_entity_keys and not normalized_relation_keys and not search_patterns:
                return {
                    "chunk_ids": normalized_chunk_ids,
                    "entity_keys": normalized_entity_keys,
                    "relation_keys": normalized_relation_keys,
                    "claim_texts": effective_claim_texts,
                    "exclude_claim_ids": normalized_exclude_claim_ids,
                    "candidates": [],
                }

            claim_active_filter = (
                "COALESCE(c.status, 'active') = 'active'"
                if "status" in claim_columns
                else "COALESCE(c.review_status, 'pending') <> 'rejected'"
            )
            candidate_query = """
            SELECT
                c.id AS claim_id,
                c.claim_type,
                c.claim_text,
                c.confidence,
                c.review_status,
                c.entity_id,
                c.relation_id,
                fe.entity_key,
                fe.canonical_name,
                r.relation_key,
                r.relation_type,
                r.relation_label,
                COUNT(DISTINCT el.id) AS evidence_count
            FROM public.kg_claim c
            LEFT JOIN public.kg_entity fe ON fe.id = c.entity_id
            LEFT JOIN public.kg_relation r ON r.id = c.relation_id
            LEFT JOIN public.kg_evidence_link el ON el.claim_id = c.id
            WHERE c.case_id = %(case_id)s
              AND (
                    %(exclude_claim_ids)s::bigint[] IS NULL
                    OR c.id <> ALL(%(exclude_claim_ids)s::bigint[])
              )
              AND (
                    (%(entity_keys)s::text[] IS NOT NULL AND fe.entity_key = ANY(%(entity_keys)s::text[]))
                    OR (%(relation_keys)s::text[] IS NOT NULL AND r.relation_key = ANY(%(relation_keys)s::text[]))
                    OR (
                        %(search_patterns)s::text[] IS NOT NULL
                        AND EXISTS (
                            SELECT 1
                            FROM unnest(%(search_patterns)s::text[]) AS pattern
                            WHERE c.claim_text ILIKE pattern
                        )
                    )
              )
              AND COALESCE(fe.status, 'active') = 'active'
              AND COALESCE(r.status, 'active') = 'active'
              AND __CLAIM_ACTIVE_FILTER__
            GROUP BY
                c.id, c.claim_type, c.claim_text, c.confidence, c.review_status,
                c.entity_id, c.relation_id,
                fe.entity_key, fe.canonical_name,
                r.relation_key, r.relation_type, r.relation_label
            ORDER BY c.confidence DESC, c.id DESC
            LIMIT %(query_limit)s
            """
            candidate_query = candidate_query.replace("__CLAIM_ACTIVE_FILTER__", claim_active_filter)
            cur.execute(
                candidate_query,
                {
                    "case_id": case_id,
                    "entity_keys": normalized_entity_keys or None,
                    "relation_keys": normalized_relation_keys or None,
                    "search_patterns": search_patterns or None,
                    "exclude_claim_ids": normalized_exclude_claim_ids or None,
                    "query_limit": max(limit * 5, limit),
                },
            )
            candidate_rows = [dict(row) for row in cur.fetchall()]

        scored_candidates: list[dict[str, Any]] = []
        for row in candidate_rows:
            matched_by: list[str] = []
            entity_key = str(row.get("entity_key", "") or "")
            relation_key = str(row.get("relation_key", "") or "")
            if entity_key and entity_key in normalized_entity_keys:
                matched_by.append("entity_key")
            if relation_key and relation_key in normalized_relation_keys:
                matched_by.append("relation_key")
            text_score = _score_claim_text_similarity(
                claim_text=str(row.get("claim_text", "") or ""),
                search_texts=effective_claim_texts,
            )
            if text_score > 0:
                matched_by.append("claim_text")
            score = 0.0
            if "entity_key" in matched_by:
                score += 0.45
            if "relation_key" in matched_by:
                score += 0.45
            score += min(text_score, 1.0) * 0.30
            score += min(float(row.get("confidence", 0) or 0), 1.0) * 0.05
            candidate = dict(row)
            candidate["matched_by"] = matched_by
            candidate["match_score"] = round(score, 4)
            scored_candidates.append(candidate)

        scored_candidates.sort(
            key=lambda item: (
                float(item.get("match_score", 0) or 0),
                float(item.get("confidence", 0) or 0),
                int(item.get("evidence_count", 0) or 0),
                int(item.get("claim_id", 0) or 0),
            ),
            reverse=True,
        )
        return {
            "chunk_ids": normalized_chunk_ids,
            "entity_keys": normalized_entity_keys,
            "relation_keys": normalized_relation_keys,
            "claim_texts": effective_claim_texts,
            "exclude_claim_ids": normalized_exclude_claim_ids,
            "candidates": scored_candidates[: max(limit, 1)],
        }

    def fetch_case_graph_snapshot(self, case_id: int) -> dict[str, Any]:
        """Fetch a lightweight persisted graph snapshot for case-level full-audit hydration."""
        if case_id <= 0:
            return {}
        with self.connect() as conn, conn.cursor() as cur:
            claim_columns = self._get_kg_claim_columns(cur)
            claim_active_filter_plain = (
                "COALESCE(status, 'active') = 'active'"
                if "status" in claim_columns
                else "COALESCE(review_status, 'pending') <> 'rejected'"
            )
            claim_active_filter_alias = (
                "COALESCE(c.status, 'active') = 'active'"
                if "status" in claim_columns
                else "COALESCE(c.review_status, 'pending') <> 'rejected'"
            )

            counts_query = """
        SELECT
            (SELECT COUNT(*) FROM public.kg_entity e WHERE e.case_id = %(case_id)s AND COALESCE(e.status, 'active') = 'active') AS entity_count,
            (SELECT COUNT(*) FROM public.kg_relation r WHERE r.case_id = %(case_id)s AND COALESCE(r.status, 'active') = 'active') AS relation_count,
            (SELECT COUNT(*) FROM public.kg_claim c WHERE c.case_id = %(case_id)s AND __CLAIM_ACTIVE_FILTER__) AS claim_count,
            (
                SELECT COUNT(*)
                FROM public.kg_evidence_link e
                JOIN public.kg_claim c ON c.id = e.claim_id
                WHERE c.case_id = %(case_id)s
                  AND __CLAIM_ACTIVE_FILTER__
            ) AS evidence_count
        """
            counts_query = counts_query.replace("__CLAIM_ACTIVE_FILTER__", claim_active_filter_alias)
            entities_query = """
        SELECT id, canonical_name, entity_type
        FROM public.kg_entity
        WHERE case_id = %(case_id)s
          AND COALESCE(status, 'active') = 'active'
        ORDER BY id DESC
        LIMIT 50
        """
            relations_query = """
        SELECT
            r.id,
            r.relation_type,
            r.relation_label,
            r.confidence,
            r.from_entity_id,
            r.to_entity_id,
            fe.canonical_name AS from_name,
            te.canonical_name AS to_name
        FROM public.kg_relation r
        JOIN public.kg_entity fe ON fe.id = r.from_entity_id
        JOIN public.kg_entity te ON te.id = r.to_entity_id
        WHERE r.case_id = %(case_id)s
          AND COALESCE(r.status, 'active') = 'active'
          AND COALESCE(fe.status, 'active') = 'active'
          AND COALESCE(te.status, 'active') = 'active'
        ORDER BY r.id DESC
        LIMIT 80
        """
            claims_query = """
        SELECT id, entity_id, relation_id, claim_type, claim_text, confidence
        FROM public.kg_claim
        WHERE case_id = %(case_id)s
          AND __CLAIM_ACTIVE_FILTER__
        ORDER BY id DESC
        LIMIT 80
        """
            claims_query = claims_query.replace("__CLAIM_ACTIVE_FILTER__", claim_active_filter_plain)
            claim_trace_query = """
        SELECT
            c.id AS claim_id,
            c.claim_type,
            c.claim_text,
            c.confidence,
            e.chunk_id,
            e.file_id,
            sf.file_name,
            e.page_no,
            e.quote_text,
            e.bbox_list,
            sc.page_id AS source_page_id,
            sp.page_image_ref
        FROM public.kg_claim c
        LEFT JOIN public.kg_evidence_link e ON e.claim_id = c.id
        LEFT JOIN public.source_file sf ON sf.id = e.file_id
        LEFT JOIN public.source_chunk sc ON sc.chunk_id = e.chunk_id
        LEFT JOIN public.source_page sp ON sp.id = sc.page_id
        WHERE c.case_id = %(case_id)s
          AND __CLAIM_ACTIVE_FILTER__
        ORDER BY c.confidence DESC, c.id DESC, e.id
        LIMIT 120
        """
            claim_trace_query = claim_trace_query.replace("__CLAIM_ACTIVE_FILTER__", claim_active_filter_alias)
            cur.execute(counts_query, {"case_id": case_id})
            counts_row = dict(cur.fetchone() or {})
            cur.execute(entities_query, {"case_id": case_id})
            entity_rows = [dict(row) for row in cur.fetchall()]
            cur.execute(relations_query, {"case_id": case_id})
            relation_rows = [dict(row) for row in cur.fetchall()]
            cur.execute(claims_query, {"case_id": case_id})
            claim_rows = [dict(row) for row in cur.fetchall()]
            cur.execute(claim_trace_query, {"case_id": case_id})
            trace_rows = [dict(row) for row in cur.fetchall()]

        if not any(int(counts_row.get(key, 0) or 0) for key in ("entity_count", "relation_count", "claim_count")):
            return {}

        grouped_traces: dict[int, dict[str, Any]] = {}
        for row in trace_rows:
            claim_id = int(row.get("claim_id", 0) or 0)
            if claim_id <= 0:
                continue
            trace = grouped_traces.setdefault(
                claim_id,
                {
                    "claim_id": claim_id,
                    "claim_type": str(row.get("claim_type", "") or ""),
                    "claim_text": str(row.get("claim_text", "") or ""),
                    "confidence": float(row.get("confidence", 0) or 0),
                    "evidences": [],
                },
            )
            chunk_id = str(row.get("chunk_id", "") or "")
            if not chunk_id:
                continue
            trace["evidences"].append(
                {
                    "chunk_id": chunk_id,
                    "file_id": int(row.get("file_id", 0) or 0),
                    "file_name": str(row.get("file_name", "") or ""),
                    "page_no": int(row.get("page_no", 0) or 0),
                    "quote_text": str(row.get("quote_text", "") or ""),
                    "bbox_list": row.get("bbox_list") or [],
                    "page_image_ref": resolve_minio_reference_url(str(row.get("page_image_ref", "") or "")),
                    "source_page_id": int(row.get("source_page_id", 0) or 0),
                }
            )
        reconciliation_rows = self.fetch_reconciliation_ledger(case_id=case_id, limit=10)
        unresolved_payload = self.fetch_unresolved_graph_items(case_id=case_id, limit=20)

        return {
            "entities": entity_rows,
            "relations": relation_rows,
            "claims": claim_rows,
            "claim_traces": list(grouped_traces.values())[:5],
            "reconciliation_items": reconciliation_rows,
            "unresolved_relations": unresolved_payload.get("unresolved_relations", []),
            "unresolved_claims": unresolved_payload.get("unresolved_claims", []),
            "evidence_count": int(counts_row.get("evidence_count", 0) or 0),
            "entity_count": int(counts_row.get("entity_count", 0) or 0),
            "relation_count": int(counts_row.get("relation_count", 0) or 0),
            "claim_count": int(counts_row.get("claim_count", 0) or 0),
        }


def _build_upload_batch_persistence_checks(
    batch: dict[str, Any],
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_file_count = int(batch.get("file_count", 0) or 0)
    linked_file_count = len(files)
    files_with_pages = sum(1 for file in files if int(file.get("page_count", 0) or 0) > 0)
    files_with_chunks = sum(1 for file in files if int(file.get("chunk_count", 0) or 0) > 0)
    files_with_doc_category = sum(1 for file in files if file.get("doc_categories") or [])
    return {
        "source_upload_batch_exists": bool(batch.get("upload_batch_id")),
        "source_file_upload_batch_count": linked_file_count,
        "source_file_count_matches": expected_file_count == linked_file_count,
        "source_page_file_count": files_with_pages,
        "source_chunk_file_count": files_with_chunks,
        "source_file_doc_category_count": files_with_doc_category,
        "all_files_have_chunks": linked_file_count > 0 and files_with_chunks == linked_file_count,
        "all_files_have_doc_category": linked_file_count > 0 and files_with_doc_category == linked_file_count,
    }


@lru_cache(maxsize=1)
def get_kg_service() -> KnowledgeGraphService:
    """Return a cached knowledge graph service instance."""
    settings = get_settings()
    LOGGER.info("kg_service_initialized")
    return KnowledgeGraphService(settings.postgres_checkpointer_dsn)


def _build_chunk_text_signals(rows: list[dict[str, Any]]) -> list[str]:
    signals: list[str] = []
    for row in rows:
        for key in ("anchor_text", "chunk_text"):
            text = str(row.get(key, "") or "").strip()
            normalized = _normalize_match_text(text)
            if len(normalized) >= 6:
                signals.append(text[:120])
    return _dedupe_text_list(signals)


def _build_claim_search_patterns(texts: list[str]) -> list[str]:
    patterns: list[str] = []
    for text in texts:
        normalized = _normalize_match_text(text)
        if len(normalized) < 6:
            continue
        patterns.append(f"%{normalized[:80]}%")
    return _dedupe_text_list(patterns)


def _score_claim_text_similarity(*, claim_text: str, search_texts: list[str]) -> float:
    normalized_claim = _normalize_match_text(claim_text)
    if not normalized_claim:
        return 0.0
    claim_ngrams = _char_ngrams(normalized_claim, size=3)
    best = 0.0
    for text in search_texts:
        normalized_text = _normalize_match_text(text)
        if not normalized_text:
            continue
        if normalized_text in normalized_claim or normalized_claim in normalized_text:
            best = max(best, 1.0)
            continue
        text_ngrams = _char_ngrams(normalized_text, size=3)
        if not claim_ngrams or not text_ngrams:
            continue
        overlap = len(claim_ngrams & text_ngrams)
        union = len(claim_ngrams | text_ngrams)
        if union > 0:
            best = max(best, overlap / union)
    return best


def _normalize_match_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text or "")
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", cleaned)
    return cleaned.strip().lower()


def _char_ngrams(text: str, *, size: int) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def _dedupe_text_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_optional_fk(value: Any) -> int | None:
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None
