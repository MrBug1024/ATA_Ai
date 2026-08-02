"""用户 / 人员标签 / 权限自省接口（Tier 3）。

- GET /me：当前登录者身份 + 角色 + 本项目可见 audience / 可访问模块 + 标签（仅需认证）。
- 标签 / 用户管理：需 admin 模块权限（运营维护；用户中心上线后可下线）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth.identity import Identity, get_current_identity
from ..auth.local_auth import hash_password
from ..auth.permissions import (
    MODULES,
    allowed_modules,
    clear_role_permissions_cache,
    require_module,
    visible_audiences,
    visible_report_sections,
)
from ..auth.roles import ADMIN_ROLE, default_company_from_seed, normalize_roles, validate_role_code
from ..services.user_service import (
    MULTI_DIMENSIONS,
    build_company_id,
    get_user_service,
)

router = APIRouter(tags=["users"])


def _write_auth_audit_safely(**kwargs) -> None:
    """Best-effort audit write; auth changes should remain usable if audit storage is temporarily unavailable."""
    try:
        get_user_service().write_auth_audit_log(**kwargs)
    except Exception:  # noqa: BLE001 - 审计失败不阻断管理主流程
        pass


class MeResponse(BaseModel):
    user_id: str = ""
    username: str = ""
    roles: list[str] = Field(default_factory=list)
    company_id: str = ""
    apps: list[str] = Field(default_factory=list)
    is_company_admin: bool = False
    is_super_admin: bool = False
    authenticated: bool = False
    visible_audiences: list[str] = Field(default_factory=list, description="本项目可见报告段落层级")
    visible_report_sections: list[str] = Field(default_factory=list, description="本项目可见审计报告段落 section_code")
    allowed_modules: list[str] = Field(default_factory=list, description="本项目可访问模块")
    tags: dict = Field(default_factory=dict, description="人员标签（project_role/title/expertise/company/region）")


class TagsUpdateRequest(BaseModel):
    dimension: str = Field(description="多选维度：project_role / title / expertise")
    values: list[str] = Field(default_factory=list, description="整维替换的标签值列表")


class CompanyUpsertRequest(BaseModel):
    company_id: str | None = Field(default=None, description="公司/机构 id；为空时按 company_name 确定性生成")
    company_name: str = Field(description="公司/机构展示名称")
    company_type: str = Field(default="customer", description="公司/机构类型")
    status: str = Field(default="active", description="状态：active / disabled")
    notes: str = Field(default="", description="备注")


class UserUpsertRequest(BaseModel):
    user_id: str | None = Field(default=None, description="用户唯一标识；POST /users 必填，PUT /users/{id} 走路径")
    username: str | None = None
    company: str | None = Field(default=None, description="所属公司名")
    company_id: str | None = Field(
        default_factory=lambda: default_company_from_seed()["company_id"],
        description="所属公司/机构 id，用于 v2 多租户隔离",
    )
    auth_source: str | None = Field(default=None, description="身份来源：local / platform / sso")
    status: str | None = Field(default=None, description="用户状态：active / disabled / locked")
    is_super_admin: bool | None = Field(default=None, description="是否内部超级管理员")
    password: str | None = Field(default=None, description="私有化本地初始/重置密码；为空则不修改密码")
    region: str | None = Field(default=None, description="常住地域 省-市-县(区)")
    note: str | None = None


class UserRolesUpdateRequest(BaseModel):
    company_id: str = Field(default="", description="角色所属公司/机构 id；普通角色必填")
    roles: list[str] = Field(default_factory=list, description="整组替换后的本项目角色列表")


@router.get("/me", summary="当前身份 + 权限 + 标签自省", response_model=MeResponse,
            description="返回当前登录者(来自用户中心 JWT)的身份、角色、本项目可见 audience/模块、人员标签。仅需认证。")
async def me(identity: Identity = Depends(get_current_identity)) -> dict:
    tags = {}
    if identity.user_id:
        try:
            tags = get_user_service().get_tags(identity.user_id)
        except Exception:  # noqa: BLE001 — 库不可达不影响身份自省
            tags = {}
    return {
        "user_id": identity.user_id,
        "username": identity.username,
        "roles": identity.roles,
        "company_id": identity.company_id,
        "apps": identity.apps,
        "is_company_admin": identity.is_company_admin,
        "is_super_admin": identity.is_super_admin,
        "authenticated": identity.authenticated,
        "visible_audiences": sorted(visible_audiences(identity)),
        "visible_report_sections": sorted(visible_report_sections(identity)),
        "allowed_modules": sorted(allowed_modules(identity)),
        "tags": tags,
    }


@router.get("/tag-catalog", summary="人员标签预设目录",
            description="返回标签预设可选项（project_role/title/expertise，expertise 带分组）。仅需认证。")
async def tag_catalog(dimension: str | None = None,
                      _: Identity = Depends(get_current_identity)) -> dict:
    return {"catalog": get_user_service().list_catalog(dimension)}


@router.get("/companies", summary="列公司/机构目录",
            dependencies=[Depends(require_module("admin"))])
async def list_companies(include_disabled: bool = False) -> dict:
    return {"companies": get_user_service().list_companies(include_disabled=include_disabled)}


@router.post("/companies", summary="创建/更新公司/机构",
             description="company_id 为空时按 company_name 标准化后 sha256 前 16 位生成。")
async def upsert_company(payload: CompanyUpsertRequest,
                         identity: Identity = Depends(require_module("admin"))) -> dict:
    from fastapi import HTTPException

    if payload.status not in ("active", "disabled"):
        raise HTTPException(status_code=422, detail="status 非法（active/disabled）")
    try:
        row = get_user_service().upsert_company(
            company_id=payload.company_id,
            company_name=payload.company_name,
            company_type=payload.company_type,
            status=payload.status,
            notes=payload.notes,
        )
        _write_auth_audit_safely(
            event_type="company_upserted",
            actor_id=identity.user_id,
            company_id=row.get("company_id", ""),
            target_type="company",
            target_id=row.get("company_id", ""),
            action="upsert_company",
            decision="success",
            detail={
                "company_name": row.get("company_name", ""),
                "status": row.get("status", ""),
                "actor_is_super_admin": identity.is_super_admin,
            },
        )
        return row
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/companies/generate-id", summary="按公司名生成确定性 company_id",
            dependencies=[Depends(require_module("admin"))])
async def generate_company_id(company_name: str) -> dict:
    from fastapi import HTTPException

    try:
        return {"company_name": company_name, "company_id": build_company_id(company_name)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/users", summary="列用户",
            dependencies=[Depends(require_module("admin"))])
async def list_users(company_id: str = "", status: str = "", limit: int = 200) -> dict:
    return {"users": get_user_service().list_users(company_id=company_id, status=status, limit=limit)}


@router.post("/users", summary="创建/更新本地用户",
             description="私有化普通用户 / 公司管理员必须绑定 company_id。")
async def create_user(payload: UserUpsertRequest,
                      identity: Identity = Depends(require_module("admin"))) -> dict:
    from fastapi import HTTPException

    user_id = (payload.user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="user_id 不能为空")
    if not payload.username:
        raise HTTPException(status_code=422, detail="username 不能为空")
    if payload.is_super_admin is not True and not payload.company_id:
        raise HTTPException(status_code=422, detail="私有化普通用户 / 公司管理员必须绑定 company_id")
    try:
        row = get_user_service().upsert_user(
            user_id,
            username=payload.username,
            company=payload.company,
            region=payload.region,
            note=payload.note,
            company_id=payload.company_id,
            auth_source=payload.auth_source or "local",
            status=payload.status or "active",
            is_super_admin=payload.is_super_admin or False,
        )
        if payload.password:
            get_user_service().set_local_password(
                user_id,
                login_identifier=user_id,
                password_hash=hash_password(payload.password, username=payload.username or user_id),
            )
        _write_auth_audit_safely(
            event_type="user_upserted",
            actor_id=identity.user_id,
            company_id=payload.company_id or identity.company_id,
            target_type="user",
            target_id=user_id,
            action="upsert_user",
            decision="success",
            detail={
                "is_super_admin": payload.is_super_admin or False,
                "status": payload.status or "active",
                "password_set": bool(payload.password),
                "actor_is_super_admin": identity.is_super_admin,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return row


@router.get("/users/{user_id}/tags", summary="查用户标签",
            dependencies=[Depends(require_module("admin"))])
async def get_user_tags(user_id: str) -> dict:
    return {"user_id": user_id, "tags": get_user_service().get_tags(user_id)}


@router.put("/users/{user_id}/tags", summary="整维替换用户多选标签",
            dependencies=[Depends(require_module("admin"))],
            description="整维替换某多选维度(project_role/title/expertise)。company/region 走 PUT /users/{id}。")
async def put_user_tags(user_id: str, payload: TagsUpdateRequest) -> dict:
    if payload.dimension not in MULTI_DIMENSIONS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"维度非法（应为 {MULTI_DIMENSIONS} 之一）：{payload.dimension}")
    values = get_user_service().set_tags(user_id, payload.dimension, payload.values)
    return {"user_id": user_id, "dimension": payload.dimension, "values": values}


@router.put("/users/{user_id}", summary="建/更新用户投影（含 company/region）",
            description="更新用户主档。普通用户必须绑定 company_id。")
async def upsert_user(user_id: str, payload: UserUpsertRequest,
                      identity: Identity = Depends(require_module("admin"))) -> dict:
    from fastapi import HTTPException

    if payload.is_super_admin is not True and not payload.company_id:
        raise HTTPException(status_code=422, detail="私有化普通用户 / 公司管理员必须绑定 company_id")
    try:
        row = get_user_service().upsert_user(
            user_id, username=payload.username, company=payload.company,
            region=payload.region, note=payload.note, company_id=payload.company_id,
            auth_source=payload.auth_source, status=payload.status,
            is_super_admin=payload.is_super_admin,
        )
        if payload.password:
            get_user_service().set_local_password(
                user_id,
                login_identifier=user_id,
                password_hash=hash_password(payload.password, username=payload.username or user_id),
            )
        _write_auth_audit_safely(
            event_type="user_upserted",
            actor_id=identity.user_id,
            company_id=payload.company_id or identity.company_id,
            target_type="user",
            target_id=user_id,
            action="upsert_user",
            decision="success",
            detail={
                "is_super_admin": payload.is_super_admin,
                "status": payload.status,
                "password_set": bool(payload.password),
                "actor_is_super_admin": identity.is_super_admin,
            },
        )
        return row
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/users/{user_id}/roles", summary="查询用户本项目角色",
            dependencies=[Depends(require_module("admin"))],
            description="v2-A 本地角色来源：读取 app_user_role。company_id 为空时返回该用户全部公司内角色。")
async def get_user_roles(user_id: str, company_id: str = "") -> dict:
    roles = get_user_service().list_user_roles(user_id, company_id=company_id)
    return {"user_id": user_id, "company_id": company_id, "roles": roles}


@router.put("/users/{user_id}/roles", summary="替换用户本项目角色",
            description="整组替换某用户在某公司下的本项目角色。普通角色必须提供 company_id。")
async def put_user_roles(user_id: str, payload: UserRolesUpdateRequest,
                         identity: Identity = Depends(require_module("admin"))) -> dict:
    from fastapi import HTTPException

    normalized_roles = normalize_roles(payload.roles)
    if any(role != ADMIN_ROLE for role in normalized_roles) and not payload.company_id:
        raise HTTPException(status_code=422, detail="普通角色必须绑定 company_id")
    try:
        roles = get_user_service().replace_user_roles(
            user_id,
            company_id=payload.company_id,
            roles=normalized_roles,
            assigned_by=identity.user_id,
        )
        _write_auth_audit_safely(
            event_type="user_roles_replaced",
            actor_id=identity.user_id,
            company_id=payload.company_id or identity.company_id,
            target_type="user",
            target_id=user_id,
            action="replace_roles",
            decision="success",
            detail={"roles": roles, "actor_is_super_admin": identity.is_super_admin},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user_id, "company_id": payload.company_id, "roles": roles}


# ── 角色 → 权限映射配置（前端可视化配权限）──────────────────────────────────
class RolePermissionRequest(BaseModel):
    role_name: str | None = Field(default=None, description="角色展示名，如 公司管理员；role_code 必须为英文稳定码")
    tier: str = Field(description="最高可见报告段落层级：field / expert / management")
    modules: list[str] = Field(default_factory=list, description='可访问模块码数组；["*"]=全部')
    visible_report_sections: list[str] | None = Field(
        default=None,
        description='可见审计报告段落 section_code 数组；["*"]=全部；不传则保留原配置',
    )
    description: str = Field(default="", description="角色说明")


@router.get("/roles", summary="列角色→权限映射 + 可选模块",
            dependencies=[Depends(require_module("admin"))],
            description="返回所有角色的权限映射(DB) + 可配模块全集，供前端权限配置界面渲染。")
async def list_roles() -> dict:
    return {
        "roles": get_user_service().list_role_permissions(),
        "report_sections": get_user_service().list_report_sections(),
        "all_modules": sorted(MODULES),
        "tiers": ["field", "expert", "management"],
    }


@router.put("/roles/{role_code}", summary="配置某角色的权限映射",
            description="建/改角色→权限(tier + modules)。改后立即生效(清授权缓存)。")
async def put_role_permission(role_code: str, payload: RolePermissionRequest,
                              identity: Identity = Depends(require_module("admin"))) -> dict:
    from fastapi import HTTPException

    try:
        role_code = validate_role_code(role_code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.tier not in ("field", "expert", "management"):
        raise HTTPException(status_code=422, detail=f"tier 非法（field/expert/management）：{payload.tier}")
    bad = [m for m in payload.modules if m != "*" and m not in MODULES]
    if bad:
        raise HTTPException(status_code=422, detail=f"未知模块码：{bad}（可选 {sorted(MODULES)} 或 ['*']）")
    if payload.visible_report_sections is not None:
        known_sections = {str(section["section_code"]) for section in get_user_service().list_report_sections()}
        bad_sections = [code for code in payload.visible_report_sections if code != "*" and code not in known_sections]
        if bad_sections:
            raise HTTPException(status_code=422, detail=f"未知报告段落码：{bad_sections}")
    row = get_user_service().upsert_role_permission(
        role_code,
        role_name=payload.role_name,
        tier=payload.tier,
        modules=payload.modules,
        description=payload.description,
    )
    visible_sections = None
    if payload.visible_report_sections is not None:
        visible_sections = get_user_service().replace_role_report_sections(role_code, payload.visible_report_sections)
        row["visible_report_sections"] = visible_sections
    _write_auth_audit_safely(
        event_type="role_permission_changed",
        actor_id=identity.user_id,
        company_id=identity.company_id,
        target_type="role",
        target_id=role_code,
        action="upsert_role_permission",
        decision="success",
        detail={
            "tier": payload.tier,
            "modules": payload.modules,
            "visible_report_sections": visible_sections,
            "actor_is_super_admin": identity.is_super_admin,
        },
    )
    clear_role_permissions_cache()  # 立即生效
    return row
