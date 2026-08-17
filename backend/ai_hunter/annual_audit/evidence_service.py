"""Bridge deterministic annual findings into the original report evidence UI."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ai_hunter.app.graph.context_loader import get_heavy_payload
from ai_hunter.app.graph.heavy_state import put_heavy_payload
from ai_hunter.app.settings import Settings, get_settings
from ai_hunter.app.services.minio_service import resolve_minio_reference_url

from .storage import mysql_connection


LOGGER = logging.getLogger(__name__)


_ANALYSIS_TOOL_TYPES = {
    "analyze_sales_receivables": "sales_receivables",
    "analyze_cash_and_bank": "cash_and_bank",
}
MAX_RESPONSE_CITATIONS = 20
_EXPLICIT_FINDING_MARKER = re.compile(r"\[\[AF:([1-9]\d*)\]\]")


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


def trace_items_from_deterministic_findings(
    findings: list[dict[str, Any]],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Make a response-local trace snapshot from the analysis just executed.

    The deterministic annual findings live in the MySQL annual domain rather
    than PostgreSQL kg_claim, so their numeric IDs must not be persisted into
    report_citation_map. The returned traces are instead resolved by their
    response-local citation IDs from the immutable report payload.
    """
    trace_items: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        evidences = []
        for ordinal, reference in enumerate(finding.get("evidence_refs") or [], start=1):
            if not isinstance(reference, dict):
                continue
            evidence = _evidence_item(reference, ordinal)
            if evidence is not None:
                evidences.append(evidence)
        if not evidences:
            continue
        title = str(finding.get("title") or "").strip()
        description = str(finding.get("description") or "").strip()
        trace_items.append(
            {
                "citation_id": "",
                "claim_id": 0,
                "claim_type": str(finding.get("finding_type") or ""),
                "claim_text": "：".join(part for part in (title, description) if part),
                "confidence": 1.0,
                "entity_id": 0,
                "_graph_backed": False,
                "evidences": evidences,
            }
        )
        if len(trace_items) >= max(1, min(limit, 100)):
            break
    return trace_items


def _normalize_trace_candidate(trace: dict[str, Any]) -> dict[str, Any] | None:
    """Copy one candidate trace and remove malformed evidence rows."""
    if not isinstance(trace, dict):
        return None
    evidences = [
        dict(evidence)
        for evidence in trace.get("evidences") or []
        if isinstance(evidence, dict)
    ]
    if not evidences:
        return None
    return {
        "citation_id": str(trace.get("citation_id") or ""),
        "claim_id": int(trace.get("claim_id") or 0),
        "claim_type": str(trace.get("claim_type") or ""),
        "claim_text": str(trace.get("claim_text") or ""),
        "confidence": float(trace.get("confidence") or 0),
        "entity_id": int(trace.get("entity_id") or 0),
        # This is internal metadata. It tells the persistence layer that the
        # claim id originated in PostgreSQL kg_claim rather than annual_finding.
        "_graph_backed": bool(trace.get("_graph_backed")),
        "evidences": evidences,
    }


def _traces_from_current_evidence_result(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build traces from evidence.resolve's current execution result only.

    This deliberately does not read state.trace_items: that field belongs to
    the previous persisted response until normalize_input starts the new turn.
    """
    result = state.get("business_line_result")
    if not isinstance(result, dict):
        return []
    raw_items = result.get("evidence_items")
    if not isinstance(raw_items, list):
        return []

    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    evidence_fields = {
        "chunk_id",
        "file_id",
        "file_name",
        "page_no",
        "quote_text",
        "bbox_list",
        "page_image_ref",
        "source_page_id",
        "source_file_url",
        "content_type",
        "locator_kind",
        "sheet_name",
        "row_start",
        "row_end",
        "cell_range",
        "preview_ref",
        "preview_available",
        "page_width",
        "page_height",
    }
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        claim_id = int(raw.get("claim_id") or 0)
        claim_text = str(raw.get("claim_text") or "").strip()
        key = (claim_id, claim_text)
        trace = grouped.setdefault(
            key,
            {
                "citation_id": "",
                "claim_id": claim_id,
                "claim_type": str(raw.get("claim_type") or ""),
                "claim_text": claim_text,
                "confidence": float(raw.get("confidence") or 0),
                "entity_id": int(raw.get("entity_id") or 0),
                "_graph_backed": bool(raw.get("_graph_backed")),
                "evidences": [],
            },
        )
        # A grouped claim can have several evidence rows.  Preserve a
        # graph-backed marker supplied by the source query without guessing
        # based on the numeric claim ID or case scope.
        trace["_graph_backed"] = bool(trace.get("_graph_backed")) or bool(
            raw.get("_graph_backed")
        )
        trace["evidences"].append(
            {key: value for key, value in raw.items() if key in evidence_fields}
        )
    traces = []
    for item in grouped.values():
        trace = _normalize_trace_candidate(item)
        if trace is not None:
            trace["_graph_backed"] = bool(trace.get("_graph_backed")) and int(
                trace.get("claim_id") or 0
            ) > 0
            traces.append(trace)
    return traces


def _traces_from_response_snapshot(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Read only trace candidates explicitly produced by this graph run."""
    raw_items = state.get("response_trace_candidates")
    if not isinstance(raw_items, list):
        return []
    return [
        trace
        for trace in (_normalize_trace_candidate(item) for item in raw_items)
        if trace is not None
    ]


def _current_analysis_run_scopes(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only analysis runs explicitly returned by this turn's tools.

    The drilldown agent records these scopes while reading its ToolMessages.  A
    scope is deliberately not inferred from the user's wording, the final LLM
    prose, or a project's newest run: all of those can drift after a rerun.
    """

    raw_scopes = state.get("response_analysis_runs")
    if not isinstance(raw_scopes, list):
        return []

    scopes: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for raw_scope in raw_scopes:
        if not isinstance(raw_scope, dict):
            continue
        tool_name = str(raw_scope.get("tool_name") or "").strip()
        expected_type = _ANALYSIS_TOOL_TYPES.get(tool_name)
        if not expected_type:
            continue
        try:
            run_id = int(raw_scope.get("analysis_run_id") or 0)
        except (TypeError, ValueError):
            continue
        if run_id <= 0:
            continue
        reported_type = str(raw_scope.get("analysis_type") or "").strip()
        if reported_type and reported_type != expected_type:
            continue
        key = (expected_type, run_id)
        if key in seen:
            continue
        seen.add(key)
        scopes.append(
            {
                "tool_name": tool_name,
                "analysis_type": expected_type,
                "analysis_run_id": run_id,
            }
        )
    return scopes


def _current_analysis_run_findings(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Load findings belonging to the exact deterministic runs used this turn."""

    engagement_id = int(state.get("current_case_id") or 0)
    scopes = _current_analysis_run_scopes(state)
    if engagement_id <= 0 or not scopes:
        return []

    scope_by_run = {
        int(scope["analysis_run_id"]): str(scope["analysis_type"])
        for scope in scopes
    }
    run_ids = list(scope_by_run)
    placeholders = ", ".join(["%s"] * len(run_ids))
    try:
        with mysql_connection(get_settings()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT f.id, f.analysis_run_id, f.finding_type, f.risk_level,
                           f.title, f.description, f.amount, f.evidence_refs_json,
                           ar.analysis_type
                    FROM annual_finding f
                    JOIN annual_analysis_run ar ON ar.id = f.analysis_run_id
                    WHERE f.engagement_id = %s
                      AND f.analysis_run_id IN ({placeholders})
                      AND f.status = 'open'
                      AND ar.status = 'completed'
                    ORDER BY f.analysis_run_id, f.id
                    """,
                    (engagement_id, *run_ids),
                )
                rows = list(cursor.fetchall())
    except Exception:
        LOGGER.exception(
            "annual_current_run_finding_load_failed case_id=%s run_ids=%s",
            engagement_id,
            run_ids,
        )
        return []

    scope_order = {int(scope["analysis_run_id"]): index for index, scope in enumerate(scopes)}
    findings: list[dict[str, Any]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            scope_order.get(int(item.get("analysis_run_id") or 0), len(scope_order)),
            int(item.get("id") or 0),
        ),
    ):
        run_id = int(row.get("analysis_run_id") or 0)
        if str(row.get("analysis_type") or "") != scope_by_run.get(run_id):
            continue
        try:
            evidence_refs = _loads(row.get("evidence_refs_json")) or []
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence_refs = []
        findings.append(
            {
                "finding_id": int(row.get("id") or 0),
                "analysis_run_id": run_id,
                "analysis_type": str(row.get("analysis_type") or ""),
                "finding_type": str(row.get("finding_type") or ""),
                "risk_level": str(row.get("risk_level") or ""),
                "title": str(row.get("title") or ""),
                "description": str(row.get("description") or ""),
                "amount": row.get("amount"),
                "evidence_refs": [
                    dict(reference)
                    for reference in evidence_refs
                    if isinstance(reference, dict)
                ],
            }
        )
    return findings


def _traces_and_coverage_from_current_analysis_runs(
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Project just this turn's deterministic findings and retain coverage gaps."""

    findings = _current_analysis_run_findings(state)
    if not findings:
        return [], None

    engagement_id = int(state.get("current_case_id") or 0)
    try:
        from .analysis_service import ANALYSIS_RULES_VERSION
        from .engagement_repository import get_engagement
        from .knowledge_graph_projection import (
            annual_finding_key,
            project_annual_findings_to_knowledge_graph,
        )

        engagement = get_engagement(engagement_id)
        projection = project_annual_findings_to_knowledge_graph(
            case_id=engagement_id,
            entity_name=str(engagement.get("entity_name") or ""),
            findings=findings,
            analysis_rules_version=ANALYSIS_RULES_VERSION,
        )
    except Exception:
        LOGGER.exception(
            "annual_current_run_graph_projection_failed case_id=%s",
            engagement_id,
        )
        projection = {"trace_by_finding_key": {}}
        annual_finding_key = lambda finding: str(finding.get("finding_id") or "")

    trace_by_finding_key = dict(projection.get("trace_by_finding_key") or {})
    traces: list[dict[str, Any]] = []
    missing_items: list[dict[str, Any]] = []
    unbound_count = 0
    for finding in findings:
        finding_key = annual_finding_key(finding)
        projected_trace = trace_by_finding_key.get(finding_key)
        graph_backed = bool(
            isinstance(projected_trace, dict)
            and projected_trace.get("_graph_backed")
            and int(projected_trace.get("claim_id") or 0) > 0
        )
        fallback = trace_items_from_deterministic_findings([finding], limit=1)
        fallback_evidences = list((fallback[0] if fallback else {}).get("evidences") or [])
        if graph_backed and len(traces) < MAX_RESPONSE_CITATIONS:
            traces.append(
                {
                    **dict(projected_trace),
                    "annual_finding_id": int(finding.get("finding_id") or 0),
                    "analysis_run_id": int(finding.get("analysis_run_id") or 0),
                    "analysis_type": str(finding.get("analysis_type") or ""),
                    "finding_type": str(finding.get("finding_type") or ""),
                }
            )
            continue

        if not any(_is_bound_evidence(item) for item in fallback_evidences if isinstance(item, dict)):
            unbound_count += 1
        missing_items.append(
            {
                "citation_id": "",
                "claim_id": int((projected_trace or {}).get("claim_id") or 0),
                "annual_finding_id": int(finding.get("finding_id") or 0),
                "analysis_run_id": int(finding.get("analysis_run_id") or 0),
                "claim_type": str(finding.get("finding_type") or ""),
                "claim_text": "：".join(
                    part
                    for part in (
                        str(finding.get("title") or ""),
                        str(finding.get("description") or ""),
                    )
                    if part
                ),
            }
        )

    total_claims = len(findings)
    cited_claims = len(traces)
    coverage = {
        "total_claims": total_claims,
        "cited_claims": cited_claims,
        "uncited_claims": total_claims - cited_claims,
        "coverage_ratio": cited_claims / total_claims if total_claims else 0.0,
        "missing_items": missing_items,
        "unbound_count": unbound_count,
        "evidence_blocked": bool(missing_items),
        "blocking_status": "evidence_blocked" if missing_items else "ready",
    }
    return traces, coverage


def response_trace_items(
    state: dict[str, Any],
    _answer: str,
    *,
    limit: int = 20,
    current_analysis_traces: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assign response-local citations from explicit current-turn evidence.

    No project-wide lookup or text-similarity matching is permitted here.
    Ordinary chat/drilldown answers have no evidence index unless their current
    executor returned evidence. Full-audit/re-audit responses receive a
    deterministic trace snapshot generated by that same report workflow.
    """
    selected = _traces_from_response_snapshot(state)
    if not selected:
        selected = _traces_from_current_evidence_result(state)
    if not selected:
        selected = (
            current_analysis_traces
            if current_analysis_traces is not None
            else _traces_and_coverage_from_current_analysis_runs(state)[0]
        )
    selected = selected[: max(1, min(limit, MAX_RESPONSE_CITATIONS))]
    return [
        {**trace, "citation_id": str(index)}
        for index, trace in enumerate(selected, start=1)
    ]


def _apply_explicit_finding_markers(answer: str, trace_items: list[dict[str, Any]]) -> str:
    """Replace only exact model-emitted annual finding markers with citations."""

    citation_by_finding_id = {
        int(item.get("annual_finding_id") or 0): str(item.get("citation_id") or "")
        for item in trace_items
        if int(item.get("annual_finding_id") or 0) > 0
        and str(item.get("citation_id") or "")
    }

    def replace(match: re.Match[str]) -> str:
        citation_id = citation_by_finding_id.get(int(match.group(1)))
        return f"[[cite:{citation_id}]]" if citation_id else ""

    return _EXPLICIT_FINDING_MARKER.sub(replace, answer)


def _render_scoped_finding_citations(
    rendered: str,
    trace_items: list[dict[str, Any]],
) -> str:
    """Expose exact current-run citations when the model omitted its marker.

    This is intentionally a small, response-scoped fact list rather than a
    project-wide evidence index. It gives the reader an auditable link without
    guessing which natural-language sentence a finding was meant to support.
    """

    existing = {match.group(1) for match in re.finditer(r"\[\[cite:([1-9]\d*)\]\]", rendered)}
    uncited = [
        item
        for item in trace_items
        if str(item.get("citation_id") or "") not in existing
    ]
    if not uncited:
        return rendered
    lines = ["### 本轮已核验的规则发现"]
    for item in uncited:
        claim_text = str(item.get("claim_text") or "").strip()
        citation_id = str(item.get("citation_id") or "")
        if claim_text and citation_id:
            lines.append(f"- {claim_text} [[cite:{citation_id}]]")
    if len(lines) == 1:
        return rendered
    scoped_block = "\n".join(lines)
    return f"{rendered.rstrip()}\n\n{scoped_block}"


def _is_bound_evidence(item: dict[str, Any]) -> bool:
    """Return whether an evidence item has a canonical platform anchor."""
    return bool(
        int(item.get("file_id") or 0) > 0
        and int(item.get("source_page_id") or 0) > 0
        and str(item.get("chunk_id") or "")
    )


def _claim_text(row: dict[str, Any]) -> str:
    return f"{str(row.get('title') or '')}: {str(row.get('description') or '')}"


def _coverage_from_latest_findings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate evidence coverage without dropping findings that lack anchors."""
    cited_claims = 0
    missing_items: list[dict[str, Any]] = []
    for row in rows:
        evidences: list[dict[str, Any]] = []
        for ordinal, reference in enumerate(_loads(row.get("evidence_refs_json")) or [], start=1):
            if not isinstance(reference, dict):
                continue
            item = _evidence_item(reference, ordinal)
            if item is not None:
                evidences.append(item)

        if any(_is_bound_evidence(item) for item in evidences):
            cited_claims += 1
            continue

        missing_items.append(
            {
                "citation_id": "",
                "claim_id": int(row.get("id") or 0),
                "claim_type": str(row.get("finding_type") or ""),
                "claim_text": _claim_text(row),
            }
        )

    total_claims = len(rows)
    unbound_count = total_claims - cited_claims
    evidence_blocked = unbound_count > 0
    return {
        "total_claims": total_claims,
        "cited_claims": cited_claims,
        "uncited_claims": unbound_count,
        "coverage_ratio": cited_claims / total_claims if total_claims else 0.0,
        "missing_items": missing_items,
        "unbound_count": unbound_count,
        "evidence_blocked": evidence_blocked,
        "blocking_status": "evidence_blocked" if evidence_blocked else "ready",
    }


def _coverage_from_trace_items(trace_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate coverage for the citations attached to this response only."""
    missing_items: list[dict[str, Any]] = []
    cited_claims = 0
    for item in trace_items:
        evidences = [
            evidence
            for evidence in item.get("evidences") or []
            if isinstance(evidence, dict)
        ]
        if any(_is_bound_evidence(evidence) for evidence in evidences):
            cited_claims += 1
            continue
        missing_items.append(
            {
                "citation_id": str(item.get("citation_id") or ""),
                "claim_id": int(item.get("claim_id") or 0),
                "claim_type": str(item.get("claim_type") or ""),
                "claim_text": str(item.get("claim_text") or ""),
            }
        )
    total_claims = len(trace_items)
    unbound_count = total_claims - cited_claims
    return {
        "total_claims": total_claims,
        "cited_claims": cited_claims,
        "uncited_claims": unbound_count,
        "coverage_ratio": cited_claims / total_claims if total_claims else 0.0,
        "missing_items": missing_items,
        "unbound_count": unbound_count,
        "evidence_blocked": unbound_count > 0,
        "blocking_status": "evidence_blocked" if unbound_count else "ready",
    }


def _latest_finding_evidence_coverage(
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Calculate coverage over every current finding, not only rendered citations."""
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id, f.finding_type, f.title, f.description, f.evidence_refs_json
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
                """,
                (engagement_id, engagement_id),
            )
            rows = list(cursor.fetchall())
    return _coverage_from_latest_findings(rows)


def _persist_response_citation_map(
    *,
    engagement_id: int,
    report_ref: str,
    trace_items: list[dict[str, Any]],
    citation_entries: list[dict[str, Any]] | None = None,
) -> None:
    """Persist graph-backed report citations for one immutable response ref.

    annual_finding.id and kg_claim.id are different domains. Only records
    selected from the knowledge graph may be inserted into report_citation_map,
    whose foreign key targets kg_claim. The heavy payload remains authoritative
    for deterministic annual-only findings.
    """
    entry_by_citation_id = {
        str(entry.get("citation_id") or ""): entry
        for entry in (citation_entries or [])
        if isinstance(entry, dict) and str(entry.get("citation_id") or "")
    }
    rows = [
        {
            "citation_id": str(item.get("citation_id") or ""),
            "claim_id": int(item.get("claim_id") or 0),
            "report_section": str(
                entry_by_citation_id.get(str(item.get("citation_id") or ""), {}).get("section_code")
                or "chat_response"
            ),
            "ordinal": index,
            "paragraph_index": 0,
        }
        for index, item in enumerate(trace_items, start=1)
        if bool(item.get("_graph_backed"))
        and int(item.get("claim_id") or 0) > 0
        and str(item.get("citation_id") or "")
    ]
    if engagement_id <= 0 or not report_ref or not rows:
        return
    try:
        from ai_hunter.app.services.kg_service import get_kg_service

        get_kg_service().replace_report_citations(
            case_id=engagement_id,
            report_ref=report_ref,
            rows=rows,
        )
    except Exception:
        # A graph store outage must not discard an already durable reply. The
        # report heavy payload can still resolve its own trace snapshot.
        LOGGER.exception(
            "response_citation_map_persist_failed case_id=%s report_ref=%s",
            engagement_id,
            report_ref,
        )


def render_knowledge_graph_trace_appendix(trace_items: list[dict[str, Any]]) -> str:
    """Render only the evidence paths actually cited by this response."""

    if not trace_items:
        return ""
    lines = ["### 【知识图谱证据追溯】"]
    for item in trace_items:
        citation_id = str(item.get("citation_id") or "")
        claim_type = str(item.get("claim_type") or "claim")
        confidence = float(item.get("confidence") or 0)
        claim_text = str(item.get("claim_text") or "").strip()
        marker = f"[[cite:{citation_id}]] " if citation_id else ""
        lines.append(f"- {marker}[{claim_type}|{confidence:.2f}] {claim_text}".rstrip())
        evidences = [
            evidence
            for evidence in item.get("evidences") or []
            if isinstance(evidence, dict)
        ]
        if not evidences:
            lines.append("  - 证据锚点：该事项尚未完成规范绑定，不能据此放行。")
            continue
        for evidence in evidences[:3]:
            if not _is_bound_evidence(evidence):
                lines.append("  - 证据锚点：该事项尚未完成规范绑定，不能据此放行。")
                continue
            quote_text = str(evidence.get("quote_text") or "").replace("\n", " ").strip()[:160]
            lines.append(
                "  - 证据锚点: "
                f"file_id={int(evidence.get('file_id') or 0)} "
                f"page={int(evidence.get('page_no') or 0)} "
                f"chunk={str(evidence.get('chunk_id') or '')} | {quote_text}"
            )
    return "\n".join(lines)


def _manifest_trace_for_report_ref(
    *,
    engagement_id: int,
    report_ref: str,
    citation_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Load a frozen annual-report citation after an ephemeral payload expires."""

    if engagement_id <= 0 or not report_ref or not citation_id:
        return None, {}
    try:
        from .citation_manifest_service import (
            resolve_final_report_ref_citation_manifest,
        )

        entries = resolve_final_report_ref_citation_manifest(
            engagement_id=engagement_id,
            final_report_ref=report_ref,
            citation_id=citation_id,
        )
    except Exception:
        # This fallback is intentionally best-effort during a rolling schema
        # deployment. A malformed or cross-case ref still resolves to nothing.
        LOGGER.warning(
            "annual_citation_manifest_lookup_failed case_id=%s report_ref=%s",
            engagement_id,
            report_ref,
            exc_info=True,
        )
        return None, {}
    if not entries:
        return None, {}
    entry = dict(entries[0])
    finding_metadata = entry.get("finding_metadata")
    if not isinstance(finding_metadata, dict):
        finding_metadata = {}
    title = str(finding_metadata.get("title") or "").strip()
    description = str(finding_metadata.get("description") or "").strip()
    return (
        {
            "citation_id": str(entry.get("citation_id") or citation_id),
            "claim_id": int(finding_metadata.get("graph_claim_id") or 0),
            "claim_type": str(entry.get("finding_type") or "risk_signal"),
            "claim_text": "；".join(part for part in (title, description) if part),
            "entity_id": int(finding_metadata.get("graph_entity_id") or 0),
            "evidences": [
                dict(evidence)
                for evidence in entry.get("evidence_snapshot") or []
                if isinstance(evidence, dict)
            ],
        },
        {
            "annual_finding_id": int(entry.get("annual_finding_id") or 0),
            "analysis_run_id": int(entry.get("analysis_run_id") or 0),
            "analysis_type": str(entry.get("analysis_type") or ""),
            "rule_metadata": dict(entry.get("rule_metadata") or {}),
            "finding_metadata": finding_metadata,
            "anchor_status": str(entry.get("anchor_status") or ""),
            "citation_source": "annual_report_manifest",
        },
    )


def _resolved_evidence_payload(
    *,
    engagement_id: int,
    report_ref: str,
    target: dict[str, Any],
    citation_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidences = [
        dict(evidence)
        for evidence in target.get("evidences") or []
        if isinstance(evidence, dict)
    ]
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
    result = {
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
    if extra:
        result.update(extra)
    return result


def _bind_annual_report_delivery_ref(
    *,
    state: dict[str, Any],
    engagement_id: int,
    report_ref: str,
) -> dict[str, Any]:
    """Attach this assistant message to an already frozen report version."""

    manifest = state.get("annual_report_manifest")
    if not isinstance(manifest, dict) or int(manifest.get("citation_count") or 0) <= 0:
        return {"status": "not_required"}
    annual_report_id = int(manifest.get("annual_report_id") or 0)
    report_version = int(manifest.get("report_version") or 0)
    report_type = str(manifest.get("report_type") or "annual_audit_draft")
    if annual_report_id <= 0 or report_version <= 0:
        LOGGER.error(
            "annual_citation_manifest_descriptor_invalid case_id=%s", engagement_id
        )
        return {"status": "invalid_manifest_descriptor"}
    try:
        from .citation_manifest_service import bind_final_report_ref

        result = bind_final_report_ref(
            engagement_id=engagement_id,
            annual_report_id=annual_report_id,
            report_version=report_version,
            report_type=report_type,
            final_report_ref=report_ref,
        )
        return {"status": "bound", **dict(result)}
    except Exception:
        LOGGER.exception(
            "annual_citation_delivery_ref_bind_failed case_id=%s report_id=%s version=%s",
            engagement_id,
            annual_report_id,
            report_version,
        )
        return {
            "status": "binding_failed",
            "annual_report_id": annual_report_id,
            "report_version": report_version,
        }


def finalize_annual_answer(state: dict[str, Any], answer: str) -> dict[str, Any]:
    engagement_id = int(state.get("current_case_id") or 0)
    current_analysis_traces, current_analysis_coverage = (
        _traces_and_coverage_from_current_analysis_runs(state)
    )
    trace_items = response_trace_items(
        state,
        answer,
        current_analysis_traces=current_analysis_traces,
    )
    rendered = _apply_explicit_finding_markers(answer.strip(), trace_items)
    if current_analysis_coverage is not None:
        rendered = _render_scoped_finding_citations(rendered, trace_items)
    trace_appendix = render_knowledge_graph_trace_appendix(trace_items)
    if trace_appendix and "### 【知识图谱证据追溯】" not in rendered:
        rendered = f"{rendered}\n\n{trace_appendix}"
    planned_coverage = state.get("response_citation_coverage")
    coverage = (
        dict(planned_coverage)
        if isinstance(planned_coverage, dict) and "total_claims" in planned_coverage
        else (
            current_analysis_coverage
            if current_analysis_coverage is not None
            else _coverage_from_trace_items(trace_items)
        )
    )
    annual_report_manifest = dict(state.get("annual_report_manifest") or {})
    report_ref = put_heavy_payload(
        "final_report",
        {
            "text": rendered,
            "trace_items": trace_items,
            "citation_coverage": coverage,
            "citation_scope": (
                "annual_report"
                if planned_coverage
                else "response_analysis_run"
                if current_analysis_coverage is not None
                else "response"
            ),
            "case_id": engagement_id,
            "business_domain": "annual_audit",
            "annual_report_manifest": annual_report_manifest,
        },
    )
    manifest_binding = _bind_annual_report_delivery_ref(
        state=state,
        engagement_id=engagement_id,
        report_ref=report_ref,
    )
    _persist_response_citation_map(
        engagement_id=engagement_id,
        report_ref=report_ref,
        trace_items=trace_items,
        citation_entries=list(state.get("citation_entries") or []),
    )
    return {
        "current_case_id": engagement_id,
        "final_report_ref": report_ref,
        "final_report_summary": rendered[:240],
        "final_report": "",
        "agent_output": "",
        "trace_items": trace_items,
        "citation_coverage": coverage,
        "response_evidence_index": trace_appendix,
        "citation_manifest_binding": manifest_binding,
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
        target, manifest_metadata = _manifest_trace_for_report_ref(
            engagement_id=engagement_id,
            report_ref=report_ref,
            citation_id=citation_id,
        )
        if target is not None:
            return _resolved_evidence_payload(
                engagement_id=engagement_id,
                report_ref=report_ref,
                target=target,
                citation_id=citation_id,
                extra=manifest_metadata,
            )
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
    return _resolved_evidence_payload(
        engagement_id=engagement_id,
        report_ref=report_ref,
        target=target,
        citation_id=citation_id,
        extra={"citation_source": "response_payload"},
    )


__all__ = [
    "finalize_annual_answer",
    "latest_finding_trace_items",
    "render_knowledge_graph_trace_appendix",
    "resolve_report_evidence",
    "trace_items_from_deterministic_findings",
]
