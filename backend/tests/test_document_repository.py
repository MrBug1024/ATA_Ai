from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from ai_hunter.annual_audit import document_repository


class _Rows:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, statement: str, params: tuple = ()) -> _Rows:
        self.calls.append((statement, params))
        return _Rows(self.rows)


def _postgres_context(connection: _Connection):
    @contextmanager
    def connect(_settings):
        yield connection

    return connect


def test_case_doc_categories_require_usable_material_or_controlled_coverage(monkeypatch) -> None:
    connection = _Connection(
        [
            {
                "code": "raw_only",
                "name": "仅原始留存",
                "file_count": 2,
                "usable_file_count": 0,
                "chunk_count": 0,
                "failed_event_count": 0,
                "pending_event_count": 0,
                "last_uploaded_at": None,
            },
            {
                "code": "failed",
                "name": "解析失败",
                "file_count": 1,
                "usable_file_count": 0,
                "chunk_count": 0,
                "failed_event_count": 1,
                "pending_event_count": 0,
                "last_uploaded_at": None,
            },
            {
                "code": "pending",
                "name": "处理中",
                "file_count": 1,
                "usable_file_count": 0,
                "chunk_count": 0,
                "failed_event_count": 0,
                "pending_event_count": 1,
                "last_uploaded_at": None,
            },
            {
                "code": "confirmations",
                "name": "函证",
                "file_count": 1,
                "usable_file_count": 1,
                "chunk_count": 6,
                "failed_event_count": 0,
                "pending_event_count": 0,
                "last_uploaded_at": datetime(2026, 9, 3, tzinfo=timezone.utc),
            },
            {
                "code": "trial_balance",
                "name": "科目余额表",
                "file_count": 0,
                "usable_file_count": 0,
                "chunk_count": 0,
                "failed_event_count": 0,
                "pending_event_count": 0,
                "last_uploaded_at": None,
            },
            {
                "code": "audit_workpapers",
                "name": "审计底稿",
                "file_count": 0,
                "usable_file_count": 0,
                "chunk_count": 0,
                "failed_event_count": 0,
                "pending_event_count": 0,
                "last_uploaded_at": None,
            },
            {
                "code": "missing",
                "name": "缺失",
                "file_count": 0,
                "usable_file_count": 0,
                "chunk_count": 0,
                "failed_event_count": 0,
                "pending_event_count": 0,
                "last_uploaded_at": None,
            },
        ]
    )
    monkeypatch.setattr(document_repository, "postgres_connection", _postgres_context(connection))
    monkeypatch.setattr(document_repository, "get_engagement", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        document_repository,
        "_structured_record_counts",
        lambda *_args, **_kwargs: {"trial_balance": 4},
    )
    monkeypatch.setattr(
        document_repository,
        "get_case_workpaper_summary",
        lambda *_args, **_kwargs: {"covered_categories": {"audit_workpapers": ["审计小结"]}},
    )

    result = document_repository.get_case_doc_categories(17, settings=object())
    categories = {item["code"]: item for item in result["categories"]}

    assert categories["raw_only"] == {
        "code": "raw_only",
        "name": "仅原始留存",
        "uploaded": False,
        "raw_uploaded": True,
        "covered_by_case_workpaper": False,
        "coverage_basis": "raw_only",
        "coverage_status": "raw_only",
        "file_count": 2,
        "usable_file_count": 0,
        "raw_only_file_count": 2,
        "chunk_count": 0,
        "record_count": 0,
        "failed_event_count": 0,
        "pending_event_count": 0,
        "last_uploaded_at": None,
    }
    assert categories["failed"]["uploaded"] is False
    assert categories["failed"]["coverage_status"] == "failed"
    assert categories["failed"]["failed_event_count"] == 1
    assert categories["pending"]["uploaded"] is False
    assert categories["pending"]["coverage_status"] == "pending"
    assert categories["pending"]["pending_event_count"] == 1

    assert categories["confirmations"]["uploaded"] is True
    assert categories["confirmations"]["coverage_basis"] == "parsed_material"
    assert categories["confirmations"]["chunk_count"] == 6
    assert categories["confirmations"]["last_uploaded_at"] == "2026-09-03T00:00:00+00:00"
    assert categories["trial_balance"]["uploaded"] is True
    assert categories["trial_balance"]["coverage_basis"] == "structured_records"
    assert categories["audit_workpapers"]["uploaded"] is True
    assert categories["audit_workpapers"]["coverage_basis"] == "case_workpaper"
    assert result["missing_categories"] == ["raw_only", "failed", "pending", "missing"]

    statement, params = connection.calls[0]
    assert params == (17, 17, 17)
    assert "COUNT(*) FILTER (WHERE chunk_count > 0)" in statement
    assert "status = 'failed'" in statement
