"""Case-party model, authorization, transaction, and OpenAPI tests."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from ai_hunter.domain_engine import api as main


def _request(token: str = "service-token") -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.fixture(autouse=True)
def _service_token(monkeypatch):
    monkeypatch.setattr(main, "AUDIT_API_TOKEN", "service-token")


def _party_row(**overrides):
    row = {
        "party_id": 2,
        "case_id": 116,
        "debtor_id": None,
        "party_name": "中国中信金融资产管理股份有限公司",
        "party_role": "asset_purchaser",
        "uscc": None,
        "is_primary": True,
        "status": "active",
        "source_type": "manual",
        "extra_fields": {},
        "created_by": "u_owner",
        "created_at": datetime(2026, 7, 14, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 14, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_case_party_request_contract_rejects_debtor_role():
    with pytest.raises(ValidationError):
        main.CasePartyUpsertReq(
            party_name="错误债务人",
            party_role="debtor",
        )


def test_list_case_parties_requires_service_token():
    with pytest.raises(HTTPException) as exc:
        main.list_case_parties(
            _request(""),
            116,
            company_id="co_1",
            user_id="u_member",
            is_company_admin=False,
            is_super_admin=False,
        )
    assert exc.value.status_code == 401


def test_list_case_parties_returns_visible_rows(monkeypatch):
    monkeypatch.setattr(
        main,
        "_get_visible_case",
        lambda *args, **kwargs: ({"case_id": 116, "company_id": "co_1", "owner_id": "u_owner"}, False, False),
    )
    monkeypatch.setattr(main.db, "query", lambda sql, params: [_party_row()])

    result = main.list_case_parties(
        _request(),
        116,
        company_id="co_1",
        user_id="u_member",
        is_company_admin=False,
        is_super_admin=False,
    )

    assert result["parties"][0]["party_role"] == "asset_purchaser"
    assert result["parties"][0]["created_at"].startswith("2026-07-14")


def test_upsert_case_party_allows_owner(monkeypatch):
    monkeypatch.setattr(
        main,
        "_get_visible_case",
        lambda *args, **kwargs: ({"case_id": 116, "company_id": "co_1", "owner_id": "u_owner"}, False, False),
    )
    captured = {}

    def _execute_returning(sql, params):
        captured["params"] = params
        return _party_row()

    monkeypatch.setattr(main.db, "execute_returning", _execute_returning)

    result = main.upsert_case_party(
        _request(),
        116,
        main.CasePartyUpsertReq(
            party_name="中国中信金融资产管理股份有限公司",
            party_role="asset_purchaser",
            is_primary=True,
        ),
        company_id="co_1",
        user_id="u_owner",
        is_company_admin=False,
        is_super_admin=False,
    )

    assert result["party_role"] == "asset_purchaser"
    assert captured["params"][0:3] == (
        116,
        "中国中信金融资产管理股份有限公司",
        "asset_purchaser",
    )


def test_upsert_case_party_rejects_non_owner_member(monkeypatch):
    monkeypatch.setattr(
        main,
        "_get_visible_case",
        lambda *args, **kwargs: ({"case_id": 116, "company_id": "co_1", "owner_id": "u_owner"}, False, False),
    )

    with pytest.raises(HTTPException) as exc:
        main.upsert_case_party(
            _request(),
            116,
            main.CasePartyUpsertReq(party_name="某债权人", party_role="creditor"),
            company_id="co_1",
            user_id="u_member",
            is_company_admin=False,
            is_super_admin=False,
        )
    assert exc.value.status_code == 403


class _FakeCursor:
    def __init__(self):
        self.statements = []
        self._returning = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        compact = " ".join(sql.split())
        self.statements.append((compact, params))
        if "RETURNING case_id" in compact:
            self._returning = (501,)
        elif "RETURNING debtor_id" in compact:
            self._returning = (601,)

    def fetchone(self):
        return self._returning


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance


def test_create_case_writes_debtor_and_purchaser_in_one_transaction(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(main, "_find_existing_case", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.db, "get_conn", lambda: connection)

    result = main.create_case(
        main.CreateCaseReq(
            case_name="晨光煤矿案件",
            debtor_name="钟山区老鹰山镇晨光煤矿",
            asset_purchaser_name="中国中信金融资产管理股份有限公司",
        )
    )

    sql_text = "\n".join(statement for statement, _ in connection.cursor_instance.statements)
    assert result["case_id"] == 501
    assert result["debtor_id"] == 601
    assert "INSERT INTO case_party" in sql_text
    assert "'debtor'" in sql_text
    assert "'asset_purchaser'" in sql_text
    assert "init_data_source_checklist" in sql_text


def test_case_party_openapi_documents_roles_and_security():
    schema = main.app.openapi()
    list_op = schema["paths"]["/api/cases/{case_id}/parties"]["get"]
    upsert_op = schema["paths"]["/api/cases/{case_id}/parties"]["post"]
    create_schema = schema["components"]["schemas"]["CreateCaseReq"]
    upsert_schema = schema["components"]["schemas"]["CasePartyUpsertReq"]

    assert "AUDIT_API_TOKEN" in list_op["description"]
    assert "owner" in upsert_op["description"]
    assert "asset_purchaser_name" in create_schema["properties"]
    assert "debtor" not in upsert_schema["properties"]["party_role"]["enum"]
