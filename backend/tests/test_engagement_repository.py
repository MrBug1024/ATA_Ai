from __future__ import annotations

from contextlib import contextmanager

from ai_hunter.annual_audit import engagement_repository


class _Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple | None]] = []
        self._fetches = [None, {"id": 42}]

    def execute(self, query: str, params: tuple | None = None) -> None:
        self.calls.append((query, params))

    def fetchone(self):
        return self._fetches.pop(0)


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.committed = False

    @contextmanager
    def cursor(self):
        yield self._cursor

    def commit(self) -> None:
        self.committed = True


def test_create_engagement_handles_missing_entity_uscc_without_untyped_null(monkeypatch) -> None:
    cursor = _Cursor()
    connection = _Connection(cursor)

    @contextmanager
    def fake_postgres_connection(_settings):
        yield connection

    monkeypatch.setattr(engagement_repository, "postgres_connection", fake_postgres_connection)

    result = engagement_repository.create_engagement(
        {
            "case_name": "历史案例迁移",
            "entity_name": "北京有限公司",
            "company_id": "co_annual_local",
            "fiscal_year": 2023,
        },
        settings=object(),
    )

    lookup_sql, lookup_params = cursor.calls[0]
    assert "entity_uscc IS NOT DISTINCT FROM %s" in lookup_sql
    assert lookup_params == (2023, "北京有限公司", "co_annual_local", None)
    assert result["case_id"] == 42
    assert connection.committed
