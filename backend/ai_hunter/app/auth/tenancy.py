"""Tenant and engagement-level access control for annual audits."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator

import psycopg
from fastapi import Depends, HTTPException
from psycopg.rows import dict_row

from ..settings import get_settings
from .identity import Identity, get_current_identity


@dataclass(frozen=True)
class CaseAccessRecord:
    case_id: int
    company_id: str
    owner_id: str = ""
    is_member: bool = False


@dataclass(frozen=True)
class ThreadAccessRecord:
    thread_id: str
    company_id: str
    created_by: str = ""
    case_id: int | None = None
    status: str = "active"


def can_access_case_record(identity: Identity, record: CaseAccessRecord | None) -> bool:
    """Return whether identity can access a case access record."""
    if record is None:
        return False
    if identity.is_super_admin:
        return True
    if not identity.company_id or identity.company_id != record.company_id:
        return False
    if identity.is_company_admin:
        return True
    if not identity.user_id:
        return False
    return record.owner_id == identity.user_id or record.is_member


def can_access_thread_record(
    identity: Identity,
    record: ThreadAccessRecord | None,
    *,
    case_record: CaseAccessRecord | None = None,
) -> bool:
    """Return whether identity can access a thread metadata record."""
    if record is None or record.status == "deleted":
        return False
    if identity.is_super_admin:
        return True
    if not identity.company_id or identity.company_id != record.company_id:
        return False
    if identity.is_company_admin:
        return True
    if not identity.user_id:
        return False
    if record.created_by == identity.user_id:
        return True
    if record.case_id and case_record is not None:
        return can_access_case_record(identity, case_record)
    return False


def can_manage_thread_record(
    identity: Identity,
    record: ThreadAccessRecord | None,
    *,
    case_record: CaseAccessRecord | None = None,
) -> bool:
    """Return whether identity may continue, regenerate, or delete a thread."""
    if not can_access_thread_record(identity, record, case_record=case_record):
        return False
    if identity.is_super_admin or identity.is_company_admin:
        return True
    if record is None or not identity.user_id:
        return False
    if record.created_by == identity.user_id:
        return True
    return case_record is not None and case_record.owner_id == identity.user_id


class TenancyService:
    """Database-backed case/thread access checks."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    def get_case_access_record(self, identity: Identity, case_id: int) -> CaseAccessRecord | None:
        if int(case_id or 0) <= 0:
            return None
        from ai_hunter.annual_audit.access_control import get_engagement_access_record

        row = get_engagement_access_record(identity, case_id)
        if not row:
            return None
        return CaseAccessRecord(
            case_id=int(row["case_id"]),
            company_id=str(row.get("company_id") or ""),
            owner_id=str(row.get("owner_id") or ""),
            is_member=bool(row.get("is_member")),
        )

    def can_access_case(self, identity: Identity, case_id: int) -> bool:
        return can_access_case_record(identity, self.get_case_access_record(identity, case_id))

    def get_thread_access_record(self, thread_id: str) -> ThreadAccessRecord | None:
        tid = str(thread_id or "").strip()
        if not tid:
            return None
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT thread_id, case_id, company_id, created_by, status
                FROM public.thread_metadata
                WHERE thread_id = %s
                """,
                (tid,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return ThreadAccessRecord(
            thread_id=str(row["thread_id"]),
            case_id=int(row["case_id"]) if row["case_id"] is not None else None,
            company_id=str(row["company_id"] or ""),
            created_by=str(row["created_by"] or ""),
            status=str(row["status"] or "active"),
        )

    def can_access_thread(self, identity: Identity, thread_id: str) -> bool:
        thread = self.get_thread_access_record(thread_id)
        case_record = None
        if thread and thread.case_id:
            case_record = self.get_case_access_record(identity, thread.case_id)
        return can_access_thread_record(identity, thread, case_record=case_record)

    def can_manage_thread(self, identity: Identity, thread_id: str) -> bool:
        thread = self.get_thread_access_record(thread_id)
        case_record = None
        if thread and thread.case_id:
            case_record = self.get_case_access_record(identity, thread.case_id)
        return can_manage_thread_record(identity, thread, case_record=case_record)

    def ensure_thread_for_invoke(
        self,
        identity: Identity,
        thread_id: str,
        case_id: int,
        *,
        allow_unbound: bool = False,
    ) -> ThreadAccessRecord:
        """Authorize an existing thread or register a new case-bound thread."""
        tid = str(thread_id or "").strip()
        requested_case_id = int(case_id or 0)
        existing = self.get_thread_access_record(tid)
        if existing is not None:
            if requested_case_id > 0 and existing.case_id not in (None, requested_case_id):
                raise HTTPException(status_code=409, detail="会话已绑定其他年审项目，不能重新绑定")
            if not self.can_manage_thread(identity, tid):
                raise HTTPException(status_code=403, detail="无权限继续运行该会话")
            if requested_case_id > 0 and existing.case_id is None:
                return self.bind_thread_case(identity, tid, requested_case_id)
            return existing

        if requested_case_id <= 0 and not allow_unbound:
            raise HTTPException(status_code=400, detail="新会话必须绑定有效 current_case_id")
        case_record = None
        if requested_case_id > 0:
            case_record = self.get_case_access_record(identity, requested_case_id)
            if not can_access_case_record(identity, case_record):
                raise HTTPException(status_code=403, detail="无权限访问该年审项目")
        if not identity.user_id:
            raise HTTPException(status_code=403, detail="当前身份缺少 user_id，不能创建会话")
        if not identity.company_id and not identity.is_super_admin:
            raise HTTPException(status_code=403, detail="当前身份缺少 company_id，不能创建会话")

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.thread_metadata (
                    thread_id, case_id, company_id, created_by, status
                ) VALUES (%s, %s, %s, %s, 'active')
                ON CONFLICT (thread_id) DO NOTHING
                """,
                (
                    tid,
                    requested_case_id if requested_case_id > 0 else None,
                    case_record.company_id if case_record else identity.company_id,
                    identity.user_id,
                ),
            )
            conn.commit()

        created = self.get_thread_access_record(tid)
        if created is None:
            raise HTTPException(status_code=503, detail="会话租户信息写入失败")
        if requested_case_id > 0 and created.case_id != requested_case_id:
            raise HTTPException(status_code=409, detail="会话已绑定其他年审项目，不能重新绑定")
        created_case = self.get_case_access_record(identity, created.case_id) if created.case_id else None
        if not can_manage_thread_record(identity, created, case_record=created_case):
            raise HTTPException(status_code=403, detail="无权限继续运行该会话")
        return created

    def bind_thread_case(self, identity: Identity, thread_id: str, case_id: int) -> ThreadAccessRecord:
        """Bind an identity-owned unbound thread after deterministic case creation."""
        tid = str(thread_id or "").strip()
        target_case_id = int(case_id or 0)
        if not tid or target_case_id <= 0:
            raise HTTPException(status_code=400, detail="会话和年审项目编号必须有效")
        existing = self.get_thread_access_record(tid)
        if existing is None or not can_manage_thread_record(identity, existing):
            raise HTTPException(status_code=403, detail="无权限绑定该会话")
        if existing.case_id not in (None, target_case_id):
            raise HTTPException(status_code=409, detail="会话已绑定其他年审项目，不能重新绑定")
        case_record = self.get_case_access_record(identity, target_case_id)
        if not can_access_case_record(identity, case_record):
            raise HTTPException(status_code=403, detail="无权限绑定新建年审项目")
        if existing.case_id is None:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.thread_metadata
                    SET case_id = %s, updated_at = now()
                    WHERE thread_id = %s AND case_id IS NULL AND status = 'active'
                    """,
                    (target_case_id, tid),
                )
                conn.commit()
        bound = self.get_thread_access_record(tid)
        if bound is None or bound.case_id != target_case_id:
            raise HTTPException(status_code=409, detail="会话年审项目绑定失败")
        return bound

    def update_thread_metadata(self, thread_id: str, *, last_intent: str = "", title: str = "") -> None:
        """Refresh non-authoritative display metadata without changing ownership."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.thread_metadata
                SET last_intent = %s,
                    title = CASE WHEN %s <> '' THEN %s ELSE title END,
                    updated_at = now()
                WHERE thread_id = %s AND status = 'active'
                """,
                (last_intent, title, title, thread_id),
            )
            conn.commit()

    def list_accessible_thread_ids(self, identity: Identity, *, case_id: int | None = None) -> list[str]:
        """Return active thread ids visible under the annual engagement ACL."""
        from ai_hunter.annual_audit.access_control import list_accessible_engagement_ids

        accessible_ids = list_accessible_engagement_ids(identity)
        if case_id is not None:
            accessible_ids = [item for item in accessible_ids if item == case_id]
        params: list[object] = []
        clauses = ["status = 'active'"]
        if not identity.is_super_admin:
            clauses.append("company_id = %s")
            params.append(identity.company_id)
            if not identity.is_company_admin:
                if accessible_ids:
                    placeholders = ", ".join(["%s"] * len(accessible_ids))
                    clauses.append(f"(created_by = %s OR case_id IN ({placeholders}))")
                    params.extend([identity.user_id, *accessible_ids])
                else:
                    clauses.append("created_by = %s")
                    params.append(identity.user_id)
        if case_id is not None:
            clauses.append("case_id = %s")
            params.append(case_id)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT thread_id FROM public.thread_metadata
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, thread_id
                """,
                params,
            )
            return [str(row["thread_id"]) for row in cur.fetchall()]


def _raise_tenancy_unavailable(exc: Exception) -> None:
    raise HTTPException(
        status_code=503,
        detail=(
            "年度审计租户数据表尚不可用，请检查外置 PostgreSQL 并运行年度审计迁移。"
        ),
    ) from exc


@lru_cache(maxsize=1)
def get_tenancy_service() -> TenancyService:
    return TenancyService(dsn=get_settings().postgres_checkpointer_dsn)


def require_case_access(case_id: int, identity: Identity = Depends(get_current_identity)) -> Identity:
    """FastAPI dependency helper for routes that already expose case_id."""
    if not get_settings().auth_enabled:
        return identity
    try:
        allowed = get_tenancy_service().can_access_case(identity, case_id)
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn) as exc:
        _raise_tenancy_unavailable(exc)
    if not allowed:
        raise HTTPException(status_code=403, detail="无权限访问该年审项目")
    return identity


def require_thread_access(thread_id: str, identity: Identity = Depends(get_current_identity)) -> Identity:
    """FastAPI dependency helper for routes that already expose thread_id."""
    if not get_settings().auth_enabled:
        return identity
    try:
        allowed = get_tenancy_service().can_access_thread(identity, thread_id)
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn) as exc:
        _raise_tenancy_unavailable(exc)
    if not allowed:
        raise HTTPException(status_code=403, detail="无权限访问该会话")
    return identity


def require_thread_manage(thread_id: str, identity: Identity = Depends(get_current_identity)) -> Identity:
    """FastAPI dependency helper for thread mutation routes."""
    if not get_settings().auth_enabled:
        return identity
    try:
        allowed = get_tenancy_service().can_manage_thread(identity, thread_id)
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn) as exc:
        _raise_tenancy_unavailable(exc)
    if not allowed:
        raise HTTPException(status_code=403, detail="无权限管理该会话")
    return identity
