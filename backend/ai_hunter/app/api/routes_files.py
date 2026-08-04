"""FastAPI routes for direct file upload and ingest into the LangGraph subgraph."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from ..auth.identity import Identity, get_current_identity
from ..auth.permissions import require_any_module
from ..auth.tenancy import require_case_access
from ..graph.context_loader import resolve_aggregated_text
from ..graph.heavy_state import get_heavy_payload, put_heavy_payload
from ..graph.schemas import CaseDocCategoryStatusModel, ValidateDocCategoryResultModel
from ..graph.state import FileItem
from ..logging_utils import build_request_logger, preview_text
from ..services.kg_service import get_kg_service
from ..services.material_event_progress import build_material_event_id, mark_upload_ingest_progress
from ..services.minio_service import resolve_minio_reference_url
from ..services.upload_ingest_jobs import enqueue_upload_ingest_job
from ..settings import get_settings
from ..subgraphs.ingest_graph import (
    CSV_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MARKDOWN_EXTENSIONS,
    TEXT_EXTENSIONS,
    build_upload_parse_graph,
)
from ..subgraphs.build_knowledge_graph_graph import build_knowledge_graph_graph
from ._upload_helpers import resolve_engagement_entity, resolve_upload_batch_id, to_file_item


router = APIRouter(prefix="/files", tags=["files"])
upload_parse_graph = build_upload_parse_graph()
knowledge_graph_graph = build_knowledge_graph_graph()
LOGGER = logging.getLogger(__name__)


class UploadBatchFileResponse(BaseModel):
    upload_batch_link_id: int | None = None
    file_id: int | None = None
    file_name: str = ""
    file_sha256: str = ""
    duplicate_of: str = ""
    file_type: str = ""
    content_type: str = ""
    storage_provider: str = ""
    storage_bucket: str = ""
    storage_key: str = ""
    storage_ref: str = ""
    created_at: str | None = None
    page_count: int = 0
    chunk_count: int = 0
    doc_categories: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"


class UploadBatchPersistenceChecksResponse(BaseModel):
    source_upload_batch_exists: bool = False
    source_file_upload_batch_count: int = 0
    source_file_count_matches: bool = False
    source_page_file_count: int = 0
    source_chunk_file_count: int = 0
    source_file_doc_category_count: int = 0
    all_files_have_chunks: bool = False
    all_files_have_doc_category: bool = False


class UploadBatchResponse(BaseModel):
    upload_batch_id: str = ""
    case_id: int | None = None
    entity_id: int | None = None
    batch_name: str = ""
    doc_category: str | None = None
    operator_id: str = ""
    operator_name: str = ""
    status: str = ""
    file_count: int = 0
    new_file_count: int = 0
    duplicate_file_count: int = 0
    suspected_mismatch_file_count: int = 0
    records_inserted: int = 0
    metadata: dict = Field(default_factory=dict)
    has_conclusion_changes: bool = False
    reconciliation_item_count: int = 0
    add_item_count: int = 0
    override_item_count: int = 0
    change_summary: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    files: list[UploadBatchFileResponse] = Field(default_factory=list)
    persistence_checks: UploadBatchPersistenceChecksResponse = Field(
        default_factory=UploadBatchPersistenceChecksResponse
    )


class UploadBatchSummaryResponse(BaseModel):
    material_event_id: str = ""
    material_event_type: str = ""
    material_event_status: str = ""
    upload_batch_id: str = ""
    batch_name: str = ""
    doc_category: str = ""
    operator_id: str = ""
    operator_name: str = ""
    file_count: int = 0
    new_file_count: int = 0
    duplicate_file_count: int = 0
    suspected_mismatch_file_count: int = 0
    status: str = ""
    stage: str = ""
    has_conclusion_changes: bool = False
    reconciliation_item_count: int = 0
    add_item_count: int = 0
    override_item_count: int = 0
    change_summary: str = ""


class MaterialEventResponse(BaseModel):
    material_event_id: str = ""
    case_id: int | None = None
    entity_id: int | None = None
    upload_batch_id: str = ""
    event_type: str = ""
    status: str = ""
    batch_name: str = ""
    doc_category: str = ""
    operator_id: str = ""
    operator_name: str = ""
    file_count: int = 0
    records_inserted: int = 0
    event_payload: dict = Field(default_factory=dict)
    stage: str = ""
    has_conclusion_changes: bool = False
    reconciliation_item_count: int = 0
    add_item_count: int = 0
    override_item_count: int = 0
    change_summary: str = ""
    error_message: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class EvolutionEvidenceResponse(BaseModel):
    chunk_id: str = ""
    file_id: int = 0
    file_name: str = ""
    page_no: int = 0
    quote_text: str = ""
    bbox_list: list[dict] = Field(default_factory=list)
    source_page_id: int = 0
    page_image_ref: str = ""
    source_file_url: str = ""
    content_type: str = ""
    entity_id: int = 0


class EvolutionItemResponse(BaseModel):
    id: int | None = None
    case_id: int = 0
    action: str = ""
    new_claim_id: int | None = None
    new_claim_type: str = ""
    new_claim_text: str = ""
    superseded_claim_id: int | None = None
    superseded_claim_type: str = ""
    superseded_claim_text: str = ""
    new_relation_id: int | None = None
    superseded_relation_id: int | None = None
    rationale: str = ""
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    decision_payload: dict = Field(default_factory=dict)
    upload_batch_id: str = ""
    batch_name: str = ""
    doc_category: str = ""
    material_event_id: str = ""
    material_event_status: str = ""
    material_event_type: str = ""
    evidences: list[EvolutionEvidenceResponse] = Field(default_factory=list)
    created_at: str | None = None


class UploadErrorResponse(BaseModel):
    error_code: str = ""
    error_message: str = ""
    retryable: bool = True
    stage: str = ""
    upload_batch_id: str = ""
    material_event_id: str = ""


class CaseUploadBatchListResponse(BaseModel):
    case_id: int
    upload_batches: list[UploadBatchResponse] = Field(default_factory=list)


class CaseMaterialEventListResponse(BaseModel):
    case_id: int
    material_events: list[MaterialEventResponse] = Field(default_factory=list)


class CaseEvolutionListResponse(BaseModel):
    case_id: int
    action: str = ""
    evolution_items: list[EvolutionItemResponse] = Field(default_factory=list)


class UnresolvedGraphItemResponse(BaseModel):
    id: int | None = None
    case_id: int = 0
    extraction_run_id: int = 0
    upload_batch_id: str = ""
    material_event_id: str = ""
    item_type: str = ""
    entity_name: str = ""
    entity_key: str = ""
    relation_key: str = ""
    entity_temp_id: str = ""
    relation_temp_id: str = ""
    claim_type: str = ""
    claim_text: str = ""
    relation_type: str = ""
    relation_label: str = ""
    missing_dependencies: list[str] = Field(default_factory=list)
    reason: str = ""
    status: str = ""
    payload: dict = Field(default_factory=dict)
    created_at: str | None = None


class CaseUnresolvedGraphItemsResponse(BaseModel):
    case_id: int
    upload_batch_id: str = ""
    status: str = ""
    unresolved_relation_count: int = 0
    unresolved_claim_count: int = 0
    unresolved_relations: list[UnresolvedGraphItemResponse] = Field(default_factory=list)
    unresolved_claims: list[UnresolvedGraphItemResponse] = Field(default_factory=list)


class UploadAndIngestResponse(BaseModel):
    accepted: bool = True
    upload_batch_id: str = ""
    material_event_id: str = ""
    status: str = "processing"
    stage: str = "stored"
    upload_batch_detail_path: str = ""
    material_event_detail_path: str = ""
    case_upload_batches_path: str = ""
    doc_category: str = ""
    batch_name: str = ""
    operator_id: str = ""
    operator_name: str = ""
    uploaded_file_count: int = 0
    upload_batch_summary: UploadBatchSummaryResponse = Field(default_factory=UploadBatchSummaryResponse)
    doc_category_validation: ValidateDocCategoryResultModel = Field(default_factory=ValidateDocCategoryResultModel)
    case_doc_category_status: CaseDocCategoryStatusModel = Field(default_factory=CaseDocCategoryStatusModel)
    duplicate_files: list[str] = Field(default_factory=list)
    suspected_mismatch_files: list[str] = Field(default_factory=list)
    new_files: list[str] = Field(default_factory=list)


class UploadRetryResponse(BaseModel):
    accepted: bool = True
    upload_batch_id: str = ""
    material_event_id: str = ""
    status: str = "processing"
    retry_stage: str = ""
    stage: str = ""
    upload_batch_detail_path: str = ""
    material_event_detail_path: str = ""


@router.get(
    "/health",
    summary="文件服务健康检查",
    description="用于确认文件上传与摄入路由是否已挂载。",
    response_description="返回简单的服务状态。",
    response_model=HealthResponse,
)
async def files_health() -> HealthResponse:
    """Simple route for file-service health checks."""
    return HealthResponse(status="ok")


@router.get(
    "/upload-batches/{upload_batch_id}",
    summary="查询上传批次详情",
    description="返回批次状态、操作员字段、文件关联、页/块/类别关系落库校验结果。",
    response_model=UploadBatchResponse,
    dependencies=[Depends(require_any_module(("graph", "report")))],
)
async def get_upload_batch(
    upload_batch_id: str,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Expose AI Hunter's persisted upload-batch result to the frontend."""
    batch = get_kg_service().fetch_source_upload_batch(upload_batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"upload_batch_id 不存在: {upload_batch_id}")
    require_case_access(int(batch.get("case_id", 0) or 0), identity)
    return _decorate_upload_batch_response(batch)


@router.get(
    "/cases/{case_id}/upload-batches",
    summary="查询案件上传批次列表",
    description="返回某案件最近的上传批次，用于操作员上传历史和状态列表。",
    response_model=CaseUploadBatchListResponse,
    dependencies=[Depends(require_any_module(("graph", "report"))), Depends(require_case_access)],
)
async def list_case_upload_batches(
    case_id: int,
    limit: int = Query(50, ge=1, le=200, description="最多返回多少个批次。"),
) -> dict:
    """List recent upload batches for a case."""
    batches = get_kg_service().list_source_upload_batches_by_case(case_id, limit=limit)
    kg_service = get_kg_service()
    return {
        "case_id": case_id,
        "upload_batches": [
            _decorate_upload_batch_response(
                kg_service.fetch_source_upload_batch(b["upload_batch_id"]) or b
            )
            for b in batches
        ],
    }


@router.get(
    "/material-events/{material_event_id}",
    summary="查询材料事件详情",
    description="返回一次上传或追加补件事件的最小状态边界。",
    response_model=MaterialEventResponse,
    dependencies=[Depends(require_any_module(("graph", "report")))],
)
async def get_material_event(
    material_event_id: str,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Fetch one material event so the frontend can inspect upload/re-audit event state."""
    event = get_kg_service().fetch_material_event(material_event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"material_event_id 不存在: {material_event_id}")
    require_case_access(int(event.get("case_id", 0) or 0), identity)
    return _decorate_material_event_response(event)


@router.get(
    "/cases/{case_id}/material-events",
    summary="查询案件材料事件列表",
    description="返回某案件最近的材料事件，用于补件治理、事件时间线和后续演进展示。",
    response_model=CaseMaterialEventListResponse,
    dependencies=[Depends(require_any_module(("graph", "report"))), Depends(require_case_access)],
)
async def list_case_material_events(
    case_id: int,
    limit: int = Query(50, ge=1, le=200, description="最多返回多少个材料事件。"),
) -> dict:
    """List recent material events for one case."""
    events = get_kg_service().list_material_events_by_case(case_id, limit=limit)
    return {
        "case_id": case_id,
        "material_events": [_decorate_material_event_response(event) for event in events],
    }


@router.get(
    "/cases/{case_id}/evolution-items",
    summary="查询案件结论演进视图",
    description="返回前端可直接消费的旧 claim -> 新 claim 演进列表，并补齐事件、批次与证据上下文。",
    response_model=CaseEvolutionListResponse,
    dependencies=[Depends(require_any_module(("graph", "report"))), Depends(require_case_access)],
)
async def list_case_evolution_items(
    case_id: int,
    action: str = Query("", description="可选，按 ADD 或 OVERRIDE 过滤。"),
    limit: int = Query(20, ge=1, le=200, description="最多返回多少条演进记录。"),
) -> dict:
    """List frontend-friendly evolution items for one case."""
    raw_items = get_kg_service().fetch_case_evolution_items(
        case_id=case_id,
        action=action,
        limit=limit,
    )
    items: list[dict] = []
    for item in raw_items:
        created_at = item.get("created_at")
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        elif created_at is not None and not isinstance(created_at, str):
            created_at = str(created_at)
        items.append({**item, "created_at": created_at})
    return {
        "case_id": case_id,
        "action": str(action or "").strip().upper(),
        "evolution_items": items,
    }


@router.get(
    "/cases/{case_id}/unresolved-items",
    summary="查询案件未决图谱项",
    description="返回某案件跨批次未补齐或已补齐的 unresolved relation / claim，可按批次与状态过滤。",
    response_model=CaseUnresolvedGraphItemsResponse,
    dependencies=[Depends(require_any_module(("graph", "report"))), Depends(require_case_access)],
)
async def list_case_unresolved_items(
    case_id: int,
    status: str = Query("pending", description="筛选状态；默认 pending，可传 resolved 或空字符串查看全部。"),
    upload_batch_id: str = Query("", description="可选，按上传批次 ID 过滤。"),
    limit: int = Query(50, ge=1, le=200, description="最多返回多少条未决项。"),
) -> dict:
    """List unresolved graph items for one case so operators can inspect cross-batch replay progress."""
    payload = get_kg_service().fetch_unresolved_graph_items(
        case_id=case_id,
        upload_batch_id=upload_batch_id,
        status=status,
        limit=limit,
    )
    def _serialize_items(items: list[dict]) -> list[dict]:
        serialized: list[dict] = []
        for item in items:
            created_at = item.get("created_at")
            if hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            elif created_at is not None and not isinstance(created_at, str):
                created_at = str(created_at)
            serialized.append({**item, "created_at": created_at})
        return serialized

    unresolved_relations = _serialize_items(payload.get("unresolved_relations", []))
    unresolved_claims = _serialize_items(payload.get("unresolved_claims", []))
    return {
        "case_id": case_id,
        "upload_batch_id": upload_batch_id,
        "status": status,
        "unresolved_relation_count": len(unresolved_relations),
        "unresolved_claim_count": len(unresolved_claims),
        "unresolved_relations": unresolved_relations,
        "unresolved_claims": unresolved_claims,
    }


@router.post(
    "/upload-batches/{upload_batch_id}/retry",
    summary="按阶段重试上传摄入任务",
    description="对失败的上传批次执行手动重试；支持 parse、graph 或 auto 自动判断。",
    response_model=UploadRetryResponse,
    dependencies=[Depends(require_any_module(("corrections", "admin")))],
)
async def retry_upload_batch(
    upload_batch_id: str,
    stage: str = Query("auto", description="重试阶段：auto、parse、graph。"),
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Retry a failed upload batch from the parse stage or graph stage."""
    batch = get_kg_service().fetch_source_upload_batch(upload_batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"upload_batch_id 不存在: {upload_batch_id}")
    require_case_access(int(batch.get("case_id", 0) or 0), identity)
    material_event_id = str((dict(batch.get("metadata", {}) or {})).get("material_event_id", "") or _build_material_event_id(upload_batch_id))
    event = get_kg_service().fetch_material_event(material_event_id) if material_event_id else {}

    try:
        resolved_stage = _resolve_retry_stage(batch=batch, event=event, requested_stage=stage)
        if resolved_stage == "parse":
            job_payload = _build_retry_parse_job_payload(batch=batch, event=event)
            next_stage = "ocr_running"
        else:
            job_payload = _build_retry_graph_job_payload(batch=batch, event=event)
            next_stage = "graph_running"
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    retry_queue_stage = f"retry_{resolved_stage}_queued"
    _mark_retry_progress(
        batch=batch,
        event=event,
        status="processing",
        stage=retry_queue_stage,
    )
    try:
        if resolved_stage == "parse":
            _enqueue_upload_ingest_job(job_payload)
        else:
            _enqueue_graph_enrichment_job(job_payload)
    except Exception as exc:
        error_payload = _build_upload_error(
            stage=retry_queue_stage,
            error_code="INGEST_RETRY_ENQUEUE_FAILED",
            message=str(exc),
            upload_batch_id=upload_batch_id,
        )
        _mark_retry_progress(
            batch=batch,
            event=event,
            status="failed",
            stage=retry_queue_stage,
            error_payload=error_payload,
            error_message=str(exc),
        )
        LOGGER.exception(
            "files_upload_retry_failed stage=%s upload_batch_id=%s",
            retry_queue_stage,
            upload_batch_id,
        )
        raise HTTPException(status_code=500, detail=error_payload) from exc

    return {
        "accepted": True,
        "upload_batch_id": upload_batch_id,
        "material_event_id": material_event_id,
        "status": "processing",
        "retry_stage": resolved_stage,
        "stage": next_stage,
        "upload_batch_detail_path": f"/files/upload-batches/{upload_batch_id}",
        "material_event_detail_path": f"/files/material-events/{material_event_id}",
    }


def _mark_retry_progress(
    *,
    batch: dict,
    event: dict,
    status: str,
    stage: str,
    error_payload: dict | None = None,
    error_message: str = "",
) -> None:
    """Persist retry acceptance before enqueue so pollers never observe stale failure."""
    metadata = dict(batch.get("metadata", {}) or {})
    event_payload = dict(event.get("event_payload", {}) or {})

    def _value(key: str, default=None):
        return event_payload.get(key, metadata.get(key, default))

    mark_upload_ingest_progress(
        case_id=int(batch.get("case_id", 0) or 0),
        entity_id=int(batch.get("entity_id", 0) or 0),
        batch_name=str(batch.get("batch_name", "") or ""),
        doc_category=str(batch.get("doc_category", "") or ""),
        operator_id=str(batch.get("operator_id", "") or ""),
        operator_name=str(batch.get("operator_name", "") or ""),
        upload_batch_id=str(batch.get("upload_batch_id", "") or ""),
        status=status,
        stage=stage,
        file_count=int(batch.get("file_count", 0) or 0),
        new_file_count=int(batch.get("new_file_count", 0) or 0),
        duplicate_file_count=int(batch.get("duplicate_file_count", 0) or 0),
        suspected_mismatch_file_count=int(batch.get("suspected_mismatch_file_count", 0) or 0),
        records_inserted=int(batch.get("records_inserted", 0) or 0),
        duplicate_files=list(_value("duplicate_files", []) or []),
        suspected_mismatch_files=list(_value("suspected_mismatch_files", []) or []),
        new_files=list(_value("new_files", []) or []),
        text_file_content_refs=dict(_value("text_file_content_refs", {}) or {}),
        categories_found=list(_value("categories_found", []) or []),
        recognized_categories=list(_value("recognized_categories", []) or []),
        parse_summary=str(_value("parse_summary", "") or ""),
        has_conclusion_changes=bool(_value("has_conclusion_changes", False)),
        reconciliation_item_count=int(_value("reconciliation_item_count", 0) or 0),
        add_item_count=int(_value("add_item_count", 0) or 0),
        override_item_count=int(_value("override_item_count", 0) or 0),
        change_summary=str(_value("change_summary", "") or ""),
        unresolved_relation_count=int(_value("unresolved_relation_count", 0) or 0),
        unresolved_claim_count=int(_value("unresolved_claim_count", 0) or 0),
        ingest_payload_ref=str(_value("ingest_payload_ref", "") or ""),
        aggregated_text_ref=str(_value("aggregated_text_ref", "") or ""),
        parse_document_result_ref=str(_value("parse_document_result_ref", "") or ""),
        chunk_batch_ref=str(_value("chunk_batch_ref", "") or ""),
        kg_subgraph_ref=str(_value("kg_subgraph_ref", "") or ""),
        error_payload=error_payload,
        error_message=error_message,
    )


@router.post(
    "/upload-and-ingest",
    summary="上传文件并异步触发摄入",
    description=(
        "接收前端 multipart 文件上传，完成校验与文件落存储后立即返回受理结果。"
        " OCR、结构化解析与图谱摄入由后台异步执行，前端可使用"
        " `material_event_id` 和 `upload_batch_id` 轮询状态接口。"
        " 上传前必须先创建并绑定年审项目，不允许 current_case_id=0；"
        "被审计单位由年审项目主数据确定。"
    ),
    response_description=(
        "返回受理成功后的批次 ID、材料事件 ID 与状态查询路径。"
    ),
    response_model=UploadAndIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_and_ingest(
    request: Request,
    files: list[UploadFile] = File(
        ...,
        description=(
            "待摄入文件列表。支持 txt/csv/md 直读；"
            "pdf/doc/docx/xls/xlsx/xlsm 走文档 OCR；图片走图片 OCR。"
        ),
    ),
    current_case_id: int = Form(
        0,
        description="年审项目 ID；始终必须大于 0，且鉴权开启时当前用户必须有项目访问权限。",
    ),
    current_entity_id: int = Form(0, description="被审计单位实体 ID。未知时可传 0。"),
    current_entity_name: str = Form(
        "",
        description="可选被审计单位名称；仅用于与年审项目主数据一致性校验。",
    ),
    doc_category: str = Form(
        "",
        description="本批审计资料类别编码。同一批次只允许上传一种类别。",
    ),
    batch_name: str = Form(
        "",
        description="可选批次名称，例如 2025-06 第一次补件。",
    ),
    upload_batch_id: str = Form(
        "",
        description="可选上传批次 ID。fastserver_api 接入后由批次接口生成；为空时本接口生成临时批次号。",
    ),
    operator_id: str = Form("", description="可选，操作员 ID。"),
    operator_name: str = Form("", description="可选，操作员名称。"),
    identity: Identity = Depends(require_any_module(("materials", "admin"))),
) -> dict:
    """Accept multipart uploads, persist lightweight metadata, and enqueue background ingest."""
    settings = get_settings()
    request_id = getattr(request.state, "request_id", "-")
    logger = build_request_logger(
        __name__,
        request_id=request_id,
        case_id=current_case_id or "-",
    )
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一个文件。")
    if len(files) > settings.max_upload_files:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多上传 {settings.max_upload_files} 个文件。",
        )
    if current_case_id <= 0:
        raise HTTPException(status_code=400, detail="上传前必须先创建并绑定有效年审项目")
    require_case_access(current_case_id, identity)
    if not doc_category.strip():
        raise HTTPException(
            status_code=400,
            detail="缺少 doc_category；当前约定同一批次只允许上传一种审计资料类别。",
        )

    operator_id = operator_id or identity.user_id
    operator_name = operator_name or identity.username
    resolved_batch_id = resolve_upload_batch_id(upload_batch_id)
    entity_resolution = resolve_engagement_entity(
        case_id=current_case_id,
        entity_id=current_entity_id,
        entity_name=current_entity_name,
        identity=identity,
    )
    current_entity_id = entity_resolution.entity_id
    current_entity_name = entity_resolution.entity_name
    kg_service = get_kg_service()
    fetch_existing_batch = getattr(kg_service, "fetch_source_upload_batch", None)
    existing_batch = fetch_existing_batch(resolved_batch_id) if callable(fetch_existing_batch) else {}
    if existing_batch:
        await _validate_upload_batch_replay(
            batch=existing_batch,
            files=files,
            case_id=current_case_id,
            entity_id=current_entity_id,
            doc_category=doc_category,
        )
        existing_status = str(existing_batch.get("status", "") or "")
        if existing_status == "failed":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"上传批次 {resolved_batch_id} 已失败；"
                    f"请调用 /files/upload-batches/{resolved_batch_id}/retry 按失败阶段重试。"
                ),
            )
        logger.info(
            "files_upload_idempotent_replay upload_batch_id=%s status=%s file_count=%s",
            resolved_batch_id,
            existing_status,
            existing_batch.get("file_count", 0),
        )
        return _build_idempotent_upload_response(existing_batch)
    logger.info(
        "files_upload_received uploaded_file_count=%s entity_id=%s entity_name=%s resolution_source=%s doc_category=%s batch_name=%s upload_batch_id=%s",
        len(files),
        current_entity_id,
        preview_text(current_entity_name, 80),
        entity_resolution.source,
        doc_category,
        preview_text(batch_name, 80),
        resolved_batch_id,
    )
    validation_payload = _resolve_doc_category_validation(
        current_case_id=current_case_id,
        doc_category=doc_category,
        file_names=[upload.filename or "uploaded-file" for upload in files],
    )
    case_doc_category_status = _resolve_case_doc_category_status(current_case_id)
    if _is_unsupported_doc_category(validation_payload):
        raise HTTPException(status_code=400, detail=validation_payload["message"])
    uploaded_files: list[FileItem] = []
    seen_hashes: dict[str, str] = {}
    duplicate_files: list[str] = []
    try:
        for upload in files:
            file_item = await to_file_item(
                upload,
                settings,
                logger,
                current_case_id=current_case_id,
                current_entity_id=current_entity_id,
                entity_name=current_entity_name,
                doc_category=doc_category,
                upload_batch_id=resolved_batch_id,
                populate_content=True,
            )
            file_hash = file_item.get("file_hash", "")
            if file_hash and file_hash in seen_hashes:
                file_item["duplicate_of"] = seen_hashes[file_hash]
                duplicate_files.append(file_item.get("name", "uploaded-file"))
            elif file_hash:
                seen_hashes[file_hash] = file_item.get("name", "uploaded-file")
            uploaded_files.append(file_item)
    except HTTPException:
        raise
    except Exception as exc:
        error_payload = _build_upload_error(
            stage="uploading",
            error_code="UPLOAD_STORAGE_FAILED",
            message=str(exc),
            upload_batch_id=resolved_batch_id,
        )
        _persist_failed_upload_batch(
            case_id=current_case_id,
            entity_id=current_entity_id,
            batch_name=batch_name,
            doc_category=doc_category,
            operator_id=operator_id,
            operator_name=operator_name,
            upload_batch_id=resolved_batch_id,
            file_count=len(files),
            error_payload=error_payload,
        )
        logger.exception("files_upload_failed stage=uploading upload_batch_id=%s", resolved_batch_id)
        raise HTTPException(status_code=500, detail=error_payload) from exc

    validation_duplicate_files = _extract_validation_file_list(validation_payload, "duplicate_files")
    validation_mismatch_files = _extract_validation_file_list(validation_payload, "suspected_mismatch_files")
    duplicate_files = _dedupe_names([*duplicate_files, *validation_duplicate_files])
    suspected_mismatch_files = _dedupe_names(validation_mismatch_files)
    new_files = [
        item.get("name", "uploaded-file")
        for item in uploaded_files
        if item.get("name", "uploaded-file") not in set(duplicate_files)
    ]
    upload_batch_summary = {
        "material_event_id": _build_material_event_id(resolved_batch_id),
        "material_event_type": "supplement_upload",
        "material_event_status": "received",
        "upload_batch_id": resolved_batch_id,
        "batch_name": batch_name,
        "doc_category": doc_category,
        "operator_id": operator_id,
        "operator_name": operator_name,
        "file_count": len(uploaded_files),
        "new_file_count": len(new_files),
        "duplicate_file_count": len(duplicate_files),
        "suspected_mismatch_file_count": len(suspected_mismatch_files),
        "status": "received",
        "stage": "uploading",
        "has_conclusion_changes": False,
        "reconciliation_item_count": 0,
        "add_item_count": 0,
        "override_item_count": 0,
        "change_summary": "",
    }
    mark_upload_ingest_progress(
        case_id=current_case_id,
        entity_id=current_entity_id,
        batch_name=batch_name,
        doc_category=doc_category,
        operator_id=operator_id,
        operator_name=operator_name,
        upload_batch_id=resolved_batch_id,
        status="received",
        stage="uploading",
        file_count=len(uploaded_files),
        new_file_count=len(new_files),
        duplicate_file_count=len(duplicate_files),
        suspected_mismatch_file_count=len(suspected_mismatch_files),
        duplicate_files=duplicate_files,
        suspected_mismatch_files=suspected_mismatch_files,
        new_files=new_files,
    )
    mark_upload_ingest_progress(
        case_id=current_case_id,
        entity_id=current_entity_id,
        batch_name=batch_name,
        doc_category=doc_category,
        operator_id=operator_id,
        operator_name=operator_name,
        upload_batch_id=resolved_batch_id,
        status="processing",
        stage="stored",
        file_count=len(uploaded_files),
        new_file_count=len(new_files),
        duplicate_file_count=len(duplicate_files),
        suspected_mismatch_file_count=len(suspected_mismatch_files),
        duplicate_files=duplicate_files,
        suspected_mismatch_files=suspected_mismatch_files,
        new_files=new_files,
    )
    try:
        _persist_uploaded_file_membership(
            case_id=current_case_id,
            entity_id=current_entity_id,
            upload_batch_id=resolved_batch_id,
            uploaded_files=uploaded_files,
        )
    except Exception as exc:
        error_payload = _build_upload_error(
            stage="stored",
            error_code="UPLOAD_METADATA_PERSIST_FAILED",
            message=str(exc),
            upload_batch_id=resolved_batch_id,
        )
        mark_upload_ingest_progress(
            case_id=current_case_id,
            entity_id=current_entity_id,
            batch_name=batch_name,
            doc_category=doc_category,
            operator_id=operator_id,
            operator_name=operator_name,
            upload_batch_id=resolved_batch_id,
            status="failed",
            stage="stored",
            file_count=len(uploaded_files),
            new_file_count=len(new_files),
            duplicate_file_count=len(duplicate_files),
            suspected_mismatch_file_count=len(suspected_mismatch_files),
            duplicate_files=duplicate_files,
            suspected_mismatch_files=suspected_mismatch_files,
            new_files=new_files,
            error_payload=error_payload,
            error_message=str(exc),
        )
        logger.exception(
            "files_upload_failed stage=stored upload_batch_id=%s",
            resolved_batch_id,
        )
        raise HTTPException(status_code=500, detail=error_payload) from exc
    job_payload = _build_upload_ingest_job_payload(
        current_case_id=current_case_id,
        current_entity_id=current_entity_id,
        current_entity_name=current_entity_name,
        doc_category=doc_category,
        batch_name=batch_name,
        upload_batch_id=resolved_batch_id,
        operator_id=operator_id,
        operator_name=operator_name,
        uploaded_files=uploaded_files,
        doc_category_validation=validation_payload,
        duplicate_files=duplicate_files,
        suspected_mismatch_files=suspected_mismatch_files,
        new_files=new_files,
        upload_batch_summary={
            **upload_batch_summary,
            "material_event_status": "processing",
            "status": "processing",
            "stage": "stored",
        },
    )
    try:
        _enqueue_upload_ingest_job(job_payload)
    except Exception as exc:
        error_payload = _build_upload_error(
            stage="queued",
            error_code="INGEST_JOB_ENQUEUE_FAILED",
            message=str(exc),
            upload_batch_id=resolved_batch_id,
        )
        mark_upload_ingest_progress(
            case_id=current_case_id,
            entity_id=current_entity_id,
            batch_name=batch_name,
            doc_category=doc_category,
            operator_id=operator_id,
            operator_name=operator_name,
            upload_batch_id=resolved_batch_id,
            file_count=len(uploaded_files),
            status="failed",
            stage="queued",
            new_file_count=len(new_files),
            duplicate_file_count=len(duplicate_files),
            suspected_mismatch_file_count=len(suspected_mismatch_files),
            duplicate_files=duplicate_files,
            suspected_mismatch_files=suspected_mismatch_files,
            new_files=new_files,
            error_payload=error_payload,
            error_message=str(exc),
        )
        logger.exception("files_upload_failed stage=queued upload_batch_id=%s", resolved_batch_id)
        raise HTTPException(status_code=500, detail=error_payload) from exc

    logger.info(
        "files_upload_accepted uploaded_file_count=%s upload_batch_id=%s material_event_id=%s",
        len(uploaded_files),
        resolved_batch_id,
        _build_material_event_id(resolved_batch_id),
    )
    return {
        "accepted": True,
        "upload_batch_id": resolved_batch_id,
        "material_event_id": _build_material_event_id(resolved_batch_id),
        "status": "processing",
        "stage": "stored",
        "upload_batch_detail_path": f"/files/upload-batches/{resolved_batch_id}",
        "material_event_detail_path": f"/files/material-events/{_build_material_event_id(resolved_batch_id)}",
        "case_upload_batches_path": f"/files/cases/{current_case_id}/upload-batches",
        "doc_category": doc_category,
        "batch_name": batch_name,
        "operator_id": operator_id,
        "operator_name": operator_name,
        "uploaded_file_count": len(uploaded_files),
        "upload_batch_summary": {
            **upload_batch_summary,
            "material_event_status": "processing",
            "status": "processing",
            "stage": "stored",
        },
        "doc_category_validation": validation_payload,
        "case_doc_category_status": case_doc_category_status,
        "duplicate_files": duplicate_files,
        "suspected_mismatch_files": suspected_mismatch_files,
        "new_files": new_files,
    }


async def _validate_upload_batch_replay(
    *,
    batch: dict,
    files: list[UploadFile],
    case_id: int,
    entity_id: int,
    doc_category: str,
) -> None:
    """Reject reuse of an upload_batch_id for a different tenant object or file set."""
    mismatched_fields = []
    if int(batch.get("case_id", 0) or 0) != int(case_id or 0):
        mismatched_fields.append("case_id")
    if int(batch.get("entity_id", 0) or 0) != int(entity_id or 0):
        mismatched_fields.append("entity_id")
    if str(batch.get("doc_category", "") or "") != str(doc_category or ""):
        mismatched_fields.append("doc_category")
    if mismatched_fields:
        raise HTTPException(
            status_code=409,
            detail=f"upload_batch_id 已绑定其他上传上下文：{', '.join(mismatched_fields)}",
        )

    incoming_files: list[tuple[str, str]] = []
    for upload in files:
        digest = hashlib.sha256()
        while chunk := await upload.read(1024 * 1024):
            digest.update(chunk)
        await upload.seek(0)
        incoming_files.append((upload.filename or "uploaded-file", digest.hexdigest()))
    persisted_files = [
        (str(item.get("file_name", "") or ""), str(item.get("file_sha256", "") or ""))
        for item in batch.get("files", []) or []
    ]
    if sorted(incoming_files) != sorted(persisted_files):
        raise HTTPException(
            status_code=409,
            detail="upload_batch_id 已绑定其他文件集合，请为新文件生成新的上传批次 ID。",
        )


def _build_idempotent_upload_response(batch: dict) -> dict:
    metadata = dict(batch.get("metadata", {}) or {})
    upload_batch_id = str(batch.get("upload_batch_id", "") or "")
    file_names = [str(item.get("file_name", "") or "") for item in batch.get("files", []) or []]
    status_value = str(batch.get("status", "") or "processing")
    stage = str(metadata.get("stage", "") or "stored")
    material_event_id = str(
        metadata.get("material_event_id", "") or _build_material_event_id(upload_batch_id)
    )
    return {
        "accepted": True,
        "upload_batch_id": upload_batch_id,
        "material_event_id": material_event_id,
        "status": status_value,
        "stage": stage,
        "upload_batch_detail_path": f"/files/upload-batches/{upload_batch_id}",
        "material_event_detail_path": f"/files/material-events/{material_event_id}",
        "case_upload_batches_path": f"/files/cases/{int(batch.get('case_id', 0) or 0)}/upload-batches",
        "doc_category": str(batch.get("doc_category", "") or ""),
        "batch_name": str(batch.get("batch_name", "") or ""),
        "operator_id": str(batch.get("operator_id", "") or ""),
        "operator_name": str(batch.get("operator_name", "") or ""),
        "uploaded_file_count": int(batch.get("file_count", 0) or 0),
        "upload_batch_summary": {
            **metadata,
            "material_event_id": material_event_id,
            "material_event_status": status_value,
            "upload_batch_id": upload_batch_id,
            "status": status_value,
            "stage": stage,
        },
        "doc_category_validation": {
            "ok": True,
            "suspected_duplicate": True,
            "duplicate_files": file_names,
            "message": "相同 upload_batch_id 与文件集合已处理，本次直接返回已有批次状态。",
        },
        "duplicate_files": file_names,
        "suspected_mismatch_files": list(metadata.get("suspected_mismatch_files", []) or []),
        "new_files": [],
    }


def _build_upload_ingest_job_payload(
    *,
    current_case_id: int,
    current_entity_id: int,
    current_entity_name: str,
    doc_category: str,
    batch_name: str,
    upload_batch_id: str,
    operator_id: str,
    operator_name: str,
    uploaded_files: list[FileItem],
    doc_category_validation: dict,
    duplicate_files: list[str],
    suspected_mismatch_files: list[str],
    new_files: list[str],
    upload_batch_summary: dict,
) -> dict:
    """Build one serializable background-ingest job payload."""
    material_event_id = _build_material_event_id(upload_batch_id)
    return {
        "current_case_id": int(current_case_id or 0),
        "current_entity_id": int(current_entity_id or 0),
        "current_entity_name": str(current_entity_name or ""),
        "doc_category": str(doc_category or ""),
        "batch_name": str(batch_name or ""),
        "upload_batch_id": str(upload_batch_id or ""),
        "material_event_id": material_event_id,
        "operator_id": str(operator_id or ""),
        "operator_name": str(operator_name or ""),
        "uploaded_files": [dict(item) for item in uploaded_files],
        "doc_category_validation": dict(doc_category_validation or {}),
        "duplicate_files": list(duplicate_files or []),
        "suspected_mismatch_files": list(suspected_mismatch_files or []),
        "new_files": list(new_files or []),
        "text_file_content_refs": _build_text_file_content_refs(uploaded_files),
        "upload_batch_summary": dict(upload_batch_summary or {}),
    }


def _persist_uploaded_file_membership(
    *,
    case_id: int,
    entity_id: int,
    upload_batch_id: str,
    uploaded_files: list[FileItem],
) -> list[dict]:
    """Persist MinIO-backed file identity before OCR so failed jobs remain retryable."""
    source_rows: list[dict] = []
    duplicate_by_sha256: dict[str, str] = {}
    for item in uploaded_files:
        file_hash = str(item.get("file_hash", "") or "").strip()
        if not file_hash:
            raise ValueError(f"上传文件缺少 SHA256: {item.get('name', 'uploaded-file')}")
        duplicate_of = str(item.get("duplicate_of", "") or "").strip()
        if duplicate_of:
            duplicate_by_sha256[file_hash] = duplicate_of
        source_rows.append(
            {
                "case_id": int(case_id),
                "entity_id": int(entity_id or 0),
                "file_name": str(item.get("name", "") or "uploaded-file"),
                "file_type": str(item.get("type", "") or "document"),
                "content_type": str(item.get("content_type", "") or ""),
                "file_sha256": file_hash,
                "file_size_bytes": int(item.get("file_size", 0) or 0),
                "storage_ref": str(item.get("storage_ref", "") or item.get("url", "") or ""),
                "storage_provider": str(item.get("storage_provider", "") or ""),
                "storage_bucket": str(item.get("storage_bucket", "") or ""),
                "storage_key": str(item.get("storage_key", "") or ""),
                "storage_etag": str(item.get("storage_etag", "") or ""),
                "storage_version": str(item.get("storage_version", "") or ""),
                "ingest_payload_ref": "",
                "ocr_provider": "",
                "ocr_version": "",
                "parser_version": "",
                "status": "active",
            }
        )

    kg_service = get_kg_service()
    inserted_files = kg_service.insert_source_files(source_rows)
    if len(inserted_files) != len(source_rows):
        raise RuntimeError("上传文件元数据未完整持久化")
    linked_files = kg_service.link_source_files_to_upload_batch(
        upload_batch_id=upload_batch_id,
        files=inserted_files,
        duplicate_by_sha256=duplicate_by_sha256,
    )
    if len(linked_files) != len(inserted_files):
        raise RuntimeError("上传批次与文件关联未完整持久化")
    return linked_files


def _enqueue_upload_ingest_job(job_payload: dict) -> None:
    """Submit one upload-parse job to the shared background executor."""
    enqueue_upload_ingest_job(job_payload, _run_upload_parse_job)


def _enqueue_graph_enrichment_job(job_payload: dict) -> None:
    """Submit one graph-enrichment job to the shared background executor."""
    enqueue_upload_ingest_job(job_payload, _run_graph_enrichment_job)


def _run_upload_ingest_job(job_payload: dict) -> None:
    """Legacy helper kept for tests; runs parse then graph inline."""
    parse_result = _run_upload_parse_job(job_payload, enqueue_graph_job=False)
    if isinstance(parse_result, dict):
        _run_graph_enrichment_job(_build_graph_enrichment_job_payload(parse_result))


def _build_base_upload_state(job_payload: dict, *, initial_stage: str) -> dict:
    """Hydrate the graph state passed into the upload-parse stage."""
    upload_batch_summary = dict(job_payload.get("upload_batch_summary", {}) or {})
    return {
        "current_case_id": int(job_payload.get("current_case_id", 0) or 0),
        "current_entity_id": int(job_payload.get("current_entity_id", 0) or 0),
        "current_entity_name": str(job_payload.get("current_entity_name", "") or ""),
        "doc_category": str(job_payload.get("doc_category", "") or ""),
        "batch_name": str(job_payload.get("batch_name", "") or ""),
        "upload_batch_id": str(job_payload.get("upload_batch_id", "") or ""),
        "material_event_id": str(job_payload.get("material_event_id", "") or ""),
        "operator_id": str(job_payload.get("operator_id", "") or ""),
        "operator_name": str(job_payload.get("operator_name", "") or ""),
        "uploaded_files": [dict(item) for item in job_payload.get("uploaded_files", []) if isinstance(item, dict)],
        "doc_category_validation": dict(job_payload.get("doc_category_validation", {}) or {}),
        "duplicate_files": [str(item) for item in job_payload.get("duplicate_files", []) or []],
        "suspected_mismatch_files": [str(item) for item in job_payload.get("suspected_mismatch_files", []) or []],
        "new_files": [str(item) for item in job_payload.get("new_files", []) or []],
        "text_file_content_refs": {
            str(key): str(value)
            for key, value in dict(job_payload.get("text_file_content_refs", {}) or {}).items()
            if str(key).strip() and str(value).strip()
        },
        "upload_batch_summary": {
            **upload_batch_summary,
            "material_event_status": "processing",
            "status": "processing",
            "stage": initial_stage,
        },
    }


def _build_graph_enrichment_job_payload(parse_result: dict) -> dict:
    """Serialize the parse-stage result into one graph-stage job payload."""
    deferred_parse_result = dict(parse_result or {})
    deferred_parse_result["defer_upload_batch_completion"] = True
    return {
        "parse_result": deferred_parse_result,
    }


def _run_upload_parse_job(job_payload: dict, *, enqueue_graph_job: bool = True) -> dict | None:
    """Execute upload parse out of band, persist progress, then optionally enqueue graph enrichment."""
    base_state = _build_base_upload_state(job_payload, initial_stage="ocr_running")
    current_case_id = int(base_state.get("current_case_id", 0) or 0)
    current_entity_id = int(base_state.get("current_entity_id", 0) or 0)
    current_entity_name = str(base_state.get("current_entity_name", "") or "")
    doc_category = str(base_state.get("doc_category", "") or "")
    batch_name = str(base_state.get("batch_name", "") or "")
    upload_batch_id = str(base_state.get("upload_batch_id", "") or "")
    operator_id = str(base_state.get("operator_id", "") or "")
    operator_name = str(base_state.get("operator_name", "") or "")
    uploaded_files = list(base_state.get("uploaded_files", []) or [])
    duplicate_files = list(base_state.get("duplicate_files", []) or [])
    suspected_mismatch_files = list(base_state.get("suspected_mismatch_files", []) or [])
    new_files = list(base_state.get("new_files", []) or [])
    text_file_content_refs = dict(base_state.get("text_file_content_refs", {}) or {})
    current_stage = "ocr_running"

    mark_upload_ingest_progress(
        case_id=current_case_id,
        entity_id=current_entity_id,
        batch_name=batch_name,
        doc_category=doc_category,
        operator_id=operator_id,
        operator_name=operator_name,
        upload_batch_id=upload_batch_id,
        status="processing",
        stage=current_stage,
        file_count=len(uploaded_files),
        new_file_count=len(new_files),
        duplicate_file_count=len(duplicate_files),
        suspected_mismatch_file_count=len(suspected_mismatch_files),
        duplicate_files=duplicate_files,
        suspected_mismatch_files=suspected_mismatch_files,
        new_files=new_files,
        text_file_content_refs=text_file_content_refs,
    )
    try:
        parse_result = upload_parse_graph.invoke(base_state)
    except Exception as exc:
        error_payload = _build_upload_error(
            stage=current_stage,
            error_code="INGEST_PARSE_FAILED",
            message=str(exc),
            upload_batch_id=upload_batch_id,
        )
        mark_upload_ingest_progress(
            case_id=current_case_id,
            entity_id=current_entity_id,
            batch_name=batch_name,
            doc_category=doc_category,
            operator_id=operator_id,
            operator_name=operator_name,
            upload_batch_id=upload_batch_id,
            status="failed",
            stage=current_stage,
            file_count=len(uploaded_files),
            new_file_count=len(new_files),
            duplicate_file_count=len(duplicate_files),
            suspected_mismatch_file_count=len(suspected_mismatch_files),
            duplicate_files=duplicate_files,
            suspected_mismatch_files=suspected_mismatch_files,
            new_files=new_files,
            text_file_content_refs=text_file_content_refs,
            error_payload=error_payload,
            error_message=str(exc),
        )
        LOGGER.exception("files_upload_failed stage=%s upload_batch_id=%s", current_stage, upload_batch_id)
        return None

    current_stage = "parse_completed"
    parse_case_id = int(parse_result.get("current_case_id", current_case_id) or 0)
    parse_entity_id = int(parse_result.get("current_entity_id", current_entity_id) or 0)
    parse_batch_name = str(parse_result.get("batch_name", batch_name) or batch_name)
    parse_doc_category = str(parse_result.get("doc_category", doc_category) or doc_category)
    parse_operator_id = str(parse_result.get("operator_id", operator_id) or operator_id)
    parse_operator_name = str(parse_result.get("operator_name", operator_name) or operator_name)
    parse_upload_batch_id = str(parse_result.get("upload_batch_id", upload_batch_id) or upload_batch_id)
    parse_duplicate_files = parse_result.get("duplicate_files", duplicate_files) or []
    parse_mismatch_files = parse_result.get("suspected_mismatch_files", suspected_mismatch_files) or []
    parse_new_files = parse_result.get("new_files", new_files) or []
    parse_categories = parse_result.get("categories_found", [])
    parse_recognized_categories = parse_result.get("recognized_categories", parse_categories)
    parse_summary = str(parse_result.get("parse_summary", "") or "")
    parse_records_inserted = int(parse_result.get("records_inserted", 0) or 0)
    ingest_payload_ref = str(parse_result.get("ingest_payload_ref", "") or "")
    aggregated_text_ref = str(parse_result.get("aggregated_text_ref", "") or "")
    parse_document_result_ref = str(parse_result.get("parse_document_result_ref", "") or "")

    mark_upload_ingest_progress(
        case_id=parse_case_id,
        entity_id=parse_entity_id,
        batch_name=parse_batch_name,
        doc_category=parse_doc_category,
        operator_id=parse_operator_id,
        operator_name=parse_operator_name,
        upload_batch_id=parse_upload_batch_id,
        status="processing",
        stage=current_stage,
        file_count=len(uploaded_files),
        new_file_count=len(parse_new_files),
        duplicate_file_count=len(parse_duplicate_files),
        suspected_mismatch_file_count=len(parse_mismatch_files),
        records_inserted=parse_records_inserted,
        duplicate_files=parse_duplicate_files,
        suspected_mismatch_files=parse_mismatch_files,
        new_files=parse_new_files,
        text_file_content_refs=text_file_content_refs,
        categories_found=parse_categories,
        recognized_categories=parse_recognized_categories,
        parse_summary=parse_summary,
        ingest_payload_ref=ingest_payload_ref,
        aggregated_text_ref=aggregated_text_ref,
        parse_document_result_ref=parse_document_result_ref,
    )
    if not enqueue_graph_job:
        return parse_result

    graph_job_payload = _build_graph_enrichment_job_payload(parse_result)
    try:
        _enqueue_graph_enrichment_job(graph_job_payload)
    except Exception as exc:
        error_payload = _build_upload_error(
            stage="parse_completed",
            error_code="GRAPH_JOB_ENQUEUE_FAILED",
            message=str(exc),
            upload_batch_id=parse_upload_batch_id,
        )
        mark_upload_ingest_progress(
            case_id=parse_case_id,
            entity_id=parse_entity_id,
            batch_name=parse_batch_name,
            doc_category=parse_doc_category,
            operator_id=parse_operator_id,
            operator_name=parse_operator_name,
            upload_batch_id=parse_upload_batch_id,
            status="failed",
            stage="parse_completed",
            file_count=len(uploaded_files),
            new_file_count=len(parse_new_files),
            duplicate_file_count=len(parse_duplicate_files),
            suspected_mismatch_file_count=len(parse_mismatch_files),
            records_inserted=parse_records_inserted,
            duplicate_files=parse_duplicate_files,
            suspected_mismatch_files=parse_mismatch_files,
            new_files=parse_new_files,
            text_file_content_refs=text_file_content_refs,
            categories_found=parse_categories,
            recognized_categories=parse_recognized_categories,
            parse_summary=parse_summary,
            ingest_payload_ref=ingest_payload_ref,
            aggregated_text_ref=aggregated_text_ref,
            parse_document_result_ref=parse_document_result_ref,
            error_payload=error_payload,
            error_message=str(exc),
        )
        LOGGER.exception("files_upload_failed stage=graph_enqueue upload_batch_id=%s", parse_upload_batch_id)
        return None
    return parse_result


def _run_graph_enrichment_job(job_payload: dict) -> None:
    """Execute graph enrichment from a persisted parse-stage result."""
    parse_result = dict(job_payload.get("parse_result", {}) or {})
    current_case_id = int(parse_result.get("current_case_id", 0) or 0)
    current_entity_id = int(parse_result.get("current_entity_id", 0) or 0)
    current_entity_name = str(parse_result.get("current_entity_name", "") or "")
    doc_category = str(parse_result.get("doc_category", "") or "")
    batch_name = str(parse_result.get("batch_name", "") or "")
    upload_batch_id = str(parse_result.get("upload_batch_id", "") or "")
    operator_id = str(parse_result.get("operator_id", "") or "")
    operator_name = str(parse_result.get("operator_name", "") or "")
    uploaded_files = [dict(item) for item in parse_result.get("uploaded_files", []) if isinstance(item, dict)]
    duplicate_files = [str(item) for item in parse_result.get("duplicate_files", []) or []]
    suspected_mismatch_files = [str(item) for item in parse_result.get("suspected_mismatch_files", []) or []]
    new_files = [str(item) for item in parse_result.get("new_files", []) or []]
    categories_found = parse_result.get("categories_found", [])
    recognized_categories = parse_result.get("recognized_categories", categories_found)
    parse_summary = str(parse_result.get("parse_summary", "") or "")
    records_inserted = int(parse_result.get("records_inserted", 0) or 0)
    text_file_content_refs = {
        str(key): str(value)
        for key, value in dict(parse_result.get("text_file_content_refs", {}) or {}).items()
        if str(key).strip() and str(value).strip()
    }
    ingest_payload_ref = str(parse_result.get("ingest_payload_ref", "") or "")
    aggregated_text_ref = str(parse_result.get("aggregated_text_ref", "") or "")
    parse_document_result_ref = str(parse_result.get("parse_document_result_ref", "") or "")

    current_stage = "graph_running"
    mark_upload_ingest_progress(
        case_id=current_case_id,
        entity_id=current_entity_id,
        batch_name=batch_name,
        doc_category=doc_category,
        operator_id=operator_id,
        operator_name=operator_name,
        upload_batch_id=upload_batch_id,
        status="processing",
        stage=current_stage,
        file_count=len(uploaded_files),
        new_file_count=len(new_files),
        duplicate_file_count=len(duplicate_files),
        suspected_mismatch_file_count=len(suspected_mismatch_files),
        records_inserted=records_inserted,
        duplicate_files=duplicate_files,
        suspected_mismatch_files=suspected_mismatch_files,
        new_files=new_files,
        text_file_content_refs=text_file_content_refs,
        categories_found=categories_found,
        recognized_categories=recognized_categories,
        parse_summary=parse_summary,
        ingest_payload_ref=ingest_payload_ref,
        aggregated_text_ref=aggregated_text_ref,
        parse_document_result_ref=parse_document_result_ref,
    )
    try:
        result = knowledge_graph_graph.invoke(parse_result)
    except Exception as exc:
        error_payload = _build_upload_error(
            stage=current_stage,
            error_code="INGEST_GRAPH_FAILED",
            message=str(exc),
            upload_batch_id=upload_batch_id,
        )
        mark_upload_ingest_progress(
            case_id=current_case_id,
            entity_id=current_entity_id,
            batch_name=batch_name,
            doc_category=doc_category,
            operator_id=operator_id,
            operator_name=operator_name,
            upload_batch_id=upload_batch_id,
            status="failed",
            stage=current_stage,
            file_count=len(uploaded_files),
            new_file_count=len(new_files),
            duplicate_file_count=len(duplicate_files),
            suspected_mismatch_file_count=len(suspected_mismatch_files),
            records_inserted=records_inserted,
            duplicate_files=duplicate_files,
            suspected_mismatch_files=suspected_mismatch_files,
            new_files=new_files,
            text_file_content_refs=text_file_content_refs,
            categories_found=categories_found,
            recognized_categories=recognized_categories,
            parse_summary=parse_summary,
            ingest_payload_ref=ingest_payload_ref,
            aggregated_text_ref=aggregated_text_ref,
            parse_document_result_ref=parse_document_result_ref,
            error_payload=error_payload,
            error_message=str(exc),
        )
        LOGGER.exception("files_upload_failed stage=%s upload_batch_id=%s", current_stage, upload_batch_id)
        return

    aggregated_text = resolve_aggregated_text(result)
    change_stats = _build_reconciliation_change_stats(result.get("reconciliation_items", []))
    response_case_id = int(result.get("current_case_id", current_case_id) or 0)
    response_batch_id = str(result.get("upload_batch_id", upload_batch_id) or upload_batch_id)

    LOGGER.info(
        "files_upload_completed entity=%s records_inserted=%s categories=%s doc_category=%s aggregated_text_chars=%s upload_batch_id=%s",
        result.get("current_entity_name", current_entity_name),
        result.get("records_inserted", 0),
        result.get("categories_found", [])[:10],
        doc_category,
        len(aggregated_text),
        response_batch_id,
    )
    mark_upload_ingest_progress(
        case_id=response_case_id,
        entity_id=int(result.get("current_entity_id", current_entity_id) or 0),
        batch_name=result.get("batch_name", batch_name),
        doc_category=result.get("doc_category", doc_category),
        operator_id=result.get("operator_id", operator_id),
        operator_name=result.get("operator_name", operator_name),
        upload_batch_id=response_batch_id,
        status="completed",
        stage="completed",
        file_count=len(uploaded_files),
        new_file_count=len(result.get("new_files", new_files) or []),
        duplicate_file_count=len(result.get("duplicate_files", duplicate_files) or []),
        suspected_mismatch_file_count=len(result.get("suspected_mismatch_files", suspected_mismatch_files) or []),
        records_inserted=int(result.get("records_inserted", 0) or 0),
        duplicate_files=result.get("duplicate_files", duplicate_files) or [],
        suspected_mismatch_files=result.get("suspected_mismatch_files", suspected_mismatch_files) or [],
        new_files=result.get("new_files", new_files) or [],
        text_file_content_refs=text_file_content_refs,
        categories_found=result.get("categories_found", []),
        recognized_categories=result.get("recognized_categories", result.get("categories_found", [])),
        parse_summary=result.get("parse_summary", ""),
        has_conclusion_changes=change_stats["has_conclusion_changes"],
        reconciliation_item_count=change_stats["reconciliation_item_count"],
        add_item_count=change_stats["add_item_count"],
        override_item_count=change_stats["override_item_count"],
        change_summary=change_stats["change_summary"],
        unresolved_relation_count=len(result.get("unresolved_relations", []) or []),
        unresolved_claim_count=len(result.get("unresolved_claims", []) or []),
        ingest_payload_ref=ingest_payload_ref or str(result.get("ingest_payload_ref", "") or ""),
        aggregated_text_ref=aggregated_text_ref or str(result.get("aggregated_text_ref", "") or ""),
        parse_document_result_ref=parse_document_result_ref or str(result.get("parse_document_result_ref", "") or ""),
        chunk_batch_ref=str(result.get("chunk_batch_ref", "") or ""),
        kg_subgraph_ref=str(result.get("kg_subgraph_ref", "") or ""),
    )


def _build_material_event_id(upload_batch_id: str) -> str:
    return build_material_event_id(upload_batch_id)


def _extract_validation_file_list(payload: dict, key: str) -> list[str]:
    value = payload.get(key, []) if isinstance(payload, dict) else []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _dedupe_names(names: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = str(name or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _build_reconciliation_change_stats(items: list[dict]) -> dict:
    normalized_items = [dict(item) for item in items if isinstance(item, dict)]
    add_count = 0
    override_count = 0
    for item in normalized_items:
        action = str(item.get("action", "") or "").upper()
        if action == "OVERRIDE":
            override_count += 1
        elif action == "ADD":
            add_count += 1
    total = add_count + override_count
    if total <= 0:
        summary = "本次补件未引发已落库结论变化。"
    elif add_count > 0 and override_count > 0:
        summary = f"本次补件新增{add_count}条结论，并替代{override_count}条旧结论。"
    elif override_count > 0:
        summary = f"本次补件替代了{override_count}条旧结论。"
    else:
        summary = f"本次补件新增了{add_count}条可追踪结论。"
    return {
        "has_conclusion_changes": total > 0,
        "reconciliation_item_count": total,
        "add_item_count": add_count,
        "override_item_count": override_count,
        "change_summary": summary,
    }


def _resolve_retry_stage(*, batch: dict, event: dict, requested_stage: str) -> str:
    """Resolve which retry stage should be enqueued for one failed upload batch."""
    normalized_stage = str(requested_stage or "auto").strip().lower() or "auto"
    if normalized_stage not in {"auto", "parse", "graph"}:
        raise HTTPException(status_code=400, detail="stage 只支持 auto、parse、graph。")

    batch_status = str(batch.get("status", "") or "").strip().lower()
    event_status = str(event.get("status", "") or "").strip().lower()
    if (event_status or batch_status) != "failed":
        raise ValueError("仅支持对失败批次执行重试。")

    metadata = dict(batch.get("metadata", {}) or {})
    event_payload = dict(event.get("event_payload", {}) or {})
    last_stage = str(event_payload.get("stage", "") or metadata.get("stage", "") or "").strip().lower()
    if normalized_stage != "auto":
        return normalized_stage
    if last_stage in {"parse_completed", "graph_running"}:
        return "graph"
    return "parse"


def _build_retry_parse_job_payload(*, batch: dict, event: dict) -> dict:
    """Rebuild the parse-stage job payload from persisted upload-batch state."""
    metadata = dict(batch.get("metadata", {}) or {})
    uploaded_files = _build_retry_uploaded_files(batch)
    _validate_retry_uploaded_files_have_content(uploaded_files, retry_stage="parse")
    entity_resolution = resolve_engagement_entity(
        case_id=int(batch.get("case_id", 0) or 0),
        entity_id=int(batch.get("entity_id", 0) or 0),
    )
    return _build_upload_ingest_job_payload(
        current_case_id=int(batch.get("case_id", 0) or 0),
        current_entity_id=entity_resolution.entity_id,
        current_entity_name=entity_resolution.entity_name,
        doc_category=str(batch.get("doc_category", "") or ""),
        batch_name=str(batch.get("batch_name", "") or ""),
        upload_batch_id=str(batch.get("upload_batch_id", "") or ""),
        operator_id=str(batch.get("operator_id", "") or ""),
        operator_name=str(batch.get("operator_name", "") or ""),
        uploaded_files=uploaded_files,
        doc_category_validation={"ok": True},
        duplicate_files=[str(item) for item in metadata.get("duplicate_files", []) or []],
        suspected_mismatch_files=[str(item) for item in metadata.get("suspected_mismatch_files", []) or []],
        new_files=[str(item) for item in metadata.get("new_files", []) or []],
        upload_batch_summary={
            "material_event_id": str(metadata.get("material_event_id", "") or _build_material_event_id(str(batch.get("upload_batch_id", "") or ""))),
            "material_event_type": str(metadata.get("material_event_type", "") or "supplement_upload"),
            "material_event_status": "processing",
            "upload_batch_id": str(batch.get("upload_batch_id", "") or ""),
            "batch_name": str(batch.get("batch_name", "") or ""),
            "doc_category": str(batch.get("doc_category", "") or ""),
            "operator_id": str(batch.get("operator_id", "") or ""),
            "operator_name": str(batch.get("operator_name", "") or ""),
            "file_count": int(batch.get("file_count", 0) or len(uploaded_files)),
            "new_file_count": int(batch.get("new_file_count", 0) or 0),
            "duplicate_file_count": int(batch.get("duplicate_file_count", 0) or 0),
            "suspected_mismatch_file_count": int(batch.get("suspected_mismatch_file_count", 0) or 0),
            "status": "processing",
            "stage": "retry_parse_queued",
        },
    )


def _build_retry_graph_job_payload(*, batch: dict, event: dict) -> dict:
    """Rebuild the graph-stage job payload from persisted upload-batch/material-event state."""
    metadata = dict(batch.get("metadata", {}) or {})
    event_payload = dict(event.get("event_payload", {}) or {})
    uploaded_files = _build_retry_uploaded_files(batch)
    _validate_retry_uploaded_files_have_content(uploaded_files, retry_stage="graph")
    entity_resolution = resolve_engagement_entity(
        case_id=int(batch.get("case_id", 0) or 0),
        entity_id=int(batch.get("entity_id", 0) or 0),
    )
    ingest_payload_ref = str(event_payload.get("ingest_payload_ref", "") or metadata.get("ingest_payload_ref", "") or "").strip()
    aggregated_text_ref = str(event_payload.get("aggregated_text_ref", "") or metadata.get("aggregated_text_ref", "") or "").strip()
    parse_document_result_ref = str(
        event_payload.get("parse_document_result_ref", "") or metadata.get("parse_document_result_ref", "") or ""
    ).strip()
    if not ingest_payload_ref:
        raise ValueError("缺少 ingest_payload_ref，当前批次无法直接重试 graph 阶段。")
    return _build_graph_enrichment_job_payload(
        {
            "current_case_id": int(batch.get("case_id", 0) or 0),
            "current_entity_id": entity_resolution.entity_id,
            "current_entity_name": entity_resolution.entity_name,
            "doc_category": str(batch.get("doc_category", "") or ""),
            "batch_name": str(batch.get("batch_name", "") or ""),
            "upload_batch_id": str(batch.get("upload_batch_id", "") or ""),
            "operator_id": str(batch.get("operator_id", "") or ""),
            "operator_name": str(batch.get("operator_name", "") or ""),
            "uploaded_files": uploaded_files,
            "duplicate_files": [str(item) for item in metadata.get("duplicate_files", []) or []],
            "suspected_mismatch_files": [str(item) for item in metadata.get("suspected_mismatch_files", []) or []],
            "new_files": [str(item) for item in metadata.get("new_files", []) or []],
            "text_file_content_refs": {
                str(key): str(value)
                for key, value in dict(
                    event_payload.get("text_file_content_refs", {}) or metadata.get("text_file_content_refs", {}) or {}
                ).items()
                if str(key).strip() and str(value).strip()
            },
            "categories_found": [str(item) for item in metadata.get("categories_found", []) or []],
            "recognized_categories": [str(item) for item in metadata.get("recognized_categories", []) or []],
            "parse_summary": str(metadata.get("parse_summary", "") or event_payload.get("parse_summary", "") or ""),
            "records_inserted": int(batch.get("records_inserted", 0) or 0),
            "ingest_payload_ref": ingest_payload_ref,
            "aggregated_text_ref": aggregated_text_ref,
            "parse_document_result_ref": parse_document_result_ref,
            "upload_batch_summary": {
                **metadata,
                "upload_batch_id": str(batch.get("upload_batch_id", "") or ""),
            },
        }
    )


def _build_retry_uploaded_files(batch: dict) -> list[FileItem]:
    """Reconstruct normalized uploaded files from persisted source-upload-batch rows."""
    metadata = dict(batch.get("metadata", {}) or {})
    content_ref_lookup = {
        str(key): str(value)
        for key, value in dict(metadata.get("text_file_content_refs", {}) or {}).items()
        if str(key).strip() and str(value).strip()
    }
    uploaded_files: list[FileItem] = []
    for item in batch.get("files", []) or []:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file_name", "") or "uploaded-file")
        extension = Path(file_name).suffix.lower()
        storage_ref = str(item.get("storage_ref", "") or "")
        file_hash = str(item.get("file_sha256", "") or "")
        content_ref = content_ref_lookup.get(file_hash, "")
        content = ""
        if content_ref:
            payload = get_heavy_payload(content_ref)
            if isinstance(payload, dict):
                content = str(payload.get("content", "") or "")
        uploaded_files.append(
            {
                "name": file_name,
                "url": resolve_minio_reference_url(storage_ref),
                "type": str(item.get("file_type", "document") or "document"),
                "extension": extension,
                "content_type": str(item.get("content_type", "") or ""),
                "content": content,
                "doc_category": str(batch.get("doc_category", "") or ""),
                "upload_batch_id": str(batch.get("upload_batch_id", "") or ""),
                "file_hash": file_hash,
                "file_size": int(item.get("file_size_bytes", 0) or 0),
                "content_ref": content_ref,
                "duplicate_of": str(item.get("duplicate_of", "") or ""),
                "storage_ref": storage_ref,
                "storage_provider": str(item.get("storage_provider", "") or ""),
                "storage_bucket": str(item.get("storage_bucket", "") or ""),
                "storage_key": str(item.get("storage_key", "") or ""),
                "storage_etag": "",
                "storage_version": "",
            }
        )
    if not uploaded_files:
        raise ValueError("当前批次没有可用于重试的文件记录。")
    return uploaded_files


def _build_text_file_content_refs(uploaded_files: list[FileItem]) -> dict[str, str]:
    """Persist text-like file contents per file so retries can restore them later."""
    refs: dict[str, str] = {}
    for item in uploaded_files:
        extension = str(item.get("extension", "") or "").lower()
        file_hash = str(item.get("file_hash", "") or "").strip()
        content = str(item.get("content", "") or "")
        if extension not in (TEXT_EXTENSIONS | CSV_EXTENSIONS | MARKDOWN_EXTENSIONS):
            continue
        if not file_hash or not content.strip():
            continue
        refs[file_hash] = put_heavy_payload(
            "text_file_content",
            {
                "file_hash": file_hash,
                "file_name": str(item.get("name", "") or ""),
                "content": content,
            },
        )
    return refs


def _validate_retry_uploaded_files_have_content(uploaded_files: list[FileItem], *, retry_stage: str) -> None:
    """Ensure text-like uploads can be reconstructed before retrying."""
    missing_files = [
        str(item.get("name", "uploaded-file") or "uploaded-file")
        for item in uploaded_files
        if str(item.get("extension", "") or "").lower() in (TEXT_EXTENSIONS | CSV_EXTENSIONS | MARKDOWN_EXTENSIONS)
        and not str(item.get("content", "") or "").strip()
    ]
    if missing_files:
        raise ValueError(
            f"{retry_stage} 重试缺少文本文件持久化内容：{', '.join(missing_files[:5])}"
        )


def _decorate_upload_batch_response(batch: dict) -> dict:
    metadata = dict(batch.get("metadata", {}) or {}) if isinstance(batch, dict) else {}
    
    # Convert datetime objects to ISO format strings
    def _datetime_to_str(dt):
        if dt is None:
            return None
        if isinstance(dt, str):
            return dt
        return dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)
    
    # Process files list to convert datetime fields
    files = batch.get("files", []) or []
    processed_files = []
    for file_item in files:
        if isinstance(file_item, dict):
            processed_file = dict(file_item)
            processed_file["created_at"] = _datetime_to_str(file_item.get("created_at"))
            processed_files.append(processed_file)
        else:
            processed_files.append(file_item)
    
    return {
        **dict(batch or {}),
        "has_conclusion_changes": bool(metadata.get("has_conclusion_changes", False)),
        "reconciliation_item_count": int(metadata.get("reconciliation_item_count", 0) or 0),
        "add_item_count": int(metadata.get("add_item_count", 0) or 0),
        "override_item_count": int(metadata.get("override_item_count", 0) or 0),
        "change_summary": str(metadata.get("change_summary", "") or ""),
        "created_at": _datetime_to_str(batch.get("created_at")),
        "updated_at": _datetime_to_str(batch.get("updated_at")),
        "files": processed_files,
    }


def _decorate_material_event_response(event: dict) -> dict:
    payload = dict(event.get("event_payload", {}) or {}) if isinstance(event, dict) else {}
    
    # Convert datetime objects to ISO format strings
    def _datetime_to_str(dt):
        if dt is None:
            return None
        if isinstance(dt, str):
            return dt
        return dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)
    
    return {
        **dict(event or {}),
        "stage": str(payload.get("stage", "") or ""),
        "has_conclusion_changes": bool(payload.get("has_conclusion_changes", False)),
        "reconciliation_item_count": int(payload.get("reconciliation_item_count", 0) or 0),
        "add_item_count": int(payload.get("add_item_count", 0) or 0),
        "override_item_count": int(payload.get("override_item_count", 0) or 0),
        "change_summary": str(payload.get("change_summary", "") or ""),
        "started_at": _datetime_to_str(event.get("started_at")),
        "completed_at": _datetime_to_str(event.get("completed_at")),
        "failed_at": _datetime_to_str(event.get("failed_at")),
        "created_at": _datetime_to_str(event.get("created_at")),
        "updated_at": _datetime_to_str(event.get("updated_at")),
    }


def _resolve_doc_category_validation(*, current_case_id: int, doc_category: str, file_names: list[str]) -> dict:
    from ai_hunter.annual_audit.document_repository import validate_doc_category

    settings = get_settings()
    if not doc_category:
        return {
            "ok": False,
            "suspected_mismatch": True,
            "suspected_duplicate": False,
            "message": "缺少 doc_category；当前约定同一批次只允许上传一种审计资料类别。",
        }
    payload = {
        "case_id": current_case_id,
        "doc_category": doc_category,
        "file_names": file_names,
        "text_preview": "",
    }
    return validate_doc_category(payload, settings=settings)


def _resolve_case_doc_category_status(case_id: int) -> dict:
    from ai_hunter.annual_audit.document_repository import get_case_doc_categories

    if int(case_id or 0) <= 0:
        return {"case_id": int(case_id or 0), "categories": [], "missing_categories": []}
    settings = get_settings()
    return get_case_doc_categories(int(case_id), settings=settings)


def _build_upload_error(
    *,
    stage: str,
    error_code: str,
    message: str,
    upload_batch_id: str,
    retryable: bool = True,
) -> dict:
    return {
        "error_code": error_code,
        "error_message": message or "上传摄入失败。",
        "retryable": retryable,
        "stage": stage,
        "upload_batch_id": upload_batch_id,
        "material_event_id": _build_material_event_id(upload_batch_id),
    }


def _persist_failed_upload_batch(
    *,
    case_id: int,
    entity_id: int,
    batch_name: str,
    doc_category: str,
    operator_id: str,
    operator_name: str,
    upload_batch_id: str,
    file_count: int,
    error_payload: dict,
) -> None:
    if int(case_id or 0) <= 0 or not upload_batch_id:
        return
    try:
        get_kg_service().upsert_source_upload_batch(
            {
                "upload_batch_id": upload_batch_id,
                "case_id": case_id,
                "entity_id": entity_id,
                "batch_name": batch_name,
                "doc_category": doc_category,
                "operator_id": operator_id,
                "operator_name": operator_name,
                "status": "failed",
                "file_count": file_count,
                "records_inserted": 0,
                "metadata": {
                    "material_event_id": _build_material_event_id(upload_batch_id),
                    "material_event_type": "supplement_upload",
                    "material_event_status": "failed",
                    "error": error_payload,
                },
            }
        )
    except Exception:
        LOGGER.exception("persist_failed_upload_batch_failed upload_batch_id=%s", upload_batch_id)


def _upsert_material_event_safe(
    *,
    case_id: int,
    entity_id: int,
    batch_name: str,
    doc_category: str,
    operator_id: str,
    operator_name: str,
    upload_batch_id: str,
    status: str,
    file_count: int,
    records_inserted: int,
    event_payload: dict,
    error_message: str = "",
) -> None:
    if int(case_id or 0) <= 0 or not upload_batch_id:
        return
    try:
        get_kg_service().upsert_material_event(
            {
                "material_event_id": _build_material_event_id(upload_batch_id),
                "case_id": int(case_id or 0),
                "entity_id": int(entity_id or 0),
                "upload_batch_id": upload_batch_id,
                "event_type": "supplement_upload",
                "status": status,
                "batch_name": batch_name,
                "doc_category": doc_category,
                "operator_id": operator_id,
                "operator_name": operator_name,
                "file_count": int(file_count or 0),
                "records_inserted": int(records_inserted or 0),
                "event_payload": event_payload or {},
                "error_message": error_message,
            }
        )
    except Exception:
        LOGGER.exception("upsert_material_event_failed upload_batch_id=%s status=%s", upload_batch_id, status)


def _upsert_source_upload_batch_completion_safe(
    *,
    case_id: int,
    entity_id: int,
    batch_name: str,
    doc_category: str,
    operator_id: str,
    operator_name: str,
    upload_batch_id: str,
    file_count: int,
    new_file_count: int,
    duplicate_file_count: int,
    suspected_mismatch_file_count: int,
    records_inserted: int,
    metadata: dict,
) -> None:
    _upsert_source_upload_batch_safe(
        case_id=case_id,
        entity_id=entity_id,
        batch_name=batch_name,
        doc_category=doc_category,
        operator_id=operator_id,
        operator_name=operator_name,
        upload_batch_id=upload_batch_id,
        status="completed",
        file_count=file_count,
        new_file_count=new_file_count,
        duplicate_file_count=duplicate_file_count,
        suspected_mismatch_file_count=suspected_mismatch_file_count,
        records_inserted=records_inserted,
        metadata=metadata,
    )


def _upsert_source_upload_batch_safe(
    *,
    case_id: int,
    entity_id: int,
    batch_name: str,
    doc_category: str,
    operator_id: str,
    operator_name: str,
    upload_batch_id: str,
    status: str,
    file_count: int,
    new_file_count: int,
    duplicate_file_count: int,
    suspected_mismatch_file_count: int,
    records_inserted: int,
    metadata: dict,
) -> None:
    if int(case_id or 0) <= 0 or not upload_batch_id:
        return
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
                "metadata": metadata or {},
            }
        )
    except Exception:
        LOGGER.exception(
            "upsert_source_upload_batch_failed upload_batch_id=%s status=%s",
            upload_batch_id,
            status,
        )


def _is_unsupported_doc_category(validation_payload: dict) -> bool:
    if validation_payload.get("ok") is not False:
        return False
    message = str(validation_payload.get("message", "") or "")
    return "未知卷宗类别" in message or "不支持的文档类型" in message
