"""Persist OCR layout into source_file/source_page/source_chunk records."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from ...services.chunking import build_chunks_from_pages, build_page_records_from_layout
from ...services.kg_service import get_kg_service
from ...services.ocr_service import get_ocr_service
from ..context_loader import resolve_ingest_payload
from ..heavy_state import put_heavy_payload
from ..state import AuditGraphState


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def load_chunks(state: AuditGraphState) -> AuditGraphState:
    """Build traceable source_file/page/chunk rows from uploaded files and OCR layout output."""
    case_id = state.get("current_case_id", 0)
    entity_id = state.get("current_entity_id", 0)
    ingest_payload_ref = state.get("ingest_payload_ref", "")
    uploaded_files = state.get("uploaded_files") or []
    if case_id <= 0 or not uploaded_files:
        return {}

    kg_service = get_kg_service()
    ocr_service = get_ocr_service()
    layout_cache = _build_layout_cache(_resolve_persisted_ingest_payload(state))
    source_file_rows: list[dict[str, Any]] = []
    layout_payloads: list[dict[str, Any]] = []

    for file_item in uploaded_files:
        file_name = file_item.get("name", "") or "uploaded-file"
        extension = (file_item.get("extension") or Path(file_name).suffix.lower()).lower()
        file_bytes = _decode_file_bytes(file_item.get("content", ""), extension)
        file_sha256 = str(file_item.get("file_hash", "") or "").strip()
        if not file_sha256:
            file_sha256 = hashlib.sha256(file_bytes).hexdigest()
        file_size_bytes = len(file_bytes)
        if file_size_bytes == 0:
            file_size_bytes = int(file_item.get("file_size", 0) or 0)
        source_file_rows.append(
            {
                "case_id": case_id,
                "entity_id": entity_id,
                "file_name": file_name,
                "file_type": file_item.get("type", "document"),
                "content_type": file_item.get("content_type", ""),
                "file_sha256": file_sha256,
                "file_size_bytes": file_size_bytes,
                "storage_ref": file_item.get("storage_ref", "") or file_item.get("url", ""),
                "storage_provider": file_item.get("storage_provider", ""),
                "storage_bucket": file_item.get("storage_bucket", ""),
                "storage_key": file_item.get("storage_key", ""),
                "storage_etag": file_item.get("storage_etag", ""),
                "storage_version": file_item.get("storage_version", ""),
                "ingest_payload_ref": ingest_payload_ref,
                "ocr_provider": "ocr.rhzy.ai",
                "ocr_version": "",
                "parser_version": "kg-load-chunks-v1",
                "status": "active",
            }
        )
        if extension not in TEXT_EXTENSIONS:
            cache_key = _build_file_cache_key(file_item, extension)
            layout_result = layout_cache.get(cache_key) or _load_layout_result(ocr_service, file_item, extension)
        else:
            layout_result = {
                "text": file_item.get("content", ""),
                "message": "text-direct-read",
                "pages": [{"width": 0, "height": 0}],
                "blocks": [
                    {
                        "type": "text",
                        "text": file_item.get("content", ""),
                        "text_level": 1,
                        "bbox": [],
                        "page_idx": 0,
                    }
                ],
                "page_width": 0,
                "page_height": 0,
                "raw_response": {},
            }
        layout_payloads.append(
            {
                "file_sha256": file_sha256,
                "file_name": file_name,
                "layout_result": layout_result,
            }
        )

    inserted_files = kg_service.insert_source_files(source_file_rows)
    file_id_map = {row["file_sha256"]: int(row["id"]) for row in inserted_files}
    batch_row = _persist_upload_batch_context(
        kg_service=kg_service,
        state=state,
        case_id=case_id,
        entity_id=entity_id,
        inserted_files=inserted_files,
        uploaded_files=uploaded_files,
    )
    category_rows = _persist_doc_category_relations(
        kg_service=kg_service,
        state=state,
        case_id=case_id,
        inserted_files=inserted_files,
    )

    all_pages: list[dict[str, Any]] = []
    for payload in layout_payloads:
        file_id = file_id_map[payload["file_sha256"]]
        page_rows = build_page_records_from_layout(file_id=file_id, layout_result=payload["layout_result"])
        all_pages.extend(page_rows)
    inserted_pages = kg_service.insert_source_pages(all_pages)
    page_id_map = {(int(row["file_id"]), int(row["page_no"])): int(row["id"]) for row in inserted_pages}

    all_chunks = []
    for payload in layout_payloads:
        file_id = file_id_map[payload["file_sha256"]]
        page_rows = [row for row in all_pages if int(row["file_id"]) == file_id]
        page_ids_for_file = {
            page_no: page_id
            for (mapped_file_id, page_no), page_id in page_id_map.items()
            if mapped_file_id == file_id
        }
        all_chunks.extend(
            build_chunks_from_pages(
                case_id=case_id,
                file_id=file_id,
                file_sha256=payload["file_sha256"],
                page_rows=page_rows,
                page_id_map=page_ids_for_file,
            )
        )
    inserted_chunks = kg_service.insert_source_chunks(all_chunks)

    chunk_batch_payload = {
        "files": inserted_files,
        "upload_batch": batch_row,
        "doc_category_links": category_rows,
        "pages": inserted_pages,
        "chunks": [chunk.model_dump() for chunk in all_chunks],
    }
    chunk_batch_ref = put_heavy_payload("kg_chunk_batch", chunk_batch_payload)
    chunk_ids = [row["chunk_id"] for row in inserted_chunks]
    return {
        "chunk_batch_ref": chunk_batch_ref,
        "chunk_batch_summary": (
            f"files={len(inserted_files)}, pages={len(inserted_pages)}, chunks={len(inserted_chunks)}"
        ),
        "chunk_ids": chunk_ids,
        "upload_batch_summary": _merge_batch_summary(state.get("upload_batch_summary", {}), batch_row),
        "source_chunks": [],
    }


def _persist_upload_batch_context(
    *,
    kg_service,
    state: AuditGraphState,
    case_id: int,
    entity_id: int,
    inserted_files: list[dict[str, Any]],
    uploaded_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist upload batch metadata and source-file membership if the DB tables exist."""
    upload_batch_id = str(state.get("upload_batch_id", "") or "").strip()
    if not upload_batch_id:
        return {}
    defer_completion = bool(state.get("defer_upload_batch_completion", False))
    batch_status = "processing" if defer_completion else "completed"
    batch_stage = "graph_running" if defer_completion else "completed"
    summary = {
        **dict(state.get("upload_batch_summary") or {}),
        "upload_batch_id": upload_batch_id,
        "case_id": case_id,
        "entity_id": entity_id,
        "batch_name": state.get("batch_name", ""),
        "doc_category": state.get("doc_category", ""),
        "operator_id": state.get("operator_id", ""),
        "operator_name": state.get("operator_name", ""),
        "file_count": len(uploaded_files),
        "new_file_count": len(state.get("new_files", []) or []),
        "duplicate_file_count": len(state.get("duplicate_files", []) or []),
        "suspected_mismatch_file_count": len(state.get("suspected_mismatch_files", []) or []),
        "status": batch_status,
        "records_inserted": int(state.get("records_inserted", 0) or 0),
        "metadata": {
            "material_event_id": str((state.get("upload_batch_summary", {}) or {}).get("material_event_id", "") or ""),
            "material_event_type": str((state.get("upload_batch_summary", {}) or {}).get("material_event_type", "") or ""),
            "material_event_status": batch_status,
            "stage": batch_stage,
            "duplicate_files": state.get("duplicate_files", []) or [],
            "suspected_mismatch_files": state.get("suspected_mismatch_files", []) or [],
            "new_files": state.get("new_files", []) or [],
        },
    }
    upsert_batch = getattr(kg_service, "upsert_source_upload_batch", None)
    link_files = getattr(kg_service, "link_source_files_to_upload_batch", None)
    if not callable(upsert_batch):
        return summary
    batch_row = upsert_batch(summary)
    if callable(link_files):
        link_files(
            upload_batch_id=upload_batch_id,
            files=inserted_files,
            duplicate_by_sha256=_build_duplicate_by_sha256(uploaded_files),
        )
    return batch_row or summary


def _persist_doc_category_relations(
    *,
    kg_service,
    state: AuditGraphState,
    case_id: int,
    inserted_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist source_file -> doc_category relationships for operator-selected category."""
    doc_category = str(state.get("doc_category", "") or "").strip()
    if not doc_category:
        return []
    upsert_links = getattr(kg_service, "upsert_source_file_doc_categories", None)
    if not callable(upsert_links):
        return []
    return upsert_links(
        case_id=case_id,
        category_code=doc_category,
        files=inserted_files,
        match_source="manual",
        confidence=1.0,
        notes="operator selected category during upload",
    )


def _build_duplicate_by_sha256(uploaded_files: list[dict[str, Any]]) -> dict[str, str]:
    """Map duplicate file hashes to the original uploaded filename when available."""
    duplicate_by_sha256: dict[str, str] = {}
    for file_item in uploaded_files:
        file_hash = str(file_item.get("file_hash", "") or "")
        duplicate_of = str(file_item.get("duplicate_of", "") or "")
        if file_hash and duplicate_of:
            duplicate_by_sha256[file_hash] = duplicate_of
    return duplicate_by_sha256


def _merge_batch_summary(summary: dict[str, Any] | object, persisted: dict[str, Any]) -> dict[str, Any]:
    merged = dict(summary) if isinstance(summary, dict) else {}
    merged.update(persisted or {})
    return merged


def _decode_file_bytes(content: str, extension: str) -> bytes:
    """Decode uploaded file content back into raw bytes for hashing and OCR transport."""
    if not (content or "").strip():
        return b""
    if extension in TEXT_EXTENSIONS:
        return (content or "").encode("utf-8")
    raw_content = (content or "").strip()
    if raw_content.startswith("data:") and ";base64," in raw_content:
        raw_content = raw_content.split(",", 1)[1]
    return base64.b64decode(raw_content)


def _build_file_cache_key(file_item: dict[str, Any], extension: str) -> str:
    """Build one stable key for ingest OCR layout reuse."""
    raw_content = (file_item.get("content", "") or "").strip()
    if raw_content:
        return hashlib.sha256(_decode_file_bytes(raw_content, extension)).hexdigest()
    file_hash = str(file_item.get("file_hash", "") or "").strip()
    if file_hash:
        return file_hash
    file_url = str(file_item.get("url", "") or "").strip()
    if file_url:
        return f"url:{file_url}"
    return f"name:{str(file_item.get('name', '') or '').strip()}"


def _build_layout_cache(ingest_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index cached OCR layout results from the parse-stage heavy payload."""
    cache: dict[str, dict[str, Any]] = {}
    for item in ingest_payload.get("ocr_layout_results", []) or []:
        if not isinstance(item, dict):
            continue
        cache_key = str(item.get("cache_key", "") or "").strip()
        layout_result = item.get("layout_result")
        if cache_key and isinstance(layout_result, dict):
            cache[cache_key] = layout_result
    return cache


def _resolve_persisted_ingest_payload(state: AuditGraphState) -> dict[str, Any]:
    """Resolve ingest payload from state first, then fall back to persisted batch metadata refs."""
    ingest_payload = resolve_ingest_payload(state)
    if any(ingest_payload.values()):
        return ingest_payload

    upload_batch_id = str(state.get("upload_batch_id", "") or "").strip()
    if not upload_batch_id:
        return ingest_payload

    fetch_batch = getattr(get_kg_service(), "fetch_source_upload_batch", None)
    if not callable(fetch_batch):
        return ingest_payload

    batch = fetch_batch(upload_batch_id)
    metadata = dict(batch.get("metadata", {}) or {}) if isinstance(batch, dict) else {}
    ingest_payload_ref = str(metadata.get("ingest_payload_ref", "") or "").strip()
    if not ingest_payload_ref:
        return ingest_payload

    return resolve_ingest_payload({"ingest_payload_ref": ingest_payload_ref})


def _load_layout_result(ocr_service, file_item: dict[str, Any], extension: str) -> dict[str, Any]:
    """Route one uploaded file through the layout-preserving OCR call."""
    common_kwargs = {
        "file_url": file_item.get("url", ""),
        "file_name": file_item.get("name", ""),
        "file_content": file_item.get("content", ""),
        "content_type": file_item.get("content_type", ""),
    }
    if extension in IMAGE_EXTENSIONS or (file_item.get("type") or "").lower() == "image":
        return ocr_service.parse_image_with_layout_sync(**common_kwargs)
    return ocr_service.parse_pdf_with_layout_sync(**common_kwargs)
