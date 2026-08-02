"""授权层（Tier 3）：角色 → 可见报告段落 audience + 可访问模块。

角色是**用户中心**的全局概念（来自 JWT），但「角色能在不良资产里看什么」这套**映射归本项目**。
默认映射写代码常量，可用 env `AUTH_ROLE_PERMISSIONS`（JSON）整体覆盖，业务口径回来再调。

- 报告段落分权：audience 层级 field ⊂ expert ⊂ management（高层级看全）。
- 模块级分权：report/drilldown/review/progress/corrections/deadline/graph/admin。
"""

from __future__ import annotations

import json
import logging

from fastapi import Depends, HTTPException

from ..settings import get_settings
from .identity import ADMIN_ROLE, Identity, get_current_identity
from .roles import canonical_role_code, report_sections_from_seed, role_permissions_from_seed

LOGGER = logging.getLogger(__name__)

# audience 由低到高；用户可见 = 其角色最高 tier 及以下全部。
AUDIENCE_ORDER = ["field", "expert", "management"]

# 模块码（与路由分组对应）
MODULES = {"report", "drilldown", "review", "progress", "corrections", "deadline", "graph", "admin"}
_ALL = sorted(MODULES)

# 进程内缓存（授权每请求都查，避免每次打库）。改角色权限后调 clear_role_permissions_cache()。
_PERM_CACHE: dict[str, dict] = {}


def _env_role_permissions() -> dict[str, dict] | None:
    raw = (get_settings().auth_role_permissions or "").strip()
    if not raw:
        return None
    try:
        override = json.loads(raw)
        if isinstance(override, dict) and override:
            return {canonical_role_code(str(k)): v for k, v in override.items()}
    except (json.JSONDecodeError, ValueError) as exc:
        LOGGER.warning("AUTH_ROLE_PERMISSIONS 解析失败，忽略: %s", str(exc)[:120])
    return None


def _role_permissions() -> dict[str, dict]:
    """角色→权限映射，三级回退：DB(app_role_permission) → env JSON → 代码默认。带进程内缓存。"""
    if "perms" in _PERM_CACHE:
        return _PERM_CACHE["perms"]
    perms: dict[str, dict] = {}
    try:
        from ..services.user_service import get_user_service

        perms = get_user_service().list_role_permissions()
    except Exception as exc:  # noqa: BLE001 — 库不可达 → 回退 env/默认
        LOGGER.warning("load_role_permissions_from_db_failed: %s", str(exc)[:120])
    if not perms:
        perms = _env_role_permissions() or role_permissions_from_seed()
    _PERM_CACHE["perms"] = perms
    return perms


def _report_sections() -> list[dict]:
    """报告段落目录，优先 DB，回退 seed。"""
    if "report_sections" in _PERM_CACHE:
        return _PERM_CACHE["report_sections"]
    sections: list[dict] = []
    try:
        from ..services.user_service import get_user_service

        sections = get_user_service().list_report_sections()
    except Exception as exc:  # noqa: BLE001 — 库不可达 → 回退 seed
        LOGGER.warning("load_report_sections_from_db_failed: %s", str(exc)[:120])
    if not sections:
        sections = report_sections_from_seed()
    _PERM_CACHE["report_sections"] = sections
    return sections


def clear_role_permissions_cache() -> None:
    """改角色权限后清缓存（PUT /roles/{code} 调用）。多 worker 下各自重载/重启生效。"""
    _PERM_CACHE.pop("perms", None)
    _PERM_CACHE.pop("report_sections", None)


def _tier_audiences(tier: str) -> set[str]:
    """某 tier 可见的 audience 集合（该 tier 及以下）。"""
    if tier not in AUDIENCE_ORDER:
        return {"field"}
    return set(AUDIENCE_ORDER[: AUDIENCE_ORDER.index(tier) + 1])


def visible_audiences(identity: Identity) -> set[str]:
    """该身份可见的报告段落 audience 集合（多角色取并集；admin 看全）。"""
    if identity.is_admin:
        return set(AUDIENCE_ORDER)
    perms = _role_permissions()
    out: set[str] = set()
    for role in identity.roles:
        cfg = perms.get(canonical_role_code(role))
        if cfg:
            out |= _tier_audiences(str(cfg.get("tier", "field")))
    return out or {"field"}  # 无匹配角色 → 最低可见，避免越权


def all_report_section_codes() -> set[str]:
    return {str(section.get("section_code") or "") for section in _report_sections() if section.get("section_code")}


def report_section_code_for_id(section_id: str) -> str | None:
    sid = str(section_id or "")
    for section in _report_sections():
        if str(section.get("section_id") or "") == sid:
            return str(section.get("section_code") or "") or None
    return None


def visible_report_sections(identity: Identity) -> set[str]:
    """该身份可见的审计报告 section_code 集合；多角色取并集。"""
    all_codes = all_report_section_codes()
    if identity.is_admin:
        return set(all_codes)
    perms = _role_permissions()
    out: set[str] = set()
    for role in identity.roles:
        cfg = perms.get(canonical_role_code(role))
        if not cfg:
            continue
        configured = cfg.get("visible_report_sections", [])
        if configured == "*" or (isinstance(configured, list) and "*" in configured):
            out |= all_codes
        elif isinstance(configured, list):
            out |= {str(code) for code in configured if str(code) in all_codes}
    if out:
        return out

    # 迁移兜底：角色尚未配置 section_code 时，按旧 audience 层级换算，避免上线瞬间无报告。
    audiences = visible_audiences(identity)
    return {
        str(section.get("section_code"))
        for section in _report_sections()
        if section.get("section_code") and section.get("audience") in audiences
    }


def allowed_modules(identity: Identity) -> set[str]:
    if identity.is_admin:
        return set(MODULES)
    perms = _role_permissions()
    out: set[str] = set()
    for role in identity.roles:
        cfg = perms.get(canonical_role_code(role))
        if not cfg:
            continue
        mods = cfg.get("modules", [])
        if mods == "*" or (isinstance(mods, list) and "*" in mods):
            out |= set(MODULES)
        else:
            out |= {m for m in mods if m in MODULES}
    return out


def has_module(identity: Identity, module: str) -> bool:
    return identity.is_admin or module in allowed_modules(identity)


def has_any_module(identity: Identity, modules: list[str] | tuple[str, ...] | set[str]) -> bool:
    return identity.is_admin or bool(allowed_modules(identity) & {m for m in modules if m in MODULES})


def require_module(module: str):
    """依赖工厂：无该模块权限 → 403。AUTH_ENABLED=false 时 identity 为 admin，恒放行。"""
    def _dep(identity: Identity = Depends(get_current_identity)) -> Identity:
        if not has_module(identity, module):
            raise HTTPException(status_code=403, detail=f"无权限访问模块：{module}")
        return identity
    return _dep


def require_any_module(modules: list[str] | tuple[str, ...] | set[str]):
    """依赖工厂：至少具备一个模块权限才放行。"""
    required = [m for m in modules if m in MODULES]

    def _dep(identity: Identity = Depends(get_current_identity)) -> Identity:
        if not has_any_module(identity, required):
            raise HTTPException(status_code=403, detail=f"无权限访问模块：{','.join(required)}")
        return identity

    return _dep
