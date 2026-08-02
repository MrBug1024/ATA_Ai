"""Shared JSON normalization helpers for graph-facing payloads."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


def make_json_safe(payload: Any) -> Any:
    """Normalize nested payloads into JSON-serializable Python primitives."""
    # Keep this aligned with values that may flow in from DB rows / graph snapshots
    # before they are persisted into Redis or PostgreSQL-backed heavy payload storage.
    if isinstance(payload, Decimal):
        return int(payload) if payload == payload.to_integral_value() else float(payload)
    if isinstance(payload, (datetime, date, time)):
        return payload.isoformat()
    if isinstance(payload, dict):
        return {str(key): make_json_safe(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [make_json_safe(item) for item in payload]
    if isinstance(payload, set):
        return [make_json_safe(item) for item in sorted(payload, key=repr)]
    return payload


def json_dumps_safe(payload: Any, **kwargs: Any) -> str:
    """Dump payload to JSON after normalizing non-serializable numeric types."""
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(make_json_safe(payload), **kwargs)
