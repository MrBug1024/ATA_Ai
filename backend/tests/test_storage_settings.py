from __future__ import annotations

import pytest

from ai_hunter.app.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_backend": "postgresql",
        "postgresql_host": "postgres.internal",
        "postgresql_port": 5432,
        "postgresql_database": "ata_ai",
        "postgresql_admin_user": "postgres",
        "postgresql_admin_password": "secret",
        "redis_host": "redis.internal",
        "redis_port": 6379,
        "redis_password": "root",
        "redis_namespace": "ata:dev:",
        "annual_minio_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_settings_expose_only_standard_database_and_redis_fields() -> None:
    settings = _settings()

    assert settings.postgres_checkpointer_dsn == "postgresql://postgres:secret@postgres.internal:5432/ata_ai"
    assert settings.redis_dsn == "redis://:root@redis.internal:6379/0"
    assert "database_url" not in Settings.model_fields
    assert "annual_redis_host" not in Settings.model_fields
    assert "ai_hunter_minio_endpoint" not in Settings.model_fields


def test_empty_postgresql_database_fails_only_when_a_connection_is_requested() -> None:
    settings = _settings(postgresql_database="")

    with pytest.raises(RuntimeError, match="POSTGRESQL_DATABASE is required"):
        _ = settings.postgres_checkpointer_dsn


def test_runtime_storage_requires_database_and_online_minio() -> None:
    with pytest.raises(RuntimeError, match="POSTGRESQL_DATABASE is required"):
        _settings(postgresql_database="").require_runtime_storage()

    with pytest.raises(RuntimeError, match="ANNUAL_MINIO_ENABLED must be true"):
        _settings().require_runtime_storage()


def test_non_postgresql_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="DATABASE_BACKEND must be postgresql"):
        _settings(database_backend="sqlite")


def test_non_postgres_checkpoint_or_non_durable_heavy_store_is_rejected() -> None:
    with pytest.raises(ValueError, match="LANGGRAPH_CHECKPOINTER must be postgres"):
        _settings(langgraph_checkpointer="memory")
    with pytest.raises(ValueError, match="HEAVY_PAYLOAD_ENABLE_POSTGRES must be true"):
        _settings(heavy_payload_enable_postgres=False)


def test_enabled_minio_requires_external_endpoint_credentials_and_buckets() -> None:
    with pytest.raises(ValueError, match="ANNUAL_MINIO_ENDPOINT"):
        _settings(annual_minio_enabled=True)
