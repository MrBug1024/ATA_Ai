"""Guarded MySQL connection factory for annual-audit repositories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from ai_hunter.app.settings import Settings, get_settings

if TYPE_CHECKING:
    import pymysql


class AnnualAuditStorageError(RuntimeError):
    """Raised when isolated annual-audit storage is not safe to use."""


def _validate_settings(settings: Settings) -> None:
    if settings.business_domain != "annual_audit":
        raise AnnualAuditStorageError(
            "annual-audit MySQL access requires BUSINESS_DOMAIN=annual_audit"
        )
    if settings.annual_mysql_database.strip().lower() != "ata_agent":
        raise AnnualAuditStorageError(
            "refusing annual-audit MySQL access outside database ata_agent"
        )


@contextmanager
def mysql_connection(
    settings: Settings | None = None,
    *,
    autocommit: bool = False,
    client_flag: int = 0,
) -> Iterator[Any]:
    """Open a dictionary-cursor connection to the isolated annual database.

    The driver import is intentionally lazy so startup can report a focused
    dependency error. Repositories own transaction boundaries;
    this helper rolls back on error and always closes the connection.
    """

    resolved = settings or get_settings()
    _validate_settings(resolved)

    try:
        import pymysql
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise AnnualAuditStorageError(
            "PyMySQL is required when BUSINESS_DOMAIN=annual_audit"
        ) from exc

    connection: pymysql.Connection | None = None
    try:
        connection = pymysql.connect(
            host=resolved.annual_mysql_host,
            port=resolved.annual_mysql_port,
            user=resolved.annual_mysql_user,
            password=resolved.annual_mysql_password,
            database=resolved.annual_mysql_database,
            charset="utf8mb4",
            connect_timeout=resolved.annual_mysql_connect_timeout_seconds,
            autocommit=autocommit,
            client_flag=client_flag,
            cursorclass=pymysql.cursors.DictCursor,
        )
        yield connection
    except AnnualAuditStorageError:
        raise
    except Exception as exc:
        if connection is not None and not autocommit:
            connection.rollback()
        raise AnnualAuditStorageError("annual-audit MySQL operation failed") from exc
    finally:
        if connection is not None:
            connection.close()
