"""PostgreSQL advisory lock helpers for cross-process serialization."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
import psycopg


def _pg_key(thread_id: str) -> int:
    """Map a thread_id to a 63-bit signed integer for pg_advisory_lock."""
    digest = hashlib.sha256(thread_id.encode()).digest()[:8]
    val = int.from_bytes(digest, byteorder="big", signed=False)
    return val & 0x7FFFFFFFFFFFFFFF


@asynccontextmanager
async def thread_advisory_lock(dsn: str, thread_id: str) -> AsyncIterator[None]:
    """Acquire a PostgreSQL advisory lock for the given thread_id.

    Works across processes (multi-worker uvicorn) because the lock lives
    in the database server.
    """
    key = _pg_key(thread_id)
    conn = await anyio.to_thread.run_sync(lambda: psycopg.connect(dsn))
    try:
        await anyio.to_thread.run_sync(
            lambda: conn.cursor().execute("SELECT pg_advisory_lock(%s)", (key,))
        )
        try:
            yield
        finally:
            await anyio.to_thread.run_sync(
                lambda: conn.cursor().execute("SELECT pg_advisory_unlock(%s)", (key,))
            )
    finally:
        await anyio.to_thread.run_sync(conn.close)
