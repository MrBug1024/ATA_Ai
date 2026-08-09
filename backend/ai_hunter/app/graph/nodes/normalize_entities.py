"""Normalize extracted entities into stable names and keys."""

from __future__ import annotations

from ...services.graph_identity import (
    DEFAULT_GRAPH_STATUS,
    build_entity_key,
    build_relation_key,
    normalize_entity_name,
    normalize_entity_type,
    normalize_graph_status,
    normalize_relation_type,
)
from ..state import AuditGraphState


def normalize_entities(state: AuditGraphState) -> AuditGraphState:
    """Normalize entity and relation identity fields into stable keys."""
    case_id = state.get("current_case_id", 0)
    normalized_entities = []
    entity_key_by_temp_id: dict[str, str] = {}
    entity_name_by_temp_id: dict[str, str] = {}
    for entity in state.get("kg_entities", []):
        entity_dict = entity if isinstance(entity, dict) else entity.model_dump()
        normalized_name = normalize_entity_name(entity_dict.get("name") or entity_dict.get("canonical_name") or "")
        raw_entity_type = str(entity_dict.get("entity_type", "") or "")
        entity_type = normalize_entity_type(raw_entity_type)
        entity_dict["entity_type"] = entity_type
        if raw_entity_type.strip() and raw_entity_type.strip().lower() != entity_type:
            attributes = entity_dict.get("attributes")
            if not isinstance(attributes, dict):
                attributes = {}
            attributes.setdefault("source_entity_type", raw_entity_type)
            entity_dict["attributes"] = attributes
        entity_key = entity_dict.get("entity_key") or build_entity_key(
            case_id=case_id,
            entity_type=entity_type,
            normalized_name=normalized_name,
        )
        entity_dict["normalized_name"] = normalized_name
        entity_dict["canonical_name"] = entity_dict.get("canonical_name") or normalized_name
        entity_dict["entity_key"] = entity_key
        entity_dict["status"] = normalize_graph_status(str(entity_dict.get("status", DEFAULT_GRAPH_STATUS) or ""))
        normalized_entities.append(entity_dict)
        temp_id = str(entity_dict.get("entity_temp_id", "") or "")
        if temp_id and entity_key:
            entity_key_by_temp_id[temp_id] = str(entity_key)
            entity_name_by_temp_id[temp_id] = str(entity_dict.get("canonical_name") or normalized_name or "")

    normalized_relations = []
    relation_key_by_temp_id: dict[str, str] = {}
    for relation in state.get("kg_relations", []):
        relation_dict = relation if isinstance(relation, dict) else relation.model_dump()
        from_entity_key = entity_key_by_temp_id.get(str(relation_dict.get("from_entity_temp_id", "")), "")
        to_entity_key = entity_key_by_temp_id.get(str(relation_dict.get("to_entity_temp_id", "")), "")
        relation_dict["from_entity_key"] = relation_dict.get("from_entity_key") or from_entity_key
        relation_dict["to_entity_key"] = relation_dict.get("to_entity_key") or to_entity_key
        relation_type = normalize_relation_type(relation_dict.get("relation_type"))
        relation_dict["relation_type"] = relation_type
        if from_entity_key and to_entity_key:
            relation_dict["relation_key"] = relation_dict.get("relation_key") or build_relation_key(
                case_id=case_id,
                relation_type=relation_type,
                from_entity_key=from_entity_key,
                to_entity_key=to_entity_key,
                relation_label=str(relation_dict.get("relation_label", "") or ""),
                event_date=str(relation_dict.get("event_date", "") or ""),
                amount=relation_dict.get("amount"),
                amount_currency=str(relation_dict.get("amount_currency", "CNY") or "CNY"),
            )
        else:
            # 不为缺少端点的关系生成“空端点 hash”。持久化层会把它明确记录为
            # unresolved，后续补齐实体后才能重放，避免假关系混入 active 图谱。
            relation_dict["relation_key"] = relation_dict.get("relation_key") or ""
            missing = []
            if not from_entity_key:
                missing.append("from_entity")
            if not to_entity_key:
                missing.append("to_entity")
            relation_dict["unresolved_reason"] = "missing_entity_reference"
            relation_dict["missing_dependencies"] = missing
        relation_dict["status"] = normalize_graph_status(str(relation_dict.get("status", DEFAULT_GRAPH_STATUS) or ""))
        normalized_relations.append(relation_dict)
        relation_temp_id = str(relation_dict.get("relation_temp_id", "") or "")
        if relation_temp_id and relation_dict.get("relation_key"):
            relation_key_by_temp_id[relation_temp_id] = str(relation_dict.get("relation_key", "") or "")

    normalized_claims = []
    for claim in state.get("kg_claims", []):
        claim_dict = claim if isinstance(claim, dict) else claim.model_dump()
        entity_temp_id = str(claim_dict.get("entity_temp_id", "") or "")
        relation_temp_id = str(claim_dict.get("relation_temp_id", "") or "")
        if entity_temp_id and not claim_dict.get("entity_key"):
            claim_dict["entity_key"] = entity_key_by_temp_id.get(entity_temp_id, "")
        if entity_temp_id and not claim_dict.get("entity_name"):
            claim_dict["entity_name"] = entity_name_by_temp_id.get(entity_temp_id, "")
        if relation_temp_id and not claim_dict.get("relation_key"):
            claim_dict["relation_key"] = relation_key_by_temp_id.get(relation_temp_id, "")
        claim_dict["status"] = normalize_graph_status(str(claim_dict.get("status", DEFAULT_GRAPH_STATUS) or ""))
        normalized_claims.append(claim_dict)
    return {"kg_entities": normalized_entities, "kg_relations": normalized_relations, "kg_claims": normalized_claims}
