"""Bridge deterministic annual findings into the original report evidence UI."""

from __future__ import annotations

import json
from typing import Any

from ai_hunter.app.graph.context_loader import get_heavy_payload
from ai_hunter.app.graph.heavy_state import put_heavy_payload
from ai_hunter.app.settings import Settings, get_settings
from ai_hunter.app.services.minio_service import resolve_minio_reference_url

from .storage import mysql_connection


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _evidence_item(reference: dict[str, Any], ordinal: int) -> dict[str, Any] | None:
    locator = reference.get("source_locator") or {}
    if not isinstance(locator, dict) or not locator:
        return None
    domain_row_type = str(reference.get("domain_row_type") or "annual_row")
    domain_row_id = int(reference.get("domain_row_id") or 0)
    row_number = int(locator.get("row_number") or 1)
    file_name = str(locator.get("file_name") or "年审结构化附件")
    sheet_name = str(locator.get("sheet_name") or "")
    display_name = f"{file_name} · {sheet_name}!{row_number}" if sheet_name else file_name
    source_file_id = int(locator.get("source_file_id") or 0)
    source_page_id = int(locator.get("source_page_id") or 0)
    source_chunk_id = str(locator.get("source_chunk_id") or "")
    bound_page_no = int(locator.get("page_no") or 0)
    content_type = str(locator.get("content_type") or "")
    source_file_ref = str(locator.get("source_file_ref") or "")
    page_image_ref = str(locator.get("page_image_ref") or "")
    row_start = int(locator.get("row_start") or row_number)
    row_end = int(locator.get("row_end") or row_start)
    locator_kind = str(locator.get("locator_kind") or ("sheet_row" if sheet_name else "unknown"))
    return {
        # Do not fabricate an annual:* chunk ID.  Unbound legacy rows remain
        # visible as unresolved evidence until the binding pass completes.
        "chunk_id": source_chunk_id,
        "file_id": source_file_id,
        "file_name": display_name,
        "page_no": bound_page_no,
        "quote_text": str(locator.get("quote_text") or ""),
        "bbox_list": list(locator.get("bbox_list") or []),
        "page_image_ref": resolve_minio_reference_url(page_image_ref),
        "source_page_id": source_page_id,
        "source_file_url": resolve_minio_reference_url(source_file_ref),
        "content_type": content_type,
        "locator_kind": locator_kind,
        "sheet_name": sheet_name,
        "row_start": row_start,
        "row_end": row_end,
        "cell_range": str(locator.get("cell_range") or ""),
        "preview_ref": resolve_minio_reference_url(str(locator.get("preview_ref") or "")),
        "preview_available": bool(locator.get("preview_available") or source_chunk_id),
        "page_width": int(locator.get("page_width") or 0),
        "page_height": int(locator.get("page_height") or 0),
        "entity_id": 0,
    }


def latest_finding_trace_items(
    engagement_id: int,
    *,
    limit: int = 20,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id, f.finding_type, f.risk_level, f.title, f.description,
                       f.evidence_refs_json, f.analysis_run_id, ar.analysis_type
                FROM annual_finding f
                JOIN annual_analysis_run ar ON ar.id = f.analysis_run_id
                JOIN (
                    SELECT analysis_type, MAX(id) AS analysis_run_id
                    FROM annual_analysis_run
                    WHERE engagement_id = %s AND status = 'completed'
                    GROUP BY analysis_type
                ) latest ON latest.analysis_run_id = f.analysis_run_id
                WHERE f.engagement_id = %s AND f.status = 'open'
                  AND ar.status = 'completed'
                ORDER BY f.analysis_run_id DESC, f.id DESC
                LIMIT %s
                """,
                (engagement_id, engagement_id, max(1, min(limit * 3, 100))),
            )
            rows = list(cursor.fetchall())

    # Only findings from the latest completed run of each analysis type may be
    # cited. A rule that disappeared after recomputation is superseded, not a
    # still-open conclusion. Keep the defensive per-rule deduplication as well.
    seen: set[tuple[str, str]] = set()
    trace_items: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row["analysis_type"]), str(row["finding_type"]))
        if key in seen:
            continue
        seen.add(key)
        evidences = []
        for ordinal, reference in enumerate(_loads(row.get("evidence_refs_json")) or [], start=1):
            if not isinstance(reference, dict):
                continue
            item = _evidence_item(reference, ordinal)
            if item:
                evidences.append(item)
        if not evidences:
            continue
        trace_items.append(
            {
                "citation_id": str(len(trace_items) + 1),
                "claim_id": int(row["id"]),
                "claim_type": str(row["finding_type"]),
                "claim_text": f"{row['title']}：{row['description']}",
                "confidence": 1.0,
                "entity_id": 0,
                "evidences": evidences,
            }
        )
        if len(trace_items) >= limit:
            break
    return trace_items


def finalize_annual_answer(state: dict[str, Any], answer: str) -> dict[str, Any]:
    engagement_id = int(state.get("current_case_id") or 0)
    trace_items = latest_finding_trace_items(engagement_id) if engagement_id > 0 else []
    rendered = answer.strip()
    if trace_items:
        evidence_index = "\n".join(
            f"- [{item['citation_id']}] {item['claim_text']}" for item in trace_items
        )
        rendered = f"{rendered}\n\n### 证据索引\n{evidence_index}"
    coverage = {
        "total_claims": len(trace_items),
        "cited_claims": len(trace_items),
        "uncited_claims": 0,
        "coverage_ratio": 1.0 if trace_items else 0.0,
        "missing_items": [],
    }
    report_ref = put_heavy_payload(
        "final_report",
        {
            "text": rendered,
            "trace_items": trace_items,
            "citation_coverage": coverage,
            "case_id": engagement_id,
            "business_domain": "annual_audit",
        },
    )
    return {
        "final_report_ref": report_ref,
        "final_report_summary": rendered[:240],
        "final_report": "",
        "agent_output": "",
        "trace_items": trace_items,
        "citation_coverage": coverage,
    }


def resolve_report_evidence(
    *,
    engagement_id: int,
    report_ref: str,
    citation_id: str = "",
    claim_id: int = 0,
) -> dict[str, Any]:
    payload = get_heavy_payload(report_ref)
    if not isinstance(payload, dict):
        return {
            "case_id": engagement_id,
            "report_ref": report_ref,
            "citation_id": citation_id,
            "claim_id": claim_id,
            "claim_text": "",
            "evidences": [],
            "primary_evidence": None,
            "primary_page": None,
            "resolution_status": "ref_not_found",
        }
    if int(payload.get("case_id") or 0) not in (0, engagement_id):
        return {
            "case_id": engagement_id,
            "report_ref": report_ref,
            "citation_id": citation_id,
            "claim_id": claim_id,
            "claim_text": "",
            "evidences": [],
            "primary_evidence": None,
            "primary_page": None,
            "resolution_status": "ref_not_found",
        }
    target = None
    for item in payload.get("trace_items") or []:
        if not isinstance(item, dict):
            continue
        if claim_id > 0 and int(item.get("claim_id") or 0) == claim_id:
            target = item
            break
        if citation_id and str(item.get("citation_id") or "") == citation_id:
            target = item
            break
    if target is None:
        return {
            "case_id": engagement_id,
            "report_ref": report_ref,
            "citation_id": citation_id,
            "claim_id": claim_id,
            "claim_text": "",
            "evidences": [],
            "primary_evidence": None,
            "primary_page": None,
            "resolution_status": "citation_not_found",
        }
    evidences = list(target.get("evidences") or [])
    primary = evidences[0] if evidences else None
    primary_page = None
    if primary:
        primary_page = {
            "file_id": int(primary.get("file_id") or 0),
            "page_no": int(primary.get("page_no") or 0),
            "page_width": int(primary.get("page_width") or 0),
            "page_height": int(primary.get("page_height") or 0),
            "page_image_ref": str(primary.get("page_image_ref") or ""),
            "source_file_url": str(primary.get("source_file_url") or ""),
            "content_type": str(primary.get("content_type") or ""),
            "locator_kind": str(primary.get("locator_kind") or "unknown"),
            "sheet_name": str(primary.get("sheet_name") or ""),
            "anchors": [primary],
        }
    return {
        "case_id": engagement_id,
        "report_ref": report_ref,
        "citation_id": str(target.get("citation_id") or citation_id),
        "claim_id": int(target.get("claim_id") or 0),
        "claim_text": str(target.get("claim_text") or ""),
        "evidences": evidences,
        "primary_evidence": primary,
        "primary_page": primary_page,
        "resolution_status": "ok" if evidences else "no_evidence",
    }


__all__ = [
    "finalize_annual_answer",
    "latest_finding_trace_items",
    "resolve_report_evidence",
]
