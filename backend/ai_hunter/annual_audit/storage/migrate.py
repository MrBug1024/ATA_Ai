"""Apply isolated annual-audit storage migrations."""

from __future__ import annotations

from pathlib import Path

from ai_hunter.app.settings import Settings, get_settings

from .mysql import AnnualAuditStorageError, mysql_connection


SQL_DIR = Path(__file__).resolve().parents[3] / "sql"
MIGRATIONS = (
    (
        "001",
        SQL_DIR / "annual_audit_mysql_v1.sql",
        "annual audit chat-first isolated storage foundation",
    ),
    (
        "002",
        SQL_DIR / "annual_audit_mysql_v2.sql",
        "annual engagement compatibility and tenancy fields",
    ),
    (
        "003",
        SQL_DIR / "annual_audit_mysql_v3.sql",
        "remove platform persistence tables from annual MySQL",
    ),
    (
        "004",
        SQL_DIR / "annual_audit_mysql_v4.sql",
        "remove platform files evidence and graph tables from annual MySQL",
    ),
    (
        "005",
        SQL_DIR / "annual_audit_mysql_v5.sql",
        "annual audit structured ledgers analysis findings and workpapers",
    ),
    (
        "006",
        SQL_DIR / "annual_audit_mysql_v6.sql",
        "annual engagement task management",
    ),
)

POSTGRES_MIGRATION = SQL_DIR / "annual_audit_postgres_v1.sql"


def _migration_applied(cursor, version: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS table_count
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = 'ata_schema_migration'
        """
    )
    if int(cursor.fetchone()["table_count"]) == 0:
        return False
    cursor.execute(
        "SELECT 1 FROM ata_schema_migration WHERE version = %s LIMIT 1",
        (version,),
    )
    return cursor.fetchone() is not None


def apply_base_schema(settings: Settings | None = None) -> None:
    resolved = settings or get_settings()

    try:
        from pymysql.constants import CLIENT
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise AnnualAuditStorageError(
            "PyMySQL is required to apply annual-audit migrations"
        ) from exc

    with mysql_connection(resolved, client_flag=CLIENT.MULTI_STATEMENTS) as connection:
        try:
            with connection.cursor() as cursor:
                for version, migration_file, description in MIGRATIONS:
                    if _migration_applied(cursor, version):
                        continue
                    cursor.execute(migration_file.read_text(encoding="utf-8"))
                    while cursor.nextset():
                        pass
                    cursor.execute(
                        """
                        INSERT INTO ata_schema_migration (version, description)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE description = VALUES(description)
                        """,
                        (version, description),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def apply_platform_schema(settings: Settings | None = None) -> None:
    """Apply idempotent migrations to the configured annual PostgreSQL database."""

    resolved = settings or get_settings()
    dsn = resolved.postgres_checkpointer_dsn
    database = dsn.rsplit("/", 1)[-1].split("?", 1)[0]
    if database != resolved.annual_postgres_database:
        raise AnnualAuditStorageError("PostgreSQL database must match ANNUAL_POSTGRES_DATABASE")

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise AnnualAuditStorageError("psycopg is required for annual platform migrations") from exc

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(POSTGRES_MIGRATION.read_text(encoding="utf-8"))


def main() -> None:
    apply_base_schema()
    apply_platform_schema()
    print("annual-audit MySQL and PostgreSQL migrations applied")


if __name__ == "__main__":
    main()
