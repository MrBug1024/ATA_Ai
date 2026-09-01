"""Guarded PostgreSQL connection factory for the annual platform store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import logging

import psycopg
from psycopg.rows import dict_row

from ai_hunter.app.settings import Settings, get_settings

from .errors import AnnualAuditStorageError


LOGGER = logging.getLogger(__name__)


@contextmanager
def postgres_connection(
    settings: Settings | None = None,
    *,
    autocommit: bool = False,
) -> Iterator[psycopg.Connection]:
    """Open the configured annual-audit PostgreSQL connection.

    Connections always use dictionary rows.  The helper owns the transaction:
    normal use commits on success and rolls back on failure, while migrations
    may request autocommit for ``CREATE INDEX CONCURRENTLY`` statements.
    """

    resolved = settings or get_settings()
    if resolved.business_domain != "annual_audit":
        raise AnnualAuditStorageError(
            "annual platform PostgreSQL access requires BUSINESS_DOMAIN=annual_audit"
        )
    connection: psycopg.Connection | None = None
    try:
        connection = psycopg.connect(
            resolved.postgres_checkpointer_dsn,
            row_factory=dict_row,
            autocommit=autocommit,
        )
        try:
            yield connection
        except Exception:
            if not autocommit:
                connection.rollback()
            raise
        else:
            if not autocommit:
                connection.commit()
    except AnnualAuditStorageError:
        raise
    except Exception as exc:
        LOGGER.exception("annual_postgresql_operation_failed")
        raise AnnualAuditStorageError(
            "annual platform PostgreSQL operation failed"
        ) from exc
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                LOGGER.warning("annual_postgresql_connection_close_failed")


__all__ = ["postgres_connection"]
