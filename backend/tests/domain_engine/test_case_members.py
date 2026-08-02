"""Tenant-aware case member API tests for auth v2-B.1."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, Request

from ai_hunter.domain_engine import api as main


def _request(token: str = "service-token") -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.fixture(autouse=True)
def _service_token(monkeypatch):
    monkeypatch.setattr(main, "AUDIT_API_TOKEN", "service-token")


def test_list_case_members_requires_service_token():
    with pytest.raises(HTTPException) as exc:
        main.list_case_members(
            _request(""),
            116,
            company_id="co_1",
            user_id="u_member",
            is_company_admin=False,
            is_super_admin=False,
        )
    assert exc.value.status_code == 401


def test_list_case_members_returns_visible_case_members(monkeypatch):
    monkeypatch.setattr(
        main,
        "_get_visible_case",
        lambda *args, **kwargs: ({"case_id": 116, "company_id": "co_1", "owner_id": "u_owner"}, False, False),
    )
    monkeypatch.setattr(
        main.db,
        "query",
        lambda sql, params: [
            {
                "case_id": 116,
                "company_id": "co_1",
                "user_id": "u_member",
                "username": "member",
                "member_role": "auditor",
                "status": "active",
                "added_by": "u_owner",
                "created_at": datetime(2026, 7, 13, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 7, 13, tzinfo=timezone.utc),
            }
        ],
    )

    result = main.list_case_members(
        _request(),
        116,
        company_id="co_1",
        user_id="u_member",
        is_company_admin=False,
        is_super_admin=False,
    )

    assert result["company_id"] == "co_1"
    assert result["members"][0]["user_id"] == "u_member"
    assert result["members"][0]["created_at"].startswith("2026-07-13")


def test_list_case_members_rejects_cross_company_caller(monkeypatch):
    captured = {}

    def _query_one(sql, params):
        captured["params"] = params
        return None

    monkeypatch.setattr(main.db, "query_one", _query_one)

    with pytest.raises(HTTPException) as exc:
        main.list_case_members(
            _request(),
            116,
            company_id="co_other",
            user_id="u_other",
            is_company_admin=False,
            is_super_admin=False,
        )

    assert exc.value.status_code == 404
    assert captured["params"] == (116, "co_other", "u_other", "u_other")


def test_upsert_case_member_allows_owner_and_soft_disable(monkeypatch):
    monkeypatch.setattr(
        main,
        "_get_visible_case",
        lambda *args, **kwargs: ({"case_id": 116, "company_id": "co_1", "owner_id": "u_owner"}, False, False),
    )
    monkeypatch.setattr(
        main.db,
        "query_one",
        lambda sql, params: {"user_id": "u_member", "username": "member", "company_id": "co_1"},
    )
    captured = {}

    def _execute_returning(sql, params):
        captured["params"] = params
        return {
            "case_id": 116,
            "company_id": "co_1",
            "user_id": "u_member",
            "member_role": "auditor",
            "status": "disabled",
            "added_by": "u_owner",
            "created_at": datetime(2026, 7, 13, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 7, 13, tzinfo=timezone.utc),
        }

    monkeypatch.setattr(main.db, "execute_returning", _execute_returning)

    result = main.upsert_case_member(
        _request(),
        116,
        "u_member",
        main.CaseMemberUpsertReq(member_role="auditor", status="disabled"),
        company_id="co_1",
        user_id="u_owner",
        is_company_admin=False,
        is_super_admin=False,
    )

    assert result["status"] == "disabled"
    assert captured["params"] == (116, "co_1", "u_member", "auditor", "disabled", "u_owner")


def test_upsert_case_member_rejects_non_owner_member(monkeypatch):
    monkeypatch.setattr(
        main,
        "_get_visible_case",
        lambda *args, **kwargs: ({"case_id": 116, "company_id": "co_1", "owner_id": "u_owner"}, False, False),
    )

    with pytest.raises(HTTPException) as exc:
        main.upsert_case_member(
            _request(),
            116,
            "u_other",
            main.CaseMemberUpsertReq(),
            company_id="co_1",
            user_id="u_member",
            is_company_admin=False,
            is_super_admin=False,
        )
    assert exc.value.status_code == 403


def test_upsert_case_member_requires_actor_user_id():
    with pytest.raises(HTTPException) as exc:
        main.upsert_case_member(
            _request(),
            116,
            "u_member",
            main.CaseMemberUpsertReq(),
            company_id="co_1",
            user_id="",
            is_company_admin=True,
            is_super_admin=False,
        )
    assert exc.value.status_code == 422


def test_upsert_case_member_rejects_cross_company_target(monkeypatch):
    monkeypatch.setattr(
        main,
        "_get_visible_case",
        lambda *args, **kwargs: ({"case_id": 116, "company_id": "co_1", "owner_id": "u_owner"}, False, False),
    )
    monkeypatch.setattr(
        main.db,
        "query_one",
        lambda sql, params: {"user_id": "u_other", "username": "other", "company_id": "co_2"},
    )

    with pytest.raises(HTTPException) as exc:
        main.upsert_case_member(
            _request(),
            116,
            "u_other",
            main.CaseMemberUpsertReq(),
            company_id="co_1",
            user_id="u_owner",
            is_company_admin=False,
            is_super_admin=False,
        )
    assert exc.value.status_code == 409


def test_case_member_openapi_documents_security_contract():
    schema = main.app.openapi()
    list_op = schema["paths"]["/api/cases/{case_id}/members"]["get"]
    upsert_op = schema["paths"]["/api/cases/{case_id}/members/{member_user_id}"]["put"]

    assert "AUDIT_API_TOKEN" in list_op["description"]
    assert "owner" in upsert_op["description"]
    assert upsert_op["requestBody"]["required"] is True
