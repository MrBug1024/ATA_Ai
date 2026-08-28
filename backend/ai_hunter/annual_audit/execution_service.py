"""Controlled execution for annual financial-statement audit engagements.

The functions in this module manage auditable workflow state. They do not
make an audit opinion and they never infer that an absent record means a
negative result. A qualified human signer remains responsible for issuing a
formal report after the release gate is satisfied.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from . import document_repository as documents
from .engagement_repository import get_engagement
from .program_catalog import PROGRAM_VERSION, baseline_program, procedure_codes
from .storage import mysql_connection, postgres_connection
from .workpaper_case import get_case_workpaper_summary, sync_case_workpaper_programs


PROFILE_REQUIRED_FIELDS = (
    "entity_type",
    "audit_purpose",
    "accounting_framework",
    "firm_name",
    "engagement_partner",
    "signing_cpa_primary",
    "data_classification",
    "data_residency",
    "model_data_policy",
)
PROFILE_TEXT_FIELDS = set(PROFILE_REQUIRED_FIELDS) | {
    "industry_code",
    "regulatory_profile",
    "signing_cpa_secondary",
    "signing_cpa_primary_user_id",
    "signing_cpa_secondary_user_id",
    "group_audit_scope",
    "internal_control_audit_scope",
}
ACCEPTANCE_STATUSES = {"pending", "accepted", "rejected", "withdrawn"}
INDEPENDENCE_STATUSES = {"pending", "cleared", "blocked", "not_applicable"}
PROGRAM_STATUSES = {
    "not_started",
    "blocked",
    "in_progress",
    "evidence_ready",
    "completed",
    "not_applicable",
    "returned",
}
REVIEW_LEVELS = ("project_manager", "department_manager", "engagement_partner")
REVIEW_DECISIONS = {"approved", "returned"}
OPINION_TYPES = {"unmodified", "qualified", "adverse", "disclaimer"}


class WorkflowBlockedError(ValueError):
    """Raised when a formal workflow transition has unresolved blockers."""

    def __init__(self, blockers: list[dict[str, Any]]):
        self.blockers = blockers
        super().__init__("年审项目尚未满足发布门禁")


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, (date, datetime)) else None


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _nonempty_text(value: Any) -> str:
    return str(value or "").strip()


def _profile_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = _loads((row or {}).get("profile_json"), {})
    profile = dict(raw) if isinstance(raw, dict) else {}
    profile.update(
        {
            "acceptance_status": str((row or {}).get("acceptance_status") or "pending"),
            "independence_status": str((row or {}).get("independence_status") or "pending"),
            "data_classification": str((row or {}).get("data_classification") or profile.get("data_classification") or ""),
            "data_residency": str((row or {}).get("data_residency") or profile.get("data_residency") or ""),
            "model_data_policy": str((row or {}).get("model_data_policy") or profile.get("model_data_policy") or ""),
            "profile_version": _as_int((row or {}).get("profile_version")) or 1,
            "updated_at": _iso((row or {}).get("updated_at")),
        }
    )
    return profile


def profile_blockers(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return deterministic blockers for the mandatory project profile."""

    current = profile or {}
    blockers = [
        {
            "code": f"profile.{field}",
            "message": f"项目画像缺少{field}",
        }
        for field in PROFILE_REQUIRED_FIELDS
        if not _nonempty_text(current.get(field))
    ]
    if str(current.get("acceptance_status") or "") != "accepted":
        blockers.append(
            {
                "code": "profile.acceptance",
                "message": "承接/续约尚未获准",
            }
        )
    if str(current.get("independence_status") or "") != "cleared":
        blockers.append(
            {
                "code": "profile.independence",
                "message": "独立性尚未清除",
            }
        )
    return blockers


def canonical_evidence_errors(evidence_refs: Any) -> list[str]:
    """Check the shape required to retain a source-file and locator anchor."""

    refs = _as_list(evidence_refs)
    if not refs:
        return ["缺少证据锚点"]
    errors: list[str] = []
    for index, reference in enumerate(refs, start=1):
        if not isinstance(reference, dict):
            errors.append(f"证据 {index} 不是对象")
            continue
        locator = reference.get("source_locator")
        locator = locator if isinstance(locator, dict) else {}
        source_file_id = _as_int(reference.get("source_file_id") or locator.get("source_file_id"))
        source_page_id = _as_int(reference.get("source_page_id") or locator.get("source_page_id"))
        source_chunk_id = _nonempty_text(
            reference.get("source_chunk_id") or locator.get("source_chunk_id")
        )
        has_locator = bool(
            source_chunk_id
            or source_page_id > 0
            or _nonempty_text(locator.get("sheet_name"))
            or _nonempty_text(locator.get("cell_range"))
            or _as_int(locator.get("page_no")) > 0
            or _as_int(locator.get("row_number")) > 0
            or _as_int(locator.get("row_start")) > 0
        )
        if source_file_id <= 0:
            errors.append(f"证据 {index} 缺少 source_file_id")
        if not has_locator:
            errors.append(f"证据 {index} 缺少页、块、单元格或行定位")
    return errors


def _source_file_ids(evidence_refs: list[Any]) -> set[int]:
    ids: set[int] = set()
    for reference in evidence_refs:
        if not isinstance(reference, dict):
            continue
        locator = reference.get("source_locator")
        locator = locator if isinstance(locator, dict) else {}
        source_file_id = _as_int(reference.get("source_file_id") or locator.get("source_file_id"))
        if source_file_id > 0:
            ids.add(source_file_id)
    return ids


def _source_chunk_ids(evidence_refs: list[Any]) -> set[str]:
    ids: set[str] = set()
    for reference in evidence_refs:
        if not isinstance(reference, dict):
            continue
        locator = reference.get("source_locator")
        locator = locator if isinstance(locator, dict) else {}
        chunk_id = _nonempty_text(reference.get("source_chunk_id") or locator.get("source_chunk_id"))
        if chunk_id:
            ids.add(chunk_id)
    return ids


def _source_page_ids(evidence_refs: list[Any]) -> set[int]:
    ids: set[int] = set()
    for reference in evidence_refs:
        if not isinstance(reference, dict):
            continue
        locator = reference.get("source_locator")
        locator = locator if isinstance(locator, dict) else {}
        source_page_id = _as_int(reference.get("source_page_id") or locator.get("source_page_id"))
        if source_page_id > 0:
            ids.add(source_page_id)
    return ids


def _anchor_file_id(reference: dict[str, Any]) -> int:
    locator = reference.get("source_locator")
    locator = locator if isinstance(locator, dict) else {}
    return _as_int(reference.get("source_file_id") or locator.get("source_file_id"))


def _anchor_page_id(reference: dict[str, Any]) -> int:
    locator = reference.get("source_locator")
    locator = locator if isinstance(locator, dict) else {}
    return _as_int(reference.get("source_page_id") or locator.get("source_page_id"))


def _anchor_chunk_id(reference: dict[str, Any]) -> str:
    locator = reference.get("source_locator")
    locator = locator if isinstance(locator, dict) else {}
    return _nonempty_text(reference.get("source_chunk_id") or locator.get("source_chunk_id"))


def validate_evidence_ownership(
    engagement_id: int,
    evidence_refs: Any,
    *,
    settings: Settings | None = None,
) -> list[str]:
    """Verify evidence references point to active files/chunks of this case."""

    refs = _as_list(evidence_refs)
    errors = canonical_evidence_errors(refs)
    if errors:
        return errors
    resolved = settings or get_settings()
    file_ids = _source_file_ids(refs)
    page_ids = _source_page_ids(refs)
    chunk_ids = _source_chunk_ids(refs)
    with postgres_connection(resolved) as connection:
        known_files = {
            int(row["id"])
            for row in connection.execute(
                """
                SELECT id
                FROM public.source_file
                WHERE case_id = %s AND status = 'active' AND id = ANY(%s)
                """,
                (engagement_id, list(file_ids)),
            ).fetchall()
        }
        if page_ids:
            pages = {
                int(row["id"]): int(row["file_id"])
                for row in connection.execute(
                    """
                    SELECT id, file_id
                    FROM public.source_page
                    WHERE id = ANY(%s)
                    """,
                    (list(page_ids),),
                ).fetchall()
            }
        else:
            pages = {}
        if chunk_ids:
            chunks = {
                str(row["chunk_id"]): int(row["file_id"])
                for row in connection.execute(
                    """
                    SELECT chunk_id, file_id
                    FROM public.source_chunk
                    WHERE case_id = %s AND chunk_id = ANY(%s)
                    """,
                    (engagement_id, list(chunk_ids)),
                ).fetchall()
            }
        else:
            chunks = {}
    missing_files = sorted(file_ids - known_files)
    missing_pages = sorted(page_ids - set(pages))
    missing_chunks = sorted(chunk_ids - set(chunks))
    errors.extend(f"证据文件 {item} 不属于当前项目或已失效" for item in missing_files)
    errors.extend(f"证据页 {item} 不存在" for item in missing_pages)
    errors.extend(f"证据块 {item} 不属于当前项目" for item in missing_chunks)
    for reference in refs:
        if not isinstance(reference, dict):
            continue
        source_file_id = _anchor_file_id(reference)
        source_page_id = _anchor_page_id(reference)
        source_chunk_id = _anchor_chunk_id(reference)
        if source_page_id in pages and pages[source_page_id] != source_file_id:
            errors.append(f"证据页 {source_page_id} 不属于证据文件 {source_file_id}")
        if source_chunk_id in chunks and chunks[source_chunk_id] != source_file_id:
            errors.append(f"证据块 {source_chunk_id} 不属于证据文件 {source_file_id}")
    return errors


def _ensure_execution_records(
    engagement_id: int,
    *,
    actor_user_id: str,
    settings: Settings,
) -> None:
    get_engagement(engagement_id, settings=settings)
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT IGNORE INTO annual_engagement_profile (
                  engagement_id, profile_json, created_by, updated_by
                ) VALUES (%s, %s, %s, %s)
                """,
                (engagement_id, _dump({}), actor_user_id, actor_user_id),
            )
            for item in baseline_program():
                cursor.execute(
                    """
                    INSERT IGNORE INTO annual_audit_program_item (
                      engagement_id, program_version, procedure_code, phase, cycle,
                      procedure_name, assertions_json, risk_area,
                      required_material_categories_json, requires_evidence
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        engagement_id,
                        PROGRAM_VERSION,
                        item["procedure_code"],
                        item["phase"],
                        item["cycle"],
                        item["procedure_name"],
                        _dump(item["assertions"]),
                        item["risk_area"],
                        _dump(item["required_material_categories"]),
                        bool(item["requires_evidence"]),
                    ),
                )
        connection.commit()


def bootstrap_execution(
    engagement_id: int,
    *,
    actor_user_id: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create missing baseline profile and programme rows without overwriting work."""

    resolved = settings or get_settings()
    _ensure_execution_records(
        engagement_id,
        actor_user_id=_nonempty_text(actor_user_id) or "system",
        settings=resolved,
    )
    sync_case_workpaper_programs(
        engagement_id,
        actor_user_id=actor_user_id or "system",
        settings=resolved,
    )
    return get_execution_snapshot(engagement_id, settings=resolved)


def _program_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _as_int(row.get("id")),
        "procedure_code": str(row.get("procedure_code") or ""),
        "program_version": str(row.get("program_version") or ""),
        "phase": str(row.get("phase") or ""),
        "cycle": str(row.get("cycle") or ""),
        "procedure_name": str(row.get("procedure_name") or ""),
        "assertions": _as_list(_loads(row.get("assertions_json"), [])),
        "risk_area": str(row.get("risk_area") or ""),
        "required_material_categories": _as_list(
            _loads(row.get("required_material_categories_json"), [])
        ),
        "requires_evidence": bool(row.get("requires_evidence")),
        "status": str(row.get("status") or "not_started"),
        "sample_plan": _loads(row.get("sample_plan_json"), {}),
        "evidence_refs": _as_list(_loads(row.get("evidence_refs_json"), [])),
        "exception_count": _as_int(row.get("exception_count")),
        "alternative_procedures": _loads(row.get("alternative_procedures_json"), {}),
        "conclusion_text": str(row.get("conclusion_text") or ""),
        "not_applicable_reason": str(row.get("not_applicable_reason") or ""),
        "prepared_by": str(row.get("prepared_by") or ""),
        "prepared_at": _iso(row.get("prepared_at")),
        "reviewed_by": str(row.get("reviewed_by") or ""),
        "reviewed_at": _iso(row.get("reviewed_at")),
        "policy_binding_id": _as_int(row.get("policy_binding_id")) or None,
        "revision": _as_int(row.get("revision")) or 1,
        "updated_at": _iso(row.get("updated_at")),
    }


def _load_state(
    engagement_id: int,
    *,
    settings: Settings,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_engagement_profile WHERE engagement_id = %s",
                (engagement_id,),
            )
            profile_row = cursor.fetchone()
            cursor.execute(
                """
                SELECT *
                FROM annual_audit_program_item
                WHERE engagement_id = %s
                ORDER BY FIELD(phase, '承接与独立性', '计划', '循环执行', '完成'),
                         procedure_code
                """,
                (engagement_id,),
            )
            program_rows = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT review_level, decision, decision_note, scope_json,
                       reviewer_user_id, created_at
                FROM annual_review_decision
                WHERE engagement_id = %s
                ORDER BY id
                """,
                (engagement_id,),
            )
            reviews = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT b.*, kr.release_code, kr.release_version,
                       kr.status AS knowledge_release_status,
                       kr.effective_from AS knowledge_effective_from,
                       kr.effective_to AS knowledge_effective_to,
                       rs.ruleset_code, rs.version AS ruleset_version,
                       rs.status AS ruleset_status,
                       rs.effective_from AS ruleset_effective_from,
                       rs.effective_to AS ruleset_effective_to
                FROM annual_engagement_policy_binding b
                LEFT JOIN annual_knowledge_release kr ON kr.id = b.knowledge_release_id
                LEFT JOIN annual_audit_ruleset rs ON rs.id = b.ruleset_id
                WHERE b.engagement_id = %s AND b.binding_status = 'frozen'
                ORDER BY b.id DESC
                LIMIT 1
                """,
                (engagement_id,),
            )
            binding_row = cursor.fetchone()
    return (
        _profile_from_row(dict(profile_row) if profile_row else None),
        [_program_row(row) for row in program_rows],
        reviews,
        dict(binding_row) if binding_row else None,
    )


def _category_index(category_response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("code") or ""): dict(item)
        for item in category_response.get("categories") or []
        if isinstance(item, dict) and str(item.get("code") or "")
    }


def program_material_gaps(
    program_item: dict[str, Any],
    categories: dict[str, dict[str, Any]],
) -> list[str]:
    return [
        code
        for code in program_item.get("required_material_categories") or []
        if not bool((categories.get(str(code)) or {}).get("uploaded"))
    ]


def _program_completion_blockers(
    program_item: dict[str, Any],
    categories: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    code = str(program_item.get("procedure_code") or "")
    status = str(program_item.get("status") or "not_started")
    blockers: list[dict[str, Any]] = []
    if status not in {"completed", "not_applicable"}:
        blockers.append(
            {
                "code": f"program.{code}.status",
                "message": f"{code} {program_item.get('procedure_name')}尚未完成",
            }
        )
        return blockers
    if status == "not_applicable":
        if not _nonempty_text(program_item.get("not_applicable_reason")):
            blockers.append(
                {
                    "code": f"program.{code}.not_applicable_reason",
                    "message": f"{code} 标记为不适用但未说明原因",
                }
            )
        return blockers
    missing_materials = program_material_gaps(program_item, categories)
    if missing_materials:
        blockers.append(
            {
                "code": f"program.{code}.materials",
                "message": f"{code} 缺少必需资料：{', '.join(missing_materials)}",
                "missing_categories": missing_materials,
            }
        )
    if bool(program_item.get("requires_evidence")):
        evidence_errors = canonical_evidence_errors(program_item.get("evidence_refs"))
        if evidence_errors:
            blockers.append(
                {
                    "code": f"program.{code}.evidence",
                    "message": f"{code} 证据锚点不完整：{'；'.join(evidence_errors)}",
                }
            )
    if not _nonempty_text(program_item.get("conclusion_text")):
        blockers.append(
            {
                "code": f"program.{code}.conclusion",
                "message": f"{code} 缺少审计结论",
            }
        )
    return blockers


def _review_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        level = str(row.get("review_level") or "")
        if level in REVIEW_LEVELS:
            latest[level] = {
                "review_level": level,
                "decision": str(row.get("decision") or ""),
                "decision_note": str(row.get("decision_note") or ""),
                "scope": _loads(row.get("scope_json"), {}),
                "reviewer_user_id": str(row.get("reviewer_user_id") or ""),
                "created_at": _iso(row.get("created_at")),
            }
    return [
        latest.get(level)
        or {
            "review_level": level,
            "decision": "pending",
            "decision_note": "",
            "scope": {},
            "reviewer_user_id": "",
            "created_at": None,
        }
        for level in REVIEW_LEVELS
    ]


def _review_blockers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    summary = _review_summary(rows)
    for index, item in enumerate(summary):
        if item["decision"] != "approved":
            blockers.append(
                {
                    "code": f"review.{item['review_level']}",
                    "message": f"{item['review_level']}尚未批准项目",
                }
            )
        elif index:
            previous = summary[index - 1]
            if previous["decision"] != "approved":
                blockers.append(
                    {
                        "code": f"review.{item['review_level']}.sequence",
                        "message": f"{item['review_level']}缺少有效的上一级批准",
                    }
                )
            elif str(previous["created_at"] or "") > str(item["created_at"] or ""):
                blockers.append(
                    {
                        "code": f"review.{item['review_level']}.renewal",
                        "message": f"{item['review_level']}须在上一级最新复核后重新批准",
                    }
                )
    return blockers


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not _nonempty_text(value):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _binding_summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "binding_id": _as_int(row.get("id")),
        "binding_status": str(row.get("binding_status") or ""),
        "reporting_period_date": _iso(row.get("reporting_period_date")),
        "knowledge_release": {
            "release_code": str(row.get("release_code") or ""),
            "release_version": str(row.get("release_version") or ""),
            "status": str(row.get("knowledge_release_status") or ""),
            "effective_from": _iso(row.get("knowledge_effective_from")),
            "effective_to": _iso(row.get("knowledge_effective_to")),
        },
        "ruleset": {
            "ruleset_code": str(row.get("ruleset_code") or ""),
            "version": str(row.get("ruleset_version") or ""),
            "status": str(row.get("ruleset_status") or ""),
            "effective_from": _iso(row.get("ruleset_effective_from")),
            "effective_to": _iso(row.get("ruleset_effective_to")),
        },
        "bound_by": str(row.get("bound_by") or ""),
        "bound_at": _iso(row.get("bound_at")),
        "snapshot": _loads(row.get("snapshot_json"), {}),
    }


def _is_effective(
    start: Any,
    end: Any,
    at_date: date,
) -> bool:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    return (start_date is None or start_date <= at_date) and (
        end_date is None or at_date <= end_date
    )


def scope_matches_profile(scope: Any, profile: dict[str, Any]) -> bool:
    """Return whether a ruleset's explicit applicability includes this engagement."""

    values = scope if isinstance(scope, dict) else {}
    checks = {
        "entity_types": "entity_type",
        "accounting_frameworks": "accounting_framework",
        "industries": "industry_code",
        "audit_purposes": "audit_purpose",
    }
    for scope_key, profile_key in checks.items():
        allowed = values.get(scope_key)
        if not allowed:
            continue
        allowed_values = {
            _nonempty_text(item)
            for item in (allowed if isinstance(allowed, list) else [allowed])
            if _nonempty_text(item)
        }
        current_value = _nonempty_text(profile.get(profile_key))
        if not current_value or current_value not in allowed_values:
            return False
    return True


def _policy_blockers(binding_row: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not binding_row:
        return [
            {
                "code": "policy.binding",
                "message": "尚未冻结适用法规/知识发布和事务所规则集版本",
            }
        ]
    reporting_date = _parse_date(binding_row.get("reporting_period_date"))
    reporting_date = reporting_date or date.today()
    blockers: list[dict[str, Any]] = []
    if str(binding_row.get("knowledge_release_status") or "") != "published":
        blockers.append(
            {
                "code": "policy.knowledge_release",
                "message": "绑定的知识发布版本未获批准发布",
            }
        )
    elif not _is_effective(
        binding_row.get("knowledge_effective_from"),
        binding_row.get("knowledge_effective_to"),
        reporting_date,
    ):
        blockers.append(
            {
                "code": "policy.knowledge_effective",
                "message": "绑定的知识发布版本不适用于报告期",
            }
        )
    if str(binding_row.get("ruleset_status") or "") != "published":
        blockers.append(
            {
                "code": "policy.ruleset",
                "message": "绑定的规则集未获批准发布",
            }
        )
    elif not _is_effective(
        binding_row.get("ruleset_effective_from"),
        binding_row.get("ruleset_effective_to"),
        reporting_date,
    ):
        blockers.append(
            {
                "code": "policy.ruleset_effective",
                "message": "绑定的规则集不适用于报告期",
            }
        )
    return blockers


def _open_finding_summary(engagement_id: int, *, settings: Settings) -> dict[str, Any]:
    # A complete supplied workpaper case may be replayed more than once while
    # validating the browser flow.  Keep every historical finding row for
    # traceability, but count identical deterministic hits once at the release
    # gate.  Ordinary live engagements retain the original row-by-row semantics.
    case_workpaper = get_case_workpaper_summary(engagement_id, settings=settings)
    deduplicate_case_replay = bool(
        case_workpaper and case_workpaper.get("is_complete_case")
    )
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id, f.risk_level, f.finding_type, f.title,
                       f.description, f.amount, f.status
                FROM annual_finding f
                LEFT JOIN annual_finding_resolution r ON r.finding_id = f.id
                WHERE f.engagement_id = %s
                  AND f.status = 'open'
                  AND COALESCE(r.resolution_status, 'open') <> 'closed'
                ORDER BY FIELD(f.risk_level, 'high', 'medium', 'low'), f.id
                """,
                (engagement_id,),
            )
            findings = []
            seen: set[tuple[str, str, str, str]] = set()
            for row in cursor.fetchall():
                item = dict(row)
                if deduplicate_case_replay:
                    identity = (
                        str(item.get("finding_type") or ""),
                        str(item.get("title") or ""),
                        str(item.get("description") or ""),
                        str(item.get("amount") or ""),
                    )
                    if identity in seen:
                        continue
                    seen.add(identity)
                findings.append(item)
    return {
        "count": len(findings),
        "findings": [
            {
                "finding_id": _as_int(row.get("id")),
                "risk_level": str(row.get("risk_level") or ""),
                "title": str(row.get("title") or ""),
                "status": str(row.get("status") or ""),
            }
            for row in findings
        ],
    }


def _confirmation_blockers(engagement_id: int, *, settings: Settings) -> list[dict[str, Any]]:
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT procedure_code, counterparty_name, status
                FROM annual_confirmation
                WHERE engagement_id = %s AND status <> 'closed'
                ORDER BY id
                """,
                (engagement_id,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
    return [
        {
            "code": f"confirmation.{row['procedure_code']}.{index}",
            "message": f"{row['procedure_code']} 对 {row['counterparty_name']} 的函证尚未闭环",
        }
        for index, row in enumerate(rows, start=1)
    ]


def build_release_gate(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Evaluate all formal-release preconditions without changing state."""

    resolved = settings or get_settings()
    _ensure_execution_records(engagement_id, actor_user_id="system", settings=resolved)
    sync_case_workpaper_programs(
        engagement_id,
        actor_user_id="case_workpaper_import",
        settings=resolved,
    )
    engagement = get_engagement(engagement_id, settings=resolved)
    profile, program, reviews, binding = _load_state(engagement_id, settings=resolved)
    category_response = documents.get_case_doc_categories(engagement_id, settings=resolved)
    categories = _category_index(category_response)
    blockers = profile_blockers(profile)
    for item in program:
        blockers.extend(_program_completion_blockers(item, categories))
    blockers.extend(_review_blockers(reviews))
    blockers.extend(_policy_blockers(binding))
    active_binding_id = _as_int((binding or {}).get("id"))
    if active_binding_id:
        for item in program:
            if item["status"] in {"completed", "not_applicable"} and (
                _as_int(item.get("policy_binding_id")) != active_binding_id
            ):
                blockers.append(
                    {
                        "code": f"program.{item['procedure_code']}.policy_binding",
                        "message": (
                            f"{item['procedure_code']} 未使用当前冻结的规则与知识版本重新确认"
                        ),
                    }
                )
    open_findings = _open_finding_summary(engagement_id, settings=resolved)
    if open_findings["count"]:
        blockers.append(
            {
                "code": "findings.open",
                "message": f"仍有 {open_findings['count']} 项开放发现未解决或未复核",
                "finding_ids": [item["finding_id"] for item in open_findings["findings"]],
            }
        )
    blockers.extend(_confirmation_blockers(engagement_id, settings=resolved))
    return {
        "case_id": engagement_id,
        "engagement_status": str(engagement.get("status") or ""),
        "gate_status": "blocked" if blockers else "ready_for_signature",
        "blockers": blockers,
        "profile": profile,
        "program_summary": {
            "total": len(program),
            "completed": sum(1 for item in program if item["status"] == "completed"),
            "not_applicable": sum(1 for item in program if item["status"] == "not_applicable"),
            "open": sum(
                1
                for item in program
                if item["status"] not in {"completed", "not_applicable"}
            ),
        },
        "open_findings": open_findings,
        "reviews": _review_summary(reviews),
        "policy_binding": _binding_summary(binding),
        "case_workpaper": get_case_workpaper_summary(engagement_id, settings=resolved),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def evaluate_release_gate(
    engagement_id: int,
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Persist an auditable release-gate evaluation and return its outcome."""

    resolved = settings or get_settings()
    gate = build_release_gate(engagement_id, settings=resolved)
    snapshot = {
        "program_summary": gate["program_summary"],
        "open_findings": gate["open_findings"],
        "reviews": gate["reviews"],
        "policy_binding": gate["policy_binding"],
    }
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO annual_release_gate (
                  engagement_id, gate_status, blockers_json, snapshot_json, evaluated_by
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    engagement_id,
                    gate["gate_status"],
                    _dump(gate["blockers"]),
                    _dump(snapshot),
                    _nonempty_text(actor_user_id) or "system",
                ),
            )
            gate_id = _as_int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO ata_audit_log (
                  actor_user_id, engagement_id, action, target_type, target_id, details_json
                ) VALUES (%s, %s, 'evaluate_release_gate', 'annual_release_gate', %s, %s)
                """,
                (
                    _nonempty_text(actor_user_id) or "system",
                    engagement_id,
                    str(gate_id),
                    _dump({"gate_status": gate["gate_status"], "blocker_count": len(gate["blockers"])}),
                ),
            )
        connection.commit()
    return {**gate, "gate_id": gate_id}


def get_execution_snapshot(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return the operator-facing programme and a non-mutating release gate."""

    resolved = settings or get_settings()
    _ensure_execution_records(engagement_id, actor_user_id="system", settings=resolved)
    sync_case_workpaper_programs(
        engagement_id,
        actor_user_id="case_workpaper_import",
        settings=resolved,
    )
    profile, program, reviews, binding = _load_state(engagement_id, settings=resolved)
    category_response = documents.get_case_doc_categories(engagement_id, settings=resolved)
    categories = _category_index(category_response)
    enriched_program = [
        {
            **item,
            "missing_material_categories": program_material_gaps(item, categories),
        }
        for item in program
    ]
    return {
        "case_id": engagement_id,
        "program_version": PROGRAM_VERSION,
        "profile": profile,
        "document_categories": category_response.get("categories") or [],
        "program": enriched_program,
        "reviews": _review_summary(reviews),
        "policy_binding": _binding_summary(binding),
        "case_workpaper": get_case_workpaper_summary(engagement_id, settings=resolved),
        "release_gate": build_release_gate(engagement_id, settings=resolved),
    }


def update_engagement_profile(
    engagement_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Update the auditable engagement profile without accepting arbitrary state."""

    resolved = settings or get_settings()
    _ensure_execution_records(engagement_id, actor_user_id=actor_user_id, settings=resolved)
    supplied = payload.get("profile")
    values = dict(supplied) if isinstance(supplied, dict) else {}
    values.update({field: payload[field] for field in PROFILE_TEXT_FIELDS if field in payload})
    for field in ("acceptance_status", "independence_status"):
        if field in payload:
            values[field] = payload[field]
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_engagement_profile WHERE engagement_id = %s FOR UPDATE",
                (engagement_id,),
            )
            before_row = dict(cursor.fetchone() or {})
            before = _profile_from_row(before_row)
            profile = {
                key: value
                for key, value in before.items()
                if key not in {"profile_version", "updated_at", "acceptance_status", "independence_status"}
            }
            for field in PROFILE_TEXT_FIELDS:
                if field in values:
                    text = _nonempty_text(values[field])
                    if text:
                        profile[field] = text
                    else:
                        profile.pop(field, None)
            acceptance_status = str(
                values.get("acceptance_status", before["acceptance_status"])
            ).strip()
            independence_status = str(
                values.get("independence_status", before["independence_status"])
            ).strip()
            if acceptance_status not in ACCEPTANCE_STATUSES:
                raise ValueError("acceptance_status 必须为 pending、accepted、rejected 或 withdrawn")
            if independence_status not in INDEPENDENCE_STATUSES:
                raise ValueError(
                    "independence_status 必须为 pending、cleared、blocked 或 not_applicable"
                )
            cursor.execute(
                """
                UPDATE annual_engagement_profile
                SET profile_json = %s,
                    acceptance_status = %s,
                    independence_status = %s,
                    data_classification = %s,
                    data_residency = %s,
                    model_data_policy = %s,
                    profile_version = profile_version + 1,
                    updated_by = %s
                WHERE engagement_id = %s
                """,
                (
                    _dump(profile),
                    acceptance_status,
                    independence_status,
                    _nonempty_text(profile.get("data_classification")) or None,
                    _nonempty_text(profile.get("data_residency")) or None,
                    _nonempty_text(profile.get("model_data_policy")) or None,
                    _nonempty_text(actor_user_id) or "system",
                    engagement_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO ata_audit_log (
                  actor_user_id, engagement_id, action, target_type, target_id, details_json
                ) VALUES (%s, %s, 'update_engagement_profile', 'annual_engagement_profile', %s, %s)
                """,
                (
                    _nonempty_text(actor_user_id) or "system",
                    engagement_id,
                    str(engagement_id),
                    _dump({"before": before, "after": profile}),
                ),
            )
        connection.commit()
    return get_execution_snapshot(engagement_id, settings=resolved)


def update_program_item(
    engagement_id: int,
    procedure_code: str,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Update one programme row and enforce evidence/completion prerequisites."""

    resolved = settings or get_settings()
    code = _nonempty_text(procedure_code)
    if code not in procedure_codes():
        raise ValueError(f"未知审计程序：{code}")
    _ensure_execution_records(engagement_id, actor_user_id=actor_user_id, settings=resolved)
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM annual_audit_program_item
                WHERE engagement_id = %s AND procedure_code = %s
                FOR UPDATE
                """,
                (engagement_id, code),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"项目未初始化审计程序：{code}")
            before = _program_row(dict(row))
            status = _nonempty_text(payload.get("status", before["status"]))
            if status not in PROGRAM_STATUSES:
                raise ValueError(f"status 必须为：{', '.join(sorted(PROGRAM_STATUSES))}")
            evidence_refs = (
                payload["evidence_refs"] if "evidence_refs" in payload else before["evidence_refs"]
            )
            if not isinstance(evidence_refs, list):
                raise ValueError("evidence_refs 必须为数组")
            sample_plan = payload["sample_plan"] if "sample_plan" in payload else before["sample_plan"]
            alternative_procedures = (
                payload["alternative_procedures"]
                if "alternative_procedures" in payload
                else before["alternative_procedures"]
            )
            if not isinstance(sample_plan, (dict, list)):
                raise ValueError("sample_plan 必须为对象或数组")
            if not isinstance(alternative_procedures, (dict, list)):
                raise ValueError("alternative_procedures 必须为对象或数组")
            exception_count = _as_int(payload.get("exception_count", before["exception_count"]))
            if exception_count < 0:
                raise ValueError("exception_count 不能小于 0")
            conclusion_text = _nonempty_text(
                payload.get("conclusion_text", before["conclusion_text"])
            )
            not_applicable_reason = _nonempty_text(
                payload.get("not_applicable_reason", before["not_applicable_reason"])
            )
            if status == "not_applicable" and not not_applicable_reason:
                raise ValueError("标记为 not_applicable 时必须填写 not_applicable_reason")
            if status == "completed":
                category_response = documents.get_case_doc_categories(
                    engagement_id, settings=resolved
                )
                missing_materials = program_material_gaps(
                    before, _category_index(category_response)
                )
                if missing_materials:
                    raise WorkflowBlockedError(
                        [
                            {
                                "code": f"program.{code}.materials",
                                "message": f"缺少必需资料：{', '.join(missing_materials)}",
                            }
                        ]
                    )
                if bool(before["requires_evidence"]):
                    evidence_errors = validate_evidence_ownership(
                        engagement_id,
                        evidence_refs,
                        settings=resolved,
                    )
                    if evidence_errors:
                        raise WorkflowBlockedError(
                            [
                                {
                                    "code": f"program.{code}.evidence",
                                    "message": "；".join(evidence_errors),
                                }
                            ]
                        )
                if not conclusion_text:
                    raise ValueError("标记为 completed 时必须填写 conclusion_text")
            cursor.execute(
                """
                SELECT id
                FROM annual_engagement_policy_binding
                WHERE engagement_id = %s AND binding_status = 'frozen'
                ORDER BY id DESC
                LIMIT 1
                """,
                (engagement_id,),
            )
            binding_row = cursor.fetchone()
            binding_id = _as_int(binding_row.get("id")) if binding_row else None
            cursor.execute(
                """
                UPDATE annual_audit_program_item
                SET status = %s,
                    sample_plan_json = %s,
                    evidence_refs_json = %s,
                    exception_count = %s,
                    alternative_procedures_json = %s,
                    conclusion_text = %s,
                    not_applicable_reason = %s,
                    prepared_by = %s,
                    prepared_at = UTC_TIMESTAMP(6),
                    policy_binding_id = %s,
                    revision = revision + 1
                WHERE engagement_id = %s AND procedure_code = %s
                """,
                (
                    status,
                    _dump(sample_plan),
                    _dump(evidence_refs),
                    exception_count,
                    _dump(alternative_procedures),
                    conclusion_text or None,
                    not_applicable_reason or None,
                    _nonempty_text(actor_user_id) or "system",
                    binding_id,
                    engagement_id,
                    code,
                ),
            )
            cursor.execute(
                """
                SELECT *
                FROM annual_audit_program_item
                WHERE engagement_id = %s AND procedure_code = %s
                """,
                (engagement_id, code),
            )
            after = _program_row(dict(cursor.fetchone()))
            cursor.execute(
                """
                INSERT INTO annual_audit_program_event (
                  engagement_id, procedure_code, event_type, before_json, after_json, actor_user_id
                ) VALUES (%s, %s, 'update', %s, %s, %s)
                """,
                (
                    engagement_id,
                    code,
                    _dump(before),
                    _dump(after),
                    _nonempty_text(actor_user_id) or "system",
                ),
            )
            cursor.execute(
                """
                UPDATE audit_engagement
                SET status = CASE
                    WHEN status IN ('planning', 'pre_audit') THEN 'fieldwork'
                    ELSE status
                END
                WHERE id = %s
                """,
                (engagement_id,),
            )
        connection.commit()
    return after


def record_review_decision(
    engagement_id: int,
    payload: dict[str, Any],
    *,
    reviewer_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Record an immutable review decision with strict level ordering."""

    resolved = settings or get_settings()
    _ensure_execution_records(engagement_id, actor_user_id=reviewer_user_id, settings=resolved)
    level = _nonempty_text(payload.get("review_level"))
    decision = _nonempty_text(payload.get("decision"))
    if level not in REVIEW_LEVELS:
        raise ValueError(f"review_level 必须为：{', '.join(REVIEW_LEVELS)}")
    if decision not in REVIEW_DECISIONS:
        raise ValueError("decision 必须为 approved 或 returned")
    if decision == "returned" and not _nonempty_text(payload.get("decision_note")):
        raise ValueError("退回复核必须填写 decision_note")
    scope = payload.get("scope") or {}
    if not isinstance(scope, (dict, list)):
        raise ValueError("scope 必须为对象或数组")
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT review_level, decision
                FROM annual_review_decision
                WHERE engagement_id = %s
                ORDER BY id
                """,
                (engagement_id,),
            )
            current = _review_summary([dict(row) for row in cursor.fetchall()])
            position = REVIEW_LEVELS.index(level)
            if position:
                previous = current[position - 1]
                if previous["decision"] != "approved":
                    raise WorkflowBlockedError(
                        [
                            {
                                "code": f"review.{previous['review_level']}",
                                "message": "上一级复核尚未批准，不能越级批准",
                            }
                        ]
                    )
            cursor.execute(
                """
                INSERT INTO annual_review_decision (
                  engagement_id, review_level, decision, decision_note, scope_json, reviewer_user_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    engagement_id,
                    level,
                    decision,
                    _nonempty_text(payload.get("decision_note")) or None,
                    _dump(scope),
                    _nonempty_text(reviewer_user_id) or "system",
                ),
            )
            cursor.execute(
                """
                UPDATE audit_engagement
                SET status = CASE
                    WHEN %s = 'approved' AND %s = 'engagement_partner'
                    THEN 'ready_for_signature'
                    ELSE 'review'
                END
                WHERE id = %s
                """,
                (decision, level, engagement_id),
            )
        connection.commit()
    return get_execution_snapshot(engagement_id, settings=resolved)


def resolve_finding(
    engagement_id: int,
    finding_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Close a deterministic finding only with a reviewed evidence-backed resolution."""

    resolved = settings or get_settings()
    _ensure_execution_records(engagement_id, actor_user_id=actor_user_id, settings=resolved)
    resolution_status = _nonempty_text(payload.get("resolution_status", "closed"))
    if resolution_status not in {"open", "closed"}:
        raise ValueError("resolution_status 必须为 open 或 closed")
    resolution_type = _nonempty_text(payload.get("resolution_type"))
    resolution_note = _nonempty_text(payload.get("resolution_note"))
    evidence_refs = payload.get("evidence_refs") or []
    if not isinstance(evidence_refs, list):
        raise ValueError("evidence_refs 必须为数组")
    if resolution_status == "closed":
        if not resolution_type or not resolution_note:
            raise ValueError("关闭发现必须说明 resolution_type 和 resolution_note")
        evidence_errors = validate_evidence_ownership(
            engagement_id, evidence_refs, settings=resolved
        )
        if evidence_errors:
            raise WorkflowBlockedError(
                [{"code": "finding.resolution.evidence", "message": "；".join(evidence_errors)}]
            )
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM annual_finding
                WHERE id = %s AND engagement_id = %s
                FOR UPDATE
                """,
                (finding_id, engagement_id),
            )
            if not cursor.fetchone():
                raise ValueError("未找到当前项目的风险发现")
            cursor.execute(
                """
                INSERT INTO annual_finding_resolution (
                  engagement_id, finding_id, resolution_status, resolution_type,
                  resolution_note, evidence_refs_json, resolved_by, resolved_at,
                  reviewed_by, reviewed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s,
                  CASE WHEN %s = 'closed' THEN UTC_TIMESTAMP(6) ELSE NULL END,
                  CASE WHEN %s = 'closed' THEN %s ELSE NULL END,
                  CASE WHEN %s = 'closed' THEN UTC_TIMESTAMP(6) ELSE NULL END)
                ON DUPLICATE KEY UPDATE
                  resolution_status = VALUES(resolution_status),
                  resolution_type = VALUES(resolution_type),
                  resolution_note = VALUES(resolution_note),
                  evidence_refs_json = VALUES(evidence_refs_json),
                  resolved_by = VALUES(resolved_by),
                  resolved_at = VALUES(resolved_at),
                  reviewed_by = VALUES(reviewed_by),
                  reviewed_at = VALUES(reviewed_at)
                """,
                (
                    engagement_id,
                    finding_id,
                    resolution_status,
                    resolution_type or None,
                    resolution_note or None,
                    _dump(evidence_refs),
                    _nonempty_text(actor_user_id) or "system",
                    resolution_status,
                    resolution_status,
                    _nonempty_text(actor_user_id) or "system",
                    resolution_status,
                ),
            )
            cursor.execute(
                """
                UPDATE annual_finding
                SET status = %s
                WHERE id = %s AND engagement_id = %s
                """,
                ("resolved" if resolution_status == "closed" else "open", finding_id, engagement_id),
            )
            cursor.execute(
                """
                INSERT INTO ata_audit_log (
                  actor_user_id, engagement_id, action, target_type, target_id, details_json
                ) VALUES (%s, %s, 'resolve_finding', 'annual_finding', %s, %s)
                """,
                (
                    _nonempty_text(actor_user_id) or "system",
                    engagement_id,
                    str(finding_id),
                    _dump({"resolution_status": resolution_status, "resolution_type": resolution_type}),
                ),
            )
        connection.commit()
    return _open_finding_summary(engagement_id, settings=resolved)


def upsert_confirmation(
    engagement_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Record confirmation control, response reliability and alternative procedures."""

    resolved = settings or get_settings()
    _ensure_execution_records(engagement_id, actor_user_id=actor_user_id, settings=resolved)
    confirmation_id = _as_int(payload.get("confirmation_id"))
    code = _nonempty_text(payload.get("procedure_code"))
    if code not in procedure_codes():
        raise ValueError("函证必须关联已定义的审计程序")
    counterparty_name = _nonempty_text(payload.get("counterparty_name"))
    confirmation_type = _nonempty_text(payload.get("confirmation_type"))
    status = _nonempty_text(payload.get("status") or "planned")
    valid_statuses = {
        "planned",
        "prepared",
        "sent",
        "received",
        "exception",
        "alternative_performed",
        "closed",
    }
    if not counterparty_name or not confirmation_type:
        raise ValueError("counterparty_name 和 confirmation_type 不能为空")
    if status not in valid_statuses:
        raise ValueError(f"未知函证状态：{status}")
    request_refs = payload.get("request_evidence_refs") or []
    response_refs = payload.get("response_evidence_refs") or []
    alternative_procedures = payload.get("alternative_procedures") or {}
    if not isinstance(request_refs, list) or not isinstance(response_refs, list):
        raise ValueError("函证证据必须为数组")
    if not isinstance(alternative_procedures, (dict, list)):
        raise ValueError("alternative_procedures 必须为对象或数组")
    auditor_controlled = bool(payload.get("auditor_controlled_delivery"))
    conclusion_text = _nonempty_text(payload.get("conclusion_text"))
    if status in {"sent", "received", "exception"} and not auditor_controlled:
        raise ValueError("发函、回函和回函异常必须记录审计师控制的发送/接收链路")
    if request_refs:
        evidence_errors = validate_evidence_ownership(
            engagement_id, request_refs, settings=resolved
        )
        if evidence_errors:
            raise WorkflowBlockedError(
                [{"code": "confirmation.request_evidence", "message": "；".join(evidence_errors)}]
            )
    if response_refs:
        if not auditor_controlled:
            raise ValueError("有回函证据时必须记录审计师控制的发送/接收链路")
        evidence_errors = validate_evidence_ownership(
            engagement_id, response_refs, settings=resolved
        )
        if evidence_errors:
            raise WorkflowBlockedError(
                [{"code": "confirmation.response_evidence", "message": "；".join(evidence_errors)}]
            )
    if status == "closed":
        if not conclusion_text:
            raise ValueError("关闭函证事项必须填写 conclusion_text")
        if not response_refs and not alternative_procedures:
            raise ValueError("关闭函证事项必须有回函证据或替代程序")
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            if confirmation_id:
                cursor.execute(
                    """
                    SELECT id FROM annual_confirmation
                    WHERE id = %s AND engagement_id = %s
                    FOR UPDATE
                    """,
                    (confirmation_id, engagement_id),
                )
                if not cursor.fetchone():
                    raise ValueError("未找到当前项目函证事项")
                cursor.execute(
                    """
                    UPDATE annual_confirmation
                    SET procedure_code = %s, counterparty_name = %s, confirmation_type = %s,
                        status = %s, auditor_controlled_delivery = %s,
                        request_evidence_refs_json = %s, response_evidence_refs_json = %s,
                        reliability_assessment = %s, exception_description = %s,
                        alternative_procedures_json = %s, conclusion_text = %s,
                        prepared_by = %s
                    WHERE id = %s
                    """,
                    (
                        code,
                        counterparty_name,
                        confirmation_type,
                        status,
                        auditor_controlled,
                        _dump(request_refs),
                        _dump(response_refs),
                        _nonempty_text(payload.get("reliability_assessment")) or None,
                        _nonempty_text(payload.get("exception_description")) or None,
                        _dump(alternative_procedures),
                        conclusion_text or None,
                        _nonempty_text(actor_user_id) or "system",
                        confirmation_id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO annual_confirmation (
                      engagement_id, procedure_code, counterparty_name, confirmation_type,
                      status, auditor_controlled_delivery, request_evidence_refs_json,
                      response_evidence_refs_json, reliability_assessment, exception_description,
                      alternative_procedures_json, conclusion_text, prepared_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        engagement_id,
                        code,
                        counterparty_name,
                        confirmation_type,
                        status,
                        auditor_controlled,
                        _dump(request_refs),
                        _dump(response_refs),
                        _nonempty_text(payload.get("reliability_assessment")) or None,
                        _nonempty_text(payload.get("exception_description")) or None,
                        _dump(alternative_procedures),
                        conclusion_text or None,
                        _nonempty_text(actor_user_id) or "system",
                    ),
                )
                confirmation_id = _as_int(cursor.lastrowid)
        connection.commit()
    return {
        "case_id": engagement_id,
        "confirmation_id": confirmation_id,
        "status": status,
    }


def freeze_policy_binding(
    engagement_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Freeze approved knowledge and rules versions used for this engagement."""

    resolved = settings or get_settings()
    _ensure_execution_records(engagement_id, actor_user_id=actor_user_id, settings=resolved)
    knowledge_release_id = _as_int(payload.get("knowledge_release_id"))
    ruleset_id = _as_int(payload.get("ruleset_id"))
    if knowledge_release_id <= 0 or ruleset_id <= 0:
        raise ValueError("冻结规则依据时必须选择已发布的知识发布版本和规则集")
    engagement = get_engagement(engagement_id, settings=resolved)
    profile, _, _, _ = _load_state(engagement_id, settings=resolved)
    reporting_date = _parse_date(payload.get("reporting_period_date")) or engagement["period_end"]
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM annual_knowledge_release WHERE id = %s",
                (knowledge_release_id,),
            )
            knowledge_release = dict(cursor.fetchone() or {})
            cursor.execute(
                "SELECT * FROM annual_audit_ruleset WHERE id = %s",
                (ruleset_id,),
            )
            ruleset = dict(cursor.fetchone() or {})
            blockers: list[dict[str, Any]] = []
            if str(knowledge_release.get("status") or "") != "published":
                blockers.append(
                    {
                        "code": "policy.knowledge_release",
                        "message": "选择的知识发布版本未发布",
                    }
                )
            elif not _is_effective(
                knowledge_release.get("effective_from"),
                knowledge_release.get("effective_to"),
                reporting_date,
            ):
                blockers.append(
                    {
                        "code": "policy.knowledge_effective",
                        "message": "选择的知识发布版本不适用于报告期",
                    }
                )
            if str(ruleset.get("status") or "") != "published":
                blockers.append(
                    {
                        "code": "policy.ruleset",
                        "message": "选择的规则集未发布",
                    }
                )
            elif not _is_effective(
                ruleset.get("effective_from"),
                ruleset.get("effective_to"),
                reporting_date,
            ):
                blockers.append(
                    {
                        "code": "policy.ruleset_effective",
                        "message": "选择的规则集不适用于报告期",
                    }
                )
            ruleset_scope = _loads(ruleset.get("scope_json"), {})
            if not scope_matches_profile(ruleset_scope, profile):
                blockers.append(
                    {
                        "code": "policy.ruleset_scope",
                        "message": "选择的规则集不适用于当前项目画像",
                    }
                )
            if blockers:
                raise WorkflowBlockedError(blockers)
            snapshot = {
                "knowledge_release": {
                    "id": knowledge_release_id,
                    "release_code": knowledge_release.get("release_code"),
                    "release_version": knowledge_release.get("release_version"),
                    "approved_by": knowledge_release.get("approved_by"),
                    "approved_at": _iso(knowledge_release.get("approved_at")),
                },
                "ruleset": {
                    "id": ruleset_id,
                    "ruleset_code": ruleset.get("ruleset_code"),
                    "version": ruleset.get("version"),
                    "approved_by": ruleset.get("approved_by"),
                    "approved_at": _iso(ruleset.get("approved_at")),
                },
                "reporting_period_date": _iso(reporting_date),
            }
            cursor.execute(
                """
                INSERT INTO annual_engagement_policy_binding (
                  engagement_id, knowledge_release_id, ruleset_id, binding_status,
                  reporting_period_date, bound_by, bound_at, snapshot_json
                ) VALUES (%s, %s, %s, 'frozen', %s, %s, UTC_TIMESTAMP(6), %s)
                """,
                (
                    engagement_id,
                    knowledge_release_id,
                    ruleset_id,
                    reporting_date,
                    _nonempty_text(actor_user_id) or "system",
                    _dump(snapshot),
                ),
            )
            binding_id = _as_int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO ata_audit_log (
                  actor_user_id, engagement_id, action, target_type, target_id, details_json
                ) VALUES (%s, %s, 'freeze_policy_binding', 'annual_engagement_policy_binding', %s, %s)
                """,
                (
                    _nonempty_text(actor_user_id) or "system",
                    engagement_id,
                    str(binding_id),
                    _dump(snapshot),
                ),
            )
        connection.commit()
    return {
        "case_id": engagement_id,
        "binding_id": binding_id,
        "binding_status": "frozen",
        "snapshot": snapshot,
    }


def _valid_sha256(value: Any) -> bool:
    text = _nonempty_text(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def issue_audit_report(
    engagement_id: int,
    payload: dict[str, Any],
    *,
    signed_by: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Record human-attested formal issuance after every gate has passed."""

    resolved = settings or get_settings()
    if not bool(payload.get("signing_attestation")):
        raise ValueError("正式签发必须由具备资格的签字人员明确确认")
    report_artifact_ref = _nonempty_text(payload.get("report_artifact_ref"))
    report_artifact_sha256 = _nonempty_text(payload.get("report_artifact_sha256"))
    opinion_type = _nonempty_text(payload.get("opinion_type"))
    if not report_artifact_ref or not _valid_sha256(report_artifact_sha256):
        raise ValueError("正式签发必须提供已签名成果物引用及其 SHA-256")
    if opinion_type not in OPINION_TYPES:
        raise ValueError(f"opinion_type 必须为：{', '.join(sorted(OPINION_TYPES))}")
    signer = _nonempty_text(signed_by)
    if not signer:
        raise ValueError("缺少签发人身份")
    profile, _, _, _ = _load_state(engagement_id, settings=resolved)
    nominated_signers = {
        _nonempty_text(profile.get("signing_cpa_primary_user_id")),
        _nonempty_text(profile.get("signing_cpa_secondary_user_id")),
    } - {""}
    if nominated_signers and signer not in nominated_signers:
        raise WorkflowBlockedError(
            [
                {
                    "code": "issuance.signer",
                    "message": "当前签发人不在项目画像中冻结的签字注册会计师名单内",
                }
            ]
        )
    gate = evaluate_release_gate(
        engagement_id,
        actor_user_id=signer,
        settings=resolved,
    )
    if gate["gate_status"] != "ready_for_signature":
        raise WorkflowBlockedError(gate["blockers"])
    signed_at = datetime.now(timezone.utc)
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM annual_audit_issuance WHERE engagement_id = %s",
                (engagement_id,),
            )
            if cursor.fetchone():
                raise ValueError("该项目已有正式签发记录，不能重复签发")
            cursor.execute(
                """
                INSERT INTO annual_audit_issuance (
                  engagement_id, gate_id, report_artifact_ref, report_artifact_sha256,
                  signing_attestation, signed_by, signed_at, opinion_type, issuance_note
                ) VALUES (%s, %s, %s, %s, TRUE, %s, %s, %s, %s)
                """,
                (
                    engagement_id,
                    gate["gate_id"],
                    report_artifact_ref,
                    report_artifact_sha256.lower(),
                    signer,
                    signed_at.replace(tzinfo=None),
                    opinion_type,
                    _nonempty_text(payload.get("issuance_note")) or None,
                ),
            )
            issuance_id = _as_int(cursor.lastrowid)
            cursor.execute(
                "UPDATE audit_engagement SET status = 'issued' WHERE id = %s",
                (engagement_id,),
            )
            cursor.execute(
                """
                INSERT INTO ata_audit_log (
                  actor_user_id, engagement_id, action, target_type, target_id, details_json
                ) VALUES (%s, %s, 'issue_audit_report', 'annual_audit_issuance', %s, %s)
                """,
                (
                    signer,
                    engagement_id,
                    str(issuance_id),
                    _dump(
                        {
                            "gate_id": gate["gate_id"],
                            "opinion_type": opinion_type,
                            "report_artifact_sha256": report_artifact_sha256.lower(),
                        }
                    ),
                ),
            )
        connection.commit()
    return {
        "case_id": engagement_id,
        "issuance_id": issuance_id,
        "status": "issued",
        "signed_at": signed_at.isoformat(),
        "opinion_type": opinion_type,
    }


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def archive_audit_engagement(
    engagement_id: int,
    payload: dict[str, Any],
    *,
    actor_user_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Close the project with an immutable archive manifest and retention date."""

    resolved = settings or get_settings()
    manifest_ref = _nonempty_text(payload.get("archive_manifest_ref"))
    manifest_hash = _nonempty_text(payload.get("archive_manifest_sha256"))
    if not manifest_ref or not _valid_sha256(manifest_hash):
        raise ValueError("归档必须提供完整归档清单引用及其 SHA-256")
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, signed_at
                FROM annual_audit_issuance
                WHERE engagement_id = %s
                """,
                (engagement_id,),
            )
            issuance = dict(cursor.fetchone() or {})
            if not issuance:
                raise WorkflowBlockedError(
                    [{"code": "archive.issuance", "message": "正式签发后才能归档"}]
                )
            signed_at = issuance.get("signed_at")
            signed_date = signed_at.date() if isinstance(signed_at, datetime) else date.today()
            minimum_retention = _add_years(signed_date, 10)
            retention_until = _parse_date(payload.get("retention_until")) or minimum_retention
            if retention_until < minimum_retention:
                raise ValueError("审计档案保管期限不得少于签发日起十年")
            cursor.execute(
                "SELECT id FROM annual_audit_archive WHERE engagement_id = %s",
                (engagement_id,),
            )
            if cursor.fetchone():
                raise ValueError("该项目已经归档")
            archive_completed_at = datetime.now(timezone.utc)
            archive_late = archive_completed_at.date() > signed_date + timedelta(days=60)
            cursor.execute(
                """
                INSERT INTO annual_audit_archive (
                  engagement_id, issuance_id, archive_manifest_ref, archive_manifest_sha256,
                  archive_completed_at, retention_until, archived_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    engagement_id,
                    _as_int(issuance.get("id")),
                    manifest_ref,
                    manifest_hash.lower(),
                    archive_completed_at.replace(tzinfo=None),
                    retention_until,
                    _nonempty_text(actor_user_id) or "system",
                ),
            )
            archive_id = _as_int(cursor.lastrowid)
            cursor.execute(
                "UPDATE audit_engagement SET status = 'archived' WHERE id = %s",
                (engagement_id,),
            )
            cursor.execute(
                """
                INSERT INTO ata_audit_log (
                  actor_user_id, engagement_id, action, target_type, target_id, details_json
                ) VALUES (%s, %s, 'archive_audit_engagement', 'annual_audit_archive', %s, %s)
                """,
                (
                    _nonempty_text(actor_user_id) or "system",
                    engagement_id,
                    str(archive_id),
                    _dump(
                        {
                            "retention_until": retention_until,
                            "archive_late": archive_late,
                            "archive_manifest_sha256": manifest_hash.lower(),
                        }
                    ),
                ),
            )
        connection.commit()
    return {
        "case_id": engagement_id,
        "archive_id": archive_id,
        "status": "archived",
        "retention_until": retention_until.isoformat(),
        "archive_late": archive_late,
    }


__all__ = [
    "ACCEPTANCE_STATUSES",
    "INDEPENDENCE_STATUSES",
    "OPINION_TYPES",
    "PROGRAM_STATUSES",
    "REVIEW_LEVELS",
    "WorkflowBlockedError",
    "archive_audit_engagement",
    "bootstrap_execution",
    "build_release_gate",
    "canonical_evidence_errors",
    "evaluate_release_gate",
    "freeze_policy_binding",
    "get_execution_snapshot",
    "issue_audit_report",
    "profile_blockers",
    "record_review_decision",
    "resolve_finding",
    "scope_matches_profile",
    "update_engagement_profile",
    "update_program_item",
    "upsert_confirmation",
    "validate_evidence_ownership",
]
