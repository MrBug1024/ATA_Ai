"""权限网关（Tier 3）：身份解析 / 授权映射 / 报告段落过滤 / 模块级 403 / /me。"""

import jwt
import pytest
from fastapi.testclient import TestClient

from ai_hunter.app.auth.identity import Identity
from ai_hunter.app.auth.permissions import (
    allowed_modules,
    has_any_module,
    has_module,
    visible_audiences,
    visible_report_sections,
)
from ai_hunter.app.auth.report_filter import filter_report_text, filter_report_text_by_sections
from ai_hunter.app.auth.local_auth import hash_password
from ai_hunter.app.main import create_app
from ai_hunter.app.settings import get_settings
from ai_hunter.app.services.case_api import stamp_case_payload, tenant_params_from_identity
from ai_hunter.app.services.user_service import build_company_id


# ── 授权映射（纯逻辑）─────────────────────────────────────────────────────
def test_admin_sees_everything():
    adm = Identity.admin()
    assert visible_audiences(adm) == {"field", "expert", "management"}
    assert has_module(adm, "graph") and has_module(adm, "admin")


def test_role_audience_tiers():
    # project_manager=management(看全)；legal_specialist=expert(field+expert)；project_assistant=field
    assert visible_audiences(Identity(roles=["project_manager"])) == {"field", "expert", "management"}
    assert visible_audiences(Identity(roles=["legal_specialist"])) == {"field", "expert"}
    assert visible_audiences(Identity(roles=["project_assistant"])) == {"field"}
    # 未知角色 → 最低可见，避免越权
    assert visible_audiences(Identity(roles=["陌生角色"])) == {"field"}


def test_role_modules():
    assert "admin" in allowed_modules(Identity(roles=["project_manager"]))
    fz = allowed_modules(Identity(roles=["legal_specialist"]))
    assert "corrections" in fz and "admin" not in fz
    # finance_specialist无 deadline 模块
    assert not has_module(Identity(roles=["finance_specialist"]), "deadline")
    assert has_any_module(Identity(roles=["finance_specialist"]), ("report", "deadline"))
    assert not has_any_module(Identity(roles=["finance_specialist"]), ("deadline", "admin"))


def test_role_report_sections_from_seed(monkeypatch):
    import ai_hunter.app.auth.permissions as perms

    class _UnavailableSvc:
        def list_role_permissions(self):
            raise RuntimeError("db unavailable")

        def list_report_sections(self):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr("ai_hunter.app.services.user_service.get_user_service", lambda: _UnavailableSvc())
    perms.clear_role_permissions_cache()
    try:
        finance_sections = visible_report_sections(Identity(roles=["finance_specialist"]))
        assert finance_sections == {
            "data_gap_audit",
            "asset_revaluation",
            "restructuring_feasibility",
            "recovery_reconciliation_index",
        }
        investment_sections = visible_report_sections(Identity(roles=["investment_specialist"]))
        assert "execution_task_board" in investment_sections
    finally:
        perms.clear_role_permissions_cache()


def test_case_api_tenant_params_from_identity():
    ident = Identity(
        user_id="u_001",
        company_id="co_001",
        is_company_admin=True,
        is_super_admin=False,
    )
    assert tenant_params_from_identity(ident) == {
        "company_id": "co_001",
        "user_id": "u_001",
        "is_company_admin": True,
        "is_super_admin": False,
    }
    assert tenant_params_from_identity(None) == {}


def test_case_create_payload_stamps_tenant_fields():
    ident = Identity(user_id="u_owner", company_id="co_001")
    payload = {"case_name": "测试案件", "case_type": "单户", "debtor_name": "债务人A"}
    stamped = stamp_case_payload(payload, ident)
    assert stamped["company_id"] == "co_001"
    assert stamped["owner_id"] == "u_owner"
    assert stamped["created_by"] == "u_owner"
    assert "company_id" not in payload

    explicit = stamp_case_payload({"company_id": "co_other", "owner_id": "u_other"}, ident)
    assert explicit["company_id"] == "co_001"
    assert explicit["owner_id"] == "u_owner"
    assert explicit["created_by"] == "u_owner"

    admin = Identity(user_id="u_admin", company_id="co_001", is_company_admin=True)
    delegated = stamp_case_payload({"company_id": "co_other", "owner_id": "u_other"}, admin)
    assert delegated["company_id"] == "co_001"
    assert delegated["owner_id"] == "u_other"
    assert delegated["created_by"] == "u_admin"


# ── 报告段落过滤 ──────────────────────────────────────────────────────────
_REPORT = (
    "# 案件116报告\n\n"
    "### 1. 【数据洗脱】field 段正文\n\n"
    "### 3. 【资金流】expert 段正文\n\n"
    "### 6. 【博弈策略】management 段正文\n\n"
    "—— 角标溯源附录 ——"
)


def test_filter_field_only_sees_field():
    out = filter_report_text(_REPORT, {"field"})
    assert "数据洗脱" in out and "资金流" not in out and "博弈策略" not in out
    assert "# 案件116报告" in out  # 段头前导言保留


def test_filter_expert_sees_field_and_expert():
    out = filter_report_text(_REPORT, {"field", "expert"})
    assert "数据洗脱" in out and "资金流" in out and "博弈策略" not in out


def test_filter_management_sees_all():
    out = filter_report_text(_REPORT, {"field", "expert", "management"})
    assert "数据洗脱" in out and "资金流" in out and "博弈策略" in out and "溯源附录" in out


def test_filter_no_headers_unchanged():
    assert filter_report_text("下钻的纯文字回答，无段头", {"field"}) == "下钻的纯文字回答，无段头"


def test_filter_by_report_sections():
    report = (
        "# 案件116报告\n\n"
        "### 1. 【数据洗脱】数据段\n\n"
        "### 3. 【资金流】白手套段\n\n"
        "### 5. 【重整】盘活段\n\n"
        "### 8. 【对账】回款段\n\n"
        "—— 角标溯源附录 ——"
    )
    out = filter_report_text_by_sections(
        report,
        {"data_gap_audit", "restructuring_feasibility", "recovery_reconciliation_index"},
    )
    assert "数据洗脱" in out and "重整" in out and "对账" in out
    assert "资金流" not in out
    assert "# 案件116报告" in out


# ── 身份解析（依赖 settings，monkeypatch 同一缓存实例）──────────────────────
@pytest.fixture
def settings_auth(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "auth_identity_mode", "platform")
    monkeypatch.setattr(s, "auth_dev_trust_headers", True)
    monkeypatch.setattr(s, "auth_legacy_roles_enabled", True)
    monkeypatch.setattr(s, "user_center_jwt_alg", "HS256")
    monkeypatch.setattr(s, "auth_local_jwt_secret", "")
    monkeypatch.setattr(s, "user_center_jwt_secret", "test-secret-key-at-least-32-bytes-long!!")
    return s


def test_jwt_hs256_verified_identity(settings_auth):
    from ai_hunter.app.auth.identity import get_current_identity

    token = jwt.encode({"sub": "u-1", "name": "张三", "roles": ["legal_specialist"]},
                       "test-secret-key-at-least-32-bytes-long!!", algorithm="HS256")

    class _Req:
        headers = {"authorization": f"Bearer {token}"}

    ident = get_current_identity(_Req())
    assert ident.user_id == "u-1" and ident.username == "张三"
    assert ident.roles == ["legal_specialist"] and ident.authenticated is True


def test_bad_jwt_401_when_enabled(settings_auth):
    from fastapi import HTTPException
    from ai_hunter.app.auth.identity import get_current_identity

    class _Req:
        headers = {"authorization": "Bearer not.a.validtoken"}

    with pytest.raises(HTTPException) as ei:
        get_current_identity(_Req())
    assert ei.value.status_code == 401


def test_dev_header_trust(settings_auth):
    from ai_hunter.app.auth.identity import get_current_identity

    class _Req:
        headers = {"x-user-id": "u-9", "x-user-roles": "project_manager,legal_specialist"}

    ident = get_current_identity(_Req())
    assert ident.user_id == "u-9" and ident.roles == ["project_manager", "legal_specialist"]
    assert ident.authenticated is False


def test_enabled_no_creds_401(settings_auth):
    from fastapi import HTTPException
    from ai_hunter.app.auth.identity import get_current_identity

    monkey_req = type("R", (), {"headers": {}})()
    with pytest.raises(HTTPException) as ei:
        get_current_identity(monkey_req)
    assert ei.value.status_code == 401


def test_disabled_returns_admin(monkeypatch):
    from ai_hunter.app.auth.identity import get_current_identity

    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", False)
    assert s.auth_enabled is False  # 默认放行
    ident = get_current_identity(type("R", (), {"headers": {}})())
    assert ident.is_admin


# ── 模块级 403（接口；中文角色走 JWT body，不放 HTTP header）─────────────────
_SECRET = "test-secret-key-at-least-32-bytes-long!!"


def _bearer(roles, user_id="u1", name="", company=""):
    token = jwt.encode(
        {"sub": user_id, "name": name, "roles": roles, "company": company},
        _SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _enable_jwt(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "auth_identity_mode", "platform")
    monkeypatch.setattr(s, "auth_legacy_roles_enabled", True)
    monkeypatch.setattr(s, "user_center_jwt_alg", "HS256")
    monkeypatch.setattr(s, "auth_local_jwt_secret", "")
    monkeypatch.setattr(s, "user_center_jwt_secret", _SECRET)


def _enable_private_local_auth(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "auth_identity_mode", "private")
    monkeypatch.setattr(s, "user_center_jwt_alg", "HS256")
    monkeypatch.setattr(s, "auth_local_jwt_secret", _SECRET)
    monkeypatch.setattr(s, "user_center_jwt_secret", "")
    monkeypatch.setattr(s, "auth_local_access_token_minutes", 480)
    monkeypatch.setattr(s, "auth_legacy_roles_enabled", False)
    return s


def test_module_gate_403(monkeypatch):
    _enable_jwt(monkeypatch)
    client = TestClient(create_app())
    # finance_specialist无 deadline 模块 → 403
    r = client.get("/cases/116/deadline-board", headers=_bearer(["finance_specialist"]))
    assert r.status_code == 403


def test_module_gate_allows(monkeypatch):
    _enable_jwt(monkeypatch)

    class _Tenancy:
        def can_access_case(self, identity, case_id):
            return True

    class _Client:
        def audit_deadline_scan_sync(self, case_id):
            return {"alerts": []}

    import ai_hunter.app.services.audit_api as api
    monkeypatch.setattr(api, "get_audit_api_client", lambda: _Client())
    monkeypatch.setattr("ai_hunter.app.auth.tenancy.get_tenancy_service", lambda: _Tenancy())
    client = TestClient(create_app())
    # project_assistant有 deadline 模块 → 放行
    r = client.get("/cases/116/deadline-board", headers=_bearer(["project_assistant"]))
    assert r.status_code == 200 and r.json()["available"] is True


def test_module_gate_still_rejects_case_without_object_access(monkeypatch):
    _enable_jwt(monkeypatch)

    class _Tenancy:
        def can_access_case(self, identity, case_id):
            return False

    monkeypatch.setattr("ai_hunter.app.auth.tenancy.get_tenancy_service", lambda: _Tenancy())
    client = TestClient(create_app())
    r = client.get("/cases/116/deadline-board", headers=_bearer(["project_assistant"]))
    assert r.status_code == 403
    assert r.json()["detail"] == "无权限访问该案件"


def test_me_endpoint(monkeypatch):
    _enable_jwt(monkeypatch)
    client = TestClient(create_app())
    r = client.get("/me", headers=_bearer(["legal_specialist"], name="李四", company="c-1"))
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "u1" and body["roles"] == ["legal_specialist"]
    assert body["company_id"] == "c-1"
    assert body["is_company_admin"] is False
    assert set(body["visible_audiences"]) == {"field", "expert"}
    assert isinstance(body["visible_report_sections"], list)
    assert "corrections" in body["allowed_modules"]


def test_identity_loads_local_roles_before_jwt_roles(monkeypatch):
    from ai_hunter.app.auth.identity import get_current_identity

    _enable_jwt(monkeypatch)

    class _Svc:
        def list_user_roles(self, user_id, *, company_id=""):
            assert user_id == "u-local" and company_id == "c-local"
            return ["company_admin"]

    monkeypatch.setattr("ai_hunter.app.services.user_service.get_user_service", lambda: _Svc())
    token = jwt.encode(
        {"sub": "u-local", "name": "本地用户", "company": "c-local", "roles": ["project_assistant"]},
        _SECRET,
        algorithm="HS256",
    )

    class _Req:
        headers = {"authorization": f"Bearer {token}"}

    ident = get_current_identity(_Req())
    assert ident.roles == ["company_admin"]
    assert ident.company_id == "c-local"
    assert ident.is_company_admin is True


def test_platform_project_access_gate(monkeypatch):
    from fastapi import HTTPException
    from ai_hunter.app.auth.identity import get_current_identity

    _enable_jwt(monkeypatch)
    s = get_settings()
    monkeypatch.setattr(s, "auth_identity_mode", "platform")
    monkeypatch.setattr(s, "auth_require_project_access", True)
    monkeypatch.setattr(s, "auth_project_code", "ai_hunter")
    token = jwt.encode({"sub": "u-no-app", "apps": ["other"]}, _SECRET, algorithm="HS256")

    class _Req:
        headers = {"authorization": f"Bearer {token}"}

    with pytest.raises(HTTPException) as ei:
        get_current_identity(_Req())
    assert ei.value.status_code == 403


def test_company_id_is_deterministic():
    assert build_company_id("国金中恒企业管理（海南）有限公司") == "co_f1824b82e2116701"


def test_password_policy_requires_length_and_digit():
    from ai_hunter.app.auth.local_auth import validate_password_policy

    with pytest.raises(ValueError):
        validate_password_policy("short1")
    with pytest.raises(ValueError):
        validate_password_policy("abcdefghij")
    with pytest.raises(ValueError):
        validate_password_policy("username123", username="username123")


def test_disabled_endpoints_open(monkeypatch):
    # AUTH_ENABLED=false → 无身份头也放行（admin）
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", False)
    client = TestClient(create_app())
    r = client.get("/me")
    assert r.status_code == 200 and r.json()["roles"] == ["super_admin"]


# ── 角色权限可配（DB 优先 + 接口）─────────────────────────────────────────
def test_role_permissions_db_first(monkeypatch):
    # DB 返回自定义映射 → 授权层优先采用（而非代码默认）
    import ai_hunter.app.auth.permissions as perms

    class _Svc:
        def list_role_permissions(self):
            return {"custom_role": {"tier": "management", "modules": ["*"]}}

    monkeypatch.setattr("ai_hunter.app.services.user_service.get_user_service", lambda: _Svc())
    perms.clear_role_permissions_cache()
    try:
        ident = Identity(roles=["custom_role"])
        assert visible_audiences(ident) == {"field", "expert", "management"}
        assert has_module(ident, "admin")
    finally:
        perms.clear_role_permissions_cache()  # 不污染后续用例


def test_role_config_endpoints(monkeypatch):
    _enable_jwt(monkeypatch)
    captured = {}

    class _Svc:
        def list_role_permissions(self):
            return {"legal_specialist": {"tier": "expert", "modules": ["report"], "description": ""}}

        def list_report_sections(self):
            return [
                {"section_code": "data_gap_audit", "section_id": "1", "title": "数据洗脱与缺失核查"},
                {"section_code": "legal_limitation_board", "section_id": "4", "title": "司法时效预警看板"},
            ]

        def upsert_role_permission(self, role_code, *, tier, modules, description="", role_name=None):
            captured.update({"role_code": role_code, "role_name": role_name, "tier": tier, "modules": modules})
            return {
                "role_code": role_code,
                "role_name": role_name or "",
                "tier": tier,
                "modules": modules,
                "description": description,
            }

        def replace_role_report_sections(self, role_code, section_codes):
            captured["visible_report_sections"] = section_codes
            return section_codes

        def write_auth_audit_log(self, **kwargs):
            captured["audit"] = kwargs

    monkeypatch.setattr("ai_hunter.app.api.routes_users.get_user_service", lambda: _Svc())
    client = TestClient(create_app())
    # project_manager(admin 模块) 可列角色
    r = client.get("/roles", headers=_bearer(["project_manager"]))
    body = r.json()
    assert r.status_code == 200 and "legal_specialist" in body["roles"] and "all_modules" in body
    assert body["report_sections"][0]["section_code"] == "data_gap_audit"
    # 配置角色权限
    r = client.put("/roles/legal_assistant", headers=_bearer(["project_manager"]),
                   json={
                       "tier": "expert",
                       "modules": ["report", "deadline"],
                       "visible_report_sections": ["data_gap_audit", "legal_limitation_board"],
                       "description": "升级",
                   })
    assert r.status_code == 200 and captured["tier"] == "expert"
    assert captured["visible_report_sections"] == ["data_gap_audit", "legal_limitation_board"]
    assert captured["audit"]["event_type"] == "role_permission_changed"
    assert captured["audit"]["target_id"] == "legal_assistant"
    # 非法模块码 → 422
    r = client.put("/roles/legal_assistant", headers=_bearer(["project_manager"]),
                   json={"tier": "field", "modules": ["不存在的模块"]})
    assert r.status_code == 422
    # 非 admin 角色 → 403
    r = client.get("/roles", headers=_bearer(["project_assistant"]))
    assert r.status_code == 403


def test_user_role_assignment_endpoints(monkeypatch):
    _enable_jwt(monkeypatch)
    captured = {}

    class _Svc:
        def list_user_roles(self, user_id, *, company_id=""):
            return ["legal_specialist"] if user_id == "u2" else []

        def replace_user_roles(self, user_id, *, company_id, roles, assigned_by=""):
            captured.update({"user_id": user_id, "company_id": company_id, "roles": roles, "assigned_by": assigned_by})
            return roles

        def write_auth_audit_log(self, **kwargs):
            captured["audit"] = kwargs

    svc = _Svc()
    monkeypatch.setattr("ai_hunter.app.services.user_service.get_user_service", lambda: svc)
    monkeypatch.setattr("ai_hunter.app.api.routes_users.get_user_service", lambda: svc)

    client = TestClient(create_app())
    r = client.get("/users/u2/roles", headers=_bearer(["project_manager"]))
    assert r.status_code == 200 and r.json()["roles"] == ["legal_specialist"]

    r = client.put(
        "/users/u2/roles",
        headers=_bearer(["project_manager"], user_id="admin-1"),
        json={"company_id": "c-1", "roles": ["legal_specialist", "project_assistant"]},
    )
    assert r.status_code == 200
    assert captured["assigned_by"] == "admin-1"
    assert captured["audit"]["event_type"] == "user_roles_replaced"

    r = client.put(
        "/users/u2/roles",
        headers=_bearer(["project_manager"]),
        json={"company_id": "", "roles": ["legal_specialist"]},
    )
    assert r.status_code == 422


def test_company_and_user_management_endpoints(monkeypatch):
    _enable_jwt(monkeypatch)
    captured = {}

    class _Svc:
        def list_companies(self, *, include_disabled=False):
            captured["include_disabled"] = include_disabled
            return [{"company_id": "co_1", "company_name": "公司A"}]

        def upsert_company(self, *, company_id=None, company_name, company_type="customer", status="active", notes=""):
            captured["company"] = {
                "company_id": company_id or "co_generated",
                "company_name": company_name,
                "company_type": company_type,
                "status": status,
                "notes": notes,
            }
            return captured["company"]

        def list_users(self, *, company_id="", status="", limit=200):
            captured["list_users"] = {"company_id": company_id, "status": status, "limit": limit}
            return [{"user_id": "u2", "company_id": company_id}]

        def upsert_user(self, user_id, **kwargs):
            captured["user"] = {"user_id": user_id, **kwargs}
            return captured["user"]

        def set_local_password(self, user_id, *, login_identifier, password_hash, password_algo="argon2id"):
            captured["password"] = {
                "user_id": user_id,
                "login_identifier": login_identifier,
                "password_hash": password_hash,
                "password_algo": password_algo,
            }

        def write_auth_audit_log(self, **kwargs):
            captured["audit"] = kwargs

    svc = _Svc()
    monkeypatch.setattr("ai_hunter.app.api.routes_users.get_user_service", lambda: svc)
    client = TestClient(create_app())

    r = client.get("/companies", headers=_bearer(["project_manager"]))
    assert r.status_code == 200 and r.json()["companies"][0]["company_id"] == "co_1"

    r = client.post(
        "/companies",
        headers=_bearer(["project_manager"], user_id="admin-1"),
        json={"company_name": "公司A", "status": "active"},
    )
    assert r.status_code == 200 and captured["company"]["company_name"] == "公司A"
    assert captured["audit"]["event_type"] == "company_upserted"
    assert captured["audit"]["actor_id"] == "admin-1"

    r = client.get("/companies/generate-id", headers=_bearer(["project_manager"]), params={"company_name": "公司A"})
    assert r.status_code == 200 and r.json()["company_id"].startswith("co_")

    r = client.get("/users", headers=_bearer(["project_manager"]), params={"company_id": "co_1", "status": "active"})
    assert r.status_code == 200 and captured["list_users"]["company_id"] == "co_1"

    r = client.post(
        "/users",
        headers=_bearer(["project_manager"], user_id="admin-1"),
        json={"user_id": "u2", "username": "李四", "company_id": "co_1", "password": "Passw0rd123"},
    )
    assert r.status_code == 200
    assert captured["user"]["user_id"] == "u2"
    assert captured["password"]["user_id"] == "u2"
    assert captured["audit"]["event_type"] == "user_upserted"

    r = client.put(
        "/users/u2",
        headers=_bearer(["project_manager"], user_id="admin-1"),
        json={"username": "李四", "company_id": "co_1", "status": "active"},
    )
    assert r.status_code == 200
    assert captured["audit"]["event_type"] == "user_upserted"

    r = client.post(
        "/users",
        headers=_bearer(["project_manager"]),
        json={"user_id": "u3", "username": "王五", "company_id": ""},
    )
    assert r.status_code == 422


def test_local_login_success_and_bad_password(monkeypatch):
    _enable_private_local_auth(monkeypatch)
    captured = {"failures": 0}
    password_hash = hash_password("Passw0rd123", username="李四")

    class _Svc:
        def get_local_login_record(self, login_identifier):
            if login_identifier != "u2":
                return None
            return {
                "user_id": "u2",
                "username": "李四",
                "company_id": "co_1",
                "auth_source": "local",
                "status": "active",
                "is_super_admin": False,
                "password_hash": password_hash,
                "failed_login_count": 0,
                "locked_until": None,
            }

        def record_login_failure(self, login_identifier, *, threshold, lock_minutes):
            captured["failures"] += 1

        def record_login_success(self, user_id):
            captured["success"] = user_id

        def write_auth_audit_log(self, **kwargs):
            captured.setdefault("audit", []).append(kwargs)

    monkeypatch.setattr("ai_hunter.app.api.routes_auth.get_user_service", lambda: _Svc())
    client = TestClient(create_app())

    r = client.post("/auth/login", json={"login_identifier": "u2", "password": "bad-password"})
    assert r.status_code == 401
    assert captured["failures"] == 1

    r = client.post("/auth/login", json={"login_identifier": "u2", "password": "Passw0rd123"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert captured["success"] == "u2"
    decoded = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
    assert decoded["sub"] == "u2" and "roles" not in decoded


def test_v2a1_files_and_chat_routes_require_identity(monkeypatch):
    _enable_jwt(monkeypatch)
    client = TestClient(create_app())

    assert client.get("/files/health").status_code == 200
    assert client.get("/files/upload-batches/batch-1").status_code == 401
    assert client.get("/chat/threads").status_code == 401
    assert client.get("/chat/threads/t1").status_code == 401
    assert client.delete("/chat/threads/t1").status_code == 401
    assert client.get("/chat/threads/t1/messages").status_code == 401
    assert client.get("/chat/threads/t1/turns").status_code == 401


def test_v2a1_module_gates_block_wrong_roles(monkeypatch):
    _enable_jwt(monkeypatch)
    client = TestClient(create_app())
    unknown = _bearer(["unknown_role"])

    assert client.post("/chat/invoke", headers=unknown, json={"query": "案件116出具完整审计报告"}).status_code == 403
    assert client.post(
        "/chat/upload-files",
        headers=unknown,
        files={"files": ("a.txt", b"hello", "text/plain")},
        data={"current_case_id": "116"},
    ).status_code == 403
    assert client.post("/files/upload-batches/batch-1/retry", headers=_bearer(["investment_specialist"])).status_code == 403
    assert client.post(
        "/files/upload-and-ingest",
        headers=_bearer(["project_assistant"]),
        files={"files": ("a.txt", b"hello", "text/plain")},
        data={"current_case_id": "116", "doc_category": "contract"},
    ).status_code == 403
