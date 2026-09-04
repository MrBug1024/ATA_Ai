from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

from ai_hunter.annual_audit import evidence_catalog_service


class _Result:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return self._rows


class _Connection:
    def __init__(self, responses: list[list[dict]]):
        self.responses = list(responses)
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, parameters: tuple):
        self.executed.append((query, parameters))
        return _Result(self.responses.pop(0))


def _postgres_context(connection: _Connection):
    @contextmanager
    def connect(_settings):
        yield connection

    return connect


def test_source_quality_hints_are_conservative():
    assert evidence_catalog_service.infer_source_quality("银行函证模板.docx")["code"] == "template"
    assert evidence_catalog_service.infer_source_quality("银行流水-底稿抽查派生.xlsx")["code"] == "derived"
    assert evidence_catalog_service.infer_source_quality("2025年审计工作底稿.xlsx")["code"] == "auditor_generated"
    assert evidence_catalog_service.infer_source_quality("中国银行回函.pdf")["code"] == "external_candidate"
    assert evidence_catalog_service.infer_source_quality("中国银行对账单.pdf")["code"] == "unverified_source"


def test_list_evidence_candidates_returns_selectable_canonical_references(monkeypatch):
    connection = _Connection(
        [
            [
                {
                    "id": 41,
                    "file_name": "银行对账单.pdf",
                    "content_type": "application/pdf",
                    "file_size_bytes": 2048,
                    "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                    "page_count": 2,
                    "chunk_count": 3,
                    "first_page_id": 501,
                    "first_page_no": 1,
                    "categories": [
                        {
                            "code": "bank_statements",
                            "name": "银行流水及对账单",
                            "match_source": "detected",
                            "confidence": Decimal("0.9500"),
                        }
                    ],
                }
            ],
            [
                {
                    "file_id": 41,
                    "source_chunk_id": "a" * 64,
                    "source_page_id": 501,
                    "page_no": 1,
                    "anchor_text": "期末银行存款余额 100,000.00 元",
                    "chunk_text": "",
                    "metadata": {},
                    "locator_rank": 1,
                }
            ],
        ]
    )
    monkeypatch.setattr(
        evidence_catalog_service,
        "postgres_connection",
        _postgres_context(connection),
    )

    result = evidence_catalog_service.list_evidence_candidates(
        7,
        query="银行",
        limit=25,
        settings=object(),
    )

    assert result["case_id"] == 7
    assert result["total"] == 1
    item = result["items"][0]
    assert item["source_file_id"] == 41
    assert item["categories"][0]["confidence"] == 0.95
    assert item["source_quality"]["code"] == "unverified_source"
    assert item["needs_manual_locator"] is False
    assert item["default_reference"] == {
        "source_file_id": 41,
        "source_page_id": 501,
        "source_chunk_id": "a" * 64,
        "source_locator": {
            "source_file_id": 41,
            "source_page_id": 501,
            "page_no": 1,
        },
        "label": "期末银行存款余额 100,000.00 元",
    }
    assert connection.executed[0][1][-1] == 25


def test_list_evidence_candidates_falls_back_to_first_page(monkeypatch):
    connection = _Connection(
        [
            [
                {
                    "id": 52,
                    "file_name": "租赁询证函模板.docx",
                    "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "file_size_bytes": 4096,
                    "created_at": None,
                    "page_count": 1,
                    "chunk_count": 0,
                    "first_page_id": 902,
                    "first_page_no": 1,
                    "categories": [],
                }
            ],
            [],
        ]
    )
    monkeypatch.setattr(
        evidence_catalog_service,
        "postgres_connection",
        _postgres_context(connection),
    )

    result = evidence_catalog_service.list_evidence_candidates(9, settings=object())

    item = result["items"][0]
    assert item["source_quality"]["code"] == "template"
    assert item["default_reference"]["source_page_id"] == 902
    assert item["needs_manual_locator"] is False

