"""Build a lightweight graph summary for downstream report and agent nodes."""

from __future__ import annotations

from ..heavy_state import get_heavy_payload
from ..state import AuditGraphState


def build_graph_summary(state: AuditGraphState) -> AuditGraphState:
    """Derive a compact graph summary from the persisted graph payload."""
    payload = get_heavy_payload(state.get("kg_subgraph_ref", ""))
    if not isinstance(payload, dict):
        return {}
    entities = payload.get("entities", [])
    relations = payload.get("relations", [])
    claims = payload.get("claims", [])
    summary = (
        f"已构建案件图谱：实体{len(entities)}个，"
        f"关系{len(relations)}条，"
        f"断言{len(claims)}条。"
    )
    superseded_claim_ids = [int(item) for item in state.get("superseded_claim_ids", []) if int(item) > 0]
    superseded_relation_ids = [int(item) for item in state.get("superseded_relation_ids", []) if int(item) > 0]
    if superseded_claim_ids or superseded_relation_ids:
        summary += (
            f" 本次增量对账软失效旧断言{len(superseded_claim_ids)}条，"
            f"旧关系{len(superseded_relation_ids)}条。"
        )
    return {
        "kg_summary": summary,
        # Preserve the source-anchor binding result when the knowledge-graph
        # subgraph returns to the outer chat graph.
        "annual_evidence_binding_summary": state.get("annual_evidence_binding_summary", {}),
    }
