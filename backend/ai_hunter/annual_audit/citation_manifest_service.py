"""Immutable, version-scoped citation manifests for annual audit reports.

The chat heavy payload remains the delivery representation for a response.
This service is the durable audit record for a generated annual report
version: it freezes the finding, rule context and source anchors behind each
citation. It deliberately does not reuse PostgreSQL report_citation_map:
that table has a foreign key to kg_claim, while deterministic annual findings
belong to the isolated MySQL annual domain.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .storage import mysql_connection


DEFAULT_REPORT_TYPE = "annual_audit_draft"
ANCHOR_STATUSES = frozenset({"bound", "partial", "unbound", "no_evidence"})


class CitationManifestError(ValueError):
    """Raised when an annual report citation manifest is malformed or unsafe."""


class CitationManifestConflictError(CitationManifestError):
    """Raised when a caller tries to mutate an immutable report version."""


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _bounded_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    required: bool = False,
) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise CitationManifestError(f"{field} 不能为空")
    if len(text) > max_length:
        raise CitationManifestError(f"{field} 不能超过 {max_length} 个字符")
    return text


def _required_positive_id(value: Any, *, field: str) -> int:
    identifier = _integer(value)
    if identifier <= 0:
        raise CitationManifestError(f"{field} 必须是正整数")
    return identifier


def _canonical_value(value: Any) -> Any:
    """Return a recursively JSON-safe value with deterministic map ordering."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CitationManifestError("引用快照不能包含非有限数值")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key in normalized:
                raise CitationManifestError("引用快照包含冲突的对象键")
            normalized[key] = _canonical_value(raw_value)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized_items = [_canonical_value(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    raise CitationManifestError(
        f"引用快照包含不支持的数据类型：{type(value).__name__}"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _final_report_ref_hash(value: str) -> str:
    """Index opaque delivery refs without imposing a short MySQL prefix."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_object(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CitationManifestError(f"{field} 必须是对象")
    normalized = _canonical_value(value)
    if not isinstance(normalized, dict):
        raise CitationManifestError(f"{field} 必须是对象")
    return normalized


def _evidence_snapshot(value: Any) -> list[dict[str, Any]]:
    """Normalize the frozen source anchors without inventing missing fields."""

    if value is None:
        return []
    raw_items: Sequence[Any]
    if isinstance(value, Mapping):
        embedded = value.get("evidences")
        raw_items = embedded if isinstance(embedded, Sequence) and not isinstance(
            embedded, (str, bytes, bytearray)
        ) else [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        raw_items = value
    else:
        raise CitationManifestError("evidence_snapshot 必须是证据对象或证据对象列表")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            raise CitationManifestError(f"evidence_snapshot[{index}] 必须是对象")
        canonical = _canonical_value(item)
        if not isinstance(canonical, dict):
            raise CitationManifestError(f"evidence_snapshot[{index}] 必须是对象")
        normalized.append(canonical)
    return normalized


def _is_bound_anchor(item: Mapping[str, Any]) -> bool:
    """Use the canonical annual anchor contract; never infer a source ID."""

    file_id = _integer(item.get("source_file_id") or item.get("file_id"))
    page_id = _integer(item.get("source_page_id"))
    chunk_id = _bounded_text(
        item.get("source_chunk_id") or item.get("chunk_id"),
        field="source_chunk_id",
        max_length=256,
    )
    return file_id > 0 and page_id > 0 and bool(chunk_id)


def derive_anchor_status(evidence_snapshot: Any) -> str:
    """Classify frozen anchors as fully bound, partial, unbound or absent."""

    evidences = _evidence_snapshot(evidence_snapshot)
    if not evidences:
        return "no_evidence"
    bound = [_is_bound_anchor(item) for item in evidences]
    if all(bound):
        return "bound"
    if any(bound):
        return "partial"
    return "unbound"


def build_annual_finding_key(
    *,
    engagement_id: int,
    annual_finding_id: int = 0,
    analysis_run_id: int = 0,
    finding_metadata: Mapping[str, Any] | None = None,
) -> str:
    """Build a deterministic key for the persisted annual finding snapshot."""

    case_id = _required_positive_id(engagement_id, field="engagement_id")
    metadata = _json_object(finding_metadata, field="finding_metadata")
    payload = {
        "engagement_id": case_id,
        "annual_finding_id": _integer(annual_finding_id),
        "analysis_run_id": _integer(analysis_run_id),
        "finding_metadata": metadata,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_manifest_snapshot_hash(entry: Mapping[str, Any]) -> str:
    """Hash the immutable part of one citation record.

    final_report_ref is intentionally excluded: it is bound after the
    immutable report evidence has already been frozen, so linking a chat
    heavy-payload must not change the audit snapshot hash.
    """

    payload = {
        "engagement_id": _required_positive_id(
            entry.get("engagement_id"), field="engagement_id"
        ),
        "annual_report_id": _required_positive_id(
            entry.get("annual_report_id"), field="annual_report_id"
        ),
        "report_type": _bounded_text(
            entry.get("report_type"),
            field="report_type",
            max_length=64,
            required=True,
        ),
        "report_version": _required_positive_id(
            entry.get("report_version"), field="report_version"
        ),
        "citation_id": _bounded_text(
            entry.get("citation_id"),
            field="citation_id",
            max_length=128,
            required=True,
        ),
        "section_key": _bounded_text(
            entry.get("section_key"),
            field="section_key",
            max_length=255,
        ),
        "paragraph_key": _bounded_text(
            entry.get("paragraph_key"),
            field="paragraph_key",
            max_length=255,
        ),
        "annual_finding_id": _integer(entry.get("annual_finding_id")),
        "annual_finding_key": _bounded_text(
            entry.get("annual_finding_key"),
            field="annual_finding_key",
            max_length=64,
            required=True,
        ).lower(),
        "analysis_run_id": _integer(entry.get("analysis_run_id")),
        "analysis_type": _bounded_text(
            entry.get("analysis_type"),
            field="analysis_type",
            max_length=64,
        ),
        "finding_type": _bounded_text(
            entry.get("finding_type"),
            field="finding_type",
            max_length=64,
        ),
        "risk_level": _bounded_text(
            entry.get("risk_level"),
            field="risk_level",
            max_length=16,
        ),
        "rule_metadata": _json_object(
            entry.get("rule_metadata"), field="rule_metadata"
        ),
        "finding_metadata": _json_object(
            entry.get("finding_metadata"), field="finding_metadata"
        ),
        "evidence_snapshot": _evidence_snapshot(entry.get("evidence_snapshot")),
        "anchor_status": _bounded_text(
            entry.get("anchor_status"),
            field="anchor_status",
            max_length=32,
            required=True,
        ),
    }
    if payload["anchor_status"] not in ANCHOR_STATUSES:
        raise CitationManifestError("anchor_status 不在允许范围内")
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def build_manifest_entry(
    *,
    engagement_id: int,
    annual_report_id: int,
    report_version: int,
    citation_id: str | int,
    report_type: str = DEFAULT_REPORT_TYPE,
    section_key: str = "",
    paragraph_key: str = "",
    annual_finding_id: int | None = None,
    annual_finding_key: str = "",
    analysis_run_id: int | None = None,
    analysis_type: str = "",
    finding_type: str = "",
    risk_level: str = "",
    rule_metadata: Mapping[str, Any] | None = None,
    finding_metadata: Mapping[str, Any] | None = None,
    evidence_snapshot: Any = None,
    anchor_status: str = "",
    final_report_ref: str = "",
) -> dict[str, Any]:
    """Build a JSON-safe immutable manifest entry without database I/O."""

    finding_id = _integer(annual_finding_id)
    run_id = _integer(analysis_run_id)
    if finding_id < 0 or run_id < 0:
        raise CitationManifestError("annual_finding_id 和 analysis_run_id 不能为负数")
    normalized_finding_metadata = _json_object(
        finding_metadata, field="finding_metadata"
    )
    normalized_evidence = _evidence_snapshot(evidence_snapshot)
    requested_status = _bounded_text(
        anchor_status,
        field="anchor_status",
        max_length=32,
    )
    if requested_status and requested_status not in ANCHOR_STATUSES:
        raise CitationManifestError("anchor_status 不在允许范围内")
    effective_status = requested_status or derive_anchor_status(normalized_evidence)
    supplied_finding_key = _bounded_text(
        annual_finding_key,
        field="annual_finding_key",
        max_length=64,
    ).lower()
    if supplied_finding_key and not _valid_sha256(supplied_finding_key):
        raise CitationManifestError("annual_finding_key 必须是 SHA-256 十六进制摘要")

    entry = {
        "engagement_id": _required_positive_id(
            engagement_id, field="engagement_id"
        ),
        "annual_report_id": _required_positive_id(
            annual_report_id, field="annual_report_id"
        ),
        "report_type": _bounded_text(
            report_type,
            field="report_type",
            max_length=64,
            required=True,
        ),
        "report_version": _required_positive_id(
            report_version, field="report_version"
        ),
        "citation_id": _bounded_text(
            citation_id,
            field="citation_id",
            max_length=128,
            required=True,
        ),
        "section_key": _bounded_text(
            section_key,
            field="section_key",
            max_length=255,
        ),
        "paragraph_key": _bounded_text(
            paragraph_key,
            field="paragraph_key",
            max_length=255,
        ),
        "annual_finding_id": finding_id,
        "annual_finding_key": supplied_finding_key
        or build_annual_finding_key(
            engagement_id=_required_positive_id(
                engagement_id, field="engagement_id"
            ),
            annual_finding_id=finding_id,
            analysis_run_id=run_id,
            finding_metadata=normalized_finding_metadata,
        ),
        "analysis_run_id": run_id,
        "analysis_type": _bounded_text(
            analysis_type,
            field="analysis_type",
            max_length=64,
        ),
        "finding_type": _bounded_text(
            finding_type,
            field="finding_type",
            max_length=64,
        ),
        "risk_level": _bounded_text(
            risk_level,
            field="risk_level",
            max_length=16,
        ),
        "rule_metadata": _json_object(rule_metadata, field="rule_metadata"),
        "finding_metadata": normalized_finding_metadata,
        "evidence_snapshot": normalized_evidence,
        "anchor_status": effective_status,
        "final_report_ref": _bounded_text(
            final_report_ref,
            field="final_report_ref",
            max_length=1024,
        ),
    }
    entry["snapshot_hash"] = build_manifest_snapshot_hash(entry)
    return entry


def _normalize_entry(
    raw_entry: Mapping[str, Any],
    *,
    engagement_id: int,
    annual_report_id: int,
    report_type: str,
    report_version: int,
    final_report_ref: str,
) -> dict[str, Any]:
    if not isinstance(raw_entry, Mapping):
        raise CitationManifestError("manifest entries 必须是对象列表")

    for field, expected in (
        ("engagement_id", engagement_id),
        ("annual_report_id", annual_report_id),
        ("report_type", report_type),
        ("report_version", report_version),
    ):
        supplied = raw_entry.get(field, expected)
        if str(supplied) != str(expected):
            raise CitationManifestError(f"manifest entry 的 {field} 与报告版本不一致")

    raw_ref = _bounded_text(
        raw_entry.get("final_report_ref"),
        field="final_report_ref",
        max_length=1024,
    )
    if raw_ref and final_report_ref and raw_ref != final_report_ref:
        raise CitationManifestError("manifest entry 的 final_report_ref 与本次绑定不一致")
    entry = build_manifest_entry(
        engagement_id=engagement_id,
        annual_report_id=annual_report_id,
        report_type=report_type,
        report_version=report_version,
        citation_id=raw_entry.get("citation_id"),
        section_key=raw_entry.get("section_key", ""),
        paragraph_key=raw_entry.get("paragraph_key", ""),
        annual_finding_id=raw_entry.get("annual_finding_id"),
        annual_finding_key=raw_entry.get("annual_finding_key", ""),
        analysis_run_id=raw_entry.get("analysis_run_id"),
        analysis_type=raw_entry.get("analysis_type", ""),
        finding_type=raw_entry.get("finding_type", ""),
        risk_level=raw_entry.get("risk_level", ""),
        rule_metadata=raw_entry.get("rule_metadata"),
        finding_metadata=raw_entry.get("finding_metadata"),
        evidence_snapshot=raw_entry.get("evidence_snapshot"),
        anchor_status=raw_entry.get("anchor_status", ""),
        final_report_ref=final_report_ref or raw_ref,
    )
    supplied_hash = _bounded_text(
        raw_entry.get("snapshot_hash"),
        field="snapshot_hash",
        max_length=64,
    ).lower()
    if supplied_hash and supplied_hash != entry["snapshot_hash"]:
        raise CitationManifestError("manifest entry 的 snapshot_hash 与冻结内容不一致")
    return entry


def _lock_report_version(
    cursor: Any,
    *,
    engagement_id: int,
    annual_report_id: int,
    report_type: str,
    report_version: int,
) -> None:
    cursor.execute(
        """
        SELECT id
        FROM audit_report
        WHERE id = %s
          AND engagement_id = %s
          AND report_type = %s
          AND report_version = %s
        FOR UPDATE
        """,
        (annual_report_id, engagement_id, report_type, report_version),
    )
    if not cursor.fetchone():
        raise CitationManifestError("报告不存在，或不属于指定项目/版本")


def _verify_finding_scope(
    cursor: Any,
    *,
    entry: Mapping[str, Any],
) -> None:
    """Reject manually supplied foreign IDs that cross the annual engagement."""

    engagement_id = _integer(entry.get("engagement_id"))
    finding_id = _integer(entry.get("annual_finding_id"))
    run_id = _integer(entry.get("analysis_run_id"))
    analysis_type = str(entry.get("analysis_type") or "")

    if finding_id:
        cursor.execute(
            """
            SELECT f.analysis_run_id, ar.analysis_type
            FROM annual_finding f
            JOIN annual_analysis_run ar ON ar.id = f.analysis_run_id
            WHERE f.id = %s AND f.engagement_id = %s
            """,
            (finding_id, engagement_id),
        )
        finding = cursor.fetchone()
        if not finding:
            raise CitationManifestError("annual_finding_id 不属于指定项目")
        actual_run_id = _integer(finding.get("analysis_run_id"))
        if not run_id:
            raise CitationManifestError("annual_finding_id 必须同时记录 analysis_run_id")
        if run_id != actual_run_id:
            raise CitationManifestError("annual_finding_id 与 analysis_run_id 不匹配")
        actual_type = str(finding.get("analysis_type") or "")
        if analysis_type and actual_type and analysis_type != actual_type:
            raise CitationManifestError("analysis_type 与分析运行不匹配")

    if run_id:
        cursor.execute(
            """
            SELECT analysis_type
            FROM annual_analysis_run
            WHERE id = %s AND engagement_id = %s
            """,
            (run_id, engagement_id),
        )
        analysis = cursor.fetchone()
        if not analysis:
            raise CitationManifestError("analysis_run_id 不属于指定项目")
        actual_type = str(analysis.get("analysis_type") or "")
        if analysis_type and actual_type and analysis_type != actual_type:
            raise CitationManifestError("analysis_type 与分析运行不匹配")


def _row_to_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    def loads(value: Any, fallback: Any) -> Any:
        if value is None:
            return fallback
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return fallback
        return value

    return {
        "id": _integer(row.get("id")),
        "engagement_id": _integer(row.get("engagement_id")),
        "annual_report_id": _integer(row.get("annual_report_id")),
        "report_type": str(row.get("report_type") or ""),
        "report_version": _integer(row.get("report_version")),
        "citation_id": str(row.get("citation_id") or ""),
        "section_key": str(row.get("section_key") or ""),
        "paragraph_key": str(row.get("paragraph_key") or ""),
        "annual_finding_id": _integer(row.get("annual_finding_id")),
        "annual_finding_key": str(row.get("annual_finding_key") or ""),
        "analysis_run_id": _integer(row.get("analysis_run_id")),
        "analysis_type": str(row.get("analysis_type") or ""),
        "finding_type": str(row.get("finding_type") or ""),
        "risk_level": str(row.get("risk_level") or ""),
        "rule_metadata": loads(row.get("rule_metadata_json"), {}),
        "finding_metadata": loads(row.get("finding_metadata_json"), {}),
        "evidence_snapshot": loads(row.get("evidence_snapshot_json"), []),
        "anchor_status": str(row.get("anchor_status") or ""),
        "snapshot_hash": str(row.get("snapshot_hash") or ""),
        "final_report_ref": str(row.get("final_report_ref") or ""),
        "created_at": (
            row["created_at"].isoformat()
            if isinstance(row.get("created_at"), (date, datetime))
            else row.get("created_at")
        ),
        "updated_at": (
            row["updated_at"].isoformat()
            if isinstance(row.get("updated_at"), (date, datetime))
            else row.get("updated_at")
        ),
    }


def _select_entries(
    cursor: Any,
    *,
    engagement_id: int,
    annual_report_id: int,
    report_type: str,
    report_version: int,
    citation_id: str = "",
    final_report_ref: str = "",
) -> list[dict[str, Any]]:
    conditions = [
        "m.engagement_id = %s",
        "m.annual_report_id = %s",
        "m.report_type = %s",
        "m.report_version = %s",
    ]
    params: list[Any] = [
        engagement_id,
        annual_report_id,
        report_type,
        report_version,
    ]
    if citation_id:
        conditions.append("m.citation_id = %s")
        params.append(citation_id)
    delivery_join = ""
    if final_report_ref:
        delivery_join = """
        JOIN annual_report_citation_delivery_ref d
          ON d.engagement_id = m.engagement_id
         AND d.annual_report_id = m.annual_report_id
         AND d.report_type = m.report_type
         AND d.report_version = m.report_version
        """
        conditions.extend(
            [
                "d.final_report_ref_hash = %s",
                "d.final_report_ref = %s",
            ]
        )
        params.extend([_final_report_ref_hash(final_report_ref), final_report_ref])
    cursor.execute(
        f"""
        SELECT m.*
        FROM annual_report_citation_manifest m
        {delivery_join}
        JOIN audit_report r
          ON r.id = m.annual_report_id
         AND r.engagement_id = m.engagement_id
         AND r.report_type = m.report_type
         AND r.report_version = m.report_version
        WHERE {' AND '.join(conditions)}
        ORDER BY m.id
        """,
        tuple(params),
    )
    return [_row_to_entry(dict(row)) for row in cursor.fetchall()]


def persist_report_citation_manifest(
    *,
    engagement_id: int,
    annual_report_id: int,
    report_version: int,
    entries: Iterable[Mapping[str, Any]],
    report_type: str = DEFAULT_REPORT_TYPE,
    final_report_ref: str = "",
    complete_manifest: bool = True,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Persist a complete immutable manifest for exactly one report version.

    Retrying the same generation is idempotent. A changed snapshot, a missing
    prior citation in a complete retry, or a citation from another engagement
    raises a conflict instead of silently mutating the report's audit trail.
    """

    case_id = _required_positive_id(engagement_id, field="engagement_id")
    report_id = _required_positive_id(annual_report_id, field="annual_report_id")
    version = _required_positive_id(report_version, field="report_version")
    normalized_type = _bounded_text(
        report_type,
        field="report_type",
        max_length=64,
        required=True,
    )
    normalized_ref = _bounded_text(
        final_report_ref,
        field="final_report_ref",
        max_length=1024,
    )
    normalized_entries = [
        _normalize_entry(
            entry,
            engagement_id=case_id,
            annual_report_id=report_id,
            report_type=normalized_type,
            report_version=version,
            final_report_ref=normalized_ref,
        )
        for entry in entries
    ]
    citation_ids = [entry["citation_id"] for entry in normalized_entries]
    if len(citation_ids) != len(set(citation_ids)):
        raise CitationManifestError("同一报告版本内 citation_id 必须唯一")

    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            _lock_report_version(
                cursor,
                engagement_id=case_id,
                annual_report_id=report_id,
                report_type=normalized_type,
                report_version=version,
            )
            cursor.execute(
                """
                SELECT citation_id, snapshot_hash, final_report_ref
                FROM annual_report_citation_manifest
                WHERE engagement_id = %s
                  AND annual_report_id = %s
                  AND report_type = %s
                  AND report_version = %s
                FOR UPDATE
                """,
                (case_id, report_id, normalized_type, version),
            )
            existing_rows = [dict(row) for row in cursor.fetchall()]
            existing_by_citation = {
                str(row.get("citation_id") or ""): row for row in existing_rows
            }
            incoming_ids = set(citation_ids)
            if complete_manifest and existing_by_citation and set(existing_by_citation) != incoming_ids:
                raise CitationManifestConflictError(
                    "该报告版本已有不同的完整引用清单，不能覆盖或删减"
                )

            for entry in normalized_entries:
                _verify_finding_scope(cursor, entry=entry)
                existing = existing_by_citation.get(entry["citation_id"])
                if existing:
                    if str(existing.get("snapshot_hash") or "") != entry["snapshot_hash"]:
                        raise CitationManifestConflictError(
                            f"citation_id={entry['citation_id']} 的证据快照已冻结"
                        )
                    existing_ref = str(existing.get("final_report_ref") or "")
                    effective_ref = entry["final_report_ref"]
                    if existing_ref and effective_ref and existing_ref != effective_ref:
                        raise CitationManifestConflictError(
                            "该报告版本已绑定其他 final_report_ref"
                        )
                    if effective_ref and not existing_ref:
                        cursor.execute(
                            """
                            UPDATE annual_report_citation_manifest
                            SET final_report_ref = %s
                            WHERE engagement_id = %s
                              AND annual_report_id = %s
                              AND report_type = %s
                              AND report_version = %s
                              AND citation_id = %s
                              AND (final_report_ref IS NULL OR final_report_ref = '')
                            """,
                            (
                                effective_ref,
                                case_id,
                                report_id,
                                normalized_type,
                                version,
                                entry["citation_id"],
                            ),
                        )
                    continue

                cursor.execute(
                    """
                    INSERT INTO annual_report_citation_manifest (
                      engagement_id, annual_report_id, report_type, report_version,
                      citation_id, section_key, paragraph_key, annual_finding_id,
                      annual_finding_key, analysis_run_id, analysis_type, finding_type,
                      risk_level, rule_metadata_json, finding_metadata_json,
                      evidence_snapshot_json, anchor_status, snapshot_hash,
                      final_report_ref
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        case_id,
                        report_id,
                        normalized_type,
                        version,
                        entry["citation_id"],
                        entry["section_key"],
                        entry["paragraph_key"],
                        entry["annual_finding_id"] or None,
                        entry["annual_finding_key"],
                        entry["analysis_run_id"] or None,
                        entry["analysis_type"] or None,
                        entry["finding_type"] or None,
                        entry["risk_level"] or None,
                        _canonical_json(entry["rule_metadata"]),
                        _canonical_json(entry["finding_metadata"]),
                        _canonical_json(entry["evidence_snapshot"]),
                        entry["anchor_status"],
                        entry["snapshot_hash"],
                        entry["final_report_ref"] or None,
                    ),
                )
            connection.commit()

    if normalized_ref:
        bind_final_report_ref(
            engagement_id=case_id,
            annual_report_id=report_id,
            report_type=normalized_type,
            report_version=version,
            final_report_ref=normalized_ref,
            settings=resolved,
        )
    return fetch_report_citation_manifest(
        engagement_id=case_id,
        annual_report_id=report_id,
        report_type=normalized_type,
        report_version=version,
        settings=resolved,
    )


def fetch_report_citation_manifest(
    *,
    engagement_id: int,
    annual_report_id: int,
    report_version: int,
    report_type: str = DEFAULT_REPORT_TYPE,
    citation_id: str = "",
    final_report_ref: str = "",
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Fetch manifest entries only when report ID, case and version all match."""

    case_id = _required_positive_id(engagement_id, field="engagement_id")
    report_id = _required_positive_id(annual_report_id, field="annual_report_id")
    version = _required_positive_id(report_version, field="report_version")
    normalized_type = _bounded_text(
        report_type,
        field="report_type",
        max_length=64,
        required=True,
    )
    normalized_citation = _bounded_text(
        citation_id,
        field="citation_id",
        max_length=128,
    )
    normalized_ref = _bounded_text(
        final_report_ref,
        field="final_report_ref",
        max_length=1024,
    )
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            return _select_entries(
                cursor,
                engagement_id=case_id,
                annual_report_id=report_id,
                report_type=normalized_type,
                report_version=version,
                citation_id=normalized_citation,
                final_report_ref=normalized_ref,
            )


def resolve_final_report_ref_citation_manifest(
    *,
    engagement_id: int,
    final_report_ref: str,
    citation_id: str = "",
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Resolve a message-scoped report ref to its frozen citation entries.

    The delivery-ref table permits several immutable chat messages to deliver
    the same report version. It is intentionally queried with the engagement
    scope and an opaque ref rather than accepting a client-supplied report ID.
    """

    case_id = _required_positive_id(engagement_id, field="engagement_id")
    normalized_ref = _bounded_text(
        final_report_ref,
        field="final_report_ref",
        max_length=1024,
        required=True,
    )
    normalized_citation = _bounded_text(
        citation_id,
        field="citation_id",
        max_length=128,
    )
    conditions = [
        "d.engagement_id = %s",
        "d.final_report_ref_hash = %s",
        "d.final_report_ref = %s",
    ]
    params: list[Any] = [
        case_id,
        _final_report_ref_hash(normalized_ref),
        normalized_ref,
    ]
    if normalized_citation:
        conditions.append("m.citation_id = %s")
        params.append(normalized_citation)
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT m.*
                FROM annual_report_citation_delivery_ref d
                JOIN annual_report_citation_manifest m
                  ON m.engagement_id = d.engagement_id
                 AND m.annual_report_id = d.annual_report_id
                 AND m.report_type = d.report_type
                 AND m.report_version = d.report_version
                JOIN audit_report r
                  ON r.id = m.annual_report_id
                 AND r.engagement_id = m.engagement_id
                 AND r.report_type = m.report_type
                 AND r.report_version = m.report_version
                WHERE {' AND '.join(conditions)}
                ORDER BY m.id
                """,
                tuple(params),
            )
            entries = [_row_to_entry(dict(row)) for row in cursor.fetchall()]
    for entry in entries:
        entry["final_report_ref"] = normalized_ref
    return entries


def bind_final_report_ref(
    *,
    engagement_id: int,
    annual_report_id: int,
    report_version: int,
    final_report_ref: str,
    report_type: str = DEFAULT_REPORT_TYPE,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Bind one delivery ref without changing frozen citation snapshots."""

    case_id = _required_positive_id(engagement_id, field="engagement_id")
    report_id = _required_positive_id(annual_report_id, field="annual_report_id")
    version = _required_positive_id(report_version, field="report_version")
    normalized_type = _bounded_text(
        report_type,
        field="report_type",
        max_length=64,
        required=True,
    )
    normalized_ref = _bounded_text(
        final_report_ref,
        field="final_report_ref",
        max_length=1024,
        required=True,
    )
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            _lock_report_version(
                cursor,
                engagement_id=case_id,
                annual_report_id=report_id,
                report_type=normalized_type,
                report_version=version,
            )
            cursor.execute(
                """
                SELECT annual_report_id, report_type, report_version, final_report_ref
                FROM annual_report_citation_delivery_ref
                WHERE engagement_id = %s AND final_report_ref_hash = %s
                FOR UPDATE
                """,
                (case_id, _final_report_ref_hash(normalized_ref)),
            )
            existing_delivery = cursor.fetchone()
            if existing_delivery:
                if (
                    int(existing_delivery.get("annual_report_id") or 0) != report_id
                    or str(existing_delivery.get("report_type") or "") != normalized_type
                    or int(existing_delivery.get("report_version") or 0) != version
                    or str(existing_delivery.get("final_report_ref") or "") != normalized_ref
                ):
                    raise CitationManifestConflictError(
                        "final_report_ref is already bound to another report version"
                    )
                delivery_bound_count = 0
            else:
                cursor.execute(
                    """
                    INSERT INTO annual_report_citation_delivery_ref (
                      engagement_id, annual_report_id, report_type, report_version,
                      final_report_ref, final_report_ref_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        case_id,
                        report_id,
                        normalized_type,
                        version,
                        normalized_ref,
                        _final_report_ref_hash(normalized_ref),
                    ),
                )
                delivery_bound_count = max(0, int(cursor.rowcount or 0))
            cursor.execute(
                """
                SELECT COUNT(*) AS manifest_count
                FROM annual_report_citation_manifest
                WHERE engagement_id = %s
                  AND annual_report_id = %s
                  AND report_type = %s
                  AND report_version = %s
                """,
                (case_id, report_id, normalized_type, version),
            )
            row = cursor.fetchone() or {}
        connection.commit()
    return {
        "engagement_id": case_id,
        "annual_report_id": report_id,
        "report_type": normalized_type,
        "report_version": version,
        "final_report_ref": normalized_ref,
        "bound_count": delivery_bound_count,
        "manifest_count": _integer(row.get("manifest_count")),
    }


__all__ = [
    "ANCHOR_STATUSES",
    "CitationManifestConflictError",
    "CitationManifestError",
    "DEFAULT_REPORT_TYPE",
    "bind_final_report_ref",
    "build_annual_finding_key",
    "build_manifest_entry",
    "build_manifest_snapshot_hash",
    "derive_anchor_status",
    "fetch_report_citation_manifest",
    "persist_report_citation_manifest",
    "resolve_final_report_ref_citation_manifest",
]
