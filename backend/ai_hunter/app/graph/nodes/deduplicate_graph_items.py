"""Deduplicate normalized graph items before persistence."""

from __future__ import annotations

from ..state import AuditGraphState


def deduplicate_graph_items(state: AuditGraphState) -> AuditGraphState:
    """Drop duplicate entities, relations, and claims by their stable keys/text."""
    entities = []
    seen_entity_keys = set()
    for entity in state.get("kg_entities", []):
        entity_dict = entity if isinstance(entity, dict) else entity.model_dump()
        entity_key = entity_dict.get("entity_key", "")
        if entity_key and entity_key not in seen_entity_keys:
            seen_entity_keys.add(entity_key)
            entities.append(entity_dict)

    relations = []
    seen_relation_keys = set()
    for relation in state.get("kg_relations", []):
        relation_dict = relation if isinstance(relation, dict) else relation.model_dump()
        relation_key = relation_dict.get("relation_key", "")
        if relation_key and relation_key not in seen_relation_keys:
            seen_relation_keys.add(relation_key)
            relations.append(relation_dict)

    claims = []
    seen_claim_texts = set()
    for claim in state.get("kg_claims", []):
        claim_dict = claim if isinstance(claim, dict) else claim.model_dump()
        signature = (
            claim_dict.get("claim_type", ""),
            claim_dict.get("claim_text", ""),
            tuple(claim_dict.get("evidence_chunk_ids", [])),
        )
        if signature not in seen_claim_texts:
            seen_claim_texts.add(signature)
            claims.append(claim_dict)

    return {
        "kg_entities": entities,
        "kg_relations": relations,
        "kg_claims": claims,
    }
