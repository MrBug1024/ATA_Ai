"""File ingestion subgraph: OCR documents, infer debtor, and ingest parsed text."""

from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

from langgraph.graph import END, START, StateGraph

from ..graph.context_loader import resolve_aggregated_text, resolve_ingest_payload
from ..graph.heavy_state import put_heavy_payload
from ..graph.schemas import ParseDocumentResultModel
from ..graph.state import AuditGraphState
from ..services.audit_api import get_audit_api_client
from ..services.doc_category_api import get_doc_category_api_client, get_mock_doc_category_service
from ..services.ocr_service import get_ocr_service
from ..settings import get_settings
from .build_knowledge_graph_graph import build_knowledge_graph_graph


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
TEXT_EXTENSIONS = {".txt"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
CSV_EXTENSIONS = {".csv"}
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
    return (
        f"txt={len(payload.get('txt_contents', []))}, "
        f"csv={len(payload.get('csv_contents', []))}, "
        f"md={len(payload.get('md_contents', []))}, "
        f"document={len(payload.get('document_ocr_contents', []))}, "
        f"image={len(payload.get('image_ocr_contents', []))}, "
        f"layout={len(payload.get('ocr_layout_results', []))}"
    )


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
    from ..services.minio_service import get_minio_service

    service = get_ocr_service()
    storage_ref = (file_item.get("storage_ref") or "").strip()
    content = file_item.get("content", "")
    file_url = file_item.get("url", "")

    if storage_ref.startswith("minio://"):
        try:
            raw_bytes = get_minio_service().get_object_bytes(storage_ref)
        except Exception as exc:
            raise RuntimeError(
                f"MinIO 拉取失败 {file_item.get('name', 'unknown-file')}: {exc}"
            ) from exc
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
    url = str(file_item.get("url", "") or "").strip()
    if url:
        return f"url:{url}"
    return f"name:{str(file_item.get('name', '') or '').strip()}"


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


def infer_debtor_name(state: AuditGraphState) -> AuditGraphState:
    """Require case master data instead of inferring a debtor from document text."""
    if int(state.get("current_case_id", 0) or 0) > 0:
        return {}
    raise ValueError("卷宗摄入前必须先建案并确认债务人，禁止从材料文本自动创建债务人")


def load_doc_category_context(state: AuditGraphState) -> AuditGraphState:
    """Hydrate doc-category catalog and case coverage so upload flows can guide operators."""
    settings = get_settings()
    case_id = int(state.get("current_case_id", 0) or 0)
    doc_category = str(state.get("doc_category", "") or "").strip()
    if settings.enable_doc_category_api_mock:
        mock_service = get_mock_doc_category_service()
        catalog = mock_service.get_doc_categories().model_dump()
        case_status = mock_service.get_case_doc_categories(case_id).model_dump() if case_id > 0 else {}
        validation = (
            mock_service.validate_doc_category(
                {
                    "case_id": case_id,
                    "doc_category": doc_category,
                    "file_names": [str(item.get("name", "") or "") for item in state.get("uploaded_files") or []],
                    "text_preview": "",
                }
            ).model_dump()
            if doc_category
            else {}
        )
        return {
            "doc_category_catalog": catalog,
            "case_doc_category_status": case_status,
            "missing_categories": case_status.get("missing_categories", []) if isinstance(case_status, dict) else [],
            "doc_category_validation": validation or state.get("doc_category_validation", {}),
        }

    updates: dict[str, object] = {}
    try:
        updates["doc_category_catalog"] = get_doc_category_api_client().get_doc_categories_sync()
    except Exception:
        updates["doc_category_catalog"] = {}
    if case_id > 0:
        try:
            case_status = get_doc_category_api_client().get_case_doc_categories_sync(case_id)
            updates["case_doc_category_status"] = case_status
            updates["missing_categories"] = case_status.get("missing_categories", [])
        except Exception:
            pass
    if doc_category:
        try:
            updates["doc_category_validation"] = get_doc_category_api_client().validate_doc_category_sync(
                {
                    "case_id": case_id,
                    "doc_category": doc_category,
                    "file_names": [str(item.get("name", "") or "") for item in state.get("uploaded_files") or []],
                    "text_preview": "",
                }
            )
        except Exception:
            pass
    return updates


def parse_document_and_ingest(state: AuditGraphState) -> AuditGraphState:
    """Send aggregated text into the live parse-document API."""
    aggregated_text = resolve_aggregated_text(state)
    if not aggregated_text.strip():
        return {}
    upload_batch_summary = _mark_upload_batch_summary(state, status="processing", stage="parsing")
    payload = {
        "case_id": state.get("current_case_id") or None,
        "debtor_id": state.get("current_debtor_id") or None,
        "debtor_name": state.get("current_debtor_name") or None,
        "text": aggregated_text,
        "source_filename": state.get("current_debtor_name") or "uploaded-material",
    }
    try:
        response = ParseDocumentResultModel.model_validate(
            get_audit_api_client().parse_document_sync(payload)
        )
        response_payload = response.model_dump()
        response_ref = put_heavy_payload("parse_document_result", response_payload)
        return {
            "parse_document_result_ref": response_ref,
            "parse_document_result": {},
            "parse_summary": response.message or "补充材料已入库。",
            "categories_found": response.categories_found,
            "recognized_categories": response.categories_found,
            "records_inserted": response.records_inserted,
            "current_case_id": response.case_id or state.get("current_case_id", 0),
            "current_debtor_id": response.debtor_id or state.get("current_debtor_id", 0),
            "current_debtor_name": response.debtor_name
            or state.get("current_debtor_name", ""),
            "upload_batch_summary": _mark_upload_batch_summary(
                state,
                status="processing",
                stage="parsed",
                records_inserted=response.records_inserted,
                categories_found=response.categories_found,
            ),
        }
    except Exception as exc:
        raise RuntimeError(f"parse-document 摄入失败: {exc}") from exc


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
    graph.add_node("filter_files", filter_files)
    graph.add_node("merge_texts", merge_texts)
    graph.add_node("infer_debtor_name", infer_debtor_name)
    graph.add_node("load_doc_category_context", load_doc_category_context)
    graph.add_node("parse_document_and_ingest", parse_document_and_ingest)

    graph.add_edge(START, "filter_files")
    graph.add_edge("filter_files", "merge_texts")
    graph.add_edge("merge_texts", "infer_debtor_name")
    graph.add_edge("infer_debtor_name", "load_doc_category_context")
    graph.add_edge("load_doc_category_context", "parse_document_and_ingest")
    graph.add_edge("parse_document_and_ingest", END)
    return graph.compile()
