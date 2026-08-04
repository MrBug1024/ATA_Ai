"""Hydrate persisted knowledge-graph context for full-audit runs without fresh uploads."""

from __future__ import annotations

from ...services.kg_service import get_kg_service
from ..heavy_state import put_heavy_payload
from ..state import AuditGraphState


def _load_case_material_sources(case_id: int) -> list[dict]:
    """Load persisted file/page/chunk coverage for report disclosure."""
    service = get_kg_service()
    sources: list[dict] = []
    for batch in service.list_source_upload_batches_by_case(case_id, limit=20):
        upload_batch_id = str(batch.get("upload_batch_id") or "")
        details = service.fetch_source_upload_batch(upload_batch_id)
        for file_item in details.get("files") or []:
            sources.append(
                {
                    "upload_batch_id": upload_batch_id,
                    "batch_name": str(batch.get("batch_name") or ""),
                    "status": str(batch.get("status") or ""),
                    "doc_category": str(batch.get("doc_category") or ""),
                    "records_inserted": int(batch.get("records_inserted") or 0),
                    "file_name": str(file_item.get("file_name") or ""),
                    "file_type": str(file_item.get("file_type") or ""),
                    "page_count": int(file_item.get("page_count") or 0),
                    "chunk_count": int(file_item.get("chunk_count") or 0),
                }
            )
    return sources


def hydrate_case_graph_context(state: AuditGraphState) -> AuditGraphState:
    """Restore graph snapshot by case_id when the current turn does not upload new files."""
    if state.get("uploaded_files"):
        return {}

    case_id = int(state.get("current_case_id", 0) or 0)
    if case_id <= 0:
        return {}

    try:
        material_sources = _load_case_material_sources(case_id)
        if state.get("kg_subgraph_ref"):
            return {"case_material_sources": material_sources}

        snapshot = get_kg_service().fetch_case_graph_snapshot(case_id)
        if not snapshot and not material_sources:
            return {}

        updates: AuditGraphState = {"case_material_sources": material_sources}
        if not snapshot:
            return updates

        summary = (
            f"实体{int(snapshot.get('entity_count', 0) or 0)}个，"
            f"关系{int(snapshot.get('relation_count', 0) or 0)}条，"
            f"断言{int(snapshot.get('claim_count', 0) or 0)}条，"
            f"证据映射{int(snapshot.get('evidence_count', 0) or 0)}条"
        )
        updates.update({
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
        })
        return updates
    except Exception as exc:
        # Log the error but don't fail the entire graph execution
        import logging
        logging.getLogger(__name__).warning(
            "Failed to hydrate case graph context for case_id=%s: %s",
            case_id,
            exc,
        )
        return {}
