from datetime import datetime, timezone
from decimal import Decimal

from ai_hunter.app.graph.heavy_state import get_heavy_payload, put_heavy_payload


def test_put_heavy_payload_normalizes_decimal_values(monkeypatch):
    monkeypatch.setattr("ai_hunter.app.graph.heavy_state._get_redis_client", lambda: None)
    monkeypatch.setattr("ai_hunter.app.graph.heavy_state._put_postgres_payload", lambda key, prefix, payload: None)

    key = put_heavy_payload(
        "test_payload",
        {
            "count": Decimal("3"),
            "ratio": Decimal("3.25"),
            "rows": [{"amount": Decimal("9.50")}],
        },
    )

    payload = get_heavy_payload(key)

    assert payload == {
        "count": 3,
        "ratio": 3.25,
        "rows": [{"amount": 9.5}],
    }


def test_put_heavy_payload_normalizes_datetime_values(monkeypatch):
    monkeypatch.setattr("ai_hunter.app.graph.heavy_state._get_redis_client", lambda: None)
    monkeypatch.setattr("ai_hunter.app.graph.heavy_state._put_postgres_payload", lambda key, prefix, payload: None)

    key = put_heavy_payload(
        "test_payload",
        {
            "created_at": datetime(2026, 5, 15, 12, 34, 56, tzinfo=timezone.utc),
        },
    )

    payload = get_heavy_payload(key)

    assert payload == {
        "created_at": "2026-05-15T12:34:56+00:00",
    }
