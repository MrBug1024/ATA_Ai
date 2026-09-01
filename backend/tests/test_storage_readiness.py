from __future__ import annotations

from contextlib import contextmanager

import pytest

from ai_hunter.app.services import storage_readiness
from ai_hunter.annual_audit.storage.migrate import MIGRATIONS


class _Result:
    def __init__(self, *, one=None, many=None) -> None:
        self.one = one
        self.many = list(many or [])

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class _Connection:
    def __init__(self, *, migration_table: str | None = "annual_audit_schema_migration") -> None:
        self.migration_table = migration_table
        self.executed: list[str] = []

    def execute(self, statement, _params=()):
        normalized = " ".join(str(statement).split())
        self.executed.append(normalized)
        if "to_regclass" in normalized:
            return _Result(one={"migration_table": self.migration_table})
        if "SELECT version" in normalized:
            return _Result(many=[{"version": version} for version, _path, _description in MIGRATIONS])
        return _Result(one={"ok": 1})


class _Settings:
    redis_dsn = "redis://:root@redis.internal:6379/0"
    annual_minio_bucket_raw = "raw"
    annual_minio_bucket_derived = "derived"
    annual_minio_bucket_artifacts = "artifacts"
    annual_minio_bucket_templates = "templates"

    def __init__(self) -> None:
        self.runtime_storage_checked = False

    def require_runtime_storage(self) -> None:
        self.runtime_storage_checked = True


class _RedisClient:
    def __init__(self, *, ping_result: bool = True) -> None:
        self.ping_result = ping_result
        self.closed = False

    def ping(self) -> bool:
        return self.ping_result

    def close(self) -> None:
        self.closed = True


class _Redis:
    client = _RedisClient()

    @classmethod
    def from_url(cls, _dsn, **_kwargs):
        return cls.client


class _MinioClient:
    def __init__(self, buckets: set[str]) -> None:
        self.buckets = buckets

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets


class _MinioService:
    def __init__(self, buckets: set[str]) -> None:
        self.client = _MinioClient(buckets)


def _install_postgres(monkeypatch, connection: _Connection) -> None:
    @contextmanager
    def connect(_settings):
        yield connection

    monkeypatch.setattr(storage_readiness, "postgres_connection", connect)


def test_readiness_requires_applied_migrations_redis_and_minio(monkeypatch) -> None:
    settings = _Settings()
    _install_postgres(monkeypatch, _Connection())
    monkeypatch.setattr(storage_readiness, "Redis", _Redis)
    monkeypatch.setattr(
        storage_readiness,
        "get_minio_service",
        lambda: _MinioService({"raw", "derived", "artifacts", "templates"}),
    )

    result = storage_readiness.check_storage_readiness(settings)

    assert settings.runtime_storage_checked is True
    assert result["postgres"] == "ok"
    assert result["redis"] == "ok"
    assert result["minio"] == "ok"
    assert result["postgres_migrations"] == [version for version, _path, _description in MIGRATIONS]


def test_readiness_explains_when_postgres_has_not_been_migrated(monkeypatch) -> None:
    _install_postgres(monkeypatch, _Connection(migration_table=None))

    with pytest.raises(storage_readiness.StorageReadinessError, match="not migrated"):
        storage_readiness._verify_postgres(_Settings())


def test_readiness_rejects_missing_minio_bucket(monkeypatch) -> None:
    monkeypatch.setattr(
        storage_readiness,
        "get_minio_service",
        lambda: _MinioService({"raw", "derived", "artifacts"}),
    )

    with pytest.raises(storage_readiness.StorageReadinessError, match="templates"):
        storage_readiness._verify_minio(_Settings())
