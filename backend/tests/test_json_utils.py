from datetime import date, datetime, time, timezone
from decimal import Decimal

from ai_hunter.app.graph.json_utils import json_dumps_safe, make_json_safe


def test_make_json_safe_normalizes_nested_decimal_values():
    payload = {
        "count": Decimal("2"),
        "ratio": Decimal("2.75"),
        "items": [{"amount": Decimal("9.50")}],
        "tags": {Decimal("1"), "x"},
    }

    normalized = make_json_safe(payload)

    assert normalized["count"] == 2
    assert normalized["ratio"] == 2.75
    assert normalized["items"] == [{"amount": 9.5}]
    assert len(normalized["tags"]) == 2
    assert 1 in normalized["tags"]
    assert "x" in normalized["tags"]


def test_json_dumps_safe_serializes_decimal_payloads():
    rendered = json_dumps_safe({"score": Decimal("0.80"), "total": Decimal("3")})

    assert '"score": 0.8' in rendered
    assert '"total": 3' in rendered


def test_make_json_safe_normalizes_datetime_family_values():
    payload = {
        "created_at": datetime(2026, 5, 15, 12, 34, 56, tzinfo=timezone.utc),
        "hearing_date": date(2026, 5, 15),
        "hearing_time": time(14, 30, 0),
    }

    normalized = make_json_safe(payload)

    assert normalized == {
        "created_at": "2026-05-15T12:34:56+00:00",
        "hearing_date": "2026-05-15",
        "hearing_time": "14:30:00",
    }


def test_json_dumps_safe_serializes_datetime_family_values():
    rendered = json_dumps_safe(
        {
            "created_at": datetime(2026, 5, 15, 12, 34, 56, tzinfo=timezone.utc),
            "hearing_date": date(2026, 5, 15),
        }
    )

    assert '"created_at": "2026-05-15T12:34:56+00:00"' in rendered
    assert '"hearing_date": "2026-05-15"' in rendered
