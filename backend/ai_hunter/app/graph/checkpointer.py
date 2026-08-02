import atexit
import asyncio
from functools import lru_cache
import logging

from langgraph.checkpoint.memory import MemorySaver

from ..settings import get_settings


_LOGGER = logging.getLogger(__name__)
_POOL = None
_ASYNC_POOL = None
_async_saver = None
_async_checkpointer_lock = None

_CHECKPOINTER_POOL_MAX_SIZE = 10


def _get_async_lock() -> asyncio.Lock:
    """Delay Lock creation until an event loop is running."""
    global _async_checkpointer_lock
    if _async_checkpointer_lock is None:
        _async_checkpointer_lock = asyncio.Lock()
    return _async_checkpointer_lock


@lru_cache(maxsize=1)
def get_checkpointer():
    """Build the LangGraph checkpointer.

    Uses a pooled sync ``PostgresSaver`` when ``LANGGRAPH_CHECKPOINTER=postgres``
    so conversations survive restarts and are visible to the history API. This
    sync saver serves the **non-streaming JSON path** (``/chat/invoke`` without
    ``stream``), which runs ``graph.stream`` inside a threadpool.

    The **SSE streaming path does NOT use this saver**: ``astream_events``
    requires ``aget_tuple``, which the sync ``PostgresSaver`` lacks, so streaming
    is served by a separately compiled async graph bound to ``AsyncPostgresSaver``
    (see ``get_async_checkpointer`` and ``routes_chat._ensure_async_graph``).
    Both savers read/write the same ``checkpoints`` table and are serialized
    per-thread via a PostgreSQL advisory lock.

    Falls back to ``MemorySaver`` for the ``memory`` mode or when Postgres is
    unreachable, keeping local/offline runs and tests working.
    """
    settings = get_settings()
    mode = settings.langgraph_checkpointer.lower()

    if mode == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            global _POOL
            _POOL = ConnectionPool(
                settings.postgres_checkpointer_dsn,
                max_size=_CHECKPOINTER_POOL_MAX_SIZE,
                open=True,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            atexit.register(_POOL.close)
            saver = PostgresSaver(_POOL)
            if settings.langgraph_checkpointer_auto_setup:
                saver.setup()
            _LOGGER.info("Using PostgresSaver for checkpointing (sync, pooled)")
            return saver
        except Exception as exc:  # pragma: no cover - depends on live Postgres
            _LOGGER.warning(
                "Postgres checkpointer unavailable, falling back to MemorySaver: %s",
                exc,
            )
            return MemorySaver()

    _LOGGER.info("Using MemorySaver for checkpointing")
    return MemorySaver()


async def get_async_checkpointer():
    """Build an async LangGraph checkpointer for astream_events paths.

    Uses module-level double-checked locking so only one ``AsyncConnectionPool``
    and ``AsyncPostgresSaver`` are created per process.  Cleanup is handled by
    the FastAPI lifespan (see ``close_async_checkpointer``).
    """
    global _async_saver, _ASYNC_POOL

    if _async_saver is not None:
        return _async_saver

    async with _get_async_lock():
        if _async_saver is not None:
            return _async_saver

        settings = get_settings()
        mode = settings.langgraph_checkpointer.lower()

        if mode == "postgres":
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                from psycopg_pool import AsyncConnectionPool

                _ASYNC_POOL = AsyncConnectionPool(
                    settings.postgres_checkpointer_dsn,
                    max_size=_CHECKPOINTER_POOL_MAX_SIZE,
                    open=False,
                    kwargs={
                        "autocommit": True,
                        "prepare_threshold": 0,
                    },
                )
                await _ASYNC_POOL.open()
                saver = AsyncPostgresSaver(_ASYNC_POOL)
                if settings.langgraph_checkpointer_auto_setup:
                    await saver.setup()
                _async_saver = saver
                _LOGGER.info(
                    "Using AsyncPostgresSaver for checkpointing (async, pooled, singleton)"
                )
                return _async_saver
            except Exception as exc:  # pragma: no cover - depends on live Postgres
                _LOGGER.warning(
                    "Async Postgres checkpointer unavailable, falling back to MemorySaver: %s",
                    exc,
                )
                _async_saver = MemorySaver()
                return _async_saver

        _LOGGER.info("Using MemorySaver for async checkpointing")
        _async_saver = MemorySaver()
        return _async_saver


async def close_async_checkpointer() -> None:
    """Gracefully close the async connection pool.

    Called by the FastAPI lifespan shutdown stage.
    """
    global _ASYNC_POOL, _async_saver
    if _ASYNC_POOL is not None:
        try:
            await _ASYNC_POOL.close()
            _LOGGER.info("AsyncConnectionPool closed gracefully")
        except Exception as exc:
            _LOGGER.warning("Error closing AsyncConnectionPool: %s", exc)
        finally:
            _ASYNC_POOL = None
            _async_saver = None
