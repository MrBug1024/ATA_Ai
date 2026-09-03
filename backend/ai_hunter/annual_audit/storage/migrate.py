"""Apply idempotent annual-audit PostgreSQL migrations."""

from __future__ import annotations

from pathlib import Path
import re

from ai_hunter.app.settings import Settings, get_settings

from .errors import AnnualAuditStorageError
from .postgres import postgres_connection


SQL_DIR = Path(__file__).resolve().parents[3] / "sql"

# Keep the shared PostgreSQL initialization order stable across environments.
MIGRATIONS: tuple[tuple[str, Path, str], ...] = (
    ("010", SQL_DIR / "langgraph_checkpointer.sql", "LangGraph checkpoint tables"),
    ("011", SQL_DIR / "add_soft_delete_to_checkpoints.sql", "checkpoint soft delete"),
    ("020", SQL_DIR / "conversation_messages.sql", "conversation messages"),
    ("030", SQL_DIR / "heavy_payload_store.sql", "heavy payload persistence"),
    ("040", SQL_DIR / "auth_tables.sql", "authentication tables"),
    ("041", SQL_DIR / "auth_v2_private_tables.sql", "private authentication tables"),
    ("042", SQL_DIR / "auth_report_section_permissions.sql", "report section permissions"),
    ("050", SQL_DIR / "knowledge_graph_v1.sql", "knowledge graph"),
    ("051", SQL_DIR / "source_file_minio_fields.sql", "MinIO source-file metadata"),
    ("060", SQL_DIR / "annual_platform_contract.sql", "annual platform contract"),
    ("061", SQL_DIR / "annual_audit_postgres_v1.sql", "annual platform compatibility"),
    ("062", SQL_DIR / "annual_audit_postgres_v2.sql", "annual material catalogue"),
    ("063", SQL_DIR / "document_templates_postgres_v1.sql", "document templates"),
    ("064", SQL_DIR / "document_templates_postgres_v2.sql", "template storage ledger"),
    ("065", SQL_DIR / "annual_audit_postgres_v3.sql", "annual audit PostgreSQL baseline"),
    ("066", SQL_DIR / "annual_audit_postgres_v4.sql", "annual engagement tenancy contract"),
    ("070", SQL_DIR / "case_corrections.sql", "case correction ledger"),
    ("071", SQL_DIR / "remove_legacy_auth_seed.sql", "remove unreferenced legacy auth seed"),
)
POSTGRES_MIGRATIONS = tuple(path for _version, path, _description in MIGRATIONS)
REQUIRED_POSTGRES_EXTENSIONS = ("pgcrypto", "vector")
MINIMUM_POSTGRES_VERSION_NUM = 120000
_MIGRATION_LOCK_NAME = "ata_ai:annual_audit_schema_migration"
_DOLLAR_QUOTE_START = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_CONCURRENT_INDEX_PATTERN = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<index_name>[A-Za-z0-9_.\"]+)",
    re.IGNORECASE,
)


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split PostgreSQL SQL without breaking quoted or dollar-quoted bodies.

    Migrations include PL/pgSQL functions and ``CREATE INDEX CONCURRENTLY``.
    Psycopg must receive concurrent-index statements independently while
    autocommit is enabled, so a plain ``str.split(';')`` is unsafe here.
    """

    statements: list[str] = []
    start = 0
    index = 0
    state = "normal"
    dollar_delimiter = ""
    block_comment_depth = 0
    length = len(sql_text)

    while index < length:
        character = sql_text[index]
        if state == "normal":
            if sql_text.startswith("--", index):
                state = "line_comment"
                index += 2
                continue
            if sql_text.startswith("/*", index):
                state = "block_comment"
                block_comment_depth = 1
                index += 2
                continue
            if character == "'":
                state = "single_quote"
                index += 1
                continue
            if character == '"':
                state = "double_quote"
                index += 1
                continue
            if character == "$":
                match = _DOLLAR_QUOTE_START.match(sql_text, index)
                if match:
                    dollar_delimiter = match.group(0)
                    state = "dollar_quote"
                    index += len(dollar_delimiter)
                    continue
            if character == ";":
                statement = sql_text[start : index + 1].strip()
                if statement:
                    statements.append(statement)
                start = index + 1
            index += 1
            continue

        if state == "line_comment":
            if character in "\r\n":
                state = "normal"
            index += 1
            continue

        if state == "block_comment":
            if sql_text.startswith("/*", index):
                block_comment_depth += 1
                index += 2
                continue
            if sql_text.startswith("*/", index):
                block_comment_depth -= 1
                index += 2
                if block_comment_depth == 0:
                    state = "normal"
                continue
            index += 1
            continue

        if state == "single_quote":
            if character == "\\" and index + 1 < length:
                index += 2
                continue
            if character == "'":
                if index + 1 < length and sql_text[index + 1] == "'":
                    index += 2
                    continue
                state = "normal"
            index += 1
            continue

        if state == "double_quote":
            if character == '"':
                if index + 1 < length and sql_text[index + 1] == '"':
                    index += 2
                    continue
                state = "normal"
            index += 1
            continue

        if state == "dollar_quote":
            if sql_text.startswith(dollar_delimiter, index):
                state = "normal"
                index += len(dollar_delimiter)
                continue
            index += 1
            continue

    # PostgreSQL accepts a line comment that reaches EOF without a trailing
    # newline. Other open lexical states are malformed migration SQL.
    if state == "line_comment":
        state = "normal"
    if state != "normal":
        raise AnnualAuditStorageError("unterminated quoted or commented PostgreSQL migration SQL")
    tail = sql_text[start:].strip()
    if tail:
        statements.append(tail)
    return statements


def _validate_migration_files() -> None:
    missing = [str(path) for _version, path, _description in MIGRATIONS if not path.is_file()]
    if missing:
        raise AnnualAuditStorageError(f"annual-audit migration files are missing: {', '.join(missing)}")


def _ensure_current_database(connection, settings: Settings) -> None:
    expected_database = settings.postgresql_database.strip()
    if not expected_database:
        raise AnnualAuditStorageError("POSTGRESQL_DATABASE is required for migrations")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database() AS database_name")
        row = cursor.fetchone()
    current_database = str((row or {}).get("database_name") or "")
    if current_database != expected_database:
        raise AnnualAuditStorageError("migration connection is not using POSTGRESQL_DATABASE")


def _ensure_required_extensions_available(connection) -> None:
    """Fail before DDL when the PostgreSQL server lacks required extension packages."""

    rows = connection.execute(
        """
        SELECT name
        FROM pg_available_extensions
        WHERE name = ANY(%s)
        """,
        (list(REQUIRED_POSTGRES_EXTENSIONS),),
    ).fetchall()
    available = {str(row["name"]) for row in rows}
    missing = sorted(set(REQUIRED_POSTGRES_EXTENSIONS) - available)
    if missing:
        raise AnnualAuditStorageError(
            "PostgreSQL server is missing required extension packages: "
            f"{', '.join(missing)}. Install pgvector and PostgreSQL contrib before migrating."
        )


def _ensure_supported_postgres_version(connection) -> None:
    row = connection.execute("SHOW server_version_num").fetchone() or {}
    try:
        version_num = int(row.get("server_version_num") or 0)
    except (TypeError, ValueError):
        version_num = 0
    if version_num < MINIMUM_POSTGRES_VERSION_NUM:
        raise AnnualAuditStorageError(
            "PostgreSQL 12 or newer is required for generated-column migrations"
        )


def _repair_invalid_concurrent_index(connection, statement: str) -> None:
    """Remove a crash-left invalid concurrent index before retrying its DDL."""

    match = _CONCURRENT_INDEX_PATTERN.match(statement)
    if match is None:
        return
    index_name = match.group("index_name")
    row = connection.execute(
        """
        SELECT index_entry.indisvalid
        FROM pg_index AS index_entry
        WHERE index_entry.indexrelid = to_regclass(%s)
        """,
        (index_name,),
    ).fetchone()
    if row is not None and not bool(row.get("indisvalid")):
        connection.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")


def _ensure_migration_table(connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS public.annual_audit_schema_migration (
            version VARCHAR(64) PRIMARY KEY,
            description VARCHAR(255) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _migration_applied(connection, version: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM public.annual_audit_schema_migration WHERE version = %s",
            (version,),
        )
        return cursor.fetchone() is not None


def _record_migration(connection, version: str, description: str) -> None:
    connection.execute(
        """
        INSERT INTO public.annual_audit_schema_migration (version, description)
        VALUES (%s, %s)
        ON CONFLICT (version) DO UPDATE SET description = EXCLUDED.description
        """,
        (version, description),
    )


def apply_migrations(settings: Settings | None = None) -> None:
    """Apply all annual-audit PostgreSQL migrations exactly once.

    Autocommit is required because several base migrations create indexes with
    ``CONCURRENTLY``. Each SQL artifact is idempotent and gets a durable record
    only after it executes successfully.
    """

    resolved = settings or get_settings()
    _validate_migration_files()
    with postgres_connection(resolved, autocommit=True) as connection:
        _ensure_current_database(connection, resolved)
        _ensure_supported_postgres_version(connection)
        _ensure_required_extensions_available(connection)
        connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (_MIGRATION_LOCK_NAME,))
        try:
            _ensure_migration_table(connection)
            for version, migration_file, description in MIGRATIONS:
                if _migration_applied(connection, version):
                    continue
                for statement in _split_sql_statements(migration_file.read_text(encoding="utf-8")):
                    _repair_invalid_concurrent_index(connection, statement)
                    connection.execute(statement)
                _record_migration(connection, version, description)
        finally:
            connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_MIGRATION_LOCK_NAME,))


def main() -> None:
    apply_migrations()
    print("annual-audit PostgreSQL migrations applied")


if __name__ == "__main__":
    main()
