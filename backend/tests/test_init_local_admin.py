from __future__ import annotations

from contextlib import contextmanager

import pytest

from ai_hunter.app.scripts import init_local_admin
from ai_hunter.app.services.user_service import UserService


class _ProductionBootstrapService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def bootstrap_production_superadmin(self, **kwargs):
        self.calls.append(("bootstrap_production_superadmin", kwargs))
        return {"user_id": kwargs["user_id"]}


def test_superadmin_only_bootstrap_creates_no_company_or_demo_configuration(monkeypatch) -> None:
    service = _ProductionBootstrapService()
    monkeypatch.setattr(init_local_admin, "get_user_service", lambda: service)
    monkeypatch.setattr(init_local_admin, "hash_password", lambda password, **_kwargs: f"hash:{password}")
    monkeypatch.setattr(init_local_admin, "_password_from_env_or_prompt", lambda *_args: "StrongPassword123")
    monkeypatch.setattr(
        init_local_admin,
        "load_auth_seed",
        lambda *_args: pytest.fail("--superadmin-only must not load the demo seed"),
    )

    assert init_local_admin.main(["--superadmin-only"]) == 0

    names = [name for name, _kwargs in service.calls]
    assert names == ["bootstrap_production_superadmin"]
    request = service.calls[0][1]
    assert request["user_id"] == init_local_admin.SUPERADMIN_USER_ID
    assert request["login_identifier"] == "superadmin"
    assert request["password_hash"] == "hash:StrongPassword123"
    assert request["role_code"] == init_local_admin.ADMIN_ROLE


def test_superadmin_only_bootstrap_requires_a_password(monkeypatch) -> None:
    monkeypatch.setattr(init_local_admin, "get_user_service", lambda: object())

    with pytest.raises(ValueError, match="cannot be combined"):
        init_local_admin.main(["--superadmin-only", "--skip-passwords"])


class _BootstrapCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def execute(self, statement, params=()) -> None:
        self.executed.append((" ".join(str(statement).split()), tuple(params)))

    def fetchone(self):
        return {"user_id": init_local_admin.SUPERADMIN_USER_ID}


class _BootstrapConnection:
    def __init__(self) -> None:
        self.cursor_instance = _BootstrapCursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1


def test_production_superadmin_bootstrap_uses_one_transaction(monkeypatch) -> None:
    connection = _BootstrapConnection()

    @contextmanager
    def connect(_self):
        yield connection

    monkeypatch.setattr(UserService, "connect", connect)
    service = UserService("postgresql://configured")

    result = service.bootstrap_production_superadmin(
        user_id=init_local_admin.SUPERADMIN_USER_ID,
        username="系统超级管理员",
        login_identifier="superadmin",
        password_hash="argon2-hash",
    )

    statements = [statement for statement, _params in connection.cursor_instance.executed]
    assert result == {"user_id": init_local_admin.SUPERADMIN_USER_ID}
    assert connection.commits == 1
    assert any("INSERT INTO public.app_role_permission" in statement for statement in statements)
    assert any("INSERT INTO public.app_user" in statement for statement in statements)
    assert any("INSERT INTO public.local_user_credential" in statement for statement in statements)
    assert any("INSERT INTO public.app_user_role" in statement for statement in statements)
    assert any("INSERT INTO public.auth_audit_log" in statement for statement in statements)
