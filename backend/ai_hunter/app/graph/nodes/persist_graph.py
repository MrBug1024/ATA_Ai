"""Persist extracted graph items and build a lightweight graph summary."""

from __future__ import annotations

import logging
from typing import Any

from ...services.graph_identity import DEFAULT_GRAPH_STATUS, normalize_entity_name, normalize_graph_status
from ...services.kg_service import get_kg_service
from ..heavy_state import get_heavy_payload, put_heavy_payload
from ..state import AuditGraphState

LOGGER = logging.getLogger(__name__)


def persist_graph(state: AuditGraphState) -> AuditGraphState:
    """Persist extracted entities, relations, and claims into PostgreSQL."""
    case_id = state.get("current_case_id", 0)
    run_id = state.get("kg_extraction_run_id", 0)
    entities = state.get("kg_entities", [])
    relations = state.get("kg_relations", [])
    claims = state.get("kg_claims", [])
    if case_id <= 0 or run_id <= 0:
        return {}

    kg_service = get_kg_service()
    persisted_entities = kg_service.upsert_entities(case_id=case_id, rows=entities)

    entity_id_by_temp_id: dict[str, int] = {}
    entity_key_by_temp_id: dict[str, str] = {}
    entity_name_by_temp_id: dict[str, str] = {}
    for source, persisted in zip(entities, persisted_entities, strict=False):
        entity_dict = source if isinstance(source, dict) else source.model_dump()
        temp_id = entity_dict.get("entity_temp_id", "")
        if temp_id:
            entity_id_by_temp_id[str(temp_id)] = int(persisted["id"])
            entity_key_by_temp_id[str(temp_id)] = str(entity_dict.get("entity_key", "") or persisted.get("entity_key", "") or "")
            entity_name_by_temp_id[str(temp_id)] = str(
                entity_dict.get("canonical_name", "") or entity_dict.get("name", "") or persisted.get("canonical_name", "") or ""
            )
    entity_lookup = _build_entity_lookup(
        case_id=case_id,
        kg_service=kg_service,
        persisted_entities=persisted_entities,
        entity_key_by_temp_id=entity_key_by_temp_id,
        entity_name_by_temp_id=entity_name_by_temp_id,
    )

    relation_rows: list[dict[str, Any]] = []
    persisted_source_relations: list[dict[str, Any]] = []
    unresolved_relations: list[dict[str, Any]] = []
    for relation in relations:
        relation_dict = relation if isinstance(relation, dict) else relation.model_dump()
        from_entity_id = _resolve_entity_id(
            relation_dict=relation_dict,
            temp_field="from_entity_temp_id",
            key_field="from_entity_key",
            name_field="from_entity_name",
            entity_id_by_temp_id=entity_id_by_temp_id,
            entity_lookup=entity_lookup,
        )
        to_entity_id = _resolve_entity_id(
            relation_dict=relation_dict,
            temp_field="to_entity_temp_id",
            key_field="to_entity_key",
            name_field="to_entity_name",
            entity_id_by_temp_id=entity_id_by_temp_id,
            entity_lookup=entity_lookup,
        )
        if from_entity_id <= 0 or to_entity_id <= 0:
            missing_dependencies: list[str] = []
            if from_entity_id <= 0:
                missing_dependencies.append("from_entity")
            if to_entity_id <= 0:
                missing_dependencies.append("to_entity")
            unresolved_relations.append(
                {
                    "relation_temp_id": str(relation_dict.get("relation_temp_id", "") or ""),
                    "relation_key": str(relation_dict.get("relation_key", "") or ""),
                    "relation_type": str(relation_dict.get("relation_type", "") or ""),
                    "relation_label": str(relation_dict.get("relation_label", "") or ""),
                    "from_entity_temp_id": str(relation_dict.get("from_entity_temp_id", "") or ""),
                    "to_entity_temp_id": str(relation_dict.get("to_entity_temp_id", "") or ""),
                    "from_entity_key": str(relation_dict.get("from_entity_key", "") or ""),
                    "to_entity_key": str(relation_dict.get("to_entity_key", "") or ""),
                    "from_entity_name": str(relation_dict.get("from_entity_name", "") or ""),
                    "to_entity_name": str(relation_dict.get("to_entity_name", "") or ""),
                    "direction": str(relation_dict.get("direction", "directed") or "directed"),
                    "amount": relation_dict.get("amount"),
                    "amount_currency": str(relation_dict.get("amount_currency", "CNY") or "CNY"),
                    "event_date": relation_dict.get("event_date"),
                    "attributes": relation_dict.get("attributes", {}),
                    "confidence": relation_dict.get("confidence", 0),
                    "source_count": relation_dict.get("source_count", len(relation_dict.get("evidence_chunk_ids", []))),
                    "human_verified": relation_dict.get("human_verified", False),
                    "status": relation_dict.get("status", "active"),
                    "missing_dependencies": missing_dependencies,
                    "reason": "missing_entity_reference",
                    "evidence_chunk_ids": [str(item) for item in relation_dict.get("evidence_chunk_ids", [])],
                }
            )
            continue
        relation_rows.append(
            {
                "relation_key": relation_dict.get("relation_key", ""),
                "from_entity_id": from_entity_id,
                "to_entity_id": to_entity_id,
                "relation_type": relation_dict.get("relation_type", ""),
                "relation_label": relation_dict.get("relation_label", ""),
                "direction": relation_dict.get("direction", "directed"),
                "amount": relation_dict.get("amount"),
                "amount_currency": relation_dict.get("amount_currency", "CNY"),
                "event_date": relation_dict.get("event_date"),
                "attributes": relation_dict.get("attributes", {}),
                "confidence": relation_dict.get("confidence", 0),
                "source_count": relation_dict.get("source_count", len(relation_dict.get("evidence_chunk_ids", []))),
                "human_verified": relation_dict.get("human_verified", False),
                "status": relation_dict.get("status", "active"),
            }
        )
        persisted_source_relations.append(relation_dict)
    persisted_relations = kg_service.upsert_relations(case_id=case_id, rows=relation_rows)

    relation_id_by_temp_id: dict[str, int] = {}
    relation_key_by_temp_id: dict[str, str] = {}
    for source, persisted in zip(persisted_source_relations, persisted_relations, strict=False):
        relation_dict = source if isinstance(source, dict) else source.model_dump()
        temp_id = relation_dict.get("relation_temp_id", "")
        if temp_id:
            relation_id_by_temp_id[str(temp_id)] = int(persisted["id"])
            relation_key_by_temp_id[str(temp_id)] = str(relation_dict.get("relation_key", "") or persisted.get("relation_key", "") or "")
    relation_lookup = _build_relation_lookup(case_id=case_id, kg_service=kg_service, persisted_relations=persisted_relations)

    replayed_relations, resolved_relation_updates = _replay_unresolved_relations(
        case_id=case_id,
        kg_service=kg_service,
        entity_lookup=entity_lookup,
        relation_lookup=relation_lookup,
    )
    if replayed_relations:
        persisted_relations.extend(replayed_relations)
        relation_lookup = _build_relation_lookup(case_id=case_id, kg_service=kg_service, persisted_relations=persisted_relations)

    claim_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    source_chunk_map = _load_source_chunk_map(state)
    persisted_source_claims: list[dict[str, Any]] = []
    unresolved_claims: list[dict[str, Any]] = []

    for claim in claims:
        claim_dict = claim if isinstance(claim, dict) else claim.model_dump()
        entity_temp_id = str(claim_dict.get("entity_temp_id", "") or "")
        relation_temp_id = str(claim_dict.get("relation_temp_id", "") or "")
        entity_id = entity_id_by_temp_id.get(entity_temp_id) if entity_temp_id else None
        if entity_id is None:
            entity_id = _resolve_entity_id_for_claim(claim_dict, entity_lookup)
        relation_id = relation_id_by_temp_id.get(relation_temp_id) if relation_temp_id else None
        if relation_id is None:
            relation_id = _resolve_relation_id_for_claim(claim_dict, relation_lookup)
        missing_dependencies: list[str] = []
        if (entity_temp_id or claim_dict.get("entity_key") or claim_dict.get("entity_name")) and entity_id is None:
            missing_dependencies.append("entity")
        if (relation_temp_id or claim_dict.get("relation_key")) and relation_id is None:
            missing_dependencies.append("relation")
        if missing_dependencies:
            unresolved_claims.append(
                {
                    "claim_type": str(claim_dict.get("claim_type", "") or ""),
                    "claim_text": str(claim_dict.get("claim_text", "") or ""),
                    "entity_name": str(claim_dict.get("entity_name", "") or ""),
                    "entity_key": str(claim_dict.get("entity_key", "") or ""),
                    "entity_temp_id": entity_temp_id,
                    "relation_key": str(claim_dict.get("relation_key", "") or ""),
                    "relation_temp_id": relation_temp_id,
                    "claim_value": claim_dict.get("claim_value", {}),
                    "confidence": claim_dict.get("confidence", 0),
                    "status": normalize_graph_status(str(claim_dict.get("status", DEFAULT_GRAPH_STATUS) or "")),
                    "review_status": str(claim_dict.get("review_status", "pending") or "pending"),
                    "missing_dependencies": missing_dependencies,
                    "reason": "missing_graph_reference",
                    "evidence_chunk_ids": [str(item) for item in claim_dict.get("evidence_chunk_ids", [])],
                }
            )
            continue
        claim_rows.append(
            {
                "entity_id": entity_id,
                "relation_id": relation_id,
                "claim_type": claim_dict.get("claim_type", ""),
                "claim_text": claim_dict.get("claim_text", ""),
                "claim_value": claim_dict.get("claim_value", {}),
                "confidence": claim_dict.get("confidence", 0),
                "status": normalize_graph_status(str(claim_dict.get("status", DEFAULT_GRAPH_STATUS) or "")),
                "review_status": str(claim_dict.get("review_status", "pending") or "pending"),
            }
        )
        persisted_source_claims.append(claim_dict)

    persisted_claims = kg_service.insert_claims(
        case_id=case_id,
        extraction_run_id=run_id,
        rows=claim_rows,
    )
    replayed_claims, replayed_evidence_rows, resolved_claim_updates, replay_skipped_evidences = _replay_unresolved_claims(
        case_id=case_id,
        run_id=run_id,
        kg_service=kg_service,
        entity_lookup=entity_lookup,
        relation_lookup=relation_lookup,
        source_chunk_map=source_chunk_map,
    )
    replay_reconciliation_items = _build_replay_reconciliation_items(
        case_id=case_id,
        replayed_claims=replayed_claims,
        resolved_claim_updates=resolved_claim_updates,
    )
    if replayed_claims:
        persisted_claims.extend(replayed_claims)
        evidence_rows.extend(replayed_evidence_rows)

    claim_traces: list[dict[str, Any]] = []
    skipped_evidences: list[dict[str, Any]] = list(replay_skipped_evidences)
    for source_claim, persisted_claim in zip(persisted_source_claims, persisted_claims, strict=False):
        claim_dict = source_claim if isinstance(source_claim, dict) else source_claim.model_dump()
        trace_evidences: list[dict[str, Any]] = []
        for chunk_id in claim_dict.get("evidence_chunk_ids", []):
            chunk_payload = source_chunk_map.get(str(chunk_id), {})
            evidence_payload = _build_evidence_payload(
                claim_id=int(persisted_claim["id"]),
                chunk_id=str(chunk_id),
                chunk_payload=chunk_payload,
                score=float(claim_dict.get("confidence", 0) or 0),
            )
            if evidence_payload is None:
                skipped_evidences.append(
                    _build_skipped_evidence_record(
                        claim_id=int(persisted_claim["id"]),
                        claim_text=str(persisted_claim.get("claim_text", "") or claim_dict.get("claim_text", "")),
                        chunk_id=str(chunk_id),
                        chunk_payload=chunk_payload,
                        path="claim",
                    )
                )
                continue
            evidence_rows.append(evidence_payload)
            trace_evidences.append(
                {
                    "chunk_id": evidence_payload["chunk_id"],
                    "file_id": evidence_payload["file_id"],
                    "page_no": evidence_payload["page_no"],
                    "quote_text": evidence_payload["quote_text"],
                    "bbox_list": chunk_payload.get("bbox_list", []),
                    "source_page_id": int(chunk_payload.get("page_id", 0) or 0),
                    "page_image_ref": str(chunk_payload.get("page_image_ref", "") or ""),
                }
            )
        claim_traces.append(
            {
                "claim_id": int(persisted_claim["id"]),
                "claim_type": str(persisted_claim.get("claim_type", "") or claim_dict.get("claim_type", "")),
                "claim_text": str(persisted_claim.get("claim_text", "") or claim_dict.get("claim_text", "")),
                "confidence": float(claim_dict.get("confidence", 0) or 0),
                "evidences": trace_evidences,
            }
        )
    for replayed_claim in replayed_claims:
        replay_payload = dict(replayed_claim.get("payload", {}) or {})
        trace_evidences = []
        for evidence_row in replayed_evidence_rows:
            if int(evidence_row.get("claim_id", 0) or 0) != int(replayed_claim.get("id", 0) or 0):
                continue
            chunk_payload = source_chunk_map.get(str(evidence_row.get("chunk_id", "") or ""), {})
            trace_evidences.append(
                {
                    "chunk_id": str(evidence_row.get("chunk_id", "") or ""),
                    "file_id": int(evidence_row.get("file_id", 0) or 0),
                    "page_no": int(evidence_row.get("page_no", 0) or 0),
                    "quote_text": str(evidence_row.get("quote_text", "") or ""),
                    "bbox_list": evidence_row.get("bbox_list", []),
                    "source_page_id": int(chunk_payload.get("page_id", 0) or 0),
                    "page_image_ref": str(chunk_payload.get("page_image_ref", "") or ""),
                }
            )
        claim_traces.append(
            {
                "claim_id": int(replayed_claim.get("id", 0) or 0),
                "claim_type": str(replayed_claim.get("claim_type", "") or replay_payload.get("claim_type", "")),
                "claim_text": str(replayed_claim.get("claim_text", "") or replay_payload.get("claim_text", "")),
                "confidence": float(replay_payload.get("confidence", 0) or 0),
                "evidences": trace_evidences,
            }
        )
    if evidence_rows:
        kg_service.insert_evidence_links(evidence_rows)
    mark_resolved = getattr(kg_service, "mark_unresolved_items_resolved", None)
    if callable(mark_resolved):
        resolved_updates = [*resolved_relation_updates, *resolved_claim_updates]
        if resolved_updates:
            mark_resolved(resolved_updates)
    persisted_reconciliation_items = []
    insert_reconciliation_ledger = getattr(kg_service, "insert_reconciliation_ledger", None)
    if callable(insert_reconciliation_ledger) and replay_reconciliation_items:
        persisted_reconciliation_items = insert_reconciliation_ledger(
            case_id=case_id,
            rows=replay_reconciliation_items,
        )

    subgraph_payload = {
        "entities": persisted_entities,
        "relations": persisted_relations,
        "claims": persisted_claims,
        "claim_traces": claim_traces,
        "skipped_evidences": skipped_evidences,
        "reconciliation_items": persisted_reconciliation_items or replay_reconciliation_items,
        "unresolved_relations": unresolved_relations,
        "unresolved_claims": unresolved_claims,
        "evidence_count": len(evidence_rows),
    }
    insert_unresolved = getattr(kg_service, "insert_unresolved_graph_items", None)
    if callable(insert_unresolved) and (unresolved_relations or unresolved_claims):
        try:
            persisted_unresolved = insert_unresolved(
                case_id=case_id,
                extraction_run_id=run_id,
                upload_batch_id=str(state.get("upload_batch_id", "") or ""),
                material_event_id=str((state.get("upload_batch_summary", {}) or {}).get("material_event_id", "") or ""),
                relation_rows=unresolved_relations,
                claim_rows=unresolved_claims,
            )
            subgraph_payload["unresolved_relations"] = persisted_unresolved.get("unresolved_relations", unresolved_relations)
            subgraph_payload["unresolved_claims"] = persisted_unresolved.get("unresolved_claims", unresolved_claims)
            unresolved_relations = subgraph_payload["unresolved_relations"]
            unresolved_claims = subgraph_payload["unresolved_claims"]
        except Exception:
            pass
    summary = (
        f"实体{len(persisted_entities)}个，"
        f"关系{len(persisted_relations)}条，"
        f"断言{len(persisted_claims)}条，"
        f"证据映射{len(evidence_rows)}条"
    )
    if unresolved_relations or unresolved_claims:
        summary += f"，未决关系{len(unresolved_relations)}条，未决断言{len(unresolved_claims)}条"
    return {
        "kg_subgraph_ref": put_heavy_payload("kg_subgraph", subgraph_payload),
        "kg_summary": summary,
        "unresolved_relations": unresolved_relations,
        "unresolved_claims": unresolved_claims,
        "reconciliation_items": persisted_reconciliation_items or replay_reconciliation_items,
    }


def _build_entity_lookup(
    *,
    case_id: int,
    kg_service,
    persisted_entities: list[dict[str, Any]],
    entity_key_by_temp_id: dict[str, str],
    entity_name_by_temp_id: dict[str, str],
) -> dict[str, dict[str, int]]:
    entity_keys = [key for key in entity_key_by_temp_id.values() if key]
    entity_names = [name for name in entity_name_by_temp_id.values() if name]
    persisted_rows = list(persisted_entities)
    fetch_active_entities = getattr(kg_service, "fetch_active_entities", None)
    if callable(fetch_active_entities):
        try:
            persisted_rows.extend(fetch_active_entities(case_id=case_id, entity_keys=entity_keys, entity_names=entity_names))
        except Exception:
            pass
    entity_id_by_key: dict[str, int] = {}
    entity_id_by_name: dict[str, int] = {}
    for row in persisted_rows:
        entity_id = int(row.get("id", 0) or 0)
        if entity_id <= 0:
            continue
        entity_key = str(row.get("entity_key", "") or "")
        if entity_key:
            entity_id_by_key[entity_key] = entity_id
        for name in (row.get("canonical_name", ""), row.get("normalized_name", "")):
            normalized_name = normalize_entity_name(str(name or ""))
            if normalized_name:
                entity_id_by_name[normalized_name] = entity_id
    return {"by_key": entity_id_by_key, "by_name": entity_id_by_name}


def _build_relation_lookup(*, case_id: int, kg_service, persisted_relations: list[dict[str, Any]]) -> dict[str, int]:
    relation_keys = [str(row.get("relation_key", "") or "") for row in persisted_relations if str(row.get("relation_key", "") or "")]
    persisted_rows = list(persisted_relations)
    fetch_active_relations = getattr(kg_service, "fetch_active_relations", None)
    if callable(fetch_active_relations) and relation_keys:
        try:
            persisted_rows.extend(fetch_active_relations(case_id=case_id, relation_keys=relation_keys))
        except Exception:
            pass
    return {
        str(row.get("relation_key", "") or ""): int(row.get("id", 0) or 0)
        for row in persisted_rows
        if str(row.get("relation_key", "") or "") and int(row.get("id", 0) or 0) > 0
    }


def _resolve_entity_id(
    *,
    relation_dict: dict[str, Any],
    temp_field: str,
    key_field: str,
    name_field: str,
    entity_id_by_temp_id: dict[str, int],
    entity_lookup: dict[str, dict[str, int]],
) -> int:
    temp_id = str(relation_dict.get(temp_field, "") or "")
    if temp_id and temp_id in entity_id_by_temp_id:
        return int(entity_id_by_temp_id[temp_id])
    entity_key = str(relation_dict.get(key_field, "") or "")
    if entity_key and entity_key in entity_lookup.get("by_key", {}):
        return int(entity_lookup["by_key"][entity_key])
    entity_name = normalize_entity_name(str(relation_dict.get(name_field, "") or ""))
    if entity_name and entity_name in entity_lookup.get("by_name", {}):
        return int(entity_lookup["by_name"][entity_name])
    return 0


def _resolve_entity_id_for_claim(claim_dict: dict[str, Any], entity_lookup: dict[str, dict[str, int]]) -> int | None:
    entity_key = str(claim_dict.get("entity_key", "") or "")
    if entity_key and entity_key in entity_lookup.get("by_key", {}):
        return int(entity_lookup["by_key"][entity_key])
    entity_name = normalize_entity_name(str(claim_dict.get("entity_name", "") or ""))
    if entity_name and entity_name in entity_lookup.get("by_name", {}):
        return int(entity_lookup["by_name"][entity_name])
    return None


def _resolve_relation_id_for_claim(claim_dict: dict[str, Any], relation_lookup: dict[str, int]) -> int | None:
    relation_key = str(claim_dict.get("relation_key", "") or "")
    if relation_key and relation_key in relation_lookup:
        return int(relation_lookup[relation_key])
    return None


def _replay_unresolved_relations(
    *,
    case_id: int,
    kg_service,
    entity_lookup: dict[str, dict[str, int]],
    relation_lookup: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fetch_unresolved = getattr(kg_service, "fetch_unresolved_graph_items", None)
    if not callable(fetch_unresolved):
        return [], []
    try:
        unresolved_payload = fetch_unresolved(case_id=case_id, limit=50)
    except Exception:
        return [], []
    pending_rows = unresolved_payload.get("unresolved_relations", [])
    fetch_active_entities = getattr(kg_service, "fetch_active_entities", None)
    if callable(fetch_active_entities) and pending_rows:
        relation_entity_keys: list[str] = []
        relation_entity_names: list[str] = []
        for item in pending_rows:
            row = dict(item.get("payload", {}) or item)
            relation_entity_keys.extend(
                [
                    str(row.get("from_entity_key", "") or ""),
                    str(row.get("to_entity_key", "") or ""),
                ]
            )
            relation_entity_names.extend(
                [
                    str(row.get("from_entity_name", "") or ""),
                    str(row.get("to_entity_name", "") or ""),
                ]
            )
        try:
            for row in fetch_active_entities(
                case_id=case_id,
                entity_keys=relation_entity_keys,
                entity_names=relation_entity_names,
            ):
                entity_id = int(row.get("id", 0) or 0)
                if entity_id <= 0:
                    continue
                entity_key = str(row.get("entity_key", "") or "")
                normalized_name = normalize_entity_name(str(row.get("canonical_name", "") or row.get("normalized_name", "") or ""))
                if entity_key:
                    entity_lookup.setdefault("by_key", {})[entity_key] = entity_id
                if normalized_name:
                    entity_lookup.setdefault("by_name", {})[normalized_name] = entity_id
        except Exception:
            pass
    relation_rows = []
    source_rows: list[dict[str, Any]] = []
    for item in pending_rows:
        row = dict(item.get("payload", {}) or item)
        relation_key = str(row.get("relation_key", "") or "")
        if relation_key and relation_key in relation_lookup:
            continue
        from_entity_id = 0
        to_entity_id = 0
        for value, slot in (
            (str(row.get("from_entity_key", "") or ""), "from"),
            (str(row.get("to_entity_key", "") or ""), "to"),
        ):
            if value and value in entity_lookup.get("by_key", {}):
                if slot == "from":
                    from_entity_id = int(entity_lookup["by_key"][value])
                else:
                    to_entity_id = int(entity_lookup["by_key"][value])
        for value, slot in (
            (str(row.get("from_entity_name", "") or ""), "from"),
            (str(row.get("to_entity_name", "") or ""), "to"),
        ):
            if value and value in entity_lookup.get("by_name", {}):
                if slot == "from" and from_entity_id <= 0:
                    from_entity_id = int(entity_lookup["by_name"][value])
                if slot == "to" and to_entity_id <= 0:
                    to_entity_id = int(entity_lookup["by_name"][value])
        if from_entity_id <= 0 or to_entity_id <= 0:
            continue
        relation_rows.append(
            {
                "relation_key": relation_key,
                "from_entity_id": from_entity_id,
                "to_entity_id": to_entity_id,
                "relation_type": row.get("relation_type", ""),
                "relation_label": row.get("relation_label", ""),
                "direction": row.get("direction", "directed"),
                "amount": row.get("amount"),
                "amount_currency": row.get("amount_currency", "CNY"),
                "event_date": row.get("event_date"),
                "attributes": row.get("attributes", {}),
                "confidence": row.get("confidence", 0),
                "source_count": row.get("source_count", len(row.get("evidence_chunk_ids", []))),
                "human_verified": row.get("human_verified", False),
                "status": row.get("status", "active"),
            }
        )
        source_rows.append(dict(item))
    if not relation_rows:
        return [], []
    persisted_relations = kg_service.upsert_relations(case_id=case_id, rows=relation_rows)
    resolved_updates = []
    for source_row, persisted_row in zip(source_rows, persisted_relations, strict=False):
        unresolved_id = int(source_row.get("id", 0) or 0)
        if unresolved_id > 0:
            resolved_updates.append(
                {
                    "id": unresolved_id,
                    "resolved_relation_id": int(persisted_row.get("id", 0) or 0),
                }
            )
    return persisted_relations, resolved_updates


def _replay_unresolved_claims(
    *,
    case_id: int,
    run_id: int,
    kg_service,
    entity_lookup: dict[str, dict[str, int]],
    relation_lookup: dict[str, int],
    source_chunk_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    fetch_unresolved = getattr(kg_service, "fetch_unresolved_graph_items", None)
    fetch_chunks = getattr(kg_service, "fetch_source_chunks_by_ids", None)
    if not callable(fetch_unresolved):
        return [], [], [], []
    try:
        unresolved_payload = fetch_unresolved(case_id=case_id, limit=50)
    except Exception:
        return [], [], [], []
    pending_rows = unresolved_payload.get("unresolved_claims", [])
    fetch_active_entities = getattr(kg_service, "fetch_active_entities", None)
    fetch_active_relations = getattr(kg_service, "fetch_active_relations", None)
    if pending_rows:
        if callable(fetch_active_entities):
            try:
                for row in fetch_active_entities(
                    case_id=case_id,
                    entity_keys=[str((dict(item.get("payload", {}) or item)).get("entity_key", "") or "") for item in pending_rows],
                    entity_names=[str((dict(item.get("payload", {}) or item)).get("entity_name", "") or "") for item in pending_rows],
                ):
                    entity_id = int(row.get("id", 0) or 0)
                    if entity_id <= 0:
                        continue
                    entity_key = str(row.get("entity_key", "") or "")
                    normalized_name = normalize_entity_name(str(row.get("canonical_name", "") or row.get("normalized_name", "") or ""))
                    if entity_key:
                        entity_lookup.setdefault("by_key", {})[entity_key] = entity_id
                    if normalized_name:
                        entity_lookup.setdefault("by_name", {})[normalized_name] = entity_id
            except Exception:
                pass
        if callable(fetch_active_relations):
            try:
                for row in fetch_active_relations(
                    case_id=case_id,
                    relation_keys=[str((dict(item.get("payload", {}) or item)).get("relation_key", "") or "") for item in pending_rows],
                ):
                    relation_key = str(row.get("relation_key", "") or "")
                    relation_id = int(row.get("id", 0) or 0)
                    if relation_key and relation_id > 0:
                        relation_lookup[relation_key] = relation_id
            except Exception:
                pass
    claim_rows = []
    source_rows: list[dict[str, Any]] = []
    replay_chunk_ids: list[str] = []
    for item in pending_rows:
        row = dict(item.get("payload", {}) or item)
        entity_id = _resolve_entity_id_for_claim(row, entity_lookup)
        relation_id = _resolve_relation_id_for_claim(row, relation_lookup)
        if (row.get("entity_key") or row.get("entity_name") or row.get("entity_temp_id")) and entity_id is None:
            continue
        if (row.get("relation_key") or row.get("relation_temp_id")) and relation_id is None:
            continue
        claim_rows.append(
            {
                "entity_id": entity_id,
                "relation_id": relation_id,
                "claim_type": row.get("claim_type", ""),
                "claim_text": row.get("claim_text", ""),
                "claim_value": row.get("claim_value", {}),
                "confidence": row.get("confidence", 0),
                "status": normalize_graph_status(str(row.get("status", DEFAULT_GRAPH_STATUS) or "")),
                "review_status": str(row.get("review_status", "pending") or "pending"),
            }
        )
        source_rows.append(dict(item))
        replay_chunk_ids.extend([str(chunk_id) for chunk_id in row.get("evidence_chunk_ids", []) if str(chunk_id).strip()])
    if not claim_rows:
        return [], [], [], []
    persisted_claims = kg_service.insert_claims(case_id=case_id, extraction_run_id=run_id, rows=claim_rows)
    if callable(fetch_chunks) and replay_chunk_ids:
        try:
            for chunk in fetch_chunks(case_id=case_id, chunk_ids=replay_chunk_ids):
                chunk_id = str(chunk.get("chunk_id", "") or "")
                if chunk_id:
                    source_chunk_map[chunk_id] = chunk
        except Exception:
            pass
    evidence_rows: list[dict[str, Any]] = []
    resolved_updates: list[dict[str, Any]] = []
    skipped_evidences: list[dict[str, Any]] = []
    for source_row, persisted_claim in zip(source_rows, persisted_claims, strict=False):
        replay_payload = dict(source_row.get("payload", {}) or source_row)
        for chunk_id in replay_payload.get("evidence_chunk_ids", []):
            chunk_payload = source_chunk_map.get(str(chunk_id), {})
            evidence_payload = _build_evidence_payload(
                claim_id=int(persisted_claim.get("id", 0) or 0),
                chunk_id=str(chunk_id),
                chunk_payload=chunk_payload,
                score=float(replay_payload.get("confidence", 0) or 0),
            )
            if evidence_payload is None:
                skipped_evidences.append(
                    _build_skipped_evidence_record(
                        claim_id=int(persisted_claim.get("id", 0) or 0),
                        claim_text=str(persisted_claim.get("claim_text", "") or replay_payload.get("claim_text", "")),
                        chunk_id=str(chunk_id),
                        chunk_payload=chunk_payload,
                        path="replay",
                    )
                )
                continue
            evidence_rows.append(evidence_payload)
        unresolved_id = int(source_row.get("id", 0) or 0)
        if unresolved_id > 0:
            resolved_updates.append(
                {
                    "id": unresolved_id,
                    "resolved_entity_id": _resolve_entity_id_for_claim(replay_payload, entity_lookup),
                    "resolved_relation_id": _resolve_relation_id_for_claim(replay_payload, relation_lookup),
                    "resolved_claim_id": int(persisted_claim.get("id", 0) or 0),
                }
            )
        persisted_claim["payload"] = replay_payload
    return persisted_claims, evidence_rows, resolved_updates, skipped_evidences


def _build_replay_reconciliation_items(
    *,
    case_id: int,
    replayed_claims: list[dict[str, Any]],
    resolved_claim_updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    resolved_by_claim_id = {
        int(item.get("resolved_claim_id", 0) or 0): item
        for item in resolved_claim_updates
        if int(item.get("resolved_claim_id", 0) or 0) > 0
    }
    items: list[dict[str, Any]] = []
    for claim in replayed_claims:
        claim_id = int(claim.get("id", 0) or 0)
        if claim_id <= 0:
            continue
        replay_payload = dict(claim.get("payload", {}) or {})
        resolved_update = resolved_by_claim_id.get(claim_id, {})
        items.append(
            {
                "case_id": case_id,
                "action": "ADD",
                "new_claim_id": claim_id,
                "new_claim_text": str(claim.get("claim_text", "") or replay_payload.get("claim_text", "") or ""),
                "superseded_claim_id": None,
                "superseded_claim_text": "",
                "new_relation_id": _normalize_optional_int(resolved_update.get("resolved_relation_id")),
                "superseded_relation_id": None,
                "rationale": "resolved previously unresolved graph item after later upload batch",
                "evidence_chunk_ids": [str(item) for item in replay_payload.get("evidence_chunk_ids", []) if str(item)],
                "decision_payload": {
                    "source": "unresolved_replay",
                    "unresolved_item_id": _normalize_optional_int(resolved_update.get("id")),
                    "entity_key": str(replay_payload.get("entity_key", "") or ""),
                    "relation_key": str(replay_payload.get("relation_key", "") or ""),
                    "claim_type": str(replay_payload.get("claim_type", "") or ""),
                },
            }
        )
    return items


def _normalize_optional_int(value: Any) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _load_source_chunk_map(state: AuditGraphState) -> dict[str, dict[str, Any]]:
    """Load persisted chunk details from state or chunk_batch heavy payload."""
    source_chunk_map: dict[str, dict[str, Any]] = {}
    source_chunks = state.get("source_chunks", [])
    for chunk in source_chunks:
        if isinstance(chunk, dict):
            chunk_dict = chunk
        else:
            chunk_dict = chunk.model_dump()
        chunk_id = str(chunk_dict.get("chunk_id", ""))
        if chunk_id:
            source_chunk_map[chunk_id] = chunk_dict

    if source_chunk_map:
        return source_chunk_map

    payload = get_heavy_payload(state.get("chunk_batch_ref", ""))
    if not isinstance(payload, dict):
        return source_chunk_map
    for chunk in payload.get("chunks", []):
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("chunk_id", ""))
        if chunk_id:
            source_chunk_map[chunk_id] = chunk
    return source_chunk_map


def _build_evidence_payload(
    *,
    claim_id: int,
    chunk_id: str,
    chunk_payload: dict[str, Any],
    score: float,
) -> dict[str, Any] | None:
    """Build one evidence row only when the source chunk can satisfy DB FKs."""
    normalized_chunk_id = str(chunk_id or "").strip()
    if not normalized_chunk_id or not chunk_payload:
        return None
    file_id = int(chunk_payload.get("file_id", 0) or 0)
    page_no = int(chunk_payload.get("page_no", 0) or 0)
    if file_id <= 0 or page_no <= 0:
        return None
    return {
        "claim_id": claim_id,
        "chunk_id": normalized_chunk_id,
        "file_id": file_id,
        "page_no": page_no,
        "quote_text": str(chunk_payload.get("anchor_text") or chunk_payload.get("chunk_text") or ""),
        "bbox_list": chunk_payload.get("bbox_list", []),
        "score": score,
    }


def _build_skipped_evidence_record(
    *,
    claim_id: int,
    claim_text: str,
    chunk_id: str,
    chunk_payload: dict[str, Any],
    path: str,
) -> dict[str, Any]:
    """Capture why one evidence link was skipped so regressions are traceable."""
    record = {
        "claim_id": claim_id,
        "claim_text": claim_text,
        "chunk_id": str(chunk_id or "").strip(),
        "path": path,
    }
    if not chunk_payload:
        record["reason"] = "missing_source_chunk"
        LOGGER.warning(
            "Skipping evidence row because chunk_id was not found in source_chunk state",
            extra={"claim_id": claim_id, "chunk_id": record["chunk_id"], "path": path},
        )
        return record
    file_id = int(chunk_payload.get("file_id", 0) or 0)
    page_no = int(chunk_payload.get("page_no", 0) or 0)
    record["file_id"] = file_id
    record["page_no"] = page_no
    if file_id <= 0:
        record["reason"] = "invalid_file_id"
    elif page_no <= 0:
        record["reason"] = "invalid_page_no"
    else:
        record["reason"] = "invalid_chunk_payload"
    LOGGER.warning(
        "Skipping evidence row because chunk payload cannot satisfy DB foreign keys",
        extra={
            "claim_id": claim_id,
            "chunk_id": record["chunk_id"],
            "file_id": file_id,
            "page_no": page_no,
            "path": path,
            "reason": record["reason"],
        },
    )
    return record
