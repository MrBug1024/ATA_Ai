"""Fail-fast connectivity and isolation verification for the Docker stack."""

from __future__ import annotations

import json

import psycopg
from psycopg.rows import dict_row
from redis import Redis

from ai_hunter.app.settings import get_settings
from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.annual_audit.storage import mysql_connection


REQUIRED_POSTGRES_TABLES = {
    "checkpoints",
    "conversation_messages",
    "heavy_payload_store",
    "thread_metadata",
    "app_user",
    "local_user_credential",
    "source_file",
    "source_chunk",
    "kg_entity",
    "kg_relation",
    "kg_claim",
    "material_event",
}

REQUIRED_MYSQL_TABLES = {
    "audit_engagement",
    "annual_import_batch",
    "annual_account_balance",
    "annual_journal_entry_line",
    "annual_receivable_item",
    "annual_bank_transaction",
    "annual_analysis_run",
    "annual_finding",
    "annual_workpaper",
    "audit_report",
    "annual_task",
}


def main() -> None:
    settings = get_settings()
    if settings.business_domain != "annual_audit":
        raise RuntimeError("BUSINESS_DOMAIN must be annual_audit")

    with psycopg.connect(settings.postgres_checkpointer_dsn, row_factory=dict_row) as conn:
        pg_row = conn.execute(
            """
            SELECT current_database() AS database_name,
                   current_user AS user_name,
                   (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_version,
                   to_regclass('public.cases') AS legacy_cases
            """
        ).fetchone()
        table_rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        pg_tables = {str(row["tablename"]) for row in table_rows}
    missing_pg = sorted(REQUIRED_POSTGRES_TABLES - pg_tables)
    if missing_pg:
        raise RuntimeError(f"missing PostgreSQL tables: {missing_pg}")
    if pg_row["database_name"] != "ata_agent_platform":
        raise RuntimeError(f"unexpected PostgreSQL database: {pg_row['database_name']}")
    if pg_row["legacy_cases"] is not None:
        raise RuntimeError("legacy public.cases must not exist in annual PostgreSQL")

    with mysql_connection(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()"
        )
        mysql_tables = {str(row["TABLE_NAME"] if "TABLE_NAME" in row else row["table_name"]) for row in cursor.fetchall()}
        cursor.execute("SELECT version FROM ata_schema_migration ORDER BY version")
        migrations = [str(row["version"]) for row in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) AS engagement_count FROM audit_engagement")
        engagement_count = int(cursor.fetchone()["engagement_count"])
    missing_mysql = sorted(REQUIRED_MYSQL_TABLES - mysql_tables)
    if missing_mysql:
        raise RuntimeError(f"missing MySQL tables: {missing_mysql}")
    if migrations != ["001", "002", "003", "004", "005", "006"]:
        raise RuntimeError(f"unexpected MySQL migrations: {migrations}")

    if not settings.redis_url:
        redis_status = "disabled"
    else:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        redis_status = "ok" if redis_client.ping() else "failed"
        redis_client.close()
        if redis_status != "ok":
            raise RuntimeError("Redis ping failed")

    if not settings.ai_hunter_minio_enabled:
        raise RuntimeError("annual object storage must be enabled")
    minio_service = get_minio_service()
    required_buckets = {
        settings.ai_hunter_minio_bucket_raw,
        settings.ai_hunter_minio_bucket_derived,
        settings.ai_hunter_minio_bucket_artifacts,
    }
    missing_buckets = sorted(
        bucket for bucket in required_buckets if not minio_service.client.bucket_exists(bucket)
    )
    if missing_buckets:
        raise RuntimeError(f"missing MinIO buckets: {missing_buckets}")

    print(
        json.dumps(
            {
                "business_domain": settings.business_domain,
                "postgres": {
                    "database": pg_row["database_name"],
                    "user": pg_row["user_name"],
                    "vector": pg_row["vector_version"],
                    "table_count": len(pg_tables),
                    "legacy_cases_absent": True,
                },
                "mysql": {
                    "database": settings.annual_mysql_database,
                    "migrations": migrations,
                    "table_count": len(mysql_tables),
                    "engagement_count": engagement_count,
                },
                "redis": redis_status,
                "minio": {
                    "endpoint": settings.ai_hunter_minio_endpoint,
                    "buckets": sorted(required_buckets),
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
