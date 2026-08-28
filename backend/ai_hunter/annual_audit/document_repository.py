"""Annual document-category queries backed only by the isolated platform DB."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .engagement_repository import get_engagement
from .storage import mysql_connection, postgres_connection
from .workpaper_case import case_workpaper_category_codes, get_case_workpaper_summary


_STRUCTURED_TABLES = {
    "trial_balance": "annual_account_balance",
    "journal_entries": "annual_journal_entry_line",
    "receivables": "annual_receivable_item",
    "bank_statements": "annual_bank_transaction",
}

_FILE_HINTS = {
    "financial_statements": ("财务报表", "资产负债表", "利润表", "现金流量表", "附注"),
    "trial_balance": ("科目余额", "余额表", "trialbalance"),
    "journal_entries": ("序时账", "总账", "明细账", "凭证", "journal"),
    "receivables": ("应收", "往来", "receivable"),
    "bank_statements": ("银行流水", "对账单", "bankstatement"),
    "revenue_support": ("销售合同", "发票", "出库", "签收", "验收"),
    "confirmations": ("函证", "询证函", "回函"),
    "tax_materials": ("纳税", "增值税", "所得税", "税务"),
    "audit_workpapers": ("底稿", "审计程序", "复核"),
}


def list_doc_categories(*, settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        rows = connection.execute(
            """
            SELECT code, name, COALESCE(description, '') AS description,
                   sort_order, enabled, fields
            FROM public.doc_category_catalog
            WHERE enabled = TRUE
            ORDER BY sort_order, code
            """
        ).fetchall()
    return {"categories": [dict(row) for row in rows]}


def _structured_record_counts(engagement_id: int, settings: Settings) -> dict[str, int]:
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM annual_account_balance WHERE engagement_id = %s) AS trial_balance,
                  (SELECT COUNT(*) FROM annual_journal_entry_line WHERE engagement_id = %s) AS journal_entries,
                  (SELECT COUNT(*) FROM annual_receivable_item WHERE engagement_id = %s) AS receivables,
                  (SELECT COUNT(*) FROM annual_bank_transaction WHERE engagement_id = %s) AS bank_statements
                """,
                (engagement_id, engagement_id, engagement_id, engagement_id),
            )
            row = dict(cursor.fetchone())
    return {key: int(value or 0) for key, value in row.items()}


def get_case_doc_categories(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    get_engagement(engagement_id, settings=resolved)
    record_counts = _structured_record_counts(engagement_id, resolved)
    case_workpaper = get_case_workpaper_summary(engagement_id, settings=resolved)
    case_covered_categories = case_workpaper_category_codes(case_workpaper)
    with postgres_connection(resolved) as connection:
        rows = connection.execute(
            """
            SELECT c.code, c.name,
                   COUNT(DISTINCT link.file_id) AS file_count,
                   MAX(sf.updated_at) AS last_uploaded_at
            FROM public.doc_category_catalog c
            LEFT JOIN public.source_file_doc_category link
              ON link.category_code = c.code AND link.case_id = %s
            LEFT JOIN public.source_file sf
              ON sf.id = link.file_id AND sf.status = 'active'
            WHERE c.enabled = TRUE
            GROUP BY c.code, c.name, c.sort_order
            ORDER BY c.sort_order, c.code
            """,
            (engagement_id,),
        ).fetchall()
    categories = []
    missing = []
    for row in rows:
        code = str(row["code"])
        file_count = int(row["file_count"] or 0)
        record_count = int(record_counts.get(code, 0))
        raw_uploaded = file_count > 0 or record_count > 0
        covered_by_case_workpaper = code in case_covered_categories
        uploaded = raw_uploaded or covered_by_case_workpaper
        if not uploaded:
            missing.append(code)
        categories.append(
            {
                "code": code,
                "name": row["name"],
                "uploaded": uploaded,
                "raw_uploaded": raw_uploaded,
                "covered_by_case_workpaper": covered_by_case_workpaper,
                "coverage_basis": (
                    "uploaded" if raw_uploaded else "case_workpaper" if covered_by_case_workpaper else "missing"
                ),
                "file_count": file_count,
                "record_count": record_count,
                "last_uploaded_at": (
                    row["last_uploaded_at"].isoformat()
                    if row["last_uploaded_at"]
                    else None
                ),
            }
        )
    return {
        "case_id": engagement_id,
        "categories": categories,
        "missing_categories": missing,
    }


def _hinted_category(file_name: str) -> str | None:
    normalized = Path(file_name).name.lower().replace(" ", "")
    for code, hints in _FILE_HINTS.items():
        if any(hint.lower().replace(" ", "") in normalized for hint in hints):
            return code
    return None


def validate_doc_category(
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    engagement_id = int(payload.get("case_id") or 0)
    if engagement_id > 0:
        get_engagement(engagement_id, settings=resolved)
    category = str(payload.get("doc_category") or "").strip()
    file_names = [str(item).strip() for item in payload.get("file_names") or [] if str(item).strip()]
    with postgres_connection(resolved) as connection:
        category_row = connection.execute(
            "SELECT code, name FROM public.doc_category_catalog WHERE code = %s AND enabled = TRUE",
            (category,),
        ).fetchone()
        if not category_row:
            return {
                "ok": False,
                "suspected_mismatch": True,
                "suspected_duplicate": False,
                "duplicate_files": [],
                "suspected_mismatch_files": file_names,
                "message": f"未知年审资料类别：{category}",
            }
        duplicate_files: list[str] = []
        if engagement_id > 0 and file_names:
            duplicate_rows = connection.execute(
                """
                SELECT DISTINCT file_name
                FROM public.source_file
                WHERE case_id = %s AND status = 'active' AND file_name = ANY(%s)
                """,
                (engagement_id, file_names),
            ).fetchall()
            duplicate_files = [str(row["file_name"]) for row in duplicate_rows]
    mismatch_files = [
        name
        for name in file_names
        if (hinted := _hinted_category(name)) is not None and hinted != category
    ]
    mismatch = bool(mismatch_files)
    return {
        "ok": not mismatch,
        "suspected_mismatch": mismatch,
        "suspected_duplicate": bool(duplicate_files),
        "content_check_performed": bool(file_names or payload.get("text_preview")),
        "duplicate_files": duplicate_files,
        "suspected_mismatch_files": mismatch_files,
        "message": (
            f"部分文件名更像其他年审资料类别：{', '.join(mismatch_files)}"
            if mismatch
            else f"已按“{category_row['name']}”完成独立年审资料预校验。"
        ),
    }


__all__ = ["get_case_doc_categories", "list_doc_categories", "validate_doc_category"]
