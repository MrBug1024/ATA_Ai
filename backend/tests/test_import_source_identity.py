from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

from ai_hunter.annual_audit import import_service, workpaper_case


class _Cursor:
    def __init__(self, existing: dict) -> None:
        self.existing = existing
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.executed.append((statement, params))

    def fetchone(self):
        return self.existing

    def executemany(self, *_args, **_kwargs) -> None:
        raise AssertionError("a replayed source must not insert duplicate rows")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _Cursor:
        return self._cursor

    def commit(self) -> None:
        raise AssertionError("a deduplicated replay must not commit new rows")


def _postgres_context(connection: _Connection):
    @contextmanager
    def connect(_settings):
        yield connection

    return connect


def test_dataset_replay_uses_content_hash_and_sheet_fragment_when_storage_key_changes(monkeypatch) -> None:
    cursor = _Cursor({"id": 9, "row_count": 131})
    monkeypatch.setattr(import_service, "postgres_connection", _postgres_context(_Connection(cursor)))

    inserted, deduplicated = import_service._persist_dataset(
        engagement_id=1,
        dataset="account_balance",
        rows=[
            {
                "period_end": date(2023, 12, 31),
                "account_code": "1001",
                "account_name": "Cash",
                "opening_debit": 0,
                "opening_credit": 0,
                "period_debit": 0,
                "period_credit": 0,
                "closing_debit": 0,
                "closing_credit": 0,
                "currency": "CNY",
                "source_locator_json": {},
            }
        ],
        source_ref="minio://raw/project-1/new-content-key#sheet=trial",
        source_sha256="a" * 64,
        file_name="trial.xlsx",
        created_by="test",
        settings=SimpleNamespace(),
    )

    assert (inserted, deduplicated) == (131, True)
    query, params = cursor.executed[0]
    assert "split_part(source_ref, '#', 2)" in query
    assert params[-1] == "minio://raw/project-1/new-content-key#sheet=trial"


def test_case_workpaper_replay_uses_content_hash_when_storage_key_changes(monkeypatch) -> None:
    cursor = _Cursor(
        {
            "id": 4,
            "row_count": 15342,
            "metadata_json": {"is_complete_case": True, "sheet_count": 296},
        }
    )
    monkeypatch.setattr(workpaper_case, "postgres_connection", _postgres_context(_Connection(cursor)))

    replay = workpaper_case.persist_case_workpaper_summary(
        engagement_id=1,
        source_ref="minio://raw/project-1/new-content-key",
        source_sha256="b" * 64,
        summary={"is_complete_case": True, "sheet_count": 296},
        created_by="test",
        settings=SimpleNamespace(),
    )

    assert replay["deduplicated"] is True
    query, params = cursor.executed[0]
    assert "split_part(source_ref, '#', 2)" in query
    assert params[-1] == "minio://raw/project-1/new-content-key"
