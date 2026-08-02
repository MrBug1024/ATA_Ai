"""Chunking helpers for traceable page/chunk persistence."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from ..graph.schemas import ChunkBBoxModel, SourceChunkModel


def normalize_text_for_hash(text: str) -> str:
    """Normalize OCR text before hashing so trivial spacing noise does not churn IDs."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def sha256_text(text: str) -> str:
    """Return a stable SHA256 hex digest for one text payload."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_chunk_id(
    *,
    case_id: int,
    file_sha256: str,
    page_no: int,
    chunk_index: int,
    normalized_chunk_text: str,
) -> str:
    """Build the stable chunk_id defined in the knowledge-graph design."""
    chunk_text_sha256 = sha256_text(normalized_chunk_text)
    raw = f"{case_id}|{file_sha256}|{page_no}|{chunk_index}|{chunk_text_sha256}"
    return sha256_text(raw)


def estimate_token_count(text: str) -> int:
    """Rough token estimator for chunk batching and downstream LLM planning."""
    text = (text or "").strip()
    if not text:
        return 0
    return max(1, len(text) // 2)


def _normalize_bbox(raw_bbox: Any) -> list[ChunkBBoxModel]:
    """Normalize one OCR bbox payload into the frontend-facing bbox model list."""
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return []
    try:
        x1, y1, x2, y2 = [float(value) for value in raw_bbox]
    except Exception:
        return []
    return [ChunkBBoxModel(x=x1, y=y1, w=max(0.0, x2 - x1), h=max(0.0, y2 - y1))]


def build_page_records_from_layout(
    *,
    file_id: int,
    layout_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert OCR layout output into source_page upsert payloads."""
    pages = layout_result.get("pages") or []
    blocks = layout_result.get("blocks") or []
    page_map: dict[int, dict[str, Any]] = {}

    for page_index, page in enumerate(pages, start=1):
        page_map[page_index] = {
            "file_id": file_id,
            "page_no": page_index,
            "page_text": "",
            "page_image_ref": "",
            "page_width": int(page.get("width") or page.get("page_width") or 0),
            "page_height": int(page.get("height") or page.get("page_height") or 0),
            "ocr_blocks": [],
        }

    for block in blocks:
        if not isinstance(block, dict):
            continue
        page_no = int(block.get("page_idx", 0)) + 1
        page_entry = page_map.setdefault(
            page_no,
            {
                "file_id": file_id,
                "page_no": page_no,
                "page_text": "",
                "page_image_ref": "",
                "page_width": int(layout_result.get("page_width") or 0),
                "page_height": int(layout_result.get("page_height") or 0),
                "ocr_blocks": [],
            },
        )
        text = str(block.get("text") or "").strip()
        if text:
            if page_entry["page_text"]:
                page_entry["page_text"] += "\n"
            page_entry["page_text"] += text
        page_entry["ocr_blocks"].append(block)

    return [page_map[key] for key in sorted(page_map.keys())]


def build_chunks_from_pages(
    *,
    case_id: int,
    file_id: int,
    file_sha256: str,
    page_rows: list[dict[str, Any]],
    page_id_map: dict[int, int],
) -> list[SourceChunkModel]:
    """Split OCR blocks into stable chunk rows using real page_idx/text/bbox structure."""
    chunk_rows: list[SourceChunkModel] = []
    for page_row in page_rows:
        page_no = int(page_row["page_no"])
        page_id = int(page_id_map[page_no])
        span_cursor = 0
        chunk_index = 0
        for block in page_row.get("ocr_blocks", []):
            if not isinstance(block, dict):
                continue
            raw_text = str(block.get("text") or "").strip()
            if not raw_text:
                continue
            normalized_text = normalize_text_for_hash(raw_text)
            if not normalized_text:
                continue
            chunk_text_sha256 = sha256_text(normalized_text)
            chunk_id = build_chunk_id(
                case_id=case_id,
                file_sha256=file_sha256,
                page_no=page_no,
                chunk_index=chunk_index,
                normalized_chunk_text=normalized_text,
            )
            span_start = span_cursor
            span_end = span_start + len(normalized_text)
            span_cursor = span_end + 1
            chunk_rows.append(
                SourceChunkModel(
                    chunk_id=chunk_id,
                    case_id=case_id,
                    file_id=file_id,
                    page_id=page_id,
                    page_no=page_no,
                    chunk_index=chunk_index,
                    chunk_type=str(block.get("type") or "text"),
                    chunk_text=normalized_text,
                    chunk_text_sha256=chunk_text_sha256,
                    anchor_text=normalized_text[:120],
                    bbox_list=_normalize_bbox(block.get("bbox")),
                    span_start=span_start,
                    span_end=span_end,
                    token_count=estimate_token_count(normalized_text),
                    metadata={
                        "text_level": block.get("text_level"),
                        "raw_type": block.get("type"),
                    },
                )
            )
            chunk_index += 1
    return chunk_rows
