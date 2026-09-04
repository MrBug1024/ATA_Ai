"""Deterministic annual-audit progress and next-action projection.

This module does not make audit judgements or persist workflow decisions.  It
projects the governed engagement state into a stable, accountant-facing view
that can be rendered by either the API or chat without asking an LLM to decide
whether a professional prerequisite has been met.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .engagement_repository import get_engagement
from .execution_service import PROFILE_REQUIRED_FIELDS, get_execution_snapshot
from .program_catalog import PROGRAM_VERSION, baseline_program
from .storage import postgres_connection


READINESS_RULE_VERSION = "cn-annual-audit-progress-2026.1"


@dataclass(frozen=True)
class WorkPackageRule:
    code: str
    name: str
    phase: str
    procedure_codes: tuple[str, ...]
    start_material_codes: tuple[str, ...]
    outputs: tuple[str, ...]
    automation_level: str = "guided"


WORK_PACKAGE_RULES: tuple[WorkPackageRule, ...] = (
    WorkPackageRule(
        "acceptance",
        "承接与独立性",
        "acceptance",
        ("A1", "A2"),
        (),
        ("承接/续约评价草稿", "独立性评价记录", "业务约定书草稿", "首轮资料清单"),
    ),
    WorkPackageRule(
        "planning",
        "计划、重要性与风险评估",
        "planning",
        ("A3", "A4", "A5"),
        ("financial_statements", "trial_balance"),
        ("基础数据校验结果", "重要性水平底稿草稿", "风险矩阵", "总体审计策略与计划草稿"),
    ),
    WorkPackageRule(
        "cash",
        "货币资金与银行函证",
        "fieldwork",
        ("C1", "C2"),
        ("bank_statements", "trial_balance", "general_ledger"),
        ("银行账户总体", "银行函证草稿", "银行流水分析结果", "货币资金底稿草稿"),
        "deep",
    ),
    WorkPackageRule(
        "sales",
        "销售与收入",
        "fieldwork",
        ("F1",),
        ("revenue_support", "general_ledger", "journal_entries"),
        ("收入抽样方案", "收入截止测试结果", "销售与收入底稿草稿"),
        "deep",
    ),
    WorkPackageRule(
        "receivables",
        "应收账款与往来函证",
        "fieldwork",
        ("F2", "F3"),
        ("receivables", "revenue_support"),
        ("应收账款账龄分析", "往来函证清单与草稿", "期后回款测试", "应收账款底稿草稿"),
        "deep",
    ),
    WorkPackageRule(
        "purchases_payables",
        "采购与应付",
        "fieldwork",
        ("C5", "C6"),
        ("accounts_payable", "purchase_support", "general_ledger"),
        ("供应商函证清单与草稿", "采购截止测试", "未记录负债测试", "采购与应付底稿草稿"),
    ),
    WorkPackageRule(
        "inventory",
        "存货",
        "fieldwork",
        ("C9", "C10"),
        ("inventory_records", "inventory_count"),
        ("存货监盘与抽盘记录", "存货计价测试", "截止测试", "存货底稿草稿"),
    ),
    WorkPackageRule(
        "payroll",
        "薪酬与人事",
        "fieldwork",
        ("D8", "D9"),
        ("payroll_hr", "general_ledger"),
        ("人员与薪酬核查结果", "薪酬计提和支付测试", "薪酬底稿草稿"),
    ),
    WorkPackageRule(
        "fixed_assets",
        "固定资产与长期资产",
        "fieldwork",
        ("C21", "C22"),
        ("fixed_assets", "asset_rights", "general_ledger"),
        ("资产盘点与权属核查", "折旧减值测试", "资本化与处置测试", "固定资产底稿草稿"),
    ),
    WorkPackageRule(
        "completion",
        "跨循环事项与审计完成",
        "completion",
        ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "A12", "A13"),
        ("financial_statements", "adjustments", "audit_workpapers"),
        (
            "审计发现与错报汇总",
            "期后事项和持续经营评价",
            "管理层声明与治理层沟通草稿",
            "完成阶段检查表",
            "当前阶段报告草稿",
        ),
    ),
)


MATERIAL_NAMES = {
    "engagement_acceptance": "承接与独立性资料",
    "financial_statements": "财务报表及附注",
    "trial_balance": "科目余额表",
    "general_ledger": "总账/明细账",
    "journal_entries": "序时账与凭证",
    "governance_minutes": "治理层会议与内部控制资料",
    "bank_statements": "银行流水、对账单及余额调节表",
    "revenue_support": "销售与收入支持资料",
    "receivables": "应收账款明细及账龄",
    "confirmations": "函证及回函",
    "accounts_payable": "应付账款明细",
    "purchase_support": "采购与付款支持资料",
    "inventory_records": "存货收发存与计价资料",
    "inventory_count": "盘点计划及盘点记录",
    "payroll_hr": "薪酬与人事资料",
    "tax_materials": "税务资料",
    "fixed_assets": "固定资产明细",
    "asset_rights": "资产权属资料",
    "related_parties": "关联方与关联交易资料",
    "legal_contingencies": "诉讼、担保与或有事项资料",
    "subsequent_events": "期后事项资料",
    "going_concern": "持续经营资料",
    "adjustments": "审计调整与未更正错报资料",
    "management_representation": "管理层声明资料",
    "audit_workpapers": "审计工作底稿",
}


PHASE_NAMES = {
    "acceptance": "承接与独立性",
    "planning": "计划与风险评估",
    "fieldwork": "循环执行与证据获取",
    "completion": "审计完成",
    "review": "复核与签发准备",
    "issuance_archive": "签发与归档",
    "completed": "项目已完成",
}

TERMINAL_PROGRAM_STATUSES = {"completed", "not_applicable"}
ACTIVE_PROGRAM_STATUSES = {"blocked", "in_progress", "evidence_ready", "returned"}
CONFIRMATION_STATUSES = (
    "planned",
    "prepared",
    "sent",
    "received",
    "exception",
    "alternative_performed",
    "closed",
)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _iso(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value not in (None, "") else None


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _json_list(value: Any) -> list[Any]:
    parsed = _json_value(value, [])
    return parsed if isinstance(parsed, list) else []


def _normalize_confirmation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "confirmation_id": _as_int(row.get("id") or row.get("confirmation_id")),
        "case_id": _as_int(row.get("engagement_id") or row.get("case_id")),
        "procedure_code": str(row.get("procedure_code") or ""),
        "counterparty_name": str(row.get("counterparty_name") or ""),
        "confirmation_type": str(row.get("confirmation_type") or ""),
        "status": str(row.get("status") or "planned"),
        "auditor_controlled_delivery": bool(row.get("auditor_controlled_delivery")),
        "request_evidence_refs": _json_list(row.get("request_evidence_refs_json") or row.get("request_evidence_refs")),
        "response_evidence_refs": _json_list(row.get("response_evidence_refs_json") or row.get("response_evidence_refs")),
        "reliability_assessment": str(row.get("reliability_assessment") or ""),
        "exception_description": str(row.get("exception_description") or ""),
        "alternative_procedures": _json_value(
            row.get("alternative_procedures_json") or row.get("alternative_procedures"),
            {},
        ),
        "conclusion_text": str(row.get("conclusion_text") or ""),
        "prepared_by": str(row.get("prepared_by") or ""),
        "reviewed_by": str(row.get("reviewed_by") or ""),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def summarize_confirmations(confirmations: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in CONFIRMATION_STATUSES}
    other = 0
    for item in confirmations:
        status = str(item.get("status") or "planned")
        if status in counts:
            counts[status] += 1
        else:
            other += 1
    open_count = sum(count for status, count in counts.items() if status != "closed") + other
    return {
        "total": len(confirmations),
        "open": open_count,
        "closed": counts["closed"],
        "waiting_response": counts["sent"],
        "exceptions": counts["exception"],
        "planned": counts["planned"],
        "prepared": counts["prepared"],
        "sent": counts["sent"],
        "received": counts["received"],
        "alternative_performed": counts["alternative_performed"],
        "other": other,
    }


def list_confirmations(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return the complete confirmation register without changing workflow state."""

    resolved = settings or get_settings()
    get_engagement(engagement_id, settings=resolved)
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, engagement_id, procedure_code, counterparty_name,
                       confirmation_type, status, auditor_controlled_delivery,
                       request_evidence_refs_json, response_evidence_refs_json,
                       reliability_assessment, exception_description,
                       alternative_procedures_json, conclusion_text,
                       prepared_by, reviewed_by, created_at, updated_at
                FROM annual_confirmation
                WHERE engagement_id = %s
                ORDER BY id
                """,
                (engagement_id,),
            )
            confirmations = [_normalize_confirmation(dict(row)) for row in cursor.fetchall()]
    return {
        "case_id": engagement_id,
        "summary": summarize_confirmations(confirmations),
        "confirmations": confirmations,
    }


def _program(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    persisted = {
        str(item.get("procedure_code") or ""): dict(item)
        for item in snapshot.get("program") or []
        if isinstance(item, dict) and item.get("procedure_code")
    }
    merged: list[dict[str, Any]] = []
    for catalog_item in baseline_program():
        code = str(catalog_item["procedure_code"])
        merged.append(
            {
                **catalog_item,
                "status": "not_started",
                "evidence_refs": [],
                "conclusion_text": "",
                "not_applicable_reason": "",
                **persisted.pop(code, {}),
            }
        )
    merged.extend(persisted.values())
    return merged


def _category_index(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("code") or ""): dict(item)
        for item in snapshot.get("document_categories") or []
        if isinstance(item, dict) and item.get("code")
    }


def _material_name(code: str, categories: dict[str, dict[str, Any]]) -> str:
    return str((categories.get(code) or {}).get("name") or MATERIAL_NAMES.get(code) or code)


def _available_material(code: str, categories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = categories.get(code) or {}
    return {
        "code": code,
        "name": _material_name(code, categories),
        "coverage_status": str(item.get("coverage_status") or "ready"),
        "coverage_basis": str(item.get("coverage_basis") or "unknown"),
        "file_count": _as_int(item.get("file_count")),
        "record_count": _as_int(item.get("record_count")),
    }


def _missing_material(code: str, categories: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {"code": code, "name": _material_name(code, categories)}


def _is_material_ready(code: str, categories: dict[str, dict[str, Any]]) -> bool:
    return bool((categories.get(code) or {}).get("uploaded"))


def _profile_ready(profile: dict[str, Any]) -> bool:
    return (
        str(profile.get("acceptance_status") or "") == "accepted"
        and str(profile.get("independence_status") or "") == "cleared"
    )


def _required_material_codes(items: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    for item in items:
        if str(item.get("status") or "not_started") == "not_applicable":
            continue
        for code in item.get("required_material_categories") or []:
            normalized = str(code or "")
            if normalized and normalized not in codes:
                codes.append(normalized)
    return codes


def _package_status(
    *,
    rule: WorkPackageRule,
    items: list[dict[str, Any]],
    profile_ready: bool,
    start_material_ready: bool,
    confirmations: list[dict[str, Any]],
    fieldwork_complete: bool,
) -> str:
    statuses = [str(item.get("status") or "not_started") for item in items]
    all_terminal = bool(statuses) and all(status in TERMINAL_PROGRAM_STATUSES for status in statuses)
    open_confirmations = [item for item in confirmations if item.get("status") != "closed"]

    if rule.code != "acceptance" and not profile_ready:
        return "blocked"
    if rule.code == "completion" and not fieldwork_complete and not any(
        status in ACTIVE_PROGRAM_STATUSES or status in TERMINAL_PROGRAM_STATUSES
        for status in statuses
    ):
        return "blocked"
    if all_terminal and not open_confirmations:
        return "completed"
    if any(str(item.get("status") or "") == "sent" for item in open_confirmations):
        return "waiting_external"
    if statuses and all(
        status in TERMINAL_PROGRAM_STATUSES | {"evidence_ready"} for status in statuses
    ) and "evidence_ready" in statuses:
        return "ready_for_review"
    if any(status in ACTIVE_PROGRAM_STATUSES or status in TERMINAL_PROGRAM_STATUSES for status in statuses):
        return "in_progress"
    if rule.code == "acceptance":
        return "ready" if not profile_ready else "in_progress"
    if rule.start_material_codes and not start_material_ready:
        return "blocked"
    return "ready"


def _build_work_packages(
    *,
    profile: dict[str, Any],
    program: list[dict[str, Any]],
    categories: dict[str, dict[str, Any]],
    confirmations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    program_by_code = {str(item.get("procedure_code") or ""): item for item in program}
    accepted = _profile_ready(profile)
    packages: list[dict[str, Any]] = []
    fieldwork_complete = False

    for rule in WORK_PACKAGE_RULES:
        items = [program_by_code[code] for code in rule.procedure_codes if code in program_by_code]
        required_codes = _required_material_codes(items)
        available_codes = [code for code in required_codes if _is_material_ready(code, categories)]
        missing_codes = [code for code in required_codes if code not in available_codes]
        start_material_ready = not rule.start_material_codes or any(
            _is_material_ready(code, categories) for code in rule.start_material_codes
        )
        package_confirmations = [
            item for item in confirmations if str(item.get("procedure_code") or "") in rule.procedure_codes
        ]
        status = _package_status(
            rule=rule,
            items=items,
            profile_ready=accepted,
            start_material_ready=start_material_ready,
            confirmations=package_confirmations,
            fieldwork_complete=fieldwork_complete,
        )
        limitations: list[str] = []
        if rule.code != "acceptance" and not accepted:
            limitations.append("承接/续约和独立性尚未同时获准，不能正式执行该业务包。")
        if rule.phase == "fieldwork":
            planning_items = [program_by_code[code] for code in ("A3", "A4", "A5") if code in program_by_code]
            if not planning_items or not all(
                str(item.get("status") or "") in TERMINAL_PROGRAM_STATUSES for item in planning_items
            ):
                limitations.append("计划与风险评估尚未完成，执行中的程序仍可能需要调整。")
        if rule.code == "completion" and not fieldwork_complete:
            limitations.append("仍有循环审计业务包未完成，当前不能形成整体审计结论。")
        if missing_codes:
            missing_names = "、".join(_material_name(code, categories) for code in missing_codes)
            limitations.append(f"尚缺完成该业务包通常需要的资料：{missing_names}。")
        attention_codes = [
            code
            for code in required_codes
            if str((categories.get(code) or {}).get("coverage_status") or "")
            in {"pending", "failed", "raw_only"}
        ]
        if attention_codes:
            limitations.append(
                "以下资料尚未形成可用证据："
                + "、".join(_material_name(code, categories) for code in attention_codes)
                + "。"
            )
        derived_codes = [
            code
            for code in available_codes
            if bool((categories.get(code) or {}).get("covered_by_case_workpaper"))
        ]
        if derived_codes:
            limitations.append(
                "以下覆盖来自案例/历史底稿，不能替代本项目原始资料："
                + "、".join(_material_name(code, categories) for code in derived_codes)
                + "。"
            )
        if any(str(item.get("status") or "") == "returned" for item in items):
            limitations.append("存在复核退回程序，须按复核意见补充证据并重新提交。")
        open_confirmations = [item for item in package_confirmations if item.get("status") != "closed"]
        if open_confirmations:
            limitations.append(f"仍有 {len(open_confirmations)} 项函证未闭环。")
        if rule.automation_level == "guided":
            limitations.append("当前版本提供资料判断、程序记录和底稿积累，审计判断仍须人工复核。")

        outputs_now = ["资料缺口清单"]
        if status != "blocked":
            outputs_now.extend(rule.outputs)
        completed_items = sum(
            1 for item in items if str(item.get("status") or "") in TERMINAL_PROGRAM_STATUSES
        )
        packages.append(
            {
                "code": rule.code,
                "name": rule.name,
                "phase": rule.phase,
                "status": status,
                "automation_level": rule.automation_level,
                "completed_items": completed_items,
                "total_items": len(items),
                "procedure_codes": list(rule.procedure_codes),
                "available_materials": [
                    _available_material(code, categories) for code in available_codes
                ],
                "missing_materials": [
                    _missing_material(code, categories) for code in missing_codes
                ],
                "outputs_now": outputs_now,
                "limitations": limitations,
            }
        )
        if rule.phase == "fieldwork":
            fieldwork_packages = [item for item in packages if item["phase"] == "fieldwork"]
            fieldwork_complete = bool(fieldwork_packages) and all(
                item["status"] == "completed" for item in fieldwork_packages
            )
    return packages


def _program_summary(program: list[dict[str, Any]]) -> dict[str, int]:
    statuses = {
        "not_started": 0,
        "blocked": 0,
        "in_progress": 0,
        "evidence_ready": 0,
        "completed": 0,
        "not_applicable": 0,
        "returned": 0,
    }
    other = 0
    for item in program:
        status = str(item.get("status") or "not_started")
        if status in statuses:
            statuses[status] += 1
        else:
            other += 1
    return {"total": len(program), **statuses, "other": other}


def _material_summary(categories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = list(categories.values())
    available = [row for row in rows if bool(row.get("uploaded"))]
    attention = [
        row
        for row in rows
        if str(row.get("coverage_status") or "") in {"pending", "failed", "raw_only"}
    ]
    return {
        "total_categories": len(rows),
        "received_categories": sum(1 for row in rows if bool(row.get("raw_uploaded"))),
        "available_categories": len(available),
        "missing_categories": sum(1 for row in rows if not bool(row.get("uploaded"))),
        "pending_categories": sum(1 for row in rows if row.get("coverage_status") == "pending"),
        "failed_categories": sum(1 for row in rows if row.get("coverage_status") == "failed"),
        "raw_only_categories": sum(1 for row in rows if row.get("coverage_status") == "raw_only"),
        "case_workpaper_categories": sum(
            1 for row in rows if bool(row.get("covered_by_case_workpaper"))
        ),
        "available": [
            _available_material(str(row.get("code") or ""), categories) for row in available
        ],
        "attention_required": [
            {
                "code": str(row.get("code") or ""),
                "name": _material_name(str(row.get("code") or ""), categories),
                "coverage_status": str(row.get("coverage_status") or "missing"),
            }
            for row in attention
        ],
    }


def _review_summary(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    levels = []
    for item in reviews:
        if not isinstance(item, dict):
            continue
        levels.append(
            {
                "review_level": str(item.get("review_level") or ""),
                "decision": str(item.get("decision") or "pending"),
                "reviewer_user_id": str(item.get("reviewer_user_id") or ""),
                "created_at": _iso(item.get("created_at")),
            }
        )
    return {
        "total_levels": len(levels),
        "approved": sum(1 for item in levels if item["decision"] == "approved"),
        "pending": sum(1 for item in levels if item["decision"] == "pending"),
        "returned": sum(1 for item in levels if item["decision"] == "returned"),
        "levels": levels,
    }


def _finding_summary(release_gate: dict[str, Any]) -> dict[str, Any]:
    open_findings = release_gate.get("open_findings") or {}
    items = [dict(item) for item in open_findings.get("findings") or [] if isinstance(item, dict)]
    return {
        "open": _as_int(open_findings.get("count")) or len(items),
        "high": sum(1 for item in items if item.get("risk_level") == "high"),
        "medium": sum(1 for item in items if item.get("risk_level") == "medium"),
        "low": sum(1 for item in items if item.get("risk_level") == "low"),
        "items": [
            {
                "finding_id": _as_int(item.get("finding_id")),
                "risk_level": str(item.get("risk_level") or ""),
                "title": str(item.get("title") or ""),
            }
            for item in items
        ],
    }


def _release_status(engagement: dict[str, Any], release_gate: dict[str, Any]) -> dict[str, Any]:
    engagement_status = str(engagement.get("status") or "")
    blockers = [
        {
            "code": str(item.get("code") or ""),
            "message": str(item.get("message") or ""),
        }
        for item in release_gate.get("blockers") or []
        if isinstance(item, dict)
    ]
    gate_status = str(release_gate.get("gate_status") or "blocked")
    if engagement_status == "archived":
        status = "archived"
    elif engagement_status == "issued":
        status = "issued"
    else:
        status = gate_status
    return {
        "status": status,
        "gate_status": gate_status,
        "ready_for_signature": gate_status == "ready_for_signature",
        "issued": engagement_status in {"issued", "archived"},
        "archived": engagement_status == "archived",
        "blocker_count": len(blockers),
        "blockers": blockers,
    }


def _phase_statuses(
    *,
    profile: dict[str, Any],
    program: list[dict[str, Any]],
    reviews: dict[str, Any],
    release: dict[str, Any],
) -> list[dict[str, Any]]:
    by_code = {str(item.get("procedure_code") or ""): item for item in program}

    def program_phase(code: str, name: str, procedure_codes: tuple[str, ...], prerequisite: bool) -> dict[str, Any]:
        items = [by_code[item_code] for item_code in procedure_codes if item_code in by_code]
        completed = sum(
            1 for item in items if str(item.get("status") or "") in TERMINAL_PROGRAM_STATUSES
        )
        has_activity = any(str(item.get("status") or "") != "not_started" for item in items)
        if code == "acceptance" and not _profile_ready(profile):
            status = "in_progress" if has_activity else "blocked"
        elif items and completed == len(items):
            status = "completed"
        elif has_activity:
            status = "in_progress"
        elif prerequisite:
            status = "ready"
        else:
            status = "blocked"
        return {
            "code": code,
            "name": name,
            "status": status,
            "completed_items": completed,
            "total_items": len(items),
        }

    acceptance_codes = ("A1", "A2")
    planning_codes = ("A3", "A4", "A5")
    fieldwork_codes = tuple(
        str(item.get("procedure_code") or "")
        for item in program
        if str(item.get("phase") or "") == "循环执行"
    )
    completion_codes = tuple(
        str(item.get("procedure_code") or "")
        for item in program
        if str(item.get("phase") or "") == "完成"
    )
    acceptance = program_phase(
        "acceptance", PHASE_NAMES["acceptance"], acceptance_codes, True
    )
    planning = program_phase(
        "planning",
        PHASE_NAMES["planning"],
        planning_codes,
        acceptance["status"] == "completed",
    )
    fieldwork = program_phase(
        "fieldwork",
        PHASE_NAMES["fieldwork"],
        fieldwork_codes,
        planning["status"] == "completed",
    )
    completion = program_phase(
        "completion",
        PHASE_NAMES["completion"],
        completion_codes,
        fieldwork["status"] == "completed",
    )
    review_total = max(_as_int(reviews.get("total_levels")), 3)
    review_completed = _as_int(reviews.get("approved"))
    if review_completed >= review_total:
        review_status = "completed"
    elif review_completed or _as_int(reviews.get("returned")):
        review_status = "in_progress"
    elif completion["status"] == "completed":
        review_status = "ready"
    else:
        review_status = "blocked"
    review = {
        "code": "review",
        "name": PHASE_NAMES["review"],
        "status": review_status,
        "completed_items": min(review_completed, review_total),
        "total_items": review_total,
    }
    issuance_completed = int(bool(release.get("issued"))) + int(bool(release.get("archived")))
    if release.get("archived"):
        issuance_status = "completed"
    elif release.get("issued") or release.get("ready_for_signature"):
        issuance_status = "in_progress" if release.get("issued") else "ready"
    else:
        issuance_status = "blocked"
    issuance = {
        "code": "issuance_archive",
        "name": PHASE_NAMES["issuance_archive"],
        "status": issuance_status,
        "completed_items": issuance_completed,
        "total_items": 2,
    }
    return [acceptance, planning, fieldwork, completion, review, issuance]


def _next_actions(
    *,
    profile: dict[str, Any],
    categories: dict[str, dict[str, Any]],
    work_packages: list[dict[str, Any]],
    findings: dict[str, Any],
    confirmations: list[dict[str, Any]],
    reviews: dict[str, Any],
    release: dict[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    def add(
        score: int,
        *,
        code: str,
        title: str,
        reason: str,
        priority: str,
        action_type: str,
        procedure_code: str | None = None,
        material_codes: list[str] | None = None,
    ) -> None:
        actions.append(
            {
                "_score": score,
                "code": code,
                "title": title,
                "reason": reason,
                "priority": priority,
                "action_type": action_type,
                "procedure_code": procedure_code,
                "material_codes": material_codes or [],
            }
        )

    acceptance_status = str(profile.get("acceptance_status") or "pending")
    independence_status = str(profile.get("independence_status") or "pending")
    if acceptance_status in {"rejected", "withdrawn"} or independence_status == "blocked":
        add(
            0,
            code="profile.resolve_engagement_block",
            title="处理项目承接或独立性阻断",
            reason="项目当前不得继续执行审计程序。",
            priority="critical",
            action_type="update_profile",
            procedure_code="A1",
        )
    elif not _profile_ready(profile):
        add(
            10,
            code="profile.complete_acceptance",
            title="完成承接与独立性审批",
            reason="其他审计业务包必须建立在已获准承接且独立性已清除的基础上。",
            priority="high",
            action_type="update_profile",
            procedure_code="A1",
        )
    missing_profile_fields = [field for field in PROFILE_REQUIRED_FIELDS if not str(profile.get(field) or "").strip()]
    if missing_profile_fields:
        add(
            12,
            code="profile.complete_master_data",
            title="补全项目画像",
            reason=f"仍有 {len(missing_profile_fields)} 项签发所需项目控制信息未填写。",
            priority="high",
            action_type="update_profile",
        )

    failed_codes = [
        code for code, item in categories.items() if item.get("coverage_status") == "failed"
    ]
    if failed_codes:
        add(
            15,
            code="materials.retry_failed",
            title="重新处理解析失败的资料",
            reason="解析失败的文件尚不能作为可检索、可回源的审计证据。",
            priority="high",
            action_type="retry_material",
            material_codes=failed_codes,
        )
    raw_only_codes = [
        code for code, item in categories.items() if item.get("coverage_status") == "raw_only"
    ]
    if raw_only_codes:
        add(
            25,
            code="materials.parse_raw_only",
            title="确认并解析仅留存原文件",
            reason="这些文件已收到，但尚未形成可定位的证据内容。",
            priority="medium",
            action_type="classify_material",
            material_codes=raw_only_codes,
        )

    for index, package in enumerate(work_packages):
        status = str(package.get("status") or "blocked")
        procedure_codes = [str(code) for code in package.get("procedure_codes") or []]
        procedure_code = procedure_codes[0] if procedure_codes else None
        missing_codes = [
            str(item.get("code") or "")
            for item in package.get("missing_materials") or []
            if isinstance(item, dict) and item.get("code")
        ]
        if status == "blocked" and package.get("code") != "acceptance" and _profile_ready(profile):
            add(
                30 + index,
                code=f"package.{package['code']}.materials",
                title=f"补充{package['name']}资料",
                reason="当前缺少启动或完成该业务包所需的可用资料。",
                priority="high" if package.get("phase") in {"planning", "completion"} else "medium",
                action_type="upload_material",
                procedure_code=procedure_code,
                material_codes=missing_codes,
            )
        elif status == "ready":
            add(
                40 + index,
                code=f"package.{package['code']}.start",
                title=f"开始{package['name']}",
                reason="当前资料已经满足该业务包的最低启动条件。",
                priority="high" if package.get("phase") in {"acceptance", "planning"} else "medium",
                action_type="start_procedure",
                procedure_code=procedure_code,
            )
        elif status == "in_progress":
            add(
                35 + index,
                code=f"package.{package['code']}.continue",
                title=f"继续{package['name']}",
                reason="该业务包已有程序或证据记录，但尚未形成可复核结论。",
                priority="high" if package.get("phase") in {"planning", "completion"} else "medium",
                action_type="continue_procedure",
                procedure_code=procedure_code,
            )
        elif status == "waiting_external":
            pending = [
                item
                for item in confirmations
                if item.get("procedure_code") in procedure_codes and item.get("status") != "closed"
            ]
            add(
                20 + index,
                code=f"package.{package['code']}.confirmation_follow_up",
                title=f"跟进{package['name']}函证",
                reason=f"仍有 {len(pending)} 项函证待回函、差异处理或替代程序闭环。",
                priority="high",
                action_type="follow_up_confirmation",
                procedure_code=procedure_code,
            )
        elif status == "ready_for_review":
            add(
                32 + index,
                code=f"package.{package['code']}.submit_review",
                title=f"提交{package['name']}复核",
                reason="相关程序已达到证据就绪状态，需要人工复核并记录结论。",
                priority="high",
                action_type="submit_review",
                procedure_code=procedure_code,
            )

    if _as_int(findings.get("open")):
        add(
            18,
            code="findings.resolve_open",
            title="处理开放审计发现",
            reason=f"仍有 {_as_int(findings.get('open'))} 项发现未解决或未复核。",
            priority="high",
            action_type="resolve_finding",
        )
    if reviews.get("approved", 0) < reviews.get("total_levels", 3) and any(
        package.get("code") == "completion" and package.get("status") == "completed"
        for package in work_packages
    ):
        add(
            45,
            code="reviews.continue",
            title="完成项目复核",
            reason="完成阶段程序已经闭环，但规定复核尚未全部批准。",
            priority="high",
            action_type="record_review",
        )
    if release.get("ready_for_signature") and not release.get("issued"):
        add(
            50,
            code="release.issue",
            title="由项目合伙人复核并签发报告",
            reason="当前正式放行门禁已经满足。",
            priority="high",
            action_type="issue_report",
        )
    if release.get("issued") and not release.get("archived"):
        add(
            55,
            code="release.archive",
            title="完成项目归档",
            reason="报告已经签发，仍需形成完整归档清单并锁定审计档案。",
            priority="medium",
            action_type="archive_engagement",
        )

    actions.sort(key=lambda item: (int(item["_score"]), str(item["code"])))
    return [{key: value for key, value in item.items() if key != "_score"} for item in actions[:10]]


def derive_audit_progress(
    *,
    engagement: dict[str, Any],
    execution_snapshot: dict[str, Any],
    confirmations: list[dict[str, Any]],
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Project a stable progress contract from governed annual-audit state."""

    case_id = _as_int(engagement.get("id") or execution_snapshot.get("case_id"))
    profile = dict(execution_snapshot.get("profile") or {})
    program = _program(execution_snapshot)
    categories = _category_index(execution_snapshot)
    normalized_confirmations = [_normalize_confirmation(item) for item in confirmations]
    release_gate = dict(execution_snapshot.get("release_gate") or {})
    reviews = _review_summary(execution_snapshot.get("reviews") or [])
    findings = _finding_summary(release_gate)
    release = _release_status(engagement, release_gate)
    work_packages = _build_work_packages(
        profile=profile,
        program=program,
        categories=categories,
        confirmations=normalized_confirmations,
    )
    phases = _phase_statuses(
        profile=profile,
        program=program,
        reviews=reviews,
        release=release,
    )
    current = next((phase for phase in phases if phase["status"] != "completed"), None)
    current_phase = str((current or {}).get("code") or "completed")
    current_phase_name = str((current or {}).get("name") or PHASE_NAMES["completed"])
    materials = _material_summary(categories)
    program_counts = _program_summary(program)
    confirmation_counts = summarize_confirmations(normalized_confirmations)

    if release["archived"]:
        overall_status = "archived"
    elif release["issued"]:
        overall_status = "issued"
    elif release["ready_for_signature"]:
        overall_status = "ready_for_signature"
    elif str(profile.get("acceptance_status") or "") in {"rejected", "withdrawn"} or str(
        profile.get("independence_status") or ""
    ) == "blocked":
        overall_status = "blocked"
    elif program_counts["completed"] or program_counts["in_progress"] or materials["received_categories"]:
        overall_status = "in_progress"
    elif _profile_ready(profile):
        overall_status = "awaiting_materials"
    else:
        overall_status = "setup_required"

    summary = (
        f"当前控制阶段为“{current_phase_name}”。已收到 {materials['received_categories']} 类资料，"
        f"其中 {materials['available_categories']} 类可用于当前判断；"
        f"{program_counts['total']} 项审计程序中已完成 {program_counts['completed']} 项、"
        f"不适用 {program_counts['not_applicable']} 项；"
        f"函证 {confirmation_counts['total']} 项，其中 {confirmation_counts['open']} 项未闭环；"
        f"正式签发门禁仍有 {release['blocker_count']} 项阻断。"
    )
    next_actions = _next_actions(
        profile=profile,
        categories=categories,
        work_packages=work_packages,
        findings=findings,
        confirmations=normalized_confirmations,
        reviews=reviews,
        release=release,
    )
    return {
        "case_id": case_id,
        "readiness_rule_version": READINESS_RULE_VERSION,
        "program_version": str(execution_snapshot.get("program_version") or PROGRAM_VERSION),
        "current_phase": current_phase,
        "current_phase_name": current_phase_name,
        "overall_status": overall_status,
        "summary": summary,
        "phases": phases,
        "work_packages": work_packages,
        "next_actions": next_actions,
        "material_summary": materials,
        "program_summary": program_counts,
        "finding_summary": findings,
        "confirmation_summary": confirmation_counts,
        "review_summary": reviews,
        "release_status": release,
        "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
    }


def get_audit_progress(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Load current annual-audit state and return its deterministic projection."""

    resolved = settings or get_settings()
    engagement = get_engagement(engagement_id, settings=resolved)
    snapshot = get_execution_snapshot(engagement_id, settings=resolved)
    confirmation_register = list_confirmations(engagement_id, settings=resolved)
    return derive_audit_progress(
        engagement=engagement,
        execution_snapshot=snapshot,
        confirmations=confirmation_register["confirmations"],
    )


def render_progress_summary(progress: dict[str, Any]) -> str:
    """Render a concise deterministic chat answer from the API contract."""

    lines = [str(progress.get("summary") or "当前项目进度已更新。")]
    packages = [
        item
        for item in progress.get("work_packages") or []
        if isinstance(item, dict) and item.get("status") in {"ready", "in_progress", "waiting_external", "ready_for_review"}
    ]
    if packages:
        lines.append("\n当前可推进：")
        for item in packages[:5]:
            lines.append(f"- {item.get('name')}：{item.get('status')}")
    actions = [item for item in progress.get("next_actions") or [] if isinstance(item, dict)]
    if actions:
        lines.append("\n建议下一步：")
        for index, item in enumerate(actions[:5], start=1):
            lines.append(f"{index}. {item.get('title')}：{item.get('reason')}")
    release = progress.get("release_status") or {}
    if not release.get("ready_for_signature"):
        lines.append("\n说明：当前输出只能作为阶段性资料、程序或底稿草稿，不代表审计报告可以正式签发。")
    return "\n".join(lines)


__all__ = [
    "READINESS_RULE_VERSION",
    "WORK_PACKAGE_RULES",
    "derive_audit_progress",
    "get_audit_progress",
    "list_confirmations",
    "render_progress_summary",
    "summarize_confirmations",
]
