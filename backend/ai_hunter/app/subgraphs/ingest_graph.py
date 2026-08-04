"""Annual-audit ingestion: structured import, OCR, evidence, and graph enrichment."""

from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..graph.context_loader import resolve_aggregated_text, resolve_ingest_payload
from ..graph.heavy_state import put_heavy_payload
from ..graph.state import AuditGraphState
from ..services.ocr_service import get_ocr_service
from ..settings import get_settings
from ...annual_audit.document_repository import (
    get_case_doc_categories,
    list_doc_categories,
    validate_doc_category,
)
from .build_knowledge_graph_graph import build_knowledge_graph_graph


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
TEXT_EXTENSIONS = {".txt"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
CSV_EXTENSIONS = {".csv"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
DOCUMENT_OCR_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".et",
    ".ett",
}
def _build_ingest_payload_summary(payload: dict) -> str:
    """Build a compact summary for persisted ingest source payloads."""
    spreadsheet_file_count, spreadsheet_sheet_count, spreadsheet_row_count = (
        _spreadsheet_layout_counts(payload)
    )
    return (
        f"txt={len(payload.get('txt_contents', []))}, "
        f"csv={len(payload.get('csv_contents', []))}, "
        f"md={len(payload.get('md_contents', []))}, "
        f"document={len(payload.get('document_ocr_contents', []))}, "
        f"image={len(payload.get('image_ocr_contents', []))}, "
        f"layout={len(payload.get('ocr_layout_results', []))}, "
        f"spreadsheet_files={spreadsheet_file_count}, "
        f"spreadsheet_sheets={spreadsheet_sheet_count}, "
        f"spreadsheet_rows={spreadsheet_row_count}"
    )


def _spreadsheet_layout_counts(payload: dict) -> tuple[int, int, int]:
    """Read local-spreadsheet extraction totals from cached layout payloads."""
    file_count = 0
    sheet_count = 0
    row_count = 0
    for item in payload.get("ocr_layout_results", []) or []:
        if not isinstance(item, dict):
            continue
        layout_result = item.get("layout_result")
        if not isinstance(layout_result, dict):
            continue
        raw_response = layout_result.get("raw_response")
        if not isinstance(raw_response, dict):
            continue
        if raw_response.get("parser") != "annual-spreadsheet-local-v1":
            continue
        file_count += 1
        sheet_count += int(raw_response.get("sheet_count") or 0)
        row_count += int(raw_response.get("nonempty_row_count") or 0)
    return file_count, sheet_count, row_count


def import_annual_structured_files(state: AuditGraphState) -> AuditGraphState:
    """Project supported annual-audit spreadsheets before normal OCR ingestion."""

    from ai_hunter.annual_audit.import_service import import_uploaded_files

    summary = import_uploaded_files(
        engagement_id=int(state.get("current_case_id") or 0),
        files=state.get("uploaded_files") or [],
        actor=str(state.get("operator_id") or state.get("user_id") or "ai_agent"),
    )
    return {"annual_import_summary": summary}


def filter_files(state: AuditGraphState) -> AuditGraphState:
    """Split uploaded files into direct-text buckets and OCR-required buckets."""
    files = state.get("uploaded_files", [])
    txt_contents: list[str] = []
    csv_contents: list[str] = []
    md_contents: list[str] = []
    document_ocr_contents: list[str] = []
    image_ocr_contents: list[str] = []
    ocr_layout_results: list[dict] = []
    ocr_candidates: list[tuple[int, str, dict]] = []

    for index, file_item in enumerate(files):
        extension = (file_item.get("extension") or "").lower()
        content = file_item.get("content", "")
        file_type = (file_item.get("type") or "").lower()
        content_type = (file_item.get("content_type") or "").lower()

        if extension in TEXT_EXTENSIONS:
            txt_contents.append(content)
        elif extension in CSV_EXTENSIONS:
            csv_contents.append(content)
        elif extension in MARKDOWN_EXTENSIONS:
            md_contents.append(content)
        else:
            target = _classify_ocr_target(file_type, extension, content_type)
            ocr_candidates.append((index, target, file_item))

    if ocr_candidates:
        ocr_results = _run_ocr_batch(ocr_candidates)
        for _, target, text, cache_key, layout_result in sorted(ocr_results, key=lambda item: item[0]):
            if target == "image":
                image_ocr_contents.append(text)
            else:
                document_ocr_contents.append(text)
            if cache_key and isinstance(layout_result, dict):
                ocr_layout_results.append(
                    {
                        "cache_key": cache_key,
                        "layout_result": layout_result,
                    }
                )

    payload = {
        "txt_contents": txt_contents,
        "csv_contents": csv_contents,
        "md_contents": md_contents,
        "document_ocr_contents": document_ocr_contents,
        "image_ocr_contents": image_ocr_contents,
        "ocr_layout_results": ocr_layout_results,
    }
    payload_ref = put_heavy_payload("ingest_payload", payload)
    return {
        "ingest_payload_ref": payload_ref,
        "ingest_payload_summary": _build_ingest_payload_summary(payload),
        "txt_contents": [],
        "csv_contents": [],
        "md_contents": [],
        "document_ocr_contents": [],
        "image_ocr_contents": [],
        "ocr_layout_results": [],
    }


def _classify_ocr_target(file_type: str, extension: str, content_type: str) -> str:
    """Classify whether one uploaded file should go through image or document OCR mode."""
    if extension in SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if (
        file_type == "image"
        or extension in IMAGE_EXTENSIONS
        or content_type.startswith("image/")
    ):
        return "image"
    if extension in DOCUMENT_OCR_EXTENSIONS:
        return "document"
    return "document"


def _run_ocr_batch(ocr_candidates: list[tuple[int, str, dict]]) -> list[tuple[int, str, str, str, dict]]:
    """Run OCR requests concurrently while preserving a stable output order."""
    settings = get_settings()
    max_workers = max(1, min(settings.ocr_max_parallel, len(ocr_candidates)))
    results: list[tuple[int, str, str, str, dict]] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_run_one_ocr, index, target, file_item): (index, target, file_item)
            for index, target, file_item in ocr_candidates
        }
        for future in as_completed(future_map):
            index, target, file_item = future_map[future]
            try:
                _, _, text, cache_key, layout_result = future.result()
            except Exception as exc:
                text = _build_ocr_error_text(file_item, f"系统错误: {exc}")
                cache_key = _build_file_cache_key(file_item)
                layout_result = {}
            if text.startswith("[ocr-error]"):
                errors.append(text)
            results.append((index, target, text, cache_key, layout_result))

    if errors:
        raise RuntimeError(
            f"OCR 失败 ({len(errors)} 个文件): " + "; ".join(errors[:3])
        )
    return results


def _run_one_ocr(index: int, target: str, file_item: dict) -> tuple[int, str, str, str, dict]:
    """Run OCR for one file and return text plus reusable layout payload.

    Resolution priority for the file payload:
    1. ``storage_ref`` (minio://bucket/key) → fetch bytes via MinIO client,
       base64-encode, and pass as ``file_content``.
    2. ``url`` (http(s)://) → pass as ``file_url`` for OCR backend to fetch.
    3. ``content`` (legacy base64 or text) → pass as ``file_content``.
    """
    if target == "spreadsheet":
        result = _extract_spreadsheet_with_layout(file_item)
        text = str(result.get("text") or "").strip()
        cache_key = _build_file_cache_key(file_item)
        if text:
            return index, target, text, cache_key, result
        return index, target, _build_ocr_error_text(
            file_item, result.get("message", "表格未返回内容")
        ), cache_key, result

    service = get_ocr_service()
    raw_bytes = _resolve_file_bytes(file_item)
    content = file_item.get("content", "")
    file_url = file_item.get("url", "")
    if raw_bytes is not None:
        content = base64.b64encode(raw_bytes).decode("ascii")
        file_url = ""

    common_kwargs = {
        "file_url": file_url,
        "file_name": file_item.get("name", ""),
        "file_content": content,
        "content_type": file_item.get("content_type", ""),
    }
    if target == "image":
        result = service.parse_image_with_layout_sync(**common_kwargs)
    else:
        result = service.parse_pdf_with_layout_sync(**common_kwargs)

    text = (result.get("text") or "").strip()
    cache_key = _build_file_cache_key(file_item)
    if text:
        return index, target, text, cache_key, result
    return index, target, _build_ocr_error_text(file_item, result.get("message", "OCR未返回内容")), cache_key, result


def _build_file_cache_key(file_item: dict) -> str:
    """Build one stable cache key for reusing OCR layout across graph stages."""
    raw_content = str(file_item.get("content", "") or "")
    if raw_content.strip():
        return hashlib.sha256(_decode_file_bytes(file_item)).hexdigest()
    file_hash = str(file_item.get("file_hash", "") or "").strip()
    if file_hash:
        return file_hash
    url = str(file_item.get("url", "") or "").strip()
    if url:
        return f"url:{url}"
    return f"name:{str(file_item.get('name', '') or '').strip()}"


def _resolve_file_bytes(file_item: dict) -> bytes | None:
    """Resolve uploaded bytes locally when MinIO or inline content is available."""
    from ..services.minio_service import get_minio_service

    storage_ref = str(file_item.get("storage_ref", "") or "").strip()
    if storage_ref.startswith("minio://"):
        try:
            return get_minio_service().get_object_bytes(storage_ref)
        except Exception as exc:
            raise RuntimeError(
                f"MinIO 拉取失败 {file_item.get('name', 'unknown-file')}: {exc}"
            ) from exc
    content = str(file_item.get("content", "") or "").strip()
    if content:
        return _decode_file_bytes(file_item)
    return None


def _spreadsheet_cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).replace("\r", "\n").replace("\t", " ").splitlines()).strip()


def _spreadsheet_sheet_blocks(
    *,
    sheet_name: str,
    sheet_index: int,
    rows: list[list[Any]],
    max_chars: int = 6000,
) -> list[dict[str, Any]]:
    """Turn one worksheet into bounded, traceable text blocks without dropping rows."""
    header = f"## 工作表：{sheet_name}"
    lines: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        values = [_spreadsheet_cell_text(value) for value in row]
        while values and not values[-1]:
            values.pop()
        if not any(values):
            continue
        lines.append(f"[第{row_number}行] " + " | ".join(values))
    if not lines:
        lines = ["（空工作表）"]

    chunks: list[str] = []
    current = header
    for line in lines:
        candidate = f"{current}\n{line}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current != header:
            chunks.append(current)
            current = header
        while len(line) > max_chars - len(header) - 1:
            take = max_chars - len(header) - 1
            chunks.append(f"{header}\n{line[:take]}")
            line = line[take:]
        current = f"{header}\n{line}"
    if current != header:
        chunks.append(current)

    return [
        {
            "type": "spreadsheet",
            "text": chunk,
            "text_level": 1,
            "bbox": [],
            "page_idx": sheet_index,
            "sheet_name": sheet_name,
        }
        for chunk in chunks
    ]


def _extract_spreadsheet_with_layout(file_item: dict) -> dict[str, Any]:
    """Read every worksheet locally and expose one evidence page per sheet."""
    from ai_hunter.annual_audit.import_service import read_tabular_sheets

    file_name = str(file_item.get("name") or "uploaded-workbook.xlsx")
    raw_bytes = _resolve_file_bytes(file_item)
    if raw_bytes is None:
        raise ValueError(f"表格缺少可读取的本地内容: {file_name}")
    sheets = read_tabular_sheets(file_name, raw_bytes)
    if not sheets:
        raise ValueError(f"未读取到工作表: {file_name}")

    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    nonempty_row_count = 0
    for sheet_index, sheet in enumerate(sheets):
        sheet_blocks = _spreadsheet_sheet_blocks(
            sheet_name=sheet.name,
            sheet_index=sheet_index,
            rows=sheet.rows,
        )
        blocks.extend(sheet_blocks)
        nonempty_row_count += sum(1 for row in sheet.rows if any(value not in (None, "") for value in row))
        pages.append({"width": 0, "height": 0, "sheet_name": sheet.name})

    text = "\n\n".join(str(block["text"]) for block in blocks)
    return {
        "text": text,
        "message": "spreadsheet-local-read",
        "pages": pages,
        "blocks": blocks,
        "page_width": 0,
        "page_height": 0,
        "raw_response": {
            "parser": "annual-spreadsheet-local-v1",
            "sheet_count": len(sheets),
            "nonempty_row_count": nonempty_row_count,
            "block_count": len(blocks),
        },
    }


def _decode_file_bytes(file_item: dict) -> bytes:
    """Decode inline file content used by upload flows into raw bytes."""
    extension = (str(file_item.get("extension", "") or "")).lower()
    content = str(file_item.get("content", "") or "")
    if extension in TEXT_EXTENSIONS or extension in MARKDOWN_EXTENSIONS or extension in CSV_EXTENSIONS:
        return content.encode("utf-8")
    normalized = content.strip()
    if normalized.startswith("data:") and ";base64," in normalized:
        normalized = normalized.split(",", 1)[1]
    return base64.b64decode(normalized)


def _build_ocr_error_text(file_item: dict, message: str) -> str:
    """Keep OCR failures visible to downstream parse steps without crashing ingest."""
    file_name = file_item.get("name") or file_item.get("url") or "unknown-file"
    return f"[ocr-error] {file_name}: {message}"


def merge_texts(state: AuditGraphState) -> AuditGraphState:
    """Merge multi-source extraction results into one ingestion payload."""
    blocks: list[str] = []
    ingest_payload = resolve_ingest_payload(state)
    mapping = (
        ("文档OCR提取结果", ingest_payload.get("document_ocr_contents", [])),
        ("图片OCR提取结果", ingest_payload.get("image_ocr_contents", [])),
        ("CSV文件提取结果", ingest_payload.get("csv_contents", [])),
        ("TXT文件提取结果", ingest_payload.get("txt_contents", [])),
        ("Markdown文件提取结果", ingest_payload.get("md_contents", [])),
    )
    for title, items in mapping:
        if items:
            blocks.append(f"## {title}\n" + "\n".join(items))
    aggregated_text = "\n\n".join(blocks)
    aggregated_ref = put_heavy_payload("aggregated_text", {"text": aggregated_text})
    return {
        "aggregated_text_ref": aggregated_ref,
        "aggregated_text_summary": aggregated_text[:240],
        "aggregated_text": "",
    }


def require_engagement_context(state: AuditGraphState) -> AuditGraphState:
    """Require a selected annual-audit engagement before ingesting evidence."""
    if int(state.get("current_case_id", 0) or 0) > 0:
        return {}
    raise ValueError("审计资料摄入前必须先创建并选择年审项目")


def load_doc_category_context(state: AuditGraphState) -> AuditGraphState:
    """Load the annual-audit material catalog and engagement coverage."""
    settings = get_settings()
    case_id = int(state.get("current_case_id", 0) or 0)
    doc_category = str(state.get("doc_category", "") or "").strip()
    updates: dict[str, object] = {"doc_category_catalog": list_doc_categories(settings=settings)}
    if case_id > 0:
        case_status = get_case_doc_categories(case_id, settings=settings)
        updates["case_doc_category_status"] = case_status
        updates["missing_categories"] = case_status.get("missing_categories", [])
    if doc_category:
        updates["doc_category_validation"] = validate_doc_category(
            {
                "case_id": case_id,
                "doc_category": doc_category,
                "file_names": [str(item.get("name", "") or "") for item in state.get("uploaded_files") or []],
                "text_preview": "",
            },
            settings=settings,
        )
    return updates


def finalize_annual_ingest(state: AuditGraphState) -> AuditGraphState:
    """Finalize annual structured imports before graph enrichment."""

    summary = dict(state.get("annual_import_summary") or {})
    dataset_categories = {
        "account_balance": "trial_balance",
        "journal_entry": "journal_entries",
        "receivable_item": "receivables",
        "bank_transaction": "bank_statements",
    }
    categories = [
        dataset_categories[item]
        for item in summary.get("recognized_datasets") or []
        if item in dataset_categories
    ]
    records_inserted = int(summary.get("new_row_count") or 0)
    errors = summary.get("errors") or []
    skipped = summary.get("skipped") or []
    status = "partial" if errors else "processing"
    message_parts = [f"年度审计结构化导入新增 {records_inserted} 行"]
    spreadsheet_file_count, spreadsheet_sheet_count, spreadsheet_row_count = (
        _spreadsheet_layout_counts(resolve_ingest_payload(state))
    )
    if spreadsheet_file_count:
        message_parts.append(
            f"本地完整读取 {spreadsheet_file_count} 个工作簿、"
            f"{spreadsheet_sheet_count} 个工作表、{spreadsheet_row_count} 行非空数据"
        )
    if categories:
        message_parts.append(f"识别资料类别：{', '.join(categories)}")
    if skipped:
        message_parts.append(f"另有 {len(skipped)} 个文件继续进入证据与知识图谱链路")
    if errors:
        message_parts.append(f"{len(errors)} 个文件结构化导入失败，但不阻断证据链路")
    return {
        "parse_summary": "；".join(message_parts) + "。",
        "categories_found": categories,
        "recognized_categories": categories,
        "records_inserted": records_inserted,
        "upload_batch_summary": _mark_upload_batch_summary(
            state,
            status=status,
            stage="annual_structured_imported",
            records_inserted=records_inserted,
            categories_found=categories,
        ),
    }


def _mark_upload_batch_summary(
    state: AuditGraphState,
    *,
    status: str,
    stage: str = "",
    records_inserted: int | None = None,
    categories_found: list[str] | None = None,
) -> dict:
    """Keep batch metadata available before fastserver_api owns persistence."""
    summary = dict(state.get("upload_batch_summary") or {})
    summary.setdefault("upload_batch_id", state.get("upload_batch_id", ""))
    summary.setdefault("material_event_id", f"material-event:{summary['upload_batch_id']}" if summary.get("upload_batch_id") else "")
    summary.setdefault("material_event_type", "supplement_upload")
    summary["material_event_status"] = status
    summary.setdefault("batch_name", state.get("batch_name", ""))
    summary.setdefault("doc_category", state.get("doc_category", ""))
    summary.setdefault("file_count", len(state.get("uploaded_files", []) or []))
    summary.setdefault("new_file_count", len(state.get("new_files", []) or []))
    summary.setdefault("duplicate_file_count", len(state.get("duplicate_files", []) or []))
    summary.setdefault("suspected_mismatch_file_count", len(state.get("suspected_mismatch_files", []) or []))
    summary["status"] = status
    if stage:
        summary["stage"] = stage
    if records_inserted is not None:
        summary["records_inserted"] = records_inserted
    if categories_found is not None:
        summary["categories_found"] = categories_found
    return summary


def build_ingest_graph():
    """Build the standalone ingest subgraph used by the top-level orchestrator and file API."""
    graph = StateGraph(AuditGraphState)
    graph.add_node("upload_parse_graph", build_upload_parse_graph())
    graph.add_node("knowledge_graph_graph", build_knowledge_graph_graph())

    graph.add_edge(START, "upload_parse_graph")
    graph.add_edge("upload_parse_graph", "knowledge_graph_graph")
    graph.add_edge("knowledge_graph_graph", END)
    return graph.compile()


def build_upload_parse_graph():
    """Build the upload-parse stage graph used before knowledge-graph enrichment."""
    graph = StateGraph(AuditGraphState)
    graph.add_node("annual_structured_import", import_annual_structured_files)
    graph.add_node("filter_files", filter_files)
    graph.add_node("merge_texts", merge_texts)
    graph.add_node("require_engagement_context", require_engagement_context)
    graph.add_node("load_doc_category_context", load_doc_category_context)
    graph.add_node("finalize_annual_ingest", finalize_annual_ingest)

    graph.add_edge(START, "annual_structured_import")
    graph.add_edge("annual_structured_import", "filter_files")
    graph.add_edge("filter_files", "merge_texts")
    graph.add_edge("merge_texts", "require_engagement_context")
    graph.add_edge("require_engagement_context", "load_doc_category_context")
    graph.add_edge("load_doc_category_context", "finalize_annual_ingest")
    graph.add_edge("finalize_annual_ingest", END)
    return graph.compile()
