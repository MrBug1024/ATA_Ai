"""FastAPI routes for graph evidence lookup and page-anchor resolution."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..graph.schemas import (
    DemoCaseTraceValidationRequestModel,
    DemoCaseTraceValidationResponseModel,
    EvidenceItemModel,
    EvidenceResolveRequestModel,
    EvidenceResolveResponseModel,
    CaseEntityListResponse,
    GraphSubgraphRequestModel,
    GraphSubgraphResponseModel,
    PageAnchorsResponseModel,
    RelationEvidenceRequestModel,
    RelationEvidenceResponseModel,
    TraceItemModel,
)
from ..services.demo_case_trace_service import get_demo_case_trace_service
from ..services.kg_service import get_kg_service
from ..services.minio_service import resolve_minio_reference_url
from ..settings import get_settings
from ..auth.permissions import require_module
from ..auth.identity import Identity, get_current_identity
from ..auth.tenancy import require_case_access


router = APIRouter(
    tags=["graph"],
    dependencies=[Depends(require_module("graph"))],
    responses={403: {"description": "缺少 graph 模块权限或无权访问对象所属案件。"}},
)


@router.post(
    "/evidence/resolve",
    summary="按 claim 解析证据",
    description=(
        "把报告中的 citation 或 claim_id 解析为具体证据列表、主证据和首屏页锚点信息。"
        "启用鉴权后会校验案件访问权，并确保 claim/citation 属于请求中的 case_id。"
    ),
    response_model=EvidenceResolveResponseModel,
    response_description="返回 claim 对应的证据清单，以及前端证据抽屉首屏可直接使用的页锚点数据。",
)
async def resolve_evidence(
    payload: EvidenceResolveRequestModel,
    identity: Identity = Depends(get_current_identity),
) -> EvidenceResolveResponseModel:
    """Resolve one claim into concrete evidence anchors."""
    from ai_hunter.annual_audit.evidence_service import resolve_report_evidence

    require_case_access(payload.case_id, identity)
    return EvidenceResolveResponseModel.model_validate(
        resolve_report_evidence(
            engagement_id=payload.case_id,
            report_ref=payload.report_ref,
            citation_id=payload.citation_id,
            claim_id=payload.claim_id,
        )
    )


@router.post(
    "/graph/relation-evidence",
    summary="按 relation 获取证据链",
    description=(
        "按关系 ID 聚合其下 claim 与 evidence，返回前端可展示的关系证据链。"
        "启用鉴权后会校验案件访问权，并确保 relation 下的 claim 属于请求中的 case_id。"
    ),
    response_model=RelationEvidenceResponseModel,
    response_description="返回 relation 下所有 claim 的分组结果及其证据列表。",
)
async def relation_evidence(
    payload: RelationEvidenceRequestModel,
    identity: Identity = Depends(get_current_identity),
) -> RelationEvidenceResponseModel:
    """Return grouped claim traces for one relation."""
    require_case_access(payload.case_id, identity)
    kg_service = get_kg_service()
    rows = kg_service.fetch_relation_evidence(payload.relation_id, case_id=payload.case_id)
    grouped: dict[int, dict] = {}
    for row in rows:
        claim_id = int(row.get("claim_id", 0) or 0)
        item = grouped.setdefault(
            claim_id,
            {
                "citation_id": str(row.get("citation_id") or ""),
                "claim_id": claim_id,
                "claim_type": str(row.get("claim_type", "") or ""),
                "claim_text": str(row.get("claim_text", "") or ""),
                "confidence": float(row.get("confidence", 0) or 0),
                "entity_id": int(row.get("entity_id", 0) or 0),
                "evidences": [],
            },
        )
        chunk_id = str(row.get("chunk_id", "") or "")
        if not chunk_id:
            continue
        item["evidences"].append(
            EvidenceItemModel(
                chunk_id=chunk_id,
                file_id=int(row.get("file_id", 0) or 0),
                file_name=str(row.get("file_name", "") or ""),
                page_no=int(row.get("page_no", 0) or 0),
                quote_text=str(row.get("quote_text", "") or ""),
                bbox_list=row.get("bbox_list") or [],
                page_image_ref=resolve_minio_reference_url(str(row.get("page_image_ref", "") or "")),
                source_page_id=int(row.get("source_page_id", 0) or 0),
                source_file_url=resolve_minio_reference_url(str(row.get("storage_ref", "") or "")),
                content_type=str(row.get("content_type", "") or ""),
                entity_id=int(row.get("entity_id", 0) or 0),
            ).model_dump()
        )
    return RelationEvidenceResponseModel(
        case_id=payload.case_id,
        relation_id=payload.relation_id,
        trace_items=[TraceItemModel.model_validate(item) for item in grouped.values()],
    )


@router.post(
    "/graph/demo-case-trace/validate",
    summary="校验标杆案件证据回源链路",
    description="校验 citation -> claim -> evidence -> page anchor 的整条回源链路是否达到可演示状态。",
    response_model=DemoCaseTraceValidationResponseModel,
    response_description="返回逐个 citation 的回源校验结果与聚合问题摘要。",
)
async def validate_demo_case_trace_route(
    payload: DemoCaseTraceValidationRequestModel,
    identity: Identity = Depends(get_current_identity),
) -> DemoCaseTraceValidationResponseModel:
    """Validate citation -> claim -> evidence -> page-anchor readiness for demo cases."""
    require_case_access(payload.case_id, identity)
    return get_demo_case_trace_service().validate_report_trace(
        case_id=payload.case_id,
        report_ref=payload.report_ref,
        citation_ids=payload.citation_ids,
    )


@router.post(
    "/graph/subgraph",
    summary="获取实体周边子图",
    description="以指定实体为中心按层展开周边关系，返回轻量知识子图供前端可视化渲染。",
    response_model=GraphSubgraphResponseModel,
    response_description="返回中心实体周围的节点、边与统计摘要。",
)
async def graph_subgraph(
    payload: GraphSubgraphRequestModel,
    identity: Identity = Depends(get_current_identity),
) -> GraphSubgraphResponseModel:
    """Fetch a lightweight subgraph centered on one entity."""
    require_case_access(payload.case_id, identity)
    kg_service = get_kg_service()
    result = kg_service.fetch_subgraph_by_entity(
        case_id=payload.case_id,
        center_entity_id=payload.center_entity_id,
        depth=payload.depth,
        relation_types=payload.relation_types,
    )
    return GraphSubgraphResponseModel(case_id=payload.case_id, **result)


@router.get(
    "/graph/cases/{case_id}/entities",
    summary="列出案件实体（图谱中心点选择）",
    description="返回案件的实体列表及其关系连接度数（按 degree 降序），供前端 GraphModal 选择 /graph/subgraph 的中心实体。",
    response_model=CaseEntityListResponse,
)
async def list_case_entities(
    case_id: int,
    limit: int = Query(100, ge=1, le=500, description="最多返回多少个实体。"),
    _: Identity = Depends(require_case_access),
) -> dict:
    """List a case's entities with relation degree for the graph entity picker."""
    entities = get_kg_service().list_entities_by_case(case_id, limit=limit)
    return {"case_id": case_id, "entities": entities}


@router.get(
    "/files/page-anchors",
    summary="获取页内证据锚点",
    description=(
        "查询某个文件页内的证据框坐标与页图引用，供前端高亮渲染使用。"
        "启用鉴权后先从 file_id 解析所属案件并校验访问权。"
    ),
    response_model=PageAnchorsResponseModel,
    response_description="返回该页可高亮的锚点列表、页尺寸与页图地址。",
)
async def page_anchors(
    file_id: int = Query(..., description="文件 ID"),
    page_no: int = Query(..., description="页码"),
    chunk_id: str | None = Query(None, description="可选 chunk_id 过滤"),
    identity: Identity = Depends(get_current_identity),
) -> PageAnchorsResponseModel:
    """Return page-level anchors for highlighter rendering."""
    kg_service = get_kg_service()
    if get_settings().auth_enabled:
        case_id = kg_service.get_source_file_case_id(file_id)
        if case_id is None:
            raise HTTPException(status_code=404, detail="文件不存在")
        require_case_access(case_id, identity)
    rows = kg_service.fetch_page_anchors(file_id=file_id, page_no=page_no, chunk_id=chunk_id)
    if not rows:
        return PageAnchorsResponseModel(file_id=file_id, page_no=page_no, anchors=[])

    first = rows[0]
    
    def _normalize_bbox_list(bbox_list):
        """Convert bbox_list from various formats to ChunkBBoxModel list."""
        if not bbox_list:
            return []
        result = []
        for bbox in bbox_list:
            if isinstance(bbox, dict):
                # Already a dict, use as-is
                result.append(bbox)
            elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                # Convert [x, y, w, h] to {x, y, w, h}
                result.append({"x": float(bbox[0]), "y": float(bbox[1]), "w": float(bbox[2]), "h": float(bbox[3])})
            else:
                # Skip invalid bbox
                continue
        return result
    
    anchors = [
        EvidenceItemModel(
            chunk_id=str(row.get("chunk_id", "") or ""),
            file_id=file_id,
            file_name=str(row.get("file_name", "") or ""),
            page_no=page_no,
            quote_text=str(row.get("quote_text", "") or ""),
            bbox_list=_normalize_bbox_list(row.get("bbox_list") or []),
            page_image_ref=resolve_minio_reference_url(str(row.get("page_image_ref", "") or "")),
            source_page_id=int(row.get("source_page_id", 0) or 0),
            source_file_url=resolve_minio_reference_url(str(row.get("storage_ref", "") or "")),
            content_type=str(row.get("content_type", "") or ""),
        )
        for row in rows
    ]
    return PageAnchorsResponseModel(
        file_id=file_id,
        file_name=str(first.get("file_name", "") or ""),
        page_no=page_no,
        page_width=int(first.get("page_width", 0) or 0),
        page_height=int(first.get("page_height", 0) or 0),
        page_image_ref=resolve_minio_reference_url(str(first.get("page_image_ref", "") or "")),
        source_file_url=resolve_minio_reference_url(str(first.get("storage_ref", "") or "")),
        content_type=str(first.get("content_type", "") or ""),
        anchors=anchors,
    )
