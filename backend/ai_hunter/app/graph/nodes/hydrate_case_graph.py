"""Hydrate persisted knowledge-graph context for full-audit runs without fresh uploads."""

from __future__ import annotations

from ...services.kg_service import get_kg_service
from ..heavy_state import put_heavy_payload
from ..state import AuditGraphState


def hydrate_case_graph_context(state: AuditGraphState) -> AuditGraphState:
    """Restore graph snapshot by case_id when the current turn does not upload new files."""
    if state.get("uploaded_files"):
        return {}
    if state.get("kg_subgraph_ref"):
        return {}

    case_id = int(state.get("current_case_id", 0) or 0)
    if case_id <= 0:
        return {}

    try:
        snapshot = get_kg_service().fetch_case_graph_snapshot(case_id)
        if not snapshot:
            return {}

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
            "reconciliation_items": snapshot.get("reconciliation_items", []),
        }
    except Exception as exc:
        # Log the error but don't fail the entire graph execution
        import logging
        logging.getLogger(__name__).warning(
            "Failed to hydrate case graph context for case_id=%s: %s",
            case_id,
            exc,
        )
        return {}
