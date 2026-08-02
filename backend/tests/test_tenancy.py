"""Tenant object access rules for auth v2-B."""

from fastapi import HTTPException

from ai_hunter.app.auth.identity import Identity
from ai_hunter.app.settings import get_settings
from ai_hunter.app.auth.tenancy import (
    CaseAccessRecord,
    ThreadAccessRecord,
    can_access_case_record,
    can_access_thread_record,
    can_manage_thread_record,
    require_case_access,
    require_thread_access,
    TenancyService,
)


def _identity(
    *,
    user_id: str = "u_owner",
    company_id: str = "co_1",
    is_company_admin: bool = False,
    is_super_admin: bool = False,
) -> Identity:
    return Identity(
        user_id=user_id,
        company_id=company_id,
        is_company_admin=is_company_admin,
        is_super_admin=is_super_admin,
    )


def _case(
    *,
    company_id: str = "co_1",
    owner_id: str = "u_owner",
    is_member: bool = False,
) -> CaseAccessRecord:
    return CaseAccessRecord(
        case_id=116,
        company_id=company_id,
        owner_id=owner_id,
        is_member=is_member,
    )


def test_case_access_allows_super_admin_across_company():
    assert can_access_case_record(
        _identity(is_super_admin=True, company_id="co_other"),
        _case(company_id="co_1", owner_id="u_other"),
    )


def test_case_access_allows_company_admin_in_same_company():
    assert can_access_case_record(
        _identity(user_id="u_admin", is_company_admin=True),
        _case(owner_id="u_other"),
    )


def test_case_access_allows_owner_and_active_member():
    assert can_access_case_record(_identity(user_id="u_owner"), _case(owner_id="u_owner"))
    assert can_access_case_record(
        _identity(user_id="u_member"),
        _case(owner_id="u_other", is_member=True),
    )


def test_case_access_rejects_missing_record_cross_company_and_non_member():
    assert not can_access_case_record(_identity(), None)
    assert not can_access_case_record(_identity(company_id="co_2"), _case(company_id="co_1"))
    assert not can_access_case_record(
        _identity(user_id="u_viewer"),
        _case(owner_id="u_owner", is_member=False),
    )


def test_thread_access_allows_creator_and_case_member():
    thread = ThreadAccessRecord(
        thread_id="t1",
        company_id="co_1",
        created_by="u_creator",
        case_id=116,
    )
    assert can_access_thread_record(_identity(user_id="u_creator"), thread)
    assert can_access_thread_record(
        _identity(user_id="u_member"),
        thread,
        case_record=_case(owner_id="u_owner", is_member=True),
    )


def test_thread_access_allows_company_admin_and_super_admin():
    thread = ThreadAccessRecord(thread_id="t1", company_id="co_1", created_by="u_creator")
    assert can_access_thread_record(_identity(user_id="u_admin", is_company_admin=True), thread)
    assert can_access_thread_record(
        _identity(user_id="u_super", company_id="co_other", is_super_admin=True),
        thread,
    )


def test_thread_access_rejects_missing_deleted_cross_company_and_non_member():
    ident = _identity(user_id="u_viewer")
    assert not can_access_thread_record(ident, None)
    assert not can_access_thread_record(
        ident,
        ThreadAccessRecord(thread_id="t1", company_id="co_1", status="deleted"),
    )
    assert not can_access_thread_record(
        _identity(company_id="co_2"),
        ThreadAccessRecord(thread_id="t1", company_id="co_1"),
    )
    assert not can_access_thread_record(
        ident,
        ThreadAccessRecord(thread_id="t1", company_id="co_1", created_by="u_creator", case_id=116),
        case_record=_case(owner_id="u_owner", is_member=False),
    )


def test_thread_manage_allows_creator_owner_and_admin_but_rejects_other_member():
    thread = ThreadAccessRecord(
        thread_id="t1",
        company_id="co_1",
        created_by="u_creator",
        case_id=116,
    )
    assert can_manage_thread_record(
        _identity(user_id="u_creator"),
        thread,
        case_record=_case(owner_id="u_owner", is_member=False),
    )
    assert can_manage_thread_record(
        _identity(user_id="u_owner"),
        thread,
        case_record=_case(owner_id="u_owner", is_member=False),
    )
    assert can_manage_thread_record(
        _identity(user_id="u_admin", is_company_admin=True),
        thread,
        case_record=_case(owner_id="u_owner", is_member=False),
    )
    assert not can_manage_thread_record(
        _identity(user_id="u_member"),
        thread,
        case_record=_case(owner_id="u_owner", is_member=True),
    )


def test_require_case_access_raises_403_when_denied(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    class _Service:
        def can_access_case(self, identity: Identity, case_id: int) -> bool:
            return False

    monkeypatch.setattr("ai_hunter.app.auth.tenancy.get_tenancy_service", lambda: _Service())
    try:
        require_case_access(116, identity=_identity())
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "无权限访问该案件"
    else:
        raise AssertionError("expected HTTPException")


def test_require_thread_access_raises_403_when_denied(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    class _Service:
        def can_access_thread(self, identity: Identity, thread_id: str) -> bool:
            return False

    monkeypatch.setattr("ai_hunter.app.auth.tenancy.get_tenancy_service", lambda: _Service())
    try:
        require_thread_access("t1", identity=_identity())
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "无权限访问该会话"
    else:
        raise AssertionError("expected HTTPException")


def test_bind_thread_case_updates_identity_owned_unbound_thread(monkeypatch):
    from contextlib import contextmanager

    service = TenancyService("unused")
    records = {
        "t-create": ThreadAccessRecord(
            thread_id="t-create",
            company_id="co_1",
            created_by="u_owner",
            case_id=None,
        )
    }

    monkeypatch.setattr(service, "get_thread_access_record", lambda thread_id: records.get(thread_id))
    monkeypatch.setattr(
        service,
        "get_case_access_record",
        lambda identity, case_id: CaseAccessRecord(
            case_id=case_id,
            company_id="co_1",
            owner_id="u_owner",
        ),
    )

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _sql, params):
            case_id, thread_id = params
            current = records[thread_id]
            records[thread_id] = ThreadAccessRecord(
                thread_id=current.thread_id,
                company_id=current.company_id,
                created_by=current.created_by,
                case_id=case_id,
            )

    class _Connection:
        def cursor(self):
            return _Cursor()

        def commit(self):
            pass

    @contextmanager
    def fake_connect():
        yield _Connection()

    monkeypatch.setattr(service, "connect", fake_connect)
    bound = service.bind_thread_case(_identity(), "t-create", 501)

    assert bound.case_id == 501


def test_bind_thread_case_rejects_cross_company_case(monkeypatch):
    service = TenancyService("unused")
    monkeypatch.setattr(
        service,
        "get_thread_access_record",
        lambda _thread_id: ThreadAccessRecord(
            thread_id="t-create",
            company_id="co_1",
            created_by="u_owner",
        ),
    )
    monkeypatch.setattr(
        service,
        "get_case_access_record",
        lambda _identity, case_id: CaseAccessRecord(
            case_id=case_id,
            company_id="co_2",
            owner_id="u_owner",
        ),
    )

    try:
        service.bind_thread_case(_identity(), "t-create", 501)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected HTTPException")
