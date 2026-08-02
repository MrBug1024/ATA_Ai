"""用户投影 + 人员标签 + 本地角色服务（Tier 3）。

标签归不良资产本地（用户中心未上线前在本项目维护）。表见 sql/auth_tables.sql。
v2-A 起角色来源逐步切到 app_user_role；JWT/dev header roles 只做迁移期回退。
纯数据层，不调 LLM。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Iterator
import hashlib
import re

import psycopg
from psycopg.rows import dict_row

from ..settings import get_settings
from ..auth.roles import (
    ADMIN_ROLE,
    canonical_role_code,
    default_company_from_seed,
    normalize_roles,
    report_sections_from_seed,
    role_display_name,
    validate_role_code,
)

# 多选维度（存 app_user_tag 多行）；单值维度 company/region 存 app_user 主表。
MULTI_DIMENSIONS = ("project_role", "title", "expertise")

def normalize_company_name(name: str) -> str:
    """Normalize company names before uniqueness and deterministic id generation."""
    value = (name or "").strip()
    value = value.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", " ", value)


def normalize_login_identifier(value: str) -> str:
    """Normalize private-mode login identifiers."""
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def build_company_id(company_name: str) -> str:
    """Build stable company_id from normalized company name."""
    normalized = normalize_company_name(company_name)
    if not normalized:
        raise ValueError("company_name 不能为空")
    return "co_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class UserService:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    # ── 公司 / 机构目录（v2-A 私有化身份底座）──────────────────────────────
    def list_companies(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        sql = (
            "SELECT company_id, company_name, company_name_norm, company_type, status, notes, "
            "created_at, updated_at FROM public.app_company"
        )
        params: tuple[Any, ...] = ()
        if not include_disabled:
            sql += " WHERE status <> %s"
            params = ("disabled",)
        sql += " ORDER BY company_name"
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def get_company(self, company_id: str) -> dict[str, Any] | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT company_id, company_name, company_name_norm, company_type, status, notes, "
                "created_at, updated_at FROM public.app_company WHERE company_id=%s",
                (company_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def upsert_company(self, *, company_name: str, company_id: str | None = None,
                       company_type: str = "customer", status: str = "active",
                       notes: str = "") -> dict[str, Any]:
        company_name_norm = normalize_company_name(company_name)
        if not company_name_norm:
            raise ValueError("company_name 不能为空")
        cid = company_id or build_company_id(company_name_norm)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.app_company "
                "(company_id, company_name, company_name_norm, company_type, status, notes) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (company_id) DO UPDATE SET company_name=EXCLUDED.company_name, "
                "company_name_norm=EXCLUDED.company_name_norm, company_type=EXCLUDED.company_type, "
                "status=EXCLUDED.status, notes=EXCLUDED.notes, updated_at=now() RETURNING *",
                (cid, company_name_norm, company_name_norm, company_type, status, notes),
            )
            row = dict(cur.fetchone())
            conn.commit()
        return row

    def _company_name_for_id(self, company_id: str) -> str:
        if not company_id:
            return ""
        company = self.get_company(company_id)
        return str((company or {}).get("company_name") or "")

    def list_users(self, *, company_id: str = "", status: str = "", limit: int = 200) -> list[dict[str, Any]]:
        sql = (
            "SELECT u.*, c.company_name AS company_display_name "
            "FROM public.app_user u "
            "LEFT JOIN public.app_company c ON c.company_id = u.company_id "
            "WHERE 1=1"
        )
        params: list[Any] = []
        if company_id:
            sql += " AND u.company_id=%s"
            params.append(company_id)
        if status:
            sql += " AND u.status=%s"
            params.append(status)
        sql += " ORDER BY u.created_at DESC, u.user_id LIMIT %s"
        params.append(max(1, min(limit, 1000)))
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def upsert_user(self, user_id: str, *, username: str | None = None,
                    company: str | None = None, region: str | None = None,
                    note: str | None = None, company_id: str | None = None,
                    auth_source: str | None = None, status: str | None = None,
                    is_super_admin: bool | None = None) -> dict[str, Any]:
        """建/更新用户投影（只更新传入字段）。"""
        if not user_id:
            raise ValueError("user_id 不能为空")
        if is_super_admin is not True and company_id is not None and not company_id:
            raise ValueError("私有化普通用户 / 公司管理员必须绑定 company_id")
        if is_super_admin is not True and company_id:
            company_row = self.get_company(company_id)
            if not company_row:
                raise ValueError(f"company_id 不存在：{company_id}")
            if company is None:
                company = str(company_row.get("company_name") or "")
        sets = {k: v for k, v in
                {
                    "username": username,
                    "company": company,
                    "region": region,
                    "note": note,
                    "company_id": company_id,
                    "auth_source": auth_source,
                    "status": status,
                    "is_super_admin": is_super_admin,
                }.items()
                if v is not None}
        cols = ["user_id"] + list(sets)
        vals = [user_id] + list(sets.values())
        ph = ", ".join(["%s"] * len(cols))
        update = ", ".join(f"{k}=EXCLUDED.{k}" for k in sets) + (", " if sets else "") + "updated_at=now()"
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO public.app_user ({', '.join(cols)}) VALUES ({ph}) "
                f"ON CONFLICT (user_id) DO UPDATE SET {update} RETURNING *",
                vals,
            )
            row = cur.fetchone()
            conn.commit()
        return dict(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM public.app_user WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    # ── 私有化本地凭证（v2-A）───────────────────────────────────────────────
    def set_local_password(self, user_id: str, *, login_identifier: str,
                           password_hash: str, password_algo: str = "argon2id") -> None:
        login_norm = normalize_login_identifier(login_identifier)
        if not login_norm:
            raise ValueError("login_identifier 不能为空")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM public.app_user WHERE user_id=%s", (user_id,))
            if cur.fetchone() is None:
                raise ValueError(f"user_id 不存在：{user_id}")
            cur.execute(
                "INSERT INTO public.local_user_credential "
                "(user_id, login_identifier, login_identifier_norm, password_hash, password_algo, "
                "password_updated_at, failed_login_count, locked_until) "
                "VALUES (%s,%s,%s,%s,%s,now(),0,NULL) "
                "ON CONFLICT (user_id) DO UPDATE SET login_identifier=EXCLUDED.login_identifier, "
                "login_identifier_norm=EXCLUDED.login_identifier_norm, password_hash=EXCLUDED.password_hash, "
                "password_algo=EXCLUDED.password_algo, password_updated_at=now(), "
                "failed_login_count=0, locked_until=NULL, updated_at=now()",
                (user_id, login_identifier, login_norm, password_hash, password_algo),
            )
            conn.commit()

    def get_local_login_record(self, login_identifier: str) -> dict[str, Any] | None:
        login_norm = normalize_login_identifier(login_identifier)
        if not login_norm:
            return None
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT u.user_id, u.username, u.company_id, u.auth_source, u.status, u.is_super_admin, "
                "c.login_identifier, c.login_identifier_norm, c.password_hash, c.password_algo, "
                "c.failed_login_count, c.locked_until "
                "FROM public.local_user_credential c "
                "JOIN public.app_user u ON u.user_id = c.user_id "
                "WHERE c.login_identifier_norm=%s",
                (login_norm,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def get_local_credential_by_user_id(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT u.user_id, u.username, u.company_id, u.auth_source, u.status, u.is_super_admin, "
                "c.login_identifier, c.login_identifier_norm, c.password_hash, c.password_algo, "
                "c.failed_login_count, c.locked_until "
                "FROM public.local_user_credential c "
                "JOIN public.app_user u ON u.user_id = c.user_id "
                "WHERE c.user_id=%s",
                (user_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def record_login_success(self, user_id: str) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE public.local_user_credential SET failed_login_count=0, locked_until=NULL, updated_at=now() "
                "WHERE user_id=%s",
                (user_id,),
            )
            cur.execute("UPDATE public.app_user SET last_login_at=now(), updated_at=now() WHERE user_id=%s", (user_id,))
            conn.commit()

    def record_login_failure(self, login_identifier: str, *, threshold: int, lock_minutes: int) -> None:
        login_norm = normalize_login_identifier(login_identifier)
        if not login_norm:
            return
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT failed_login_count FROM public.local_user_credential WHERE login_identifier_norm=%s",
                (login_norm,),
            )
            row = cur.fetchone()
            if row is None:
                return
            failed = int(row["failed_login_count"] or 0) + 1
            locked_until = None
            if failed >= threshold:
                locked_until = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)
            cur.execute(
                "UPDATE public.local_user_credential SET failed_login_count=%s, locked_until=%s, updated_at=now() "
                "WHERE login_identifier_norm=%s",
                (failed, locked_until, login_norm),
            )
            conn.commit()

    def set_tags(self, user_id: str, dimension: str, values: list[str]) -> list[str]:
        """整维替换某用户某多选维度的标签（先删后插）。返回最终值列表。"""
        if dimension not in MULTI_DIMENSIONS:
            raise ValueError(f"invalid dimension: {dimension}")
        default_company = default_company_from_seed()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.app_user (user_id, company_id, company) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (user_id, default_company["company_id"], default_company["company_name"]),
            )
            cur.execute("DELETE FROM public.app_user_tag WHERE user_id=%s AND dimension=%s", (user_id, dimension))
            for v in dict.fromkeys(values):  # 去重保序
                cur.execute(
                    "INSERT INTO public.app_user_tag (user_id, dimension, tag_value) VALUES (%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (user_id, dimension, v),
                )
            conn.commit()
        return list(dict.fromkeys(values))

    def get_tags(self, user_id: str) -> dict[str, Any]:
        """返回该用户全部标签：多选维度 + 主表单值（company/region）。"""
        user = self.get_user(user_id) or {}
        out: dict[str, Any] = {d: [] for d in MULTI_DIMENSIONS}
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT dimension, tag_value FROM public.app_user_tag WHERE user_id=%s ORDER BY id",
                (user_id,),
            )
            for r in cur.fetchall():
                out.setdefault(r["dimension"], []).append(r["tag_value"])
        out["company"] = user.get("company", "")
        out["region"] = user.get("region", "")
        return out

    # ── 用户 → 项目角色（v2-A 私有化 / 多租户底座）─────────────────────────
    def list_user_roles(self, user_id: str, *, company_id: str = "") -> list[str]:
        """返回用户在本项目的角色；company_id 为空时返回该用户所有公司内角色。"""
        sql = "SELECT role_code FROM public.app_user_role WHERE user_id=%s"
        params: list[Any] = [user_id]
        if company_id:
            sql += " AND (company_id=%s OR role_code=%s)"
            params.extend([company_id, ADMIN_ROLE])
        sql += " ORDER BY role_code"
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return normalize_roles([str(r["role_code"]) for r in cur.fetchall()])

    def replace_user_roles(self, user_id: str, *, company_id: str, roles: list[str],
                           assigned_by: str = "") -> list[str]:
        """整组替换某用户在某公司下的项目角色。普通角色必须绑定 company_id。"""
        clean_roles = normalize_roles([r.strip() for r in roles])
        if any(role != ADMIN_ROLE for role in clean_roles) and not company_id:
            raise ValueError("普通角色必须绑定 company_id")
        company_name = self._company_name_for_id(company_id)
        if any(role != ADMIN_ROLE for role in clean_roles) and not company_name:
            raise ValueError(f"company_id 不存在：{company_id}")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.app_user (user_id, company_id, company) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (user_id, company_id, company_name),
            )
            cur.execute(
                "DELETE FROM public.app_user_role WHERE user_id=%s AND company_id=%s",
                (user_id, company_id),
            )
            for role in clean_roles:
                cur.execute(
                    "INSERT INTO public.app_user_role (user_id, company_id, role_code, assigned_by) "
                    "VALUES (%s,%s,%s,%s)",
                    (user_id, company_id, role, assigned_by),
                )
            conn.commit()
        return clean_roles

    def write_auth_audit_log(self, *, event_type: str, actor_id: str = "", company_id: str = "",
                             target_type: str = "", target_id: str = "", action: str = "",
                             decision: str = "", detail: dict[str, Any] | None = None) -> None:
        """写权限审计日志。DDL 未执行时调用方应决定是否失败或降级。"""
        import json as _json

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.auth_audit_log "
                "(event_type, actor_id, company_id, target_type, target_id, action, decision, detail) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (
                    event_type,
                    actor_id,
                    company_id,
                    target_type,
                    target_id,
                    action,
                    decision,
                    _json.dumps(detail or {}, ensure_ascii=False),
                ),
            )
            conn.commit()

    # ── 角色 → 权限映射（前端/运营可配）────────────────────────────────────
    def list_report_sections(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        """返回审计报告段落目录，供前端权限配置和过滤逻辑使用。"""
        sql = (
            "SELECT section_code, section_id, title, audience, sort_order, status, description, "
            "created_at, updated_at FROM public.app_report_section"
        )
        params: tuple[Any, ...] = ()
        if not include_disabled:
            sql += " WHERE status <> %s"
            params = ("disabled",)
        sql += " ORDER BY sort_order, section_id, section_code"
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        except psycopg.errors.UndefinedTable:
            sections = report_sections_from_seed()
            if include_disabled:
                return sections
            return [section for section in sections if section.get("status") != "disabled"]

    def upsert_report_section(self, *, section_code: str, section_id: str, title: str,
                              audience: str = "field", sort_order: int = 0,
                              status: str = "active", description: str = "") -> dict[str, Any]:
        """创建/更新审计报告段落目录。section_code 是权限判断主键。"""
        section_code = (section_code or "").strip()
        section_id = (section_id or "").strip()
        if not section_code or not section_id:
            raise ValueError("section_code/section_id 不能为空")
        if audience not in ("field", "expert", "management"):
            raise ValueError(f"invalid audience: {audience}")
        if status not in ("active", "disabled"):
            raise ValueError(f"invalid status: {status}")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.app_report_section "
                "(section_code, section_id, title, audience, sort_order, status, description) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (section_code) DO UPDATE SET section_id=EXCLUDED.section_id, "
                "title=EXCLUDED.title, audience=EXCLUDED.audience, sort_order=EXCLUDED.sort_order, "
                "status=EXCLUDED.status, description=EXCLUDED.description, updated_at=now() RETURNING *",
                (section_code, section_id, title, audience, sort_order, status, description),
            )
            row = dict(cur.fetchone())
            conn.commit()
        return row

    def replace_role_report_sections(self, role_code: str, section_codes: list[str]) -> list[str]:
        """整组替换某角色可见审计报告段落；['*'] 表示所有 active 段。"""
        role_code = validate_role_code(role_code)
        clean_codes = [str(code).strip() for code in section_codes if str(code).strip()]
        if "*" in clean_codes:
            sections = self.list_report_sections()
            clean_codes = [str(section["section_code"]) for section in sections]
        clean_codes = list(dict.fromkeys(clean_codes))
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM public.app_role_permission WHERE role_code=%s", (role_code,))
            if cur.fetchone() is None:
                raise ValueError(f"role_code 不存在：{role_code}")
            for section_code in clean_codes:
                cur.execute("SELECT 1 FROM public.app_report_section WHERE section_code=%s", (section_code,))
                if cur.fetchone() is None:
                    raise ValueError(f"section_code 不存在：{section_code}")
            cur.execute("DELETE FROM public.app_role_report_section WHERE role_code=%s", (role_code,))
            for section_code in clean_codes:
                cur.execute(
                    "INSERT INTO public.app_role_report_section (role_code, section_code) "
                    "VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (role_code, section_code),
                )
            conn.commit()
        return clean_codes

    def _list_role_permissions_base(self) -> dict[str, dict]:
        """旧表结构回退：只读 role_permission，不读段落授权表。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT role_code, tier, modules, description, "
                "COALESCE(role_name, '') AS role_name FROM public.app_role_permission"
            )
            rows = cur.fetchall()
        return {
            canonical_role_code(str(r["role_code"])): {
                "role_name": r.get("role_name") or role_display_name(str(r["role_code"])),
                "tier": r["tier"],
                "modules": r["modules"],
                "visible_report_sections": [],
                "description": r.get("description", ""),
            }
            for r in rows
        }

    def list_role_permissions(self) -> dict[str, dict]:
        """返回 {role_code: {tier, modules, visible_report_sections, description}}，供授权层读取。"""
        try:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT p.role_code, p.tier, p.modules, p.description, COALESCE(p.role_name, '') AS role_name, "
                    "COALESCE(jsonb_agg(rs.section_code ORDER BY rs.sort_order, rs.section_id) "
                    "FILTER (WHERE rs.section_code IS NOT NULL), '[]'::jsonb) AS visible_report_sections "
                    "FROM public.app_role_permission p "
                    "LEFT JOIN public.app_role_report_section rrs ON rrs.role_code = p.role_code "
                    "LEFT JOIN public.app_report_section rs ON rs.section_code = rrs.section_code "
                    "AND rs.status <> 'disabled' "
                    "GROUP BY p.role_code, p.tier, p.modules, p.description, p.role_name"
                )
                rows = cur.fetchall()
        except psycopg.errors.UndefinedTable:
            return self._list_role_permissions_base()
        return {
            canonical_role_code(str(r["role_code"])): {
                "role_name": r.get("role_name") or role_display_name(str(r["role_code"])),
                "tier": r["tier"],
                "modules": r["modules"],
                "visible_report_sections": list(r.get("visible_report_sections") or []),
                "description": r.get("description", ""),
            }
            for r in rows
        }

    def upsert_role_permission(self, role_code: str, *, tier: str,
                               modules: list[str], description: str = "",
                               role_name: str | None = None) -> dict[str, Any]:
        """建/改一个角色的权限映射。tier∈{field,expert,management}；modules 数组，["*"]=全部。"""
        role_code = validate_role_code(role_code)
        role_name = role_name if role_name is not None else role_display_name(role_code)
        if tier not in ("field", "expert", "management"):
            raise ValueError(f"invalid tier: {tier}")
        import json as _json
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.app_role_permission (role_code, role_name, tier, modules, description) "
                "VALUES (%s,%s,%s,%s::jsonb,%s) "
                "ON CONFLICT (role_code) DO UPDATE SET tier=EXCLUDED.tier, modules=EXCLUDED.modules, "
                "role_name=EXCLUDED.role_name, description=EXCLUDED.description, updated_at=now() RETURNING *",
                (role_code, role_name, tier, _json.dumps(modules), description),
            )
            row = dict(cur.fetchone())
            conn.commit()
        return row

    def upsert_tag_catalog_item(self, *, dimension: str, tag_value: str,
                                tag_group: str = "", sort_order: int = 0) -> dict[str, Any]:
        """Create/update one tag catalog item."""
        if not dimension or not tag_value:
            raise ValueError("dimension/tag_value 不能为空")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.app_tag_catalog (dimension, tag_value, tag_group, sort_order) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (dimension, tag_value) DO UPDATE SET "
                "tag_group=EXCLUDED.tag_group, sort_order=EXCLUDED.sort_order RETURNING *",
                (dimension, tag_value, tag_group, sort_order),
            )
            row = dict(cur.fetchone())
            conn.commit()
        return row

    def list_catalog(self, dimension: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT dimension, tag_value, tag_group, sort_order FROM public.app_tag_catalog"
        params: tuple = ()
        if dimension:
            sql += " WHERE dimension=%s"
            params = (dimension,)
        sql += " ORDER BY dimension, sort_order, tag_value"
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


@lru_cache(maxsize=1)
def get_user_service() -> UserService:
    return UserService(dsn=get_settings().postgres_checkpointer_dsn)
