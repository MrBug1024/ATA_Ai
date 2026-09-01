"""Shared deterministic chat turn identity helpers."""

from __future__ import annotations

import hashlib


def derive_turn_id(
    *,
    thread_id: str,
    client_turn_id: str,
    query: str,
    case_id: int,
    intent: str,
    message_count: int,
) -> str:
    if client_turn_id.strip():
        seed = f"{thread_id}:{client_turn_id.strip()}"
    else:
        seed = f"{query}:{case_id}:{intent}:{message_count}"
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def derive_assistant_message_id(**values) -> str:
    return f"{derive_turn_id(**values)}_assistant"


__all__ = ["derive_assistant_message_id", "derive_turn_id"]
