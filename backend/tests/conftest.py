"""Shared pytest defaults.

Local developer .env may enable private auth. Unit tests default to the historical
open mode unless a test explicitly enables auth.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager

import pytest

from ai_hunter.app.settings import get_settings


@pytest.fixture(autouse=True)
def _default_auth_disabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", False)


class _OfflineConversationRepo:
    """No-I/O repository used by tests that do not define a narrower fake."""

    def get_messages(self, _thread_id):
        return []

    def get_turns(self, _thread_id):
        return []

    def get_max_assistant_version(self, _thread_id, _turn_id):
        return 0

    def append_messages(self, _thread_id, _messages):
        return None


class _EmptyCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql, _params=None):
        return None

    def fetchall(self):
        return []


class _EmptyConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _EmptyCursor()

    def commit(self):
        return None


@contextmanager
def _offline_connection():
    yield _EmptyConnection()


@asynccontextmanager
async def _offline_thread_lock(_dsn, _thread_id):
    yield


@pytest.fixture(autouse=True)
def _default_external_state_isolated(monkeypatch):
    """Keep the maintained unit suite independent from live platform state."""

    repo = _OfflineConversationRepo()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.memory.get_conversation_message_repo",
        lambda: repo,
    )
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_chat.get_conversation_message_repo",
        lambda: repo,
    )
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_chat.thread_advisory_lock",
        _offline_thread_lock,
    )
    monkeypatch.setattr(
        "ai_hunter.app.services.heavy_payload_admin._connect",
        _offline_connection,
    )
