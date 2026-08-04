from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ai_hunter.app.graph import checkpointer


def test_async_pool_waits_until_connections_are_ready(monkeypatch):
    opened_with: list[bool] = []

    class FakePool:
        def __init__(self, *args, **kwargs):
            pass

        async def open(self, *, wait: bool = False):
            opened_with.append(wait)

        async def close(self):
            pass

    class FakeSaver:
        def __init__(self, pool):
            self.pool = pool

    monkeypatch.setattr(
        checkpointer,
        "get_settings",
        lambda: SimpleNamespace(
            langgraph_checkpointer="postgres",
            postgres_checkpointer_dsn="postgresql://test",
            langgraph_checkpointer_auto_setup=False,
        ),
    )
    monkeypatch.setattr("psycopg_pool.AsyncConnectionPool", FakePool)
    monkeypatch.setattr(
        "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver",
        FakeSaver,
    )
    monkeypatch.setattr(checkpointer, "_ASYNC_POOL", None)
    monkeypatch.setattr(checkpointer, "_async_saver", None)
    monkeypatch.setattr(checkpointer, "_async_checkpointer_lock", None)

    saver = asyncio.run(checkpointer.get_async_checkpointer())

    assert isinstance(saver, FakeSaver)
    assert opened_with == [True]
