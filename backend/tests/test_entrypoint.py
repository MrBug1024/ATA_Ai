from __future__ import annotations

import asyncio

from ai_hunter import __main__ as entrypoint


def test_windows_entrypoint_uses_selector_event_loop_policy(monkeypatch):
    configured = []
    sentinel_policy = object()

    monkeypatch.setattr(entrypoint.sys, "platform", "win32")
    monkeypatch.setattr(
        entrypoint.asyncio,
        "WindowsSelectorEventLoopPolicy",
        lambda: sentinel_policy,
    )
    monkeypatch.setattr(
        entrypoint.asyncio,
        "set_event_loop_policy",
        configured.append,
    )

    entrypoint.configure_event_loop_policy()

    assert configured == [sentinel_policy]


def test_non_windows_entrypoint_keeps_default_event_loop_policy(monkeypatch):
    configured = []
    monkeypatch.setattr(entrypoint.sys, "platform", "linux")
    monkeypatch.setattr(
        entrypoint.asyncio,
        "set_event_loop_policy",
        configured.append,
    )

    entrypoint.configure_event_loop_policy()

    assert configured == []


def test_uvicorn_uses_selector_factory_on_windows(monkeypatch):
    monkeypatch.setattr(entrypoint.sys, "platform", "win32")

    assert entrypoint.uvicorn_loop_setting() == (
        "ai_hunter.__main__:selector_event_loop_factory"
    )


def test_uvicorn_keeps_auto_loop_on_non_windows(monkeypatch):
    monkeypatch.setattr(entrypoint.sys, "platform", "linux")

    assert entrypoint.uvicorn_loop_setting() == "auto"
