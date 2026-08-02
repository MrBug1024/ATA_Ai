"""Authoritative debtor resolution tests for parse-document."""

import pytest
from fastapi import HTTPException

from ai_hunter.domain_engine import documents as doc_parser


def test_resolve_existing_case_debtor_by_id(monkeypatch):
    monkeypatch.setattr(
        doc_parser.db,
        "query_one",
        lambda sql, params: {"debtor_id": 76, "entity_name": "钟山区老鹰山镇晨光煤矿"},
    )

    debtor_id, debtor_name = doc_parser._resolve_existing_case_debtor(
        116,
        76,
        "钟山区 老鹰山镇 晨光煤矿",
    )

    assert debtor_id == 76
    assert debtor_name == "钟山区老鹰山镇晨光煤矿"


def test_resolve_existing_case_debtor_rejects_cross_case_id(monkeypatch):
    monkeypatch.setattr(doc_parser.db, "query_one", lambda sql, params: None)

    with pytest.raises(HTTPException) as exc:
        doc_parser._resolve_existing_case_debtor(116, 999, None)

    assert exc.value.status_code == 404


def test_resolve_existing_case_debtor_rejects_name_conflict(monkeypatch):
    monkeypatch.setattr(
        doc_parser.db,
        "query_one",
        lambda sql, params: {"debtor_id": 76, "entity_name": "钟山区老鹰山镇晨光煤矿"},
    )

    with pytest.raises(HTTPException) as exc:
        doc_parser._resolve_existing_case_debtor(
            116,
            76,
            "中国中信金融资产管理股份有限公司",
        )

    assert exc.value.status_code == 409


def test_resolve_existing_case_debtor_uses_only_case_debtor(monkeypatch):
    monkeypatch.setattr(
        doc_parser.db,
        "query",
        lambda sql, params: [{"debtor_id": 76, "entity_name": "钟山区老鹰山镇晨光煤矿"}],
    )

    result = doc_parser._resolve_existing_case_debtor(116, None, None)

    assert result == (76, "钟山区老鹰山镇晨光煤矿")


def test_resolve_existing_case_debtor_rejects_multiple_without_id(monkeypatch):
    monkeypatch.setattr(
        doc_parser.db,
        "query",
        lambda sql, params: [
            {"debtor_id": 1, "entity_name": "债务人甲"},
            {"debtor_id": 2, "entity_name": "债务人乙"},
        ],
    )

    with pytest.raises(HTTPException) as exc:
        doc_parser._resolve_existing_case_debtor(116, None, None)

    assert exc.value.status_code == 409
    assert "多个债务人" in str(exc.value.detail)
