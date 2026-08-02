"""Helpers for resolving out-of-band heavy context payloads inside graph nodes."""

from typing import Any

from ..services.minio_service import resolve_minio_reference_url
from .heavy_state import get_heavy_payload
from .json_utils import json_dumps_safe
from .metrics_engine import compute_metrics
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


# ── 报告上下文对齐（下游 1.1）+ 本息口径回收率（下游 1.2）──────────────────
# 报告改用上游权威字段（real_estate_dehydrated/mining_dehydrated 战术沙盘 +
# engine_results.valuation_squeeze 去毒明细），弃用 legacy 截断的
# real_estate_evaluations/mining_evaluations；回收率改用本息口径下游重算。

# 回收率口径参数（可配置预留；默认值见此，后续接 settings）。
RECOVERY_PARAMS = {
    "recovery_base": "principal_interest",  # 分母口径：终审本金+利息（排除罚息/复利/迟延）
}


def _num(value: Any) -> float | None:
    """Best-effort 数值化；非数字/None → None。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_recovery_metrics(full_context_data: dict[str, Any]) -> dict[str, Any]:
    """下游本息口径回收率（1.2）。

    - recovery_base = Σ(principal+interest)，仅本息齐全的 claim（排除 penalty/delayed_interest/复利）。
    - unsplittable：无本息拆分的 claim（如重整方案派生）→ 计数 + total_claim 合计 + 各自清偿率。
    - asset_net_total = valuation_squeeze.total_net_value（去毒后资产净值）。
    - recovery_rate_principal_interest = asset_net_total / recovery_base。
    与上游 valuation_squeeze.recovery_rate（分母为 SUM(total_claim)，含罚息复利）口径分离。
    """
    claims = full_context_data.get("claims") or []
    valuation = (full_context_data.get("engine_results") or {}).get("valuation_squeeze") or {}

    recovery_base = 0.0
    subordinated_total = 0.0
    split_count = 0
    unsplittable_total = 0.0
    unsplittable_count = 0
    restructuring_rates: list[float] = []

    for c in claims:
        if not isinstance(c, dict):
            continue
        principal = _num(c.get("principal"))
        interest = _num(c.get("interest"))
        penalty = _num(c.get("penalty"))
        delayed = _num(c.get("delayed_interest"))
        if principal is not None or interest is not None:
            recovery_base += (principal or 0.0) + (interest or 0.0)
            split_count += 1
        else:
            unsplittable_count += 1
            unsplittable_total += _num(c.get("total_claim")) or 0.0
        subordinated_total += (penalty or 0.0) + (delayed or 0.0)
        rate = _num(c.get("proposed_recovery_rate"))
        if rate is not None:
            restructuring_rates.append(rate)

    asset_net_total = _num(valuation.get("total_net_value"))
    rate_pi = (
        round(asset_net_total / recovery_base, 4)
        if asset_net_total is not None and recovery_base > 0
        else None
    )

    return {
        "params": dict(RECOVERY_PARAMS),
        "recovery_base_principal_interest": round(recovery_base, 2),
        "subordinated_total": round(subordinated_total, 2),
        "asset_net_total": round(asset_net_total, 2) if asset_net_total is not None else None,
        "recovery_rate_principal_interest": rate_pi,  # 0-1 比值
        "recovery_rate_principal_interest_pct": round(rate_pi * 100, 2) if rate_pi is not None else None,
        "split_claim_count": split_count,
        "unsplittable_claim_count": unsplittable_count,
        "unsplittable_total_claim": round(unsplittable_total, 2),
        "restructuring_recovery_rates": restructuring_rates,
        "note": (
            "recovery_base 为本息口径（principal+interest，排除罚息/复利/迟延）；"
            "asset_net_total 取自 valuation_squeeze 去毒净值；"
            "无本息拆分的 claim（如重整方案）计入 unsplittable，参考其 proposed_recovery_rate（清偿率）。"
        ),
    }


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
    """解析确定性数值引擎结果：优先 computed_metrics_ref（compute_metrics 节点已算），否则就地计算。"""
    payload = get_heavy_payload(state.get("computed_metrics_ref", ""))
    if isinstance(payload, dict) and payload:
        return payload
    return compute_metrics(resolve_full_context_data(state))


def build_report_context(
    full_context_data: dict[str, Any],
    computed_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """精选报告上下文（1.1）：用权威字段，弃 legacy 截断字段，注入数值引擎结果。"""
    engine = full_context_data.get("engine_results") or {}
    return {
        "case_id": full_context_data.get("case_id", 0),
        "case": full_context_data.get("case"),
        "debtors": full_context_data.get("debtors") or [],
        "claims": full_context_data.get("claims") or [],
        "guarantors": full_context_data.get("guarantors") or [],
        "financial_snapshots": full_context_data.get("financial_snapshots") or [],
        # 权威资产表示（战术沙盘：全量总账 + 核心 topN + 碎片打包 + 毒点），替代 legacy 截断字段
        "real_estate": full_context_data.get("real_estate_dehydrated") or {},
        "mining": full_context_data.get("mining_dehydrated") or {},
        # 去毒明细（net_value/discount_factors/verdict/totals）
        "valuation_detail": engine.get("valuation_squeeze") or {},
        # 时效看板 / 行为扫描 / 轧差
        "deadline_board": engine.get("deadline_scan") or {},
        "behavioral": engine.get("behavioral_scan") or {},
        "delta": engine.get("delta_check") or {},
        "whiteglove": full_context_data.get("whiteglove") or {},
        "fund_flow": full_context_data.get("fund_flow") or {},
        # 确定性数值引擎结果（本息回收率 + NPV + 去毒总账 + 数据质量）
        "computed_metrics": computed_metrics if computed_metrics is not None else compute_metrics(full_context_data),
        "_field_note": "资产请用 real_estate/mining（沙盘）+ valuation_detail（去毒）；数值用 computed_metrics（本息回收率/NPV/总账）；已弃用 legacy real_estate_evaluations/mining_evaluations 截断字段。",
    }


def resolve_report_full_context_json(state: AuditGraphState) -> str:
    """报告用的精选 full-context JSON（1.1+1.2+数值引擎）。无数据时回退原始 JSON。"""
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
