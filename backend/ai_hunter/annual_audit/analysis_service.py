"""MySQL-backed deterministic annual-audit analysis orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .deterministic_analysis import (
    analyze_cash_transactions,
    analyze_receivables,
    analyze_revenue_journal,
)
from .engagement_repository import EngagementNotFoundError, get_engagement
from .storage import mysql_connection


_READINESS_DATASETS = (
    ("trial_balance", "科目余额表", "account_balance_rows", "annual_account_balance"),
    ("journal_entries", "序时账/凭证明细", "journal_entry_rows", "annual_journal_entry_line"),
    ("receivables", "应收账款明细", "receivable_rows", "annual_receivable_item"),
    ("bank_statements", "银行流水", "bank_transaction_rows", "annual_bank_transaction"),
)

ANALYSIS_RULES_VERSION = "2026-08-03-v2"

_DERIVED_SOURCE_HINTS = (
    "审定表",
    "抽查表",
    "检查表",
    "截止性测试",
    "审计程序",
    "底稿",
    "汇总表",
    "测算表",
)
_PARTIAL_SOURCE_HINTS = (
    "工资",
    "调整明细",
    "营业外收入明细",
    "营业外支出明细",
)


def _source_quality(file_names: list[str]) -> str:
    """Classify imported rows without overstating derived or partial evidence."""

    if not file_names:
        return "unknown"
    derived = [any(hint in name for hint in _DERIVED_SOURCE_HINTS) for name in file_names]
    partial = [any(hint in name for hint in _PARTIAL_SOURCE_HINTS) for name in file_names]
    if all(derived):
        return "derived"
    if all(partial):
        return "partial"
    if any(derived) or any(partial):
        return "mixed"
    return "source"


def _source_file_names(cursor, *, case_id: int, table_name: str) -> list[str]:
    cursor.execute(
        f"""
        SELECT DISTINCT JSON_UNQUOTE(JSON_EXTRACT(source_locator_json, '$.file_name')) AS file_name
        FROM {table_name}
        WHERE engagement_id = %s
        ORDER BY file_name
        LIMIT 50
        """,
        (case_id,),
    )
    return [
        str(row.get("file_name") or "").strip()
        for row in cursor.fetchall()
        if str(row.get("file_name") or "").strip()
    ]


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _loads_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def data_readiness(case_id: int, *, settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    engagement = get_engagement(case_id, settings=resolved)
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM annual_account_balance WHERE engagement_id = %s) AS account_balance_rows,
                  (SELECT COUNT(*) FROM annual_journal_entry_line WHERE engagement_id = %s) AS journal_entry_rows,
                  (SELECT COUNT(*) FROM annual_receivable_item WHERE engagement_id = %s) AS receivable_rows,
                  (SELECT COUNT(*) FROM annual_bank_transaction WHERE engagement_id = %s) AS bank_transaction_rows,
                  (SELECT COUNT(*) FROM annual_import_batch WHERE engagement_id = %s AND status = 'completed') AS completed_imports
                """,
                (case_id, case_id, case_id, case_id, case_id),
            )
            counts = dict(cursor.fetchone())
            source_files = {
                code: _source_file_names(cursor, case_id=case_id, table_name=table_name)
                for code, _label, count_key, table_name in _READINESS_DATASETS
                if int(counts.get(count_key) or 0) > 0
            }
    counts = {key: int(value or 0) for key, value in counts.items()}
    quality_labels = {
        "source": "原始/标准化源数据",
        "partial": "局部源数据",
        "derived": "派生审计底稿数据",
        "mixed": "原始、局部或派生数据混合",
        "unknown": "来源待核实",
    }
    supplemental_labels = {
        "trial_balance": "原始科目余额表（当前数据来源仍需核验）",
        "journal_entries": "全年、全科目的完整原始序时账/凭证明细",
        "receivables": "原始应收账款明细、账龄及客户主数据",
        "bank_statements": "完整原始银行流水、对账单及回单",
    }
    available_data: list[dict[str, Any]] = []
    supplemental_required_data: list[str] = []
    for code, label, count_key, _table_name in _READINESS_DATASETS:
        row_count = counts[count_key]
        if row_count <= 0:
            continue
        files = source_files.get(code, [])
        quality = _source_quality(files)
        limitation = ""
        if quality == "derived":
            limitation = "当前结构化记录来自审计底稿，适合案例分析，不替代原始账务资料。"
        elif quality == "partial":
            limitation = "当前仅覆盖局部科目或业务范围，不能代表全年完整数据。"
        elif quality in {"mixed", "unknown"}:
            limitation = "需继续核验来源范围和完整性。"
        if quality != "source":
            supplemental_required_data.append(supplemental_labels[code])
        available_data.append(
            {
                "code": code,
                "name": label,
                "row_count": row_count,
                "source_quality": quality,
                "quality_label": quality_labels[quality],
                "source_files": files,
                "limitation": limitation,
            }
        )
    return {
        "case_id": case_id,
        "engagement_code": engagement["engagement_code"],
        "entity_name": engagement["entity_name"],
        "fiscal_year": int(engagement["fiscal_year"]),
        "period_end": engagement["period_end"].isoformat(),
        "counts": counts,
        "ready_for_sales_receivables": (
            counts["receivable_rows"] > 0 or counts["journal_entry_rows"] > 0
        ),
        "sales_receivables_complete": (
            counts["receivable_rows"] > 0 and counts["journal_entry_rows"] > 0
        ),
        "ready_for_cash_and_bank": counts["bank_transaction_rows"] > 0,
        "available_data": available_data,
        "available_required_data": [item["name"] for item in available_data],
        "missing_required_data": [
            label
            for key, label in (
                ("account_balance_rows", "科目余额表"),
                ("journal_entry_rows", "序时账/凭证明细"),
                ("receivable_rows", "应收账款明细"),
                ("bank_transaction_rows", "银行流水"),
            )
            if counts[key] == 0
        ],
        "supplemental_required_data": supplemental_required_data,
    }


def _input_version(cursor, case_id: int, analysis_type: str) -> str:
    cursor.execute(
        """
        SELECT COALESCE(MAX(id), 0) AS max_batch_id, COUNT(*) AS batch_count,
               COALESCE(SUM(row_count), 0) AS imported_rows
        FROM annual_import_batch
        WHERE engagement_id = %s AND status = 'completed'
        """,
        (case_id,),
    )
    payload = {
        "case_id": case_id,
        "analysis_type": analysis_type,
        "analysis_rules_version": ANALYSIS_RULES_VERSION,
        **dict(cursor.fetchone()),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default).encode("utf-8")
    ).hexdigest()


def _cached_result(cursor, case_id: int, analysis_type: str, input_version: str):
    cursor.execute(
        """
        SELECT id, result_json
        FROM annual_analysis_run
        WHERE engagement_id = %s AND analysis_type = %s
          AND input_version = %s AND status = 'completed'
        ORDER BY id DESC LIMIT 1
        """,
        (case_id, analysis_type, input_version),
    )
    row = cursor.fetchone()
    if not row:
        return None
    result = _loads_json(row["result_json"])
    result["analysis_run_id"] = int(row["id"])
    result["cached"] = True
    return result


def _persist_result(
    cursor,
    *,
    case_id: int,
    analysis_type: str,
    input_version: str,
    parameters: dict[str, Any],
    result: dict[str, Any],
) -> int:
    cursor.execute(
        """
        INSERT INTO annual_analysis_run (
          engagement_id, analysis_type, input_version, status,
          parameters_json, result_json, created_by, completed_at
        ) VALUES (%s, %s, %s, 'completed', %s, %s, 'ai_agent', NOW(6))
        """,
        (
            case_id,
            analysis_type,
            input_version,
            json.dumps(parameters, ensure_ascii=False, default=_json_default),
            json.dumps(result, ensure_ascii=False, default=_json_default),
        ),
    )
    run_id = int(cursor.lastrowid)
    for finding in result.get("findings", []):
        cursor.execute(
            """
            INSERT INTO annual_finding (
              engagement_id, analysis_run_id, finding_type, risk_level,
              title, description, amount, evidence_refs_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                case_id,
                run_id,
                finding["finding_type"],
                finding["risk_level"],
                finding["title"],
                finding["description"],
                finding.get("amount"),
                json.dumps(finding.get("evidence_refs", []), ensure_ascii=False, default=_json_default),
            ),
        )
    return run_id


def run_sales_receivables(
    case_id: int,
    *,
    recompute: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    engagement = get_engagement(case_id, settings=resolved)
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            input_version = _input_version(cursor, case_id, "sales_receivables")
            if not recompute and (cached := _cached_result(cursor, case_id, "sales_receivables", input_version)):
                return cached
            cursor.execute(
                """
                SELECT id, customer_name, document_no, occurrence_date, due_date,
                       balance, currency, is_related_party, source_locator_json
                FROM annual_receivable_item
                WHERE engagement_id = %s
                ORDER BY ABS(balance) DESC, id
                """,
                (case_id,),
            )
            rows = [
                {**dict(row), "source_locator_json": _loads_json(row.get("source_locator_json")), "domain_row_type": "receivable_item"}
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT id, voucher_date, voucher_no, line_no, account_code,
                       account_name, debit_amount, credit_amount, counterparty,
                       description, source_locator_json
                FROM annual_journal_entry_line
                WHERE engagement_id = %s
                  AND (
                    account_name LIKE '%%主营业务收入%%'
                    OR account_name LIKE '%%其他业务收入%%'
                    OR account_name LIKE '%%营业收入%%'
                  )
                ORDER BY voucher_date, voucher_no, line_no, id
                """,
                (case_id,),
            )
            revenue_rows = [
                {
                    **dict(row),
                    "source_locator_json": _loads_json(row.get("source_locator_json")),
                    "domain_row_type": "journal_entry_line",
                }
                for row in cursor.fetchall()
            ]
            if not rows and not revenue_rows:
                return {
                    "status": "needs_data",
                    "case_id": case_id,
                    "analysis_type": "sales_receivables",
                    "missing_required_data": ["应收账款明细", "含收入科目的序时账/凭证明细"],
                    "findings": [],
                }
            receivables_result = (
                analyze_receivables(rows, as_of=engagement["period_end"])
                if rows
                else {"status": "needs_data", "row_count": 0, "findings": []}
            )
            revenue_result = (
                analyze_revenue_journal(revenue_rows, period_end=engagement["period_end"])
                if revenue_rows
                else {"status": "needs_data", "row_count": 0, "findings": []}
            )
            result = {
                "status": "completed",
                "case_id": case_id,
                "analysis_type": "sales_receivables",
                "receivables": receivables_result,
                "revenue": revenue_result,
                "findings": [
                    *(receivables_result.get("findings") or []),
                    *(revenue_result.get("findings") or []),
                ],
                "missing_required_data": [
                    label
                    for available, label in (
                        (bool(rows), "应收账款明细"),
                        (bool(revenue_rows), "含收入科目的序时账/凭证明细"),
                    )
                    if not available
                ],
            }
            run_id = _persist_result(
                cursor,
                case_id=case_id,
                analysis_type="sales_receivables",
                input_version=input_version,
                parameters={"as_of": engagement["period_end"]},
                result=result,
            )
        connection.commit()
    result.update({"analysis_run_id": run_id, "cached": False})
    return result


def run_cash_and_bank(
    case_id: int,
    *,
    large_amount_threshold: Decimal = Decimal("1000000"),
    recompute: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    engagement = get_engagement(case_id, settings=resolved)
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            input_version = _input_version(cursor, case_id, "cash_and_bank")
            if not recompute and (cached := _cached_result(cursor, case_id, "cash_and_bank", input_version)):
                return cached
            cursor.execute(
                """
                SELECT id, bank_account, transaction_date, amount, direction,
                       counterparty, transaction_ref, description, running_balance,
                       source_locator_json
                FROM annual_bank_transaction
                WHERE engagement_id = %s
                ORDER BY transaction_date, id
                """,
                (case_id,),
            )
            rows = [
                {**dict(row), "source_locator_json": _loads_json(row.get("source_locator_json")), "domain_row_type": "bank_transaction"}
                for row in cursor.fetchall()
            ]
            if not rows:
                return {
                    "status": "needs_data",
                    "case_id": case_id,
                    "analysis_type": "cash_and_bank",
                    "missing_required_data": ["银行流水"],
                    "findings": [],
                }
            result = analyze_cash_transactions(
                rows,
                period_end=engagement["period_end"],
                large_amount_threshold=large_amount_threshold,
            )
            result.update({"status": "completed", "case_id": case_id, "analysis_type": "cash_and_bank"})
            run_id = _persist_result(
                cursor,
                case_id=case_id,
                analysis_type="cash_and_bank",
                input_version=input_version,
                parameters={
                    "period_end": engagement["period_end"],
                    "large_amount_threshold": large_amount_threshold,
                },
                result=result,
            )
        connection.commit()
    result.update({"analysis_run_id": run_id, "cached": False})
    return result


__all__ = [
    "EngagementNotFoundError",
    "_source_quality",
    "data_readiness",
    "run_cash_and_bank",
    "run_sales_receivables",
]
