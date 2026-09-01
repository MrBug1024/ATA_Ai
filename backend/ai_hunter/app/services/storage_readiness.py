"""Read-only readiness checks for the required external storage services."""

from __future__ import annotations

from typing import Any

from redis import Redis

from ai_hunter.annual_audit.storage import postgres_connection
from ai_hunter.annual_audit.storage.migrate import MIGRATIONS

from ..settings import Settings, get_settings
from .minio_service import get_minio_service


class StorageReadinessError(RuntimeError):
    """Raised when an external storage dependency is not ready for requests."""


def _verify_postgres(settings: Settings) -> list[str]:
    expected_migrations = {version for version, _path, _description in MIGRATIONS}
    try:
        with postgres_connection(settings) as connection:
            connection.execute("SELECT 1")
            relation = connection.execute(
                """
                SELECT to_regclass('public.annual_audit_schema_migration')
                    AS migration_table
                """
            ).fetchone() or {}
            if not relation.get("migration_table"):
                raise StorageReadinessError(
                    "PostgreSQL is not migrated; run ai_hunter.annual_audit.storage.migrate"
                )
            rows = connection.execute(
                "SELECT version FROM public.annual_audit_schema_migration"
            ).fetchall()
    except StorageReadinessError:
        raise
    except Exception as exc:
        raise StorageReadinessError("PostgreSQL readiness check failed") from exc

    applied = {str(row["version"]) for row in rows}
    missing = sorted(expected_migrations - applied)
    if missing:
        raise StorageReadinessError(
            f"PostgreSQL is missing migrations: {', '.join(missing)}"
        )
    return sorted(applied)


def _verify_redis(settings: Settings) -> None:
    client = Redis.from_url(
        settings.redis_dsn,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    try:
        if not client.ping():
            raise StorageReadinessError("Redis readiness ping returned false")
    except StorageReadinessError:
        raise
    except Exception as exc:
        raise StorageReadinessError("Redis readiness check failed") from exc
    finally:
        client.close()


def _verify_minio(settings: Settings) -> list[str]:
    required_buckets = {
        settings.annual_minio_bucket_raw,
        settings.annual_minio_bucket_derived,
        settings.annual_minio_bucket_artifacts,
        settings.annual_minio_bucket_templates,
    }
    try:
        service = get_minio_service()
        missing = sorted(
            bucket for bucket in required_buckets if not service.client.bucket_exists(bucket)
        )
    except Exception as exc:
        raise StorageReadinessError("MinIO readiness check failed") from exc
    if missing:
        raise StorageReadinessError(f"MinIO buckets are unavailable: {', '.join(missing)}")
    return sorted(required_buckets)


def check_storage_readiness(settings: Settings | None = None) -> dict[str, Any]:
    """Verify all external storage dependencies without writing to them."""

    resolved = settings or get_settings()
    resolved.require_runtime_storage()
    migrations = _verify_postgres(resolved)
    _verify_redis(resolved)
    buckets = _verify_minio(resolved)
    return {
        "postgres": "ok",
        "postgres_migrations": migrations,
        "redis": "ok",
        "minio": "ok",
        "minio_buckets": buckets,
    }


__all__ = ["StorageReadinessError", "check_storage_readiness"]
