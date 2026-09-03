from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ai_hunter.annual_audit.storage import migrate
from ai_hunter.annual_audit.storage.errors import AnnualAuditStorageError
from ai_hunter.annual_audit.storage import postgres


class _Cursor:
    def __init__(self, database_name: str) -> None:
        self.database_name = database_name
        self.statement = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=()):
        self.statement = str(statement)

    def fetchone(self):
        if "current_database" in self.statement:
            return {"database_name": self.database_name}
        return None


class _Result:
    def __init__(self, *, one=None, many=None) -> None:
        self.one = one
        self.many = list(many or [])

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class _Connection:
    def __init__(self, database_name: str) -> None:
        self.cursor_instance = _Cursor(database_name)
        self.executed: list[str] = []

    def cursor(self):
        return self.cursor_instance

    def execute(self, statement, _params=()):
        text = str(statement)
        self.executed.append(text)
        if "SHOW server_version_num" in text:
            return _Result(one={"server_version_num": "160000"})
        if "pg_available_extensions" in text:
            return _Result(
                many=[{"name": "pgcrypto"}, {"name": "vector"}]
            )
        return _Result()


def test_postgres_migrations_follow_the_external_storage_order() -> None:
    names = [path.name for _version, path, _description in migrate.MIGRATIONS]

    assert names == [
        "langgraph_checkpointer.sql",
        "add_soft_delete_to_checkpoints.sql",
        "conversation_messages.sql",
        "heavy_payload_store.sql",
        "auth_tables.sql",
        "auth_v2_private_tables.sql",
        "auth_report_section_permissions.sql",
        "knowledge_graph_v1.sql",
        "source_file_minio_fields.sql",
        "annual_platform_contract.sql",
        "annual_audit_postgres_v1.sql",
        "annual_audit_postgres_v2.sql",
        "document_templates_postgres_v1.sql",
        "document_templates_postgres_v2.sql",
        "annual_audit_postgres_v3.sql",
        "annual_audit_postgres_v4.sql",
        "case_corrections.sql",
        "remove_legacy_auth_seed.sql",
    ]
    assert all(path.is_file() for path in migrate.POSTGRES_MIGRATIONS)


def test_clean_deployment_migration_only_removes_the_unreferenced_legacy_seed() -> None:
    cleanup_sql = (migrate.SQL_DIR / "remove_legacy_auth_seed.sql").read_text(encoding="utf-8")

    assert "DELETE FROM public.app_company" in cleanup_sql
    assert "co_f1824b82e2116701" in cleanup_sql
    assert "information_schema.columns" in cleanup_sql
    assert "column_name = 'company_id'" in cleanup_sql
    assert "EXIT WHEN has_reference" in cleanup_sql


def test_annual_engagement_schema_carries_the_repository_tenancy_contract() -> None:
    sql_dir = migrate.SQL_DIR
    baseline = (sql_dir / "annual_audit_postgres_v3.sql").read_text(encoding="utf-8")
    repair = (sql_dir / "annual_audit_postgres_v4.sql").read_text(encoding="utf-8")

    for column in ("engagement_type", "entity_uscc", "company_id", "owner_user_id"):
        assert column in baseline
        assert column in repair


def test_migration_splitter_keeps_plpgsql_bodies_and_concurrent_indexes_separate() -> None:
    sql_dir = migrate.SQL_DIR
    function_statements = migrate._split_sql_statements(
        (sql_dir / "annual_audit_postgres_v3.sql").read_text(encoding="utf-8")
    )
    index_statements = migrate._split_sql_statements(
        (sql_dir / "knowledge_graph_v1.sql").read_text(encoding="utf-8")
    )

    assert any(
        "NEW.updated_at = now();" in statement
        and statement.rstrip().endswith("$$;")
        for statement in function_statements
    )
    concurrent_indexes = [
        statement for statement in index_statements if "CREATE INDEX CONCURRENTLY" in statement
    ]
    assert concurrent_indexes
    assert all(statement.upper().count("CREATE INDEX CONCURRENTLY") == 1 for statement in concurrent_indexes)


def test_migration_splitter_accepts_a_line_comment_at_eof() -> None:
    assert migrate._split_sql_statements("SELECT 1; -- legal EOF comment") == [
        "SELECT 1;",
        "-- legal EOF comment",
    ]


def test_migration_preflight_rejects_missing_extension_package() -> None:
    class Connection:
        def execute(self, _statement, _params=()):
            return _Result(many=[{"name": "pgcrypto"}])

    with pytest.raises(AnnualAuditStorageError, match="vector"):
        migrate._ensure_required_extensions_available(Connection())


def test_migration_preflight_rejects_unsupported_postgres_version() -> None:
    class Connection:
        def execute(self, _statement, _params=()):
            return _Result(one={"server_version_num": "110000"})

    with pytest.raises(AnnualAuditStorageError, match="PostgreSQL 12"):
        migrate._ensure_supported_postgres_version(Connection())


def test_retry_repairs_an_invalid_concurrent_index_before_recreation() -> None:
    class Connection:
        def __init__(self) -> None:
            self.executed: list[str] = []

        def execute(self, statement, _params=()):
            text = str(statement)
            self.executed.append(text)
            if "FROM pg_index" in text:
                return _Result(one={"indisvalid": False})
            return _Result()

    connection = Connection()
    migrate._repair_invalid_concurrent_index(
        connection,
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS test_index ON public.test_table (id);",
    )

    assert any("DROP INDEX CONCURRENTLY IF EXISTS test_index" in text for text in connection.executed)


def test_apply_migrations_uses_autocommit_and_records_each_success(monkeypatch) -> None:
    connection = _Connection("ata_ai")
    requested_autocommit: list[bool] = []

    @contextmanager
    def connect(_settings, *, autocommit: bool):
        requested_autocommit.append(autocommit)
        yield connection

    monkeypatch.setattr(migrate, "postgres_connection", connect)
    migrate.apply_migrations(SimpleNamespace(postgresql_database="ata_ai"))

    assert requested_autocommit == [True]
    assert any("annual_audit_schema_migration" in statement for statement in connection.executed)
    assert any("pg_advisory_lock" in statement for statement in connection.executed)
    assert any("pg_advisory_unlock" in statement for statement in connection.executed)
    assert sum("INSERT INTO public.annual_audit_schema_migration" in statement for statement in connection.executed) == len(migrate.MIGRATIONS)
    assert any("CREATE INDEX CONCURRENTLY" in statement for statement in connection.executed)


def test_conversation_indexes_are_retry_safe() -> None:
    migration_sql = (migrate.SQL_DIR / "conversation_messages.sql").read_text(encoding="utf-8")

    assert migration_sql.count("CREATE INDEX IF NOT EXISTS") == 2
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_conv_msg_user_unique" in migration_sql


def test_migration_guard_rejects_a_connection_to_another_database() -> None:
    with pytest.raises(AnnualAuditStorageError, match="not using POSTGRESQL_DATABASE"):
        migrate._ensure_current_database(
            _Connection("other_database"),
            SimpleNamespace(postgresql_database="ata_ai"),
        )


def test_postgres_connection_uses_dict_rows_and_commits_on_success(monkeypatch) -> None:
    calls: list[dict] = []

    class Connection:
        def __init__(self) -> None:
            self.commits = 0
            self.closed = 0

        def commit(self):
            self.commits += 1

        def close(self):
            self.closed += 1

    connection = Connection()

    def connect(dsn, **kwargs):
        calls.append({"dsn": dsn, **kwargs})
        return connection

    monkeypatch.setattr(postgres.psycopg, "connect", connect)
    settings = SimpleNamespace(
        business_domain="annual_audit",
        postgres_checkpointer_dsn="postgresql://configured",
    )

    with postgres.postgres_connection(settings) as resolved:
        assert resolved is connection

    assert calls == [{"dsn": "postgresql://configured", "row_factory": postgres.dict_row, "autocommit": False}]
    assert connection.commits == 1
    assert connection.closed == 1
