"""Helpers for persisting upload-ingest progress into material_event and upload_batch rows."""

from __future__ import annotations

import logging
from typing import Any

from .kg_service import get_kg_service


LOGGER = logging.getLogger(__name__)
MATERIAL_EVENT_TYPE = "supplement_upload"


def build_material_event_id(upload_batch_id: str) -> str:
    normalized = str(upload_batch_id or "").strip()
    return f"material-event:{normalized}" if normalized else ""


def mark_upload_ingest_progress(
    *,
    case_id: int,
    entity_id: int,
    batch_name: str,
    doc_category: str,
    operator_id: str,
    operator_name: str,
    upload_batch_id: str,
    status: str,
    stage: str,
    file_count: int,
    new_file_count: int = 0,
    duplicate_file_count: int = 0,
    suspected_mismatch_file_count: int = 0,
    records_inserted: int = 0,
    duplicate_files: list[str] | None = None,
    suspected_mismatch_files: list[str] | None = None,
    new_files: list[str] | None = None,
    text_file_content_refs: dict[str, str] | None = None,
    categories_found: list[str] | None = None,
    recognized_categories: list[str] | None = None,
    parse_summary: str = "",
    has_conclusion_changes: bool = False,
    reconciliation_item_count: int = 0,
    add_item_count: int = 0,
    override_item_count: int = 0,
    change_summary: str = "",
    unresolved_relation_count: int = 0,
    unresolved_claim_count: int = 0,
    ingest_payload_ref: str = "",
    aggregated_text_ref: str = "",
    parse_document_result_ref: str = "",
    chunk_batch_ref: str = "",
    kg_subgraph_ref: str = "",
    error_payload: dict[str, Any] | None = None,
    error_message: str = "",
) -> None:
    """Persist one coarse-grained upload-ingest progress checkpoint."""
    if int(case_id or 0) <= 0 or not str(upload_batch_id or "").strip():
        return

    duplicate_files = list(duplicate_files or [])
    suspected_mismatch_files = list(suspected_mismatch_files or [])
    new_files = list(new_files or [])
    text_file_content_refs = {
        str(key): str(value)
        for key, value in dict(text_file_content_refs or {}).items()
        if str(key).strip() and str(value).strip()
    }
    categories_found = list(categories_found or [])
    recognized_categories = list(recognized_categories or categories_found)
    material_event_id = build_material_event_id(upload_batch_id)

    event_payload: dict[str, Any] = {
        "stage": stage,
        "duplicate_files": duplicate_files,
        "suspected_mismatch_files": suspected_mismatch_files,
        "new_files": new_files,
    }
    if categories_found:
        event_payload["categories_found"] = categories_found
    if recognized_categories:
        event_payload["recognized_categories"] = recognized_categories
    if text_file_content_refs:
        event_payload["text_file_content_refs"] = text_file_content_refs
    if parse_summary:
        event_payload["parse_summary"] = parse_summary
    if reconciliation_item_count or add_item_count or override_item_count or change_summary:
        event_payload.update(
            {
                "has_conclusion_changes": has_conclusion_changes,
                "reconciliation_item_count": reconciliation_item_count,
                "add_item_count": add_item_count,
                "override_item_count": override_item_count,
                "change_summary": change_summary,
            }
        )
    if unresolved_relation_count or unresolved_claim_count:
        event_payload["unresolved_relation_count"] = unresolved_relation_count
        event_payload["unresolved_claim_count"] = unresolved_claim_count
    if ingest_payload_ref:
        event_payload["ingest_payload_ref"] = ingest_payload_ref
    if aggregated_text_ref:
        event_payload["aggregated_text_ref"] = aggregated_text_ref
    if parse_document_result_ref:
        event_payload["parse_document_result_ref"] = parse_document_result_ref
    if chunk_batch_ref:
        event_payload["chunk_batch_ref"] = chunk_batch_ref
    if kg_subgraph_ref:
        event_payload["kg_subgraph_ref"] = kg_subgraph_ref
    if error_payload:
        event_payload["error"] = dict(error_payload)

    batch_metadata: dict[str, Any] = {
        "material_event_id": material_event_id,
        "material_event_type": MATERIAL_EVENT_TYPE,
        "material_event_status": status,
        "stage": stage,
        "duplicate_files": duplicate_files,
        "suspected_mismatch_files": suspected_mismatch_files,
        "new_files": new_files,
    }
    if categories_found:
        batch_metadata["categories_found"] = categories_found
    if recognized_categories:
        batch_metadata["recognized_categories"] = recognized_categories
    if text_file_content_refs:
        batch_metadata["text_file_content_refs"] = text_file_content_refs
    if parse_summary:
        batch_metadata["parse_summary"] = parse_summary
    if reconciliation_item_count or add_item_count or override_item_count or change_summary:
        batch_metadata.update(
            {
                "has_conclusion_changes": has_conclusion_changes,
                "reconciliation_item_count": reconciliation_item_count,
                "add_item_count": add_item_count,
                "override_item_count": override_item_count,
                "change_summary": change_summary,
            }
        )
    if unresolved_relation_count or unresolved_claim_count:
        batch_metadata["unresolved_relation_count"] = unresolved_relation_count
        batch_metadata["unresolved_claim_count"] = unresolved_claim_count
    if ingest_payload_ref:
        batch_metadata["ingest_payload_ref"] = ingest_payload_ref
    if aggregated_text_ref:
        batch_metadata["aggregated_text_ref"] = aggregated_text_ref
    if parse_document_result_ref:
        batch_metadata["parse_document_result_ref"] = parse_document_result_ref
    if chunk_batch_ref:
        batch_metadata["chunk_batch_ref"] = chunk_batch_ref
    if kg_subgraph_ref:
        batch_metadata["kg_subgraph_ref"] = kg_subgraph_ref
    if error_payload:
        batch_metadata["error"] = dict(error_payload)

    try:
        kg_service = get_kg_service()
        kg_service.upsert_material_event(
            {
                "material_event_id": material_event_id,
                "case_id": int(case_id or 0),
                "entity_id": int(entity_id or 0),
                "upload_batch_id": upload_batch_id,
                "event_type": MATERIAL_EVENT_TYPE,
                "status": status,
                "batch_name": batch_name,
                "doc_category": doc_category,
                "operator_id": operator_id,
                "operator_name": operator_name,
                "file_count": int(file_count or 0),
                "records_inserted": int(records_inserted or 0),
                "event_payload": event_payload,
                "error_message": error_message,
            }
        )
    except Exception:
        LOGGER.exception(
            "upsert_material_event_failed upload_batch_id=%s status=%s stage=%s",
            upload_batch_id,
            status,
            stage,
        )

    try:
        get_kg_service().upsert_source_upload_batch(
            {
                "upload_batch_id": upload_batch_id,
                "case_id": int(case_id or 0),
                "entity_id": int(entity_id or 0),
                "batch_name": batch_name,
                "doc_category": doc_category,
                "operator_id": operator_id,
                "operator_name": operator_name,
                "status": status,
                "file_count": int(file_count or 0),
                "new_file_count": int(new_file_count or 0),
                "duplicate_file_count": int(duplicate_file_count or 0),
                "suspected_mismatch_file_count": int(suspected_mismatch_file_count or 0),
                "records_inserted": int(records_inserted or 0),
                "metadata": batch_metadata,
            }
        )
    except Exception:
        LOGGER.exception(
            "upsert_source_upload_batch_failed upload_batch_id=%s status=%s stage=%s",
            upload_batch_id,
            status,
            stage,
        )
