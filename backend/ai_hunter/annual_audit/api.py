"""Annual-audit HTTP API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ai_hunter.app.settings import get_settings

from . import document_repository as documents
from . import engagement_repository as engagements
from . import task_repository as tasks
from .analysis_service import data_readiness, run_cash_and_bank, run_sales_receivables
from .report_service import generate_annual_report_draft
from .storage import AnnualAuditStorageError, mysql_connection


router = APIRouter()


class CreateEngagementRequest(BaseModel):
    case_name: str = Field(min_length=1, max_length=255)
    case_type: str = "年度财务报表审计"
    entity_name: str = Field(min_length=1, max_length=255)
    entity_uscc: str | None = None
    fiscal_year: int | None = Field(default=None, ge=2000, le=2200)
    company_id: str | None = None
    owner_id: str | None = None
    created_by: str | None = None


class FullContextRequest(BaseModel):
    case_id: int = Field(gt=0)
    recompute: bool = False
    mining_transfer_prices: dict[str, Any] | None = None


class AnnualAnalysisRequest(BaseModel):
    case_id: int = Field(gt=0)
    recompute: bool = False


class CashAnalysisRequest(AnnualAnalysisRequest):
    large_amount_threshold: float = Field(default=1_000_000, gt=0)


class AnnualReportRequest(AnnualAnalysisRequest):
    corrections: list[str] = Field(default_factory=list)
    created_by: str = "ai_agent"


class ValidateDocCategoryRequest(BaseModel):
    case_id: int = Field(gt=0)
    doc_category: str = Field(min_length=1, max_length=128)
    file_names: list[str] = Field(default_factory=list)
    text_preview: str | None = None


class TaskBatchRequest(BaseModel):
    case_id: int = Field(gt=0)
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class ManageTaskRequest(BaseModel):
    case_id: int = Field(gt=0)
    action: str = Field(min_length=1, max_length=32)
    filter_status: str | None = None
    task_id: int | None = Field(default=None, gt=0)
    new_status: str | None = None
    completion_note: str | None = None
    assigned_to: str | None = None


def _storage_http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"年审独立存储不可用：{exc}")


@router.get("/health", tags=["年审基础设施"], summary="年审独立存储健康检查")
def health() -> dict[str, str]:
    try:
        with mysql_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc
    settings = get_settings()
    return {
        "status": "ok",
        "db": "connected",
        "domain": "annual_audit",
        "llm_provider": settings.resolve_provider("agent"),
    }


@router.get("/api/cases", tags=["年审项目"], summary="按原案件契约查询年审项目")
def list_cases(
    keyword: str | None = None,
    case_type: str | None = None,
    status: str | None = None,
    company_id: str | None = None,
    user_id: str | None = None,
    is_company_admin: bool = False,
    is_super_admin: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return engagements.list_engagements(
            keyword=keyword,
            case_type=case_type,
            status=status,
            company_id=company_id,
            user_id=user_id,
            is_company_admin=is_company_admin,
            is_super_admin=is_super_admin,
            page=page,
            page_size=page_size,
        )
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/ingest/case", tags=["年审项目"], summary="按原建案契约创建年审项目")
def create_case(request: CreateEngagementRequest) -> dict[str, Any]:
    try:
        return engagements.create_engagement(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.get(
    "/api/case/{case_id}/profile",
    tags=["年审项目"],
    summary="按原案件画像契约查询年审项目画像",
)
def get_case_profile(case_id: int) -> dict[str, Any]:
    try:
        return engagements.get_engagement_profile(case_id)
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.get("/api/ingest/doc-categories", tags=["年审资料"])
def list_doc_categories() -> dict[str, Any]:
    try:
        return documents.list_doc_categories()
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.get("/api/case/{case_id}/doc-categories", tags=["年审资料"])
def get_case_doc_categories(case_id: int) -> dict[str, Any]:
    try:
        return documents.get_case_doc_categories(case_id)
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/ingest/validate-doc-category", tags=["年审资料"])
def validate_doc_category(request: ValidateDocCategoryRequest) -> dict[str, Any]:
    try:
        return documents.validate_doc_category(request.model_dump())
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/tasks/create-batch", tags=["年审任务"])
def create_task_batch(request: TaskBatchRequest) -> dict[str, Any]:
    try:
        return tasks.create_task_batch(request.case_id, request.tasks)
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/tasks/manage", tags=["年审任务"])
def manage_tasks(request: ManageTaskRequest) -> dict[str, Any]:
    try:
        return tasks.manage_tasks(request.model_dump())
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post(
    "/api/audit/get_full_context",
    tags=["年审项目"],
    summary="按原完整审计契约聚合年审上下文",
)
def get_full_context(request: FullContextRequest) -> dict[str, Any]:
    try:
        return engagements.get_full_context(request.case_id)
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/annual-audit/readiness", tags=["年审分析"])
def get_data_readiness(request: AnnualAnalysisRequest) -> dict[str, Any]:
    try:
        return data_readiness(request.case_id)
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/annual-audit/sales-receivables", tags=["年审分析"])
def analyze_sales_receivables(request: AnnualAnalysisRequest) -> dict[str, Any]:
    try:
        return run_sales_receivables(request.case_id, recompute=request.recompute)
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/annual-audit/cash-and-bank", tags=["年审分析"])
def analyze_cash_and_bank(request: CashAnalysisRequest) -> dict[str, Any]:
    from decimal import Decimal

    try:
        return run_cash_and_bank(
            request.case_id,
            large_amount_threshold=Decimal(str(request.large_amount_threshold)),
            recompute=request.recompute,
        )
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.post("/api/annual-audit/report", tags=["骞村鎶ュ憡"])
def generate_report(request: AnnualReportRequest) -> dict[str, Any]:
    """Run all deterministic annual cycles and publish versioned artifacts."""

    try:
        return generate_annual_report_draft(
            request.case_id,
            recompute=request.recompute,
            corrections=request.corrections,
            created_by=request.created_by or "ai_agent",
        )
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc


@router.get("/api/annual-audit/{case_id}/artifacts", tags=["骞村鎶ュ憡"])
def list_report_artifacts(case_id: int) -> dict[str, Any]:
    """Return the latest report/workpaper artifact references for one engagement."""

    try:
        engagements.get_engagement(case_id)
        with mysql_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, report_version, template_version, status, artifact_ref, created_at
                    FROM audit_report
                    WHERE engagement_id = %s AND report_type = 'annual_audit_draft'
                    ORDER BY report_version DESC LIMIT 1
                    """,
                    (case_id,),
                )
                report = dict(cursor.fetchone() or {})
                cursor.execute(
                    """
                    SELECT id, workpaper_code, workpaper_name, template_version,
                           workpaper_version, status, artifact_ref, created_at
                    FROM annual_workpaper
                    WHERE engagement_id = %s
                    ORDER BY workpaper_code, workpaper_version DESC
                    """,
                    (case_id,),
                )
                workpapers = [dict(row) for row in cursor.fetchall()]
        return {
            "case_id": case_id,
            "report": report,
            "workpapers": workpapers,
            "artifact_status": "published" if report.get("artifact_ref") else "not_published",
        }
    except engagements.EngagementNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnualAuditStorageError as exc:
        raise _storage_http_error(exc) from exc
