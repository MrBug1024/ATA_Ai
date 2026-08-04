"""Helpers for resolving out-of-band heavy context payloads inside graph nodes."""

from typing import Any

from ..services.minio_service import resolve_minio_reference_url
from .heavy_state import get_heavy_payload
from .json_utils import json_dumps_safe
from .state import AuditGraphState


def resolve_full_context_data(state: AuditGraphState) -> dict[str, Any]:
    """Resolve full-context structured data from state or the heavy-payload store."""
    payload = state.get("full_context_data")
    if isinstance(payload, dict) and payload:
        return payload

    heavy_payload = get_heavy_payload(state.get("full_context_ref", ""))
    if isinstance(heavy_payload, dict):
        data = heavy_payload.get("data")
        if isinstance(data, dict):
            return data
    return {}


def resolve_full_context_json(state: AuditGraphState) -> str:
    """Resolve the full-context JSON string from state or the heavy-payload store."""
    full_context_json = (state.get("full_context_json") or "").strip()
    if full_context_json:
        return full_context_json

    heavy_payload = get_heavy_payload(state.get("full_context_ref", ""))
    if isinstance(heavy_payload, dict):
        payload_json = heavy_payload.get("json")
        if isinstance(payload_json, str) and payload_json.strip():
            return payload_json
        data = heavy_payload.get("data")
        if isinstance(data, dict):
            return json_dumps_safe(data)
    return "{}"


def resolve_report_section(state: AuditGraphState, section_id: str) -> str:
    """解析某段报告文本：从 report_section_refs[section_id] 的 heavy payload 取。"""
    refs = state.get("report_section_refs") or {}
    ref = refs.get(section_id, "") if isinstance(refs, dict) else ""
    payload = get_heavy_payload(ref)
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text
    return ""


def resolve_computed_metrics(state: AuditGraphState) -> dict[str, Any]:
    """Resolve annual deterministic analysis output when present."""
    payload = get_heavy_payload(state.get("computed_metrics_ref", ""))
    if isinstance(payload, dict) and payload:
        return payload
    full_context = resolve_full_context_data(state)
    engine_results = full_context.get("engine_results") or {}
    return dict(engine_results.get("annual_audit") or {})


def build_report_context(
    full_context_data: dict[str, Any],
    computed_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact annual-audit context used by chat and evidence views."""
    return {
        "case_id": full_context_data.get("case_id", 0),
        "case": full_context_data.get("case"),
        "audited_entity": full_context_data.get("audited_entity") or {},
        "annual_audit": full_context_data.get("annual_audit") or {},
        "data_completeness": full_context_data.get("data_completeness") or {},
        "analysis_results": computed_metrics if computed_metrics is not None else {},
    }


def resolve_report_full_context_json(state: AuditGraphState) -> str:
    """Resolve a compact annual-audit context JSON string."""
    data = resolve_full_context_data(state)
    if not data:
        return resolve_full_context_json(state)
    return json_dumps_safe(build_report_context(data, resolve_computed_metrics(state)))


def resolve_ingest_payload(state: AuditGraphState) -> dict[str, Any]:
    """Resolve file-split ingest payload from state or the heavy-payload store."""
    payload = {
        "txt_contents": state.get("txt_contents", []),
        "csv_contents": state.get("csv_contents", []),
        "md_contents": state.get("md_contents", []),
        "document_ocr_contents": state.get("document_ocr_contents", []),
        "image_ocr_contents": state.get("image_ocr_contents", []),
        "ocr_layout_results": state.get("ocr_layout_results", []),
    }
    if any(payload.values()):
        return payload

    heavy_payload = get_heavy_payload(state.get("ingest_payload_ref", ""))
    if isinstance(heavy_payload, dict):
        return {
            "txt_contents": heavy_payload.get("txt_contents", []),
            "csv_contents": heavy_payload.get("csv_contents", []),
            "md_contents": heavy_payload.get("md_contents", []),
            "document_ocr_contents": heavy_payload.get("document_ocr_contents", []),
            "image_ocr_contents": heavy_payload.get("image_ocr_contents", []),
            "ocr_layout_results": heavy_payload.get("ocr_layout_results", []),
        }
    return payload


def resolve_aggregated_text(state: AuditGraphState) -> str:
    """Resolve aggregated ingest text from state or the heavy-payload store."""
    aggregated_text = (state.get("aggregated_text") or "").strip()
    if aggregated_text:
        return aggregated_text

    heavy_payload = get_heavy_payload(state.get("aggregated_text_ref", ""))
    if isinstance(heavy_payload, dict):
        text = heavy_payload.get("text")
        if isinstance(text, str):
            return text
    return ""


def resolve_parse_document_result(state: AuditGraphState) -> dict[str, Any]:
    """Resolve parse-document result payload from state or the heavy-payload store."""
    payload = state.get("parse_document_result")
    if isinstance(payload, dict) and payload:
        return payload

    heavy_payload = get_heavy_payload(state.get("parse_document_result_ref", ""))
    if isinstance(heavy_payload, dict):
        return heavy_payload
    return {}


def _resolve_report_text(state: AuditGraphState, *, field_name: str, ref_name: str) -> str:
    """Resolve one report text field from state or the heavy-payload store."""
    report_text = (state.get(field_name) or "").strip()
    if report_text:
        return report_text

    heavy_payload = get_heavy_payload(state.get(ref_name, ""))
    if isinstance(heavy_payload, dict):
        text = heavy_payload.get("text")
        if isinstance(text, str):
            return text
    return ""


def resolve_report_part_a(state: AuditGraphState) -> str:
    """Resolve report part A from state or heavy storage."""
    return _resolve_report_text(state, field_name="report_part_a", ref_name="report_part_a_ref")


def resolve_report_part_b(state: AuditGraphState) -> str:
    """Resolve report part B from state or heavy storage."""
    return _resolve_report_text(state, field_name="report_part_b", ref_name="report_part_b_ref")


def resolve_final_report(state: AuditGraphState) -> str:
    """Resolve final report text from state or heavy storage."""
    return _resolve_report_text(state, field_name="final_report", ref_name="final_report_ref")


def resolve_citation_coverage(state: AuditGraphState) -> dict[str, Any]:
    """Resolve citation coverage payload from state or final-report heavy payload."""
    in_state = state.get("citation_coverage")
    if isinstance(in_state, dict) and in_state:
        return in_state

    final_report_payload = get_heavy_payload(state.get("final_report_ref", ""))
    if isinstance(final_report_payload, dict):
        coverage = final_report_payload.get("citation_coverage")
        if isinstance(coverage, dict) and coverage:
            return coverage
    return {
        "total_claims": 0,
        "cited_claims": 0,
        "uncited_claims": 0,
        "coverage_ratio": 0.0,
        "missing_items": [],
    }


def build_report_citation_id(ordinal: int) -> str:
    """Build a report-local citation id."""
    return str(ordinal) if ordinal > 0 else ""


def build_claim_placeholder(claim_id: int) -> str:
    """Build the LLM-facing inline citation placeholder for one claim."""
    return f"[[CLM-{claim_id}]]" if claim_id > 0 else ""


def parse_legacy_claim_citation_id(citation_id: str) -> int:
    """Parse the legacy fallback id format like CLM-31."""
    normalized = (citation_id or "").strip().upper()
    if not normalized.startswith("CLM-"):
        return 0
    raw_id = normalized[4:]
    return int(raw_id) if raw_id.isdigit() else 0


def resolve_kg_snapshot(state: AuditGraphState) -> dict[str, Any]:
    """Resolve a lightweight knowledge-graph snapshot for report and agent prompts."""
    payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(payload, dict):
        summary = (state.get("kg_summary") or "").strip()
        return {"summary": summary} if summary else {}

    entities = payload.get("entities", []) if isinstance(payload.get("entities"), list) else []
    relations = payload.get("relations", []) if isinstance(payload.get("relations"), list) else []
    claims = payload.get("claims", []) if isinstance(payload.get("claims"), list) else []
    reconciliation_items = (
        payload.get("reconciliation_items", []) if isinstance(payload.get("reconciliation_items"), list) else []
    )
    evidence_count = int(payload.get("evidence_count", 0) or 0)

    entity_samples = []
    for entity in entities[:6]:
        if not isinstance(entity, dict):
            continue
        entity_samples.append(
            {
                "id": int(entity.get("id", 0) or 0),
                "name": str(entity.get("canonical_name") or entity.get("name") or ""),
                "type": str(entity.get("entity_type", "") or ""),
            }
        )

    relation_samples = []
    for relation in relations[:8]:
        if not isinstance(relation, dict):
            continue
        relation_samples.append(
            {
                "id": int(relation.get("id", 0) or 0),
                "type": str(relation.get("relation_type", "") or ""),
                "label": str(relation.get("relation_label", "") or ""),
                "from_entity_id": int(relation.get("from_entity_id", 0) or 0),
                "to_entity_id": int(relation.get("to_entity_id", 0) or 0),
            }
        )

    claim_samples = []
    for claim in claims[:8]:
        if not isinstance(claim, dict):
            continue
        claim_samples.append(
            {
                "id": int(claim.get("id", 0) or 0),
                "type": str(claim.get("claim_type", "") or ""),
                "text": str(claim.get("claim_text", "") or ""),
            }
        )

    summary = (state.get("kg_summary") or "").strip()
    if not summary:
        summary = (
            f"已构建案件图谱：实体{len(entities)}个，关系{len(relations)}条，断言{len(claims)}条。"
        )

    return {
        "summary": summary,
        "entity_samples": entity_samples,
        "relation_samples": relation_samples,
        "claim_samples": claim_samples,
        "reconciliation_samples": [
            {
                "action": str(item.get("action", "") or ""),
                "new_claim_id": int(item.get("new_claim_id", 0) or 0),
                "new_claim_text": str(item.get("new_claim_text", "") or ""),
                "superseded_claim_id": int(item.get("superseded_claim_id", 0) or 0),
                "superseded_claim_text": str(item.get("superseded_claim_text", "") or ""),
                "rationale": str(item.get("rationale", "") or ""),
            }
            for item in reconciliation_items[:5]
            if isinstance(item, dict)
        ],
        "evidence_count": evidence_count,
    }


def resolve_claim_traces(state: AuditGraphState) -> list[dict[str, Any]]:
    """Resolve raw claim traces from the graph payload for report citation planning."""
    payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(payload, dict):
        return []

    claim_traces = payload.get("claim_traces", [])
    if not isinstance(claim_traces, list):
        return []

    normalized: list[dict[str, Any]] = []
    for trace in claim_traces:
        if not isinstance(trace, dict):
            continue
        claim_id = int(trace.get("claim_id", 0) or 0)
        if claim_id <= 0:
            continue
        normalized.append(
            {
                "claim_id": claim_id,
                "claim_type": str(trace.get("claim_type", "") or ""),
                "claim_text": str(trace.get("claim_text", "") or ""),
                "confidence": float(trace.get("confidence", 0) or 0),
            }
        )
    return normalized


def build_inline_citation_catalog(state: AuditGraphState, *, limit: int = 12) -> str:
    """Build a compact inline-citation catalog for report prompts."""
    traces = resolve_claim_traces(state)
    if not traces:
        return "无可用角标断言。"

    lines = []
    for trace in traces[:limit]:
        placeholder = build_claim_placeholder(int(trace.get("claim_id", 0) or 0))
        claim_text = str(trace.get("claim_text", "") or "").strip()
        claim_type = str(trace.get("claim_type", "") or "").strip()
        confidence = float(trace.get("confidence", 0) or 0)
        if not placeholder or not claim_text:
            continue
        lines.append(f"{placeholder} {claim_type or 'claim'} {confidence:.2f} {claim_text}")
    return "\n".join(lines) if lines else "无可用角标断言。"


def resolve_kg_trace_summary(
    state: AuditGraphState,
    *,
    citation_id_by_claim_id: dict[int, str] | None = None,
) -> str:
    """Resolve a compact evidence trace appendix from the graph payload."""
    payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(payload, dict):
        return ""

    claim_traces = payload.get("claim_traces", [])
    if not isinstance(claim_traces, list) or not claim_traces:
        return ""

    lines = ["### 【知识图谱证据追溯】"]
    for trace in claim_traces[:5]:
        if not isinstance(trace, dict):
            continue
        claim_id = int(trace.get("claim_id", 0) or 0)
        citation_id = (citation_id_by_claim_id or {}).get(claim_id, "")
        claim_text = str(trace.get("claim_text", "") or "").strip()
        if not claim_text:
            continue
        confidence = float(trace.get("confidence", 0) or 0)
        claim_type = str(trace.get("claim_type", "") or "").strip()
        lines.append(
            f"- [{citation_id or '?'}] [{claim_type or 'claim'}|{confidence:.2f}] {claim_text}"
        )
        evidences = trace.get("evidences", [])
        if not isinstance(evidences, list) or not evidences:
            lines.append("   - 证据锚点: 暂无页码锚点")
            continue
        for evidence in evidences[:2]:
            if not isinstance(evidence, dict):
                continue
            page_no = int(evidence.get("page_no", 0) or 0)
            file_id = int(evidence.get("file_id", 0) or 0)
            chunk_id = str(evidence.get("chunk_id", "") or "")
            quote_text = str(evidence.get("quote_text", "") or "").strip().replace("\n", " ")
            quote_text = quote_text[:90]
            lines.append(
                f"   - 证据锚点: file_id={file_id} page={page_no} chunk={chunk_id} | {quote_text}"
            )
    return "\n".join(lines)


def resolve_trace_items(state: AuditGraphState) -> list[dict[str, Any]]:
    """Resolve structured trace items for frontend evidence drilldown."""
    in_state = state.get("trace_items", [])
    resolved_from_state: list[dict[str, Any]] = []
    for item in in_state:
        if isinstance(item, dict):
            resolved_from_state.append(_normalize_trace_item(item))
        else:
            resolved_from_state.append(_normalize_trace_item(item.model_dump()))
    if resolved_from_state:
        return resolved_from_state

    final_report_payload = get_heavy_payload(state.get("final_report_ref", ""))
    if isinstance(final_report_payload, dict):
        payload_trace_items = final_report_payload.get("trace_items", [])
        if isinstance(payload_trace_items, list) and payload_trace_items:
            resolved_from_ref: list[dict[str, Any]] = []
            for item in payload_trace_items:
                if isinstance(item, dict):
                    resolved_from_ref.append(_normalize_trace_item(item))
            if resolved_from_ref:
                return resolved_from_ref

    payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(payload, dict):
        return []

    trace_items: list[dict[str, Any]] = []
    for trace in payload.get("claim_traces", [])[:5]:
        if not isinstance(trace, dict):
            continue
        evidences: list[dict[str, Any]] = []
        for evidence in trace.get("evidences", [])[:3]:
            if not isinstance(evidence, dict):
                continue
            evidences.append(
                {
                    "chunk_id": str(evidence.get("chunk_id", "") or ""),
                    "file_id": int(evidence.get("file_id", 0) or 0),
                    "file_name": str(evidence.get("file_name", "") or ""),
                    "page_no": int(evidence.get("page_no", 0) or 0),
                    "quote_text": str(evidence.get("quote_text", "") or ""),
                    "bbox_list": evidence.get("bbox_list", []) if isinstance(evidence.get("bbox_list"), list) else [],
                    "page_image_ref": resolve_minio_reference_url(str(evidence.get("page_image_ref", "") or "")),
                    "source_page_id": int(evidence.get("source_page_id", 0) or 0),
                }
            )
        trace_items.append(
            _normalize_trace_item(
                {
                "citation_id": "",
                "claim_id": int(trace.get("claim_id", 0) or 0),
                "claim_type": str(trace.get("claim_type", "") or ""),
                "claim_text": str(trace.get("claim_text", "") or ""),
                "confidence": float(trace.get("confidence", 0) or 0),
                "evidences": evidences,
                }
            )
        )
    return trace_items


def resolve_reconciliation_items(state: AuditGraphState) -> list[dict[str, Any]]:
    """Resolve incremental reconciliation ledger items for frontend display."""
    in_state = state.get("reconciliation_items", [])
    normalized_from_state: list[dict[str, Any]] = []
    for item in in_state:
        if isinstance(item, dict):
            normalized_from_state.append(dict(item))
        else:
            normalized_from_state.append(item.model_dump())
    if normalized_from_state:
        return normalized_from_state

    payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(payload, dict):
        return []
    items = payload.get("reconciliation_items", [])
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def resolve_unresolved_graph_items(state: AuditGraphState) -> dict[str, list[dict[str, Any]]]:
    """Resolve unresolved relations/claims captured during graph persistence."""
    relation_items = state.get("unresolved_relations", [])
    claim_items = state.get("unresolved_claims", [])

    normalized_relations: list[dict[str, Any]] = []
    normalized_claims: list[dict[str, Any]] = []

    for item in relation_items:
        if isinstance(item, dict):
            normalized_relations.append(dict(item))
        else:
            normalized_relations.append(item.model_dump())
    for item in claim_items:
        if isinstance(item, dict):
            normalized_claims.append(dict(item))
        else:
            normalized_claims.append(item.model_dump())

    if normalized_relations or normalized_claims:
        return {
            "unresolved_relations": normalized_relations,
            "unresolved_claims": normalized_claims,
        }

    payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(payload, dict):
        return {"unresolved_relations": [], "unresolved_claims": []}
    unresolved_relations = payload.get("unresolved_relations", [])
    unresolved_claims = payload.get("unresolved_claims", [])
    return {
        "unresolved_relations": [dict(item) for item in unresolved_relations if isinstance(item, dict)],
        "unresolved_claims": [dict(item) for item in unresolved_claims if isinstance(item, dict)],
    }


def _normalize_trace_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize outward-facing trace items so page_image_ref is directly accessible."""
    normalized = dict(item)
    evidences = normalized.get("evidences", [])
    if not isinstance(evidences, list):
        normalized["evidences"] = []
        return normalized

    normalized_evidences: list[dict[str, Any]] = []
    for evidence in evidences:
        if not isinstance(evidence, dict):
            continue
        evidence_copy = dict(evidence)
        evidence_copy["page_image_ref"] = resolve_minio_reference_url(str(evidence_copy.get("page_image_ref", "") or ""))
        normalized_evidences.append(evidence_copy)
    normalized["evidences"] = normalized_evidences
    return normalized
