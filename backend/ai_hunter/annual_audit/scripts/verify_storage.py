"""Fail-fast verification for the external PostgreSQL, Redis, and MinIO contract."""

from __future__ import annotations

import json
import socket
from urllib.parse import urljoin

import httpx
from redis import Redis

from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.app.settings import get_settings
from ai_hunter.annual_audit.storage import postgres_connection
from ai_hunter.annual_audit.storage.migrate import MIGRATIONS


REQUIRED_POSTGRES_TABLES = frozenset(
    {
        "annual_audit_schema_migration",
        "ata_schema_migration",
        "audit_engagement",
        "ata_project_member",
        "audit_report",
        "ata_audit_log",
        "annual_import_batch",
        "annual_account_balance",
        "annual_journal_entry_line",
        "annual_receivable_item",
        "annual_bank_transaction",
        "annual_analysis_run",
        "annual_finding",
        "annual_workpaper",
        "annual_task",
        "annual_engagement_profile",
        "annual_audit_program_item",
        "annual_audit_program_event",
        "annual_confirmation",
        "annual_finding_resolution",
        "annual_review_decision",
        "annual_knowledge_document",
        "annual_knowledge_version",
        "annual_knowledge_chunk",
        "annual_knowledge_release",
        "annual_knowledge_release_item",
        "annual_audit_ruleset",
        "annual_audit_rule",
        "annual_engagement_policy_binding",
        "annual_release_gate",
        "annual_audit_issuance",
        "annual_audit_archive",
        "annual_report_citation_manifest",
        "annual_report_citation_delivery_ref",
        "annual_engagement_fact",
        "annual_attachment_generation_job",
        "annual_attachment_generation_item",
        "annual_generated_artifact",
        "annual_attachment_outbox",
        "annual_artifact_access_event",
        "annual_attachment_storage_object",
        "annual_attachment_storage_reference",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "conversation_messages",
        "heavy_payload_store",
        "thread_metadata",
        "app_user",
        "local_user_credential",
        "source_file",
        "source_page",
        "source_chunk",
        "source_file_doc_category",
        "doc_category_catalog",
        "kg_entity",
        "kg_relation",
        "kg_claim",
        "material_event",
        "document_template_family",
        "document_template_version",
        "document_template_file",
        "document_template_audit_event",
        "document_template_storage_object",
        "document_template_storage_reference",
        "case_correction",
    }
)
REQUIRED_POSTGRES_MIGRATIONS = frozenset(version for version, _path, _description in MIGRATIONS)
REQUIRED_POSTGRES_COLUMNS = {
    "audit_engagement": frozenset(
        {
            "engagement_type",
            "entity_uscc",
            "company_id",
            "owner_user_id",
        }
    ),
}


def _verify_clamav(host: str, port: int, timeout_seconds: int) -> None:
    if not host:
        raise RuntimeError("ATTACHMENT_CLAMAV_HOST is required when ClamAV is mandatory")
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as connection:
            connection.sendall(b"PING\n")
            response = connection.recv(64)
    except OSError as exc:
        raise RuntimeError("ClamAV ping failed; verify the attachment scanner endpoint") from exc
    if b"PONG" not in response:
        raise RuntimeError(f"ClamAV returned an unexpected ping response: {response!r}")


def _verify_gotenberg(base_url: str, timeout_seconds: int) -> None:
    if not base_url:
        raise RuntimeError("ATTACHMENT_GOTENBERG_URL is required when previews are mandatory")
    try:
        response = httpx.get(
            urljoin(base_url.rstrip("/") + "/", "health"),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError("Gotenberg health check failed; verify the preview renderer endpoint") from exc


def _verify_postgres() -> tuple[dict[str, object], set[str], list[str], int]:
    settings = get_settings()
    with postgres_connection(settings) as connection:
        postgres_row = connection.execute(
            """
            SELECT current_database() AS database_name,
                   current_user AS user_name,
                   (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_version
            """
        ).fetchone() or {}
        table_rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        column_rows = connection.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
            """,
            (list(REQUIRED_POSTGRES_COLUMNS),),
        ).fetchall()
        migration_rows = connection.execute(
            "SELECT version FROM public.annual_audit_schema_migration ORDER BY version"
        ).fetchall()
        engagement_row = connection.execute(
            "SELECT COUNT(*) AS engagement_count FROM public.audit_engagement"
        ).fetchone() or {}

    tables = {str(row["tablename"]) for row in table_rows}
    migrations = [str(row["version"]) for row in migration_rows]
    database_name = str(postgres_row.get("database_name") or "")
    if database_name != settings.postgresql_database.strip():
        raise RuntimeError("PostgreSQL connection is not using POSTGRESQL_DATABASE")
    if not postgres_row.get("vector_version"):
        raise RuntimeError("PostgreSQL vector extension is required")
    missing_tables = sorted(REQUIRED_POSTGRES_TABLES - tables)
    if missing_tables:
        raise RuntimeError(f"missing PostgreSQL tables: {missing_tables}")
    columns_by_table: dict[str, set[str]] = {}
    for row in column_rows:
        columns_by_table.setdefault(str(row["table_name"]), set()).add(
            str(row["column_name"])
        )
    missing_columns = {
        table: sorted(required - columns_by_table.get(table, set()))
        for table, required in REQUIRED_POSTGRES_COLUMNS.items()
        if required - columns_by_table.get(table, set())
    }
    if missing_columns:
        raise RuntimeError(f"missing PostgreSQL columns: {missing_columns}")
    missing_migrations = sorted(REQUIRED_POSTGRES_MIGRATIONS - set(migrations))
    if missing_migrations:
        raise RuntimeError(f"missing PostgreSQL migrations: {missing_migrations}")
    return postgres_row, tables, migrations, int(engagement_row.get("engagement_count") or 0)


def _verify_redis() -> str:
    settings = get_settings()
    redis_client = Redis.from_url(
        settings.redis_dsn,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        if not redis_client.ping():
            raise RuntimeError("Redis ping returned false")
    except Exception as exc:
        raise RuntimeError("Redis ping failed; verify REDIS_HOST, REDIS_PORT, and REDIS_PASSWORD") from exc
    finally:
        redis_client.close()
    return "ok"


def _verify_minio() -> list[str]:
    settings = get_settings()
    if not settings.annual_minio_enabled:
        raise RuntimeError("ANNUAL_MINIO_ENABLED must be true for file storage")
    minio_service = get_minio_service()
    required_buckets = {
        settings.annual_minio_bucket_raw,
        settings.annual_minio_bucket_derived,
        settings.annual_minio_bucket_artifacts,
        settings.annual_minio_bucket_templates,
    }
    missing_buckets = sorted(
        bucket for bucket in required_buckets if not minio_service.client.bucket_exists(bucket)
    )
    if missing_buckets:
        raise RuntimeError(f"missing MinIO buckets: {missing_buckets}")
    return sorted(required_buckets)


def main() -> None:
    settings = get_settings()
    if settings.business_domain != "annual_audit":
        raise RuntimeError("BUSINESS_DOMAIN must be annual_audit")

    postgres_row, postgres_tables, migrations, engagement_count = _verify_postgres()
    redis_status = _verify_redis()
    minio_buckets = _verify_minio()

    clamav_status = "disabled"
    if settings.attachment_clamav_required:
        _verify_clamav(
            settings.attachment_clamav_host,
            settings.attachment_clamav_port,
            settings.attachment_clamav_timeout_seconds,
        )
        clamav_status = "ok"

    gotenberg_status = "disabled"
    if settings.attachment_preview_required:
        _verify_gotenberg(
            settings.attachment_gotenberg_url,
            settings.attachment_gotenberg_timeout_seconds,
        )
        gotenberg_status = "ok"

    print(
        json.dumps(
            {
                "business_domain": settings.business_domain,
                "postgres": {
                    "database": postgres_row["database_name"],
                    "user": postgres_row["user_name"],
                    "vector": postgres_row["vector_version"],
                    "migrations": migrations,
                    "table_count": len(postgres_tables),
                    "engagement_count": engagement_count,
                },
                "redis": redis_status,
                "clamav": clamav_status,
                "gotenberg": gotenberg_status,
                "minio": {
                    "endpoint": settings.annual_minio_endpoint,
                    "buckets": minio_buckets,
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
