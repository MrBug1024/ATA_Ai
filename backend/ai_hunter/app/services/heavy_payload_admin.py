"""Operational helpers for inspecting and pruning heavy payload storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from ..graph.heavy_state import _get_redis_client
from ..settings import get_settings


@dataclass
class HeavyPayloadStats:
    """Aggregated heavy payload statistics for operators."""

    total_rows: int
    type_counts: list[dict[str, Any]]
    oldest_updated_at: datetime | None
    newest_updated_at: datetime | None


def _connect():
    """Open a psycopg connection using the normalized PostgreSQL DSN."""
    return psycopg.connect(get_settings().postgres_checkpointer_dsn)


def get_heavy_payload_stats() -> HeavyPayloadStats:
    """Return row counts and time distribution for heavy_payload_store."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*), min(updated_at), max(updated_at)
                FROM public.heavy_payload_store
                """
            )
            total_rows, oldest_updated_at, newest_updated_at = cur.fetchone()
            cur.execute(
                """
                SELECT payload_type, count(*) AS row_count
                FROM public.heavy_payload_store
                GROUP BY payload_type
                ORDER BY payload_type
                """
            )
            type_counts = [
                {"payload_type": payload_type, "row_count": row_count}
                for payload_type, row_count in cur.fetchall()
            ]
    return HeavyPayloadStats(
        total_rows=total_rows,
        type_counts=type_counts,
        oldest_updated_at=oldest_updated_at,
        newest_updated_at=newest_updated_at,
    )


def prune_heavy_payloads(
    *,
    dry_run: bool = True,
    payload_type: str | None = None,
    older_than_seconds: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Prune expired heavy payload rows from PostgreSQL and matching Redis cache keys."""
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(
        seconds=older_than_seconds or settings.heavy_payload_ttl_seconds
    )
    batch_limit = limit or settings.heavy_payload_prune_batch_size

    where_clauses = ["updated_at < %s"]
    params: list[Any] = [cutoff]
    if payload_type:
        where_clauses.append("payload_type = %s")
        params.append(payload_type)

    where_sql = " AND ".join(where_clauses)
    select_sql = f"""
        SELECT payload_key, payload_type, updated_at
        FROM public.heavy_payload_store
        WHERE {where_sql}
        ORDER BY updated_at ASC
        LIMIT %s
    """
    params_with_limit = [*params, batch_limit]

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(select_sql, params_with_limit)
            rows = cur.fetchall()
            candidates = [
                {
                    "payload_key": payload_key,
                    "payload_type": row_payload_type,
                    "updated_at": updated_at.isoformat(),
                }
                for payload_key, row_payload_type, updated_at in rows
            ]

            if dry_run or not candidates:
                return {
                    "dry_run": dry_run,
                    "cutoff": cutoff.isoformat(),
                    "payload_type": payload_type or "",
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                }

            payload_keys = [row["payload_key"] for row in candidates]
            cur.execute(
                """
                DELETE FROM public.heavy_payload_store
                WHERE payload_key = ANY(%s)
                """,
                (payload_keys,),
            )
        conn.commit()

    redis_client = _get_redis_client()
    if redis_client is not None and payload_keys:
        redis_client.delete(*payload_keys)

    return {
        "dry_run": False,
        "cutoff": cutoff.isoformat(),
        "payload_type": payload_type or "",
        "deleted_count": len(payload_keys),
        "deleted_keys": payload_keys,
    }
