"""Guarded PostgreSQL connection factory for the annual platform store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from ai_hunter.app.settings import Settings, get_settings

from .mysql import AnnualAuditStorageError


@contextmanager
def postgres_connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    resolved = settings or get_settings()
    if resolved.business_domain != "annual_audit":
        raise AnnualAuditStorageError(
            "annual platform PostgreSQL access requires BUSINESS_DOMAIN=annual_audit"
        )
    try:
        with psycopg.connect(
            resolved.postgres_checkpointer_dsn,
            row_factory=dict_row,
        ) as connection:
            yield connection
    except AnnualAuditStorageError:
        raise
    except Exception as exc:
        raise AnnualAuditStorageError(
            "annual platform PostgreSQL operation failed"
        ) from exc


__all__ = ["postgres_connection"]
