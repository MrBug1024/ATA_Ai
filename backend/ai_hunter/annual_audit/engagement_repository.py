"""MySQL repository for annual-audit engagements."""

from __future__ import annotations

from datetime import date, datetime
from secrets import token_hex
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .storage import mysql_connection


class EngagementNotFoundError(LookupError):
    pass


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _case_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": int(row["id"]),
        "case_name": row["name"],
        "case_type": "年度财务报表审计",
        "entity_name": row["entity_name"],
        "status": row["status"],
        "task_count": int(row.get("task_count") or 0),
        "pending_task_count": int(row.get("pending_task_count") or 0),
        "company_id": row.get("company_id") or "",
        "owner_id": row.get("owner_user_id") or "",
        "created_by": row.get("created_by") or "",
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "engagement_code": row["engagement_code"],
        "fiscal_year": int(row["fiscal_year"]),
        "period_start": _iso(row["period_start"]),
        "period_end": _iso(row["period_end"]),
    }


def list_engagements(
    *,
    keyword: str | None = None,
    case_type: str | None = None,
    status: str | None = None,
    company_id: str | None = None,
    user_id: str | None = None,
    is_company_admin: bool = False,
    is_super_admin: bool = False,
    page: int = 1,
    page_size: int = 20,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size

    where = ["e.deleted_at IS NULL"]
    params: list[Any] = []
    if keyword and keyword.strip():
        where.append("(e.name LIKE %s OR e.entity_name LIKE %s OR e.engagement_code LIKE %s)")
        pattern = f"%{keyword.strip()}%"
        params.extend([pattern, pattern, pattern])
    if case_type and case_type not in {
        "年度财务报表审计",
        "annual_financial_statement_audit",
    }:
        where.append("1 = 0")
    if status:
        where.append("e.status = %s")
        params.append(status)
    if company_id and not is_super_admin:
        where.append("e.company_id = %s")
        params.append(company_id)
    if user_id and not (is_company_admin or is_super_admin):
        where.append(
            """
            (
              e.owner_user_id = %s
              OR EXISTS (
                SELECT 1 FROM ata_project_member pm
                WHERE pm.engagement_id = e.id AND pm.user_id = %s
              )
            )
            """
        )
        params.extend([user_id, user_id])

    where_sql = " AND ".join(where)
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) AS total FROM audit_engagement e WHERE {where_sql}",
                tuple(params),
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""
                SELECT e.*,
                       COUNT(t.id) AS task_count,
                       SUM(t.status IN ('待执行', '进行中', '逾期')) AS pending_task_count
                FROM audit_engagement e
                LEFT JOIN annual_task t
                  ON t.engagement_id = e.id AND t.deleted_at IS NULL
                WHERE {where_sql}
                GROUP BY e.id
                ORDER BY e.updated_at DESC, e.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, page_size, offset]),
            )
            rows = list(cursor.fetchall())

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "cases": [_case_item(row) for row in rows],
    }


def create_engagement(
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    name = str(payload.get("case_name") or "").strip()
    entity_name = str(payload.get("entity_name") or "").strip()
    if not name:
        raise ValueError("case_name 不能为空")
    if not entity_name:
        raise ValueError("entity_name 不能为空")

    fiscal_year = int(payload.get("fiscal_year") or (date.today().year - 1))
    period_start = date(fiscal_year, 1, 1)
    period_end = date(fiscal_year, 12, 31)
    company_id = str(payload.get("company_id") or "").strip()
    owner_user_id = str(payload.get("owner_id") or payload.get("created_by") or "").strip()
    created_by = str(payload.get("created_by") or owner_user_id or "system").strip()
    entity_uscc = str(payload.get("entity_uscc") or "").strip() or None

    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM audit_engagement
                WHERE deleted_at IS NULL
                  AND fiscal_year = %s
                  AND entity_name = %s
                  AND company_id = %s
                  AND (%s IS NULL OR entity_uscc = %s)
                ORDER BY id DESC
                LIMIT 1
                """,
                (fiscal_year, entity_name, company_id, entity_uscc, entity_uscc),
            )
            existing = cursor.fetchone()
            if existing:
                return {
                    "case_id": int(existing["id"]),
                    "message": f"复用已有年审项目：{existing['name']}",
                    "deduplicated": True,
                }

            engagement_code = f"AUD-{fiscal_year}-{token_hex(4).upper()}"
            cursor.execute(
                """
                INSERT INTO audit_engagement (
                  engagement_code, name, engagement_type, entity_name, entity_uscc,
                  fiscal_year, period_start, period_end, status,
                  company_id, owner_user_id, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'planning', %s, %s, %s)
                """,
                (
                    engagement_code,
                    name,
                    "annual_financial_statement_audit",
                    entity_name,
                    entity_uscc,
                    fiscal_year,
                    period_start,
                    period_end,
                    company_id,
                    owner_user_id,
                    created_by,
                ),
            )
            engagement_id = int(cursor.lastrowid)
            if owner_user_id:
                cursor.execute(
                    """
                    INSERT INTO ata_project_member (engagement_id, user_id, role_code)
                    VALUES (%s, %s, 'engagement_owner')
                    ON DUPLICATE KEY UPDATE role_code = VALUES(role_code)
                    """,
                    (engagement_id, owner_user_id),
                )
        connection.commit()

    return {
        "case_id": engagement_id,
        "message": f"已创建年审项目：{name}",
        "deduplicated": False,
    }


def get_engagement(case_id: int, *, settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM audit_engagement WHERE id = %s AND deleted_at IS NULL",
                (case_id,),
            )
            row = cursor.fetchone()
    if not row:
        raise EngagementNotFoundError(f"年审项目 {case_id} 不存在")
    return dict(row)


def get_engagement_profile(
    case_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    row = get_engagement(case_id, settings=settings)
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  EXISTS(SELECT 1 FROM annual_account_balance WHERE engagement_id = %s) AS account_balance,
                  EXISTS(SELECT 1 FROM annual_journal_entry_line WHERE engagement_id = %s) AS journal_entries,
                  EXISTS(SELECT 1 FROM annual_bank_transaction WHERE engagement_id = %s) AS bank_statements,
                  EXISTS(SELECT 1 FROM annual_receivable_item WHERE engagement_id = %s) AS receivable_ledger
                """,
                (case_id, case_id, case_id, case_id),
            )
            readiness = dict(cursor.fetchone())
    case = _case_item(row)
    entity = {
        "entity_id": int(row["id"]),
        "engagement_id": int(row["id"]),
        "entity_name": row["entity_name"],
        "uscc": row.get("entity_uscc"),
        "entity_role": "被审计单位",
    }
    return {
        "case": case,
        "audited_entity": entity,
        "annual_audit": {
            "engagement_code": row["engagement_code"],
            "engagement_type": row["engagement_type"],
            "entity_name": row["entity_name"],
            "entity_uscc": row.get("entity_uscc"),
            "fiscal_year": int(row["fiscal_year"]),
            "period_start": _iso(row["period_start"]),
            "period_end": _iso(row["period_end"]),
            "status": row["status"],
        },
        "data_completeness": {
            "engagement_profile": True,
            "financial_statements": False,
            "trial_balance": bool(readiness["account_balance"]),
            "general_ledger": False,
            "journal_entries": bool(readiness["journal_entries"]),
            "bank_statements": bool(readiness["bank_statements"]),
            "receivable_ledger": bool(readiness["receivable_ledger"]),
        },
    }


def get_full_context(case_id: int, *, settings: Settings | None = None) -> dict[str, Any]:
    profile = get_engagement_profile(case_id, settings=settings)
    return {
        "case_id": case_id,
        "case": profile["case"],
        "audited_entity": profile["audited_entity"],
        "engine_results": {
            "annual_audit": {
                "engagement": profile["annual_audit"],
                "data_completeness": profile["data_completeness"],
                "supported_cycles": ["sales_receivables", "cash_and_bank"],
            }
        },
        "whiteglove": {},
        "fund_flow": {},
        "annual_audit": profile["annual_audit"],
        "data_completeness": profile["data_completeness"],
    }
