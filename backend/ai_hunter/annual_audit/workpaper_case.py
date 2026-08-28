"""Case-workpaper replay support for a complete annual-audit example.

The customer supplied workbook is an audit workpaper pack, not a raw ledger
export.  It must therefore stay out of the source-fact tables, while still
being available as a first-class, traceable evidence package when the user is
replaying the supplied case.  This module owns that distinction.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from ai_hunter.app.settings import Settings, get_settings

from .storage import mysql_connection, postgres_connection


CASE_WORKPAPER_SOURCE_TYPE = "audit_workpaper_pack"
CASE_WORKPAPER_VERSION = "case-replay-v1"

# These are the workpaper indexes found in the supplied 296-sheet case.  A
# match means that the package contains evidence for the procedure; it does
# not mean that a new engagement may skip professional judgement.
PROGRAM_SHEET_HINTS: dict[str, tuple[str, ...]] = {
    "A1": ("B07业务承接", "B08业务保持", "基础信息"),
    "A2": ("B07业务承接", "B08业务保持", "基础信息", "文件送达签收单"),
    "A3": ("重要性水平", "C38总体审计策略", "C24 -01", "C24-02"),
    "A4": ("C24 -01", "资产负债趋势", "利润表趋势", "比率趋势"),
    "A5": ("C24-02", "C24-03", "C24-04"),
    "F1": ("F1-1", "F1-2", "F1-3", "F1-4", "F1-5", "F1-6"),
    "F2": ("C5-1", "C5-2", "C5-3", "C5-4", "C5-5"),
    "F3": ("C1-2", "C1-7", "C1-8", "C1-9", "C1-10"),
    "C5": ("D5-1", "D5-2", "D5-3", "D5-4", "D5-5"),
    "C6": ("D5-1", "D5-2", "D5-5", "D6-1", "D6-2", "D6-3"),
    "C9": ("C9-1", "C9-2", "C9-3", "C9-4", "C9-5", "C9-19"),
    "C10": ("C9-1", "C9-5", "C9-7", "C9-14", "C9-15", "C9-19"),
    "D8": ("D8-1", "D8-2", "D8-3", "工资", "职工薪酬明细表"),
    "D9": ("D9-1", "D9-2", "D9-3", "D9-9", "F18-1", "F18-2"),
    "C1": ("C1-1", "C1-2", "C1-3", "C1-6", "C1-7", "C1-8"),
    "C2": ("C1-7", "C1-8", "C1-9", "C1-10"),
    "C21": ("C21-1-1", "C21-1-2", "C21-1-3", "C21-1-5", "C21-1-6", "C21-1-9"),
    "C22": ("C22-1", "C22-2", "C22-3", "C22-4"),
    "G1": ("关联方", "C24-03", "客户基本情况"),
    "G2": ("D9-1", "D9-2", "F18-1", "F18-2"),
    "G3": ("C24 -01", "C24-03", "C2-", "C17-", "F14-"),
    "G4": ("C24-03", "客户基本情况"),
    "G5": ("C24-03", "C1-9", "C1-10"),
    "G6": ("C24-03", "C38总体审计策略", "审计小结"),
    "G7": ("单独资产", "单独负债", "单独利润", "单独现金流量表", "单独所有者权益变动表"),
    "G8": ("调整分录", "重分类", "列报调整汇总表", "未更正错报汇总表"),
    "A12": ("与客户交换意见", "审计小结", "三级复核"),
    "A13": ("工作底稿索引", "三级复核", "审计小结"),
}

CATEGORY_SHEET_HINTS: dict[str, tuple[str, ...]] = {
    "financial_statements": ("单独资产", "单独负债", "单独利润", "单独现金流量表", "单独所有者权益变动表"),
    "trial_balance": ("资产表(年末数)", "负债及权益表(年末数)", "利润表(本年数)"),
    "journal_entries": ("调整分录", "重分类", "现金流量表调整分录"),
    "receivables": ("C5-2", "C8-1-2", "应收"),
    "bank_statements": ("C1-2", "C1-7", "C1-8", "C1-9", "C1-10"),
    "revenue_support": ("F1-1", "F1-2", "F1-3", "F1-4", "F1-5", "F1-6"),
    "confirmations": ("C1-7", "C5-4", "函证"),
    "tax_materials": ("D9-", "F18-", "税", "所得税"),
    "audit_workpapers": ("工作底稿索引", "三级复核", "审计小结"),
    "engagement_acceptance": ("B07业务承接", "B08业务保持", "基础信息", "文件送达签收单"),
    "governance_minutes": ("与客户交换意见", "C24-03", "客户基本情况"),
    "general_ledger": ("审定表", "审计程序", "调整分录", "资产表(年末数)"),
    "accounts_payable": ("D5-1", "D5-2", "D5-3", "D5-4", "D5-5", "D6-2"),
    "purchase_support": ("D5-3", "D5-4", "D5-5", "C9-7", "固定资产增加"),
    "inventory_records": ("C9-1", "C9-2", "C9-5", "C9-8", "C9-9", "C9-10", "C9-17", "C9-18"),
    "inventory_count": ("C9-3", "C9-4", "C9-6", "C21-1-6", "C1-3"),
    "payroll_hr": ("D8-1", "D8-2", "D8-3", "工资", "职工薪酬明细表"),
    "fixed_assets": ("C21-1", "C21-2", "C22-", "C26-", "C29-"),
    "asset_rights": ("C21-1-7", "C21-1-9", "C21-1-10"),
    "related_parties": ("关联方", "C24-03"),
    "legal_contingencies": ("C24-03", "诉讼", "或有"),
    "subsequent_events": ("C24-03", "C1-9", "C1-10"),
    "going_concern": ("C24-03", "C38总体审计策略", "审计小结"),
    "adjustments": ("调整分录", "重分类", "列报调整汇总表", "未更正错报汇总表"),
    "management_representation": ("三级复核", "与客户交换意见", "今创发文审批单"),
    "other": ("封皮", "首页", "使用说明", "与审核组沟通"),
}

_ERROR_TOKENS = ("#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A")
_CONCLUSION_TOKENS = ("审计结论", "审定数", "未见异常", "核对一致", "√")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _sheet_text(sheet: Any) -> tuple[list[list[Any]], str, int, int]:
    rows: list[list[Any]] = []
    nonempty_cells = 0
    for row in sheet.rows:
        values = list(row)
        if any(value not in (None, "") for value in values):
            rows.append(values)
            nonempty_cells += sum(value not in (None, "") for value in values)
    text = "\n".join(" | ".join(_text(value) for value in row) for row in rows)
    return rows, text, len(rows), nonempty_cells


def _key_figures(name: str, rows: list[list[Any]]) -> list[dict[str, Any]]:
    labels = ("资产总计", "负债合计", "股东权益合计", "营业收入", "营业利润", "净利润", "货币资金合计", "合计")
    figures: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=1):
        row_text = " | ".join(_text(value) for value in row)
        if not any(label in row_text for label in labels):
            continue
        values = [_text(value) for value in row if value not in (None, "")]
        if values:
            figures.append({"row_number": row_number, "values": values[:24]})
    return figures[:8]


def summarize_workpaper_sheets(
    sheets: Iterable[Any],
    *,
    file_name: str = "",
) -> dict[str, Any]:
    """Create a compact, JSON-safe index of a customer workpaper workbook."""

    summaries: list[dict[str, Any]] = []
    names: list[str] = []
    formula_error_samples: list[dict[str, Any]] = []
    nonempty_row_count = 0
    nonempty_cell_count = 0
    for index, sheet in enumerate(sheets):
        name = _text(getattr(sheet, "name", ""))
        rows, text, row_count, cell_count = _sheet_text(sheet)
        names.append(name)
        nonempty_row_count += row_count
        nonempty_cell_count += cell_count
        errors = [token for token in _ERROR_TOKENS if token in text]
        if errors and len(formula_error_samples) < 20:
            formula_error_samples.append({"sheet_name": name, "tokens": errors})
        summaries.append(
            {
                "name": name,
                "sheet_index": index,
                "nonempty_row_count": row_count,
                "nonempty_cell_count": cell_count,
                "has_conclusion": any(token in text for token in _CONCLUSION_TOKENS),
                "has_formula_error": bool(errors),
                "key_figures": _key_figures(name, rows),
            }
        )

    def matches(hints: tuple[str, ...]) -> list[str]:
        return [name for name in names if any(hint in name for hint in hints)]

    covered_categories = {
        code: matching
        for code, hints in CATEGORY_SHEET_HINTS.items()
        if (matching := matches(hints))
    }
    program_evidence: dict[str, dict[str, Any]] = {}
    for code, hints in PROGRAM_SHEET_HINTS.items():
        matching = matches(hints)
        matching_set = set(matching)
        required_hint_count = len(hints)
        matched_hint_count = sum(1 for hint in hints if any(hint in name for name in matching_set))
        program_evidence[code] = {
            "sheet_names": matching[:30],
            "matched_hint_count": matched_hint_count,
            "required_hint_count": required_hint_count,
            "coverage_ratio": round(matched_hint_count / required_hint_count, 3) if required_hint_count else 0,
            "has_evidence": bool(matching),
            "has_conclusion": any(
                item["name"] in matching_set and item["has_conclusion"]
                for item in summaries
            ),
        }

    is_case_pack = (
        len(names) >= 100
        and any(name.startswith("C1-") for name in names)
        and any(name.startswith("F1-") for name in names)
        and any("三级复核" in name for name in names)
    )
    return {
        "version": CASE_WORKPAPER_VERSION,
        "file_name": file_name,
        "case_pack_type": "full_annual_audit_case" if is_case_pack else "audit_workpaper_pack",
        "is_complete_case": is_case_pack,
        "sheet_count": len(names),
        "nonempty_sheet_count": sum(1 for item in summaries if item["nonempty_row_count"]),
        "nonempty_row_count": nonempty_row_count,
        "nonempty_cell_count": nonempty_cell_count,
        "sheet_names": names,
        "sheets": summaries,
        "covered_categories": covered_categories,
        "program_evidence": program_evidence,
        "formula_error_count": sum(1 for item in summaries if item["has_formula_error"]),
        "formula_error_samples": formula_error_samples,
    }


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value if value is not None else fallback


def get_case_workpaper_summary(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, source_ref, source_sha256, row_count, metadata_json,
                       created_at, completed_at
                FROM annual_import_batch
                WHERE engagement_id = %s AND source_type = %s AND status = 'completed'
                ORDER BY id DESC LIMIT 1
                """,
                (engagement_id, CASE_WORKPAPER_SOURCE_TYPE),
            )
            row = cursor.fetchone()
    if not row:
        return None
    payload = dict(_loads(row.get("metadata_json"), {}))
    payload.update(
        {
            "import_batch_id": int(row.get("id") or 0),
            "source_ref": str(row.get("source_ref") or ""),
            "source_sha256": str(row.get("source_sha256") or ""),
            "row_count": int(row.get("row_count") or 0),
            "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
            "completed_at": row.get("completed_at").isoformat() if row.get("completed_at") else None,
        }
    )
    return payload


def persist_case_workpaper_summary(
    *,
    engagement_id: int,
    source_ref: str,
    source_sha256: str,
    summary: dict[str, Any],
    created_by: str,
    settings: Settings,
) -> dict[str, Any]:
    """Persist a replay index without projecting the workbook into raw facts."""

    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, row_count, metadata_json
                FROM annual_import_batch
                WHERE engagement_id = %s AND source_type = %s
                  AND source_sha256 = %s AND source_ref = %s AND status = 'completed'
                ORDER BY id DESC LIMIT 1
                """,
                (engagement_id, CASE_WORKPAPER_SOURCE_TYPE, source_sha256, source_ref),
            )
            existing = cursor.fetchone()
            if existing:
                return {"import_batch_id": int(existing["id"]), "deduplicated": True, **_loads(existing.get("metadata_json"), summary)}
            cursor.execute(
                """
                INSERT INTO annual_import_batch (
                  engagement_id, source_ref, source_type, source_sha256,
                  status, row_count, metadata_json, created_by, completed_at
                ) VALUES (%s, %s, %s, %s, 'completed', %s, %s, %s, NOW(6))
                """,
                (
                    engagement_id,
                    source_ref,
                    CASE_WORKPAPER_SOURCE_TYPE,
                    source_sha256,
                    int(summary.get("nonempty_row_count") or 0),
                    json.dumps(summary, ensure_ascii=False),
                    created_by or "ai_agent",
                ),
            )
            batch_id = int(cursor.lastrowid)
        connection.commit()
    return {"import_batch_id": batch_id, "deduplicated": False, **summary}


def case_workpaper_category_codes(summary: dict[str, Any] | None) -> set[str]:
    return set((summary or {}).get("covered_categories") or {})


def case_workpaper_program_evidence(
    summary: dict[str, Any] | None,
    procedure_code: str,
) -> dict[str, Any]:
    return dict(((summary or {}).get("program_evidence") or {}).get(procedure_code) or {})


def _page_refs_for_workbook(
    engagement_id: int,
    *,
    summary: dict[str, Any],
    settings: Settings,
) -> dict[str, dict[str, Any]]:
    file_name = str(summary.get("file_name") or "")
    if not file_name:
        return {}
    with postgres_connection(settings) as connection:
        rows = connection.execute(
            """
            SELECT sf.id AS file_id, sf.file_name, sp.id AS page_id, sp.page_no,
                   sp.ocr_blocks
            FROM public.source_file sf
            JOIN public.source_page sp ON sp.file_id = sf.id
            WHERE sf.case_id = %s AND sf.status = 'active' AND sf.file_name = %s
            ORDER BY sp.page_no
            """,
            (engagement_id, file_name),
        ).fetchall()
    refs: dict[str, dict[str, Any]] = {}
    for row in rows:
        blocks = row.get("ocr_blocks") or []
        for block in blocks if isinstance(blocks, list) else []:
            sheet_name = str(block.get("sheet_name") or "").strip() if isinstance(block, dict) else ""
            if sheet_name and sheet_name not in refs:
                refs[sheet_name] = {
                    "source_file_id": int(row["file_id"]),
                    "source_page_id": int(row["page_id"]),
                    "source_locator": {
                        "sheet_name": sheet_name,
                        "page_no": int(row["page_no"]),
                        "row_start": 1,
                    },
                }
    return refs


def sync_case_workpaper_programs(
    engagement_id: int,
    *,
    actor_user_id: str = "case_workpaper_import",
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Bind the case pack to controlled programs as replay evidence.

    This is deliberately gated by ``is_complete_case``.  A random historical
    workpaper upload cannot silently complete a live engagement.
    """

    resolved = settings or get_settings()
    summary = get_case_workpaper_summary(engagement_id, settings=resolved)
    if not summary or not bool(summary.get("is_complete_case")):
        return summary
    page_refs = _page_refs_for_workbook(engagement_id, summary=summary, settings=resolved)
    changed = 0
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM annual_engagement_policy_binding WHERE engagement_id = %s AND binding_status = 'frozen' ORDER BY id DESC LIMIT 1",
                (engagement_id,),
            )
            binding = cursor.fetchone()
            binding_id = int(binding["id"]) if binding else None
            cursor.execute(
                "SELECT * FROM annual_audit_program_item WHERE engagement_id = %s ORDER BY id",
                (engagement_id,),
            )
            programs = [dict(row) for row in cursor.fetchall()]
            for program in programs:
                code = str(program.get("procedure_code") or "")
                evidence = case_workpaper_program_evidence(summary, code)
                if not evidence.get("has_evidence"):
                    continue
                refs = []
                for sheet_name in evidence.get("sheet_names") or []:
                    ref = page_refs.get(str(sheet_name))
                    if ref:
                        refs.append(ref)
                    if len(refs) >= 8:
                        break
                if not refs:
                    continue
                conclusion = (
                    f"案例主底稿回放：已读取并核对 {len(evidence.get('sheet_names') or [])} 个相关工作表，"
                    "结论依据主底稿中的审计程序、审定表、审计说明及索引。该结论用于本案例重跑，"
                    "不等同于对新项目自动签发。"
                )
                before_status = str(program.get("status") or "not_started")
                cursor.execute(
                    """
                    UPDATE annual_audit_program_item
                    SET status = 'completed', evidence_refs_json = %s,
                        conclusion_text = %s, prepared_by = %s,
                        prepared_at = COALESCE(prepared_at, UTC_TIMESTAMP(6)),
                        policy_binding_id = COALESCE(%s, policy_binding_id),
                        revision = revision + CASE WHEN status <> 'completed' THEN 1 ELSE 0 END
                    WHERE engagement_id = %s AND procedure_code = %s
                    """,
                    (
                        json.dumps(refs, ensure_ascii=False),
                        conclusion,
                        actor_user_id,
                        binding_id,
                        engagement_id,
                        code,
                    ),
                )
                if before_status != "completed":
                    changed += 1
            if changed:
                cursor.execute(
                    """
                    INSERT INTO ata_audit_log (
                      actor_user_id, engagement_id, action, target_type, target_id, details_json
                    ) VALUES (%s, %s, 'case_workpaper_replay_bound', 'annual_audit_program_item', %s, %s)
                    """,
                    (
                        actor_user_id,
                        engagement_id,
                        str(engagement_id),
                        json.dumps(
                            {
                                "source_type": CASE_WORKPAPER_SOURCE_TYPE,
                                "source_file": summary.get("file_name"),
                                "sheet_count": summary.get("sheet_count"),
                                "changed_program_count": changed,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
        connection.commit()
    return {**summary, "bound_program_count": changed}


__all__ = [
    "CASE_WORKPAPER_SOURCE_TYPE",
    "CASE_WORKPAPER_VERSION",
    "CATEGORY_SHEET_HINTS",
    "PROGRAM_SHEET_HINTS",
    "case_workpaper_category_codes",
    "case_workpaper_program_evidence",
    "get_case_workpaper_summary",
    "persist_case_workpaper_summary",
    "summarize_workpaper_sheets",
    "sync_case_workpaper_programs",
]
