"""Reconcile incremental graph updates and soft-supersede conflicting historical facts."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ...settings import get_settings
from ...services.kg_service import get_kg_service
from ..heavy_state import get_heavy_payload, put_heavy_payload
from ..json_utils import json_dumps_safe
from ..llm import build_zero_temp_router_llm
from ..prompting import load_prompt
from ..schemas import GraphDeltaDecisionBundleModel
from ..state import AuditGraphState


def reconcile_graph_delta(state: AuditGraphState) -> AuditGraphState:
    """Use a small structured judgment pass to decide whether new claims add or override old ones."""
    case_id = int(state.get("current_case_id", 0) or 0)
    chunk_ids = [str(chunk_id) for chunk_id in state.get("chunk_ids", []) if str(chunk_id)]
    if case_id <= 0 or not chunk_ids:
        return {}

    subgraph_payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(subgraph_payload, dict):
        return {}

    new_claim_ids = {
        int(row.get("id", 0) or 0)
        for row in subgraph_payload.get("claims", [])
        if isinstance(row, dict) and int(row.get("id", 0) or 0) > 0
    }
    if not new_claim_ids:
        return {"superseded_claim_ids": [], "superseded_relation_ids": []}

    new_claim_signatures = _build_new_claim_signatures(state)
    if not new_claim_signatures:
        return {"superseded_claim_ids": [], "superseded_relation_ids": []}

    kg_service = get_kg_service()
    candidates_payload = kg_service.fetch_candidate_conflicts_by_chunks(
        case_id=case_id,
        chunk_ids=chunk_ids,
        entity_keys=sorted({item["entity_key"] for item in new_claim_signatures if item["entity_key"]}),
        relation_keys=sorted({item["relation_key"] for item in new_claim_signatures if item["relation_key"]}),
        claim_texts=[item["claim_text"] for item in new_claim_signatures if item["claim_text"]],
        exclude_claim_ids=sorted(new_claim_ids),
        limit=max(len(new_claim_signatures) * 4, 12),
    )
    candidates = candidates_payload.get("candidates", []) if isinstance(candidates_payload, dict) else []
    if not candidates:
        return {"superseded_claim_ids": [], "superseded_relation_ids": []}

    decisions = _decide_graph_delta(state=state, new_claim_signatures=new_claim_signatures, candidates=candidates)
    superseded_claim_ids, superseded_relation_ids, reconciliation_items = _resolve_reconciliation_result(
        case_id=case_id,
        decisions=decisions,
        candidates=candidates,
        new_claim_ids=new_claim_ids,
        subgraph_payload=subgraph_payload,
        new_claim_signatures=new_claim_signatures,
    )
    if not superseded_claim_ids and not superseded_relation_ids:
        return {
            "superseded_claim_ids": [],
            "superseded_relation_ids": [],
            "reconciliation_items": [],
        }

    if superseded_claim_ids:
        kg_service.mark_claims_superseded(superseded_claim_ids)
    if superseded_relation_ids:
        kg_service.mark_relations_superseded(superseded_relation_ids)
    if reconciliation_items:
        persisted_items = kg_service.insert_reconciliation_ledger(case_id=case_id, rows=reconciliation_items)
        reconciliation_items = _merge_reconciliation_texts(
            reconciliation_items,
            persisted_items,
        )

    snapshot = kg_service.fetch_case_graph_snapshot(case_id)
    if not snapshot:
        return {
            "superseded_claim_ids": superseded_claim_ids,
            "superseded_relation_ids": superseded_relation_ids,
            "reconciliation_items": reconciliation_items,
        }

    summary = (
        f"实体{int(snapshot.get('entity_count', 0) or 0)}个，"
        f"关系{int(snapshot.get('relation_count', 0) or 0)}条，"
        f"断言{int(snapshot.get('claim_count', 0) or 0)}条，"
        f"证据映射{int(snapshot.get('evidence_count', 0) or 0)}条"
    )
    return {
        "kg_subgraph_ref": put_heavy_payload(
            "kg_subgraph",
            {
                "entities": snapshot.get("entities", []),
                "relations": snapshot.get("relations", []),
                "claims": snapshot.get("claims", []),
                "claim_traces": snapshot.get("claim_traces", []),
                "reconciliation_items": snapshot.get("reconciliation_items", []),
                "evidence_count": int(snapshot.get("evidence_count", 0) or 0),
            },
        ),
        "kg_summary": summary,
        "superseded_claim_ids": superseded_claim_ids,
        "superseded_relation_ids": superseded_relation_ids,
        "reconciliation_items": snapshot.get("reconciliation_items", []) or reconciliation_items,
    }


def _decide_graph_delta(
    *,
    state: AuditGraphState,
    new_claim_signatures: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    settings = get_settings()
    fallback_decisions = _fallback_decisions(new_claim_signatures=new_claim_signatures, candidates=candidates)
    if settings.get_llm_config("router")["api_key"]:
        try:
            llm = build_zero_temp_router_llm()
            structured_llm = llm.with_structured_output(GraphDeltaDecisionBundleModel)
            prompt = load_prompt("reconcile_graph_delta.txt")
            result = structured_llm.invoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(
                        content=_build_reconcile_input(
                            state=state,
                            new_claim_signatures=new_claim_signatures,
                            candidates=candidates,
                        )
                    ),
                ]
            )
            return _merge_decisions_with_fallback(
                primary=[item.model_dump() for item in result.decisions],
                fallback=fallback_decisions,
            )
        except Exception:
            pass
    return fallback_decisions


def _merge_decisions_with_fallback(
    *,
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fallback_by_text = {
        _normalize_text(str(item.get("new_claim_text", "") or "")): item for item in fallback
    }
    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in primary:
        key = _normalize_text(str(item.get("new_claim_text", "") or ""))
        fallback_item = fallback_by_text.get(key)
        primary_ids = {int(claim_id) for claim_id in item.get("supersede_claim_ids", []) if int(claim_id) > 0}
        fallback_ids = set()
        if fallback_item:
            fallback_ids = {
                int(claim_id)
                for claim_id in fallback_item.get("supersede_claim_ids", [])
                if int(claim_id) > 0
            }
        merged_ids = sorted(primary_ids | fallback_ids)
        action = "OVERRIDE" if merged_ids else str(item.get("action", "ADD") or "ADD")
        rationale = str(item.get("rationale", "") or "").strip()
        if fallback_ids and not primary_ids:
            rationale = f"{rationale}; fallback heuristic corroboration".strip("; ")
        merged.append(
            {
                "new_claim_text": str(item.get("new_claim_text", "") or ""),
                "action": action,
                "supersede_claim_ids": merged_ids,
                "rationale": rationale,
            }
        )
        seen_keys.add(key)
    for item in fallback:
        key = _normalize_text(str(item.get("new_claim_text", "") or ""))
        if key in seen_keys:
            continue
        merged.append(item)
    return merged


def _build_reconcile_input(
    *,
    state: AuditGraphState,
    new_claim_signatures: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    chunk_payload = get_heavy_payload(state.get("chunk_batch_ref", ""))
    chunk_summaries: list[dict[str, Any]] = []
    if isinstance(chunk_payload, dict):
        for chunk in chunk_payload.get("chunks", [])[:12]:
            if not isinstance(chunk, dict):
                continue
            chunk_text = str(chunk.get("chunk_text", "") or "").strip()
            chunk_summaries.append(
                {
                    "chunk_id": str(chunk.get("chunk_id", "") or ""),
                    "page_no": int(chunk.get("page_no", 0) or 0),
                    "chunk_text": chunk_text[:400],
                }
            )

    compact_candidates = []
    for candidate in candidates[:24]:
        compact_candidates.append(
            {
                "claim_id": int(candidate.get("claim_id", 0) or 0),
                "claim_text": str(candidate.get("claim_text", "") or ""),
                "entity_key": str(candidate.get("entity_key", "") or ""),
                "relation_key": str(candidate.get("relation_key", "") or ""),
                "relation_id": int(candidate.get("relation_id", 0) or 0),
                "matched_by": candidate.get("matched_by", []),
                "match_score": float(candidate.get("match_score", 0) or 0),
            }
        )

    payload = {
        "query": str(state.get("query", "") or ""),
        "correction_records": state.get("correction_records", []) or [],
        "new_claims": [
            {
                "claim_text": item["claim_text"],
                "entity_key": item["entity_key"],
                "relation_key": item["relation_key"],
                "evidence_chunk_ids": item["evidence_chunk_ids"],
            }
            for item in new_claim_signatures
        ],
        "candidate_old_claims": compact_candidates,
        "chunk_evidence": chunk_summaries,
    }
    return json_dumps_safe(payload)


def _fallback_decisions(
    *,
    new_claim_signatures: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for signature in new_claim_signatures:
        supersede_claim_ids: list[int] = []
        for candidate in candidates:
            claim_id = int(candidate.get("claim_id", 0) or 0)
            if claim_id <= 0:
                continue
            if not _candidate_matches_signature(candidate, signature):
                continue
            matched_by = {str(item) for item in candidate.get("matched_by", [])}
            match_score = float(candidate.get("match_score", 0) or 0)
            has_strong_key_match = "relation_key" in matched_by or (
                "entity_key" in matched_by and "claim_text" in matched_by
            )
            if (
                not _fallback_override_would_drop_specificity(candidate, signature)
                and (
                has_strong_key_match
                or match_score >= 0.72
                or _supports_semantic_family_override(candidate, signature)
                )
            ):
                supersede_claim_ids.append(claim_id)

        decisions.append(
            {
                "new_claim_text": signature["claim_text"],
                "action": "OVERRIDE" if supersede_claim_ids else "ADD",
                "supersede_claim_ids": sorted(set(supersede_claim_ids)),
                "rationale": "fallback heuristic",
            }
        )
    return decisions


def _resolve_reconciliation_result(
    *,
    case_id: int,
    decisions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    new_claim_ids: set[int],
    subgraph_payload: dict[str, Any],
    new_claim_signatures: list[dict[str, Any]],
) -> tuple[list[int], list[int], list[dict[str, Any]]]:
    candidate_by_claim_id = {
        int(candidate.get("claim_id", 0) or 0): candidate
        for candidate in candidates
        if int(candidate.get("claim_id", 0) or 0) > 0
    }
    new_claims_by_text_norm = {
        _normalize_text(str(item.get("claim_text", "") or "")): item
        for item in subgraph_payload.get("claims", [])
        if isinstance(item, dict) and str(item.get("claim_text", "") or "").strip()
    }
    signature_by_text_norm = {
        _normalize_text(str(item.get("claim_text", "") or "")): item for item in new_claim_signatures
    }
    superseded_claim_ids: set[int] = set()
    superseded_relation_ids: set[int] = set()
    reconciliation_items: list[dict[str, Any]] = []

    for decision in decisions:
        normalized_action = str(decision.get("action", "ADD") or "ADD").upper()
        signature = signature_by_text_norm.get(_normalize_text(str(decision.get("new_claim_text", "") or "")))
        if not signature:
            continue
        new_claim = new_claims_by_text_norm.get(signature["claim_text_norm"], {})
        new_claim_id = int(new_claim.get("id", 0) or 0)
        new_relation_id = int(new_claim.get("relation_id", 0) or 0)
        rationale = str(decision.get("rationale", "") or "").strip()
        if normalized_action != "OVERRIDE":
            continue
        for claim_id in decision.get("supersede_claim_ids", []):
            normalized_claim_id = int(claim_id or 0)
            if normalized_claim_id <= 0 or normalized_claim_id in new_claim_ids:
                continue
            candidate = candidate_by_claim_id.get(normalized_claim_id)
            if not candidate or not _candidate_matches_signature(candidate, signature):
                continue
            superseded_claim_ids.add(normalized_claim_id)
            relation_id = int(candidate.get("relation_id", 0) or 0)
            if relation_id > 0 and signature["relation_key"] and str(candidate.get("relation_key", "") or "") == signature["relation_key"]:
                superseded_relation_ids.add(relation_id)
            reconciliation_items.append(
                {
                    "case_id": case_id,
                    "action": normalized_action,
                    "new_claim_id": new_claim_id,
                    "new_claim_text": signature["claim_text"],
                    "superseded_claim_id": normalized_claim_id,
                    "superseded_claim_text": str(candidate.get("claim_text", "") or ""),
                    "new_relation_id": new_relation_id if new_relation_id > 0 else None,
                    "superseded_relation_id": relation_id if relation_id > 0 else None,
                    "rationale": rationale,
                    "evidence_chunk_ids": signature["evidence_chunk_ids"],
                    "decision_payload": {
                        "matched_by": candidate.get("matched_by", []),
                        "match_score": float(candidate.get("match_score", 0) or 0),
                        "decision": dict(decision),
                    },
                }
            )

    return sorted(superseded_claim_ids), sorted(superseded_relation_ids), reconciliation_items


def _merge_reconciliation_texts(
    source_items: list[dict[str, Any]],
    persisted_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not persisted_items:
        return source_items
    index = {
        (
            int(item.get("new_claim_id", 0) or 0),
            int(item.get("superseded_claim_id", 0) or 0),
        ): item
        for item in source_items
    }
    merged: list[dict[str, Any]] = []
    for item in persisted_items:
        key = (
            int(item.get("new_claim_id", 0) or 0),
            int(item.get("superseded_claim_id", 0) or 0),
        )
        source = index.get(key, {})
        merged.append(
            {
                **dict(item),
                "new_claim_text": str(source.get("new_claim_text", "") or item.get("new_claim_text", "") or ""),
                "superseded_claim_text": str(source.get("superseded_claim_text", "") or item.get("superseded_claim_text", "") or ""),
            }
        )
    return merged


def _build_new_claim_signatures(state: AuditGraphState) -> list[dict[str, Any]]:
    entity_key_by_temp_id: dict[str, str] = {}
    entity_name_by_temp_id: dict[str, str] = {}
    for entity in state.get("kg_entities", []):
        entity_dict = entity if isinstance(entity, dict) else entity.model_dump()
        temp_id = str(entity_dict.get("entity_temp_id", "") or "")
        if temp_id:
            entity_key_by_temp_id[temp_id] = str(entity_dict.get("entity_key", "") or "")
            entity_name_by_temp_id[temp_id] = str(
                entity_dict.get("canonical_name") or entity_dict.get("name") or ""
            ).strip()

    relation_key_by_temp_id: dict[str, str] = {}
    for relation in state.get("kg_relations", []):
        relation_dict = relation if isinstance(relation, dict) else relation.model_dump()
        temp_id = str(relation_dict.get("relation_temp_id", "") or "")
        if temp_id:
            relation_key_by_temp_id[temp_id] = str(relation_dict.get("relation_key", "") or "")

    signatures: list[dict[str, Any]] = []
    for claim in state.get("kg_claims", []):
        claim_dict = claim if isinstance(claim, dict) else claim.model_dump()
        claim_text = str(claim_dict.get("claim_text", "") or "").strip()
        if not claim_text:
            continue
        entity_temp_id = str(claim_dict.get("entity_temp_id", "") or "")
        relation_temp_id = str(claim_dict.get("relation_temp_id", "") or "")
        signatures.append(
            {
                "claim_text": claim_text,
                "claim_text_norm": _normalize_text(claim_text),
                "claim_type": str(claim_dict.get("claim_type", "") or ""),
                "claim_family": _claim_semantic_family(claim_text),
                "entity_key": entity_key_by_temp_id.get(entity_temp_id, ""),
                "entity_name": entity_name_by_temp_id.get(entity_temp_id, ""),
                "relation_key": relation_key_by_temp_id.get(relation_temp_id, ""),
                "evidence_chunk_ids": [str(item) for item in claim_dict.get("evidence_chunk_ids", []) if str(item)],
            }
        )
    return signatures


def _candidate_matches_signature(candidate: dict[str, Any], signature: dict[str, Any]) -> bool:
    candidate_claim_type = str(candidate.get("claim_type", "") or "")
    signature_claim_type = str(signature.get("claim_type", "") or "")
    candidate_family = _claim_semantic_family(str(candidate.get("claim_text", "") or ""))
    signature_family = str(signature.get("claim_family", "") or "")
    if (
        candidate_claim_type
        and signature_claim_type
        and candidate_claim_type != signature_claim_type
        and candidate_family != signature_family
    ):
        return False

    candidate_entity_key = str(candidate.get("entity_key", "") or "")
    candidate_relation_key = str(candidate.get("relation_key", "") or "")
    if candidate_relation_key and signature["relation_key"] and candidate_relation_key == signature["relation_key"]:
        return True
    if candidate_entity_key and signature["entity_key"] and candidate_entity_key == signature["entity_key"]:
        return _claims_share_specific_text(candidate, signature) or _claims_share_fact_slot(
            claim_family=signature_family,
            candidate_text=str(candidate.get("claim_text", "") or ""),
            signature_text=str(signature.get("claim_text", "") or ""),
        )
    if candidate_family != "generic" and candidate_family == signature_family:
        return _claims_are_highly_similar(candidate, signature)
    return False


def _normalize_text(value: str) -> str:
    return "".join(str(value or "").strip().lower().split())


def _claims_share_specific_text(candidate: dict[str, Any], signature: dict[str, Any]) -> bool:
    candidate_text = _strip_entity_name(
        str(candidate.get("claim_text", "") or ""),
        str(candidate.get("canonical_name", "") or ""),
    )
    signature_text = _strip_entity_name(signature["claim_text"], signature.get("entity_name", ""))
    if not candidate_text or not signature_text:
        return False
    if candidate_text in signature_text or signature_text in candidate_text:
        return min(len(candidate_text), len(signature_text)) >= 8
    return SequenceMatcher(a=candidate_text, b=signature_text).ratio() >= 0.58


def _claims_are_highly_similar(candidate: dict[str, Any], signature: dict[str, Any]) -> bool:
    candidate_text = _normalize_text(str(candidate.get("claim_text", "") or ""))
    signature_text = signature["claim_text_norm"]
    if not candidate_text or not signature_text:
        return False
    return SequenceMatcher(a=candidate_text, b=signature_text).ratio() >= 0.84


def _supports_semantic_family_override(candidate: dict[str, Any], signature: dict[str, Any]) -> bool:
    candidate_family = _claim_semantic_family(str(candidate.get("claim_text", "") or ""))
    signature_family = str(signature.get("claim_family", "") or "")
    if not candidate_family or candidate_family == "generic" or candidate_family != signature_family:
        return False

    candidate_relation_key = str(candidate.get("relation_key", "") or "")
    signature_relation_key = str(signature.get("relation_key", "") or "")
    if candidate_relation_key and signature_relation_key:
        return candidate_relation_key == signature_relation_key

    candidate_entity_key = str(candidate.get("entity_key", "") or "")
    signature_entity_key = str(signature.get("entity_key", "") or "")
    if not candidate_entity_key or not signature_entity_key or candidate_entity_key != signature_entity_key:
        return False

    return _claims_share_fact_slot(
        claim_family=signature_family,
        candidate_text=str(candidate.get("claim_text", "") or ""),
        signature_text=str(signature.get("claim_text", "") or ""),
    )


def _fallback_override_would_drop_specificity(candidate: dict[str, Any], signature: dict[str, Any]) -> bool:
    signature_family = str(signature.get("claim_family", "") or "")
    if signature_family not in {
        "bankruptcy_application",
        "bankruptcy_acceptance",
        "bankruptcy_declaration",
    }:
        return False
    candidate_text = str(candidate.get("claim_text", "") or "")
    signature_text = str(signature.get("claim_text", "") or "")
    if not candidate_text or not signature_text:
        return False
    if len(_normalize_text(signature_text)) >= len(_normalize_text(candidate_text)):
        return False
    candidate_markers = _specificity_markers(candidate_text)
    signature_markers = _specificity_markers(signature_text)
    return bool(candidate_markers - signature_markers)


def _strip_entity_name(text: str, entity_name: str) -> str:
    normalized_text = _normalize_text(text)
    normalized_entity_name = _normalize_text(entity_name)
    if normalized_entity_name:
        normalized_text = normalized_text.replace(normalized_entity_name, "")
    return normalized_text


def _claims_share_fact_slot(*, claim_family: str, candidate_text: str, signature_text: str) -> bool:
    markers = _claim_family_markers(claim_family)
    if not markers:
        return False
    normalized_candidate = _normalize_text(candidate_text)
    normalized_signature = _normalize_text(signature_text)
    candidate_hits = {marker for marker in markers if marker in normalized_candidate}
    signature_hits = {marker for marker in markers if marker in normalized_signature}
    return bool(candidate_hits and signature_hits and candidate_hits & signature_hits)


def _claim_family_markers(claim_family: str) -> tuple[str, ...]:
    family_markers = {
        "insolvency": ("资不抵债", "清算净值", "资产评估总价值"),
        "restructuring_possibility": ("债权人会议", "重整", "和解"),
        "creditors_meeting": ("债权人会议", "时间", "地点", "召开", "举行"),
        "administrator_appointment": ("管理人", "指定", "担任"),
        "bankruptcy_application": ("申请", "破产清算"),
        "bankruptcy_acceptance": ("受理", "破产清算"),
        "bankruptcy_declaration": ("宣告破产", "裁定破产"),
    }
    return family_markers.get(claim_family, ())


def _specificity_markers(text: str) -> set[str]:
    normalized = _normalize_text(text)
    markers: set[str] = set()
    if "贵州省六盘水市中级人民法院" in normalized or "人民法院" in normalized or "法院" in normalized:
        markers.add("court")
    if "裁定" in normalized:
        markers.add("ruling")
    if "申请" in normalized:
        markers.add("application")
    if any(token in normalized for token in ("2024年", "2025年", "2026年", "2027年", "月", "日")):
        markers.add("date")
    return markers


def _claim_semantic_family(claim_text: str) -> str:
    normalized = _normalize_text(claim_text)
    if not normalized:
        return "generic"
    if "债权人会议" in normalized:
        if "重整" in normalized or "和解" in normalized:
            return "restructuring_possibility"
        return "creditors_meeting"
    if "资不抵债" in normalized or "清算净值" in normalized or "资产评估总价值" in normalized:
        return "insolvency"
    if "管理人" in normalized and ("指定" in normalized or "担任" in normalized):
        return "administrator_appointment"
    if "申请" in normalized and "破产" in normalized:
        return "bankruptcy_application"
    if "受理" in normalized and "破产" in normalized:
        return "bankruptcy_acceptance"
    if "宣告破产" in normalized or ("裁定" in normalized and "破产" in normalized):
        return "bankruptcy_declaration"
    return "generic"
