"""Annual attachment jobs, normalized facts, and ticketed artifact streaming."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_hunter.annual_audit.attachments import repository
from ai_hunter.annual_audit.attachments.ticket_service import (
    ArtifactTicketError,
    issue_ticket,
    verify_ticket,
)
from ai_hunter.annual_audit.execution_service import validate_evidence_ownership
from ai_hunter.app.auth.identity import Identity
from ai_hunter.app.auth.permissions import (
    all_report_section_codes,
    require_module,
    visible_report_sections,
)
from ai_hunter.app.auth.tenancy import require_case_access
from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.app.settings import get_settings


router = APIRouter(tags=["年审附件"])
_require_report = require_module("report")
_RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_CONTROL_ROLES = frozenset(
    {"engagement_manager", "reviewer", "engagement_partner"}
)
_SIGNATORY_ROLES = frozenset({"engagement_partner"})


class CreateAttachmentJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: int = Field(gt=0)
    generation_scope: str = "all_active_template_files"
    delivery_level: str = "review_draft"
    idempotency_key: str = Field(default="", max_length=128)

    @field_validator("generation_scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if value != "all_active_template_files":
            raise ValueError("only all_active_template_files is supported")
        return value

    @field_validator("delivery_level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        if value not in {"review_draft", "final_candidate", "issued"}:
            raise ValueError("unsupported delivery_level")
        return value


class FactUpsertRequest(BaseModel):
    value: Any
    display_value: str | None = Field(default=None, max_length=4000)
    data_type: str = Field(default="string", max_length=32)
    status: str = "confirmed"
    source_kind: str = "manual_review"
    source_ref: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {"candidate", "confirmed", "conflicted", "rejected"}:
            raise ValueError("unsupported fact status")
        return value

    @field_validator("source_kind")
    @classmethod
    def validate_source_kind(cls, value: str) -> str:
        allowed = {"manual_review", "material_extraction", "correction", "calculation"}
        if value not in allowed:
            raise ValueError("unsupported source_kind")
        return value


def _case_identity(case_id: int, identity: Identity) -> Identity:
    require_case_access(case_id, identity)
    return identity


def _has_any_role(identity: Identity, roles: frozenset[str]) -> bool:
    return identity.is_admin or bool(set(identity.roles) & roles)


def _require_project_control(identity: Identity) -> None:
    if not _has_any_role(identity, _PROJECT_CONTROL_ROLES):
        raise HTTPException(status_code=403, detail="仅项目管理或复核角色可执行此操作")


def _require_fact_status(identity: Identity, fact_status: str) -> None:
    if fact_status != "candidate":
        _require_project_control(identity)


def _require_delivery_level(identity: Identity, delivery_level: str) -> None:
    if delivery_level == "final_candidate":
        _require_project_control(identity)
    elif delivery_level == "issued" and not _has_any_role(identity, _SIGNATORY_ROLES):
        raise HTTPException(status_code=403, detail="正式签发仅限项目合伙人身份")


def _require_full_artifact_visibility(identity: Identity) -> None:
    all_sections = all_report_section_codes()
    visible_sections = visible_report_sections(identity)
    if not all_sections or not all_sections.issubset(visible_sections):
        raise HTTPException(
            status_code=403,
            detail="附件包含完整报告内容，当前角色无权访问全部报告章节",
        )


def _job_error(exc: Exception) -> HTTPException:
    code = str(getattr(exc, "code", "ATTACHMENT_JOB_ERROR") or "ATTACHMENT_JOB_ERROR")
    status_code = int(getattr(exc, "status_code", 422) or 422)
    detail: dict[str, Any] = {"code": code, "message": str(exc)}
    details = getattr(exc, "details", None)
    if isinstance(details, list) and details:
        detail["details"] = details
    return HTTPException(
        status_code=status_code,
        detail=detail,
    )


def _validate_fact_evidence_refs(case_id: int, evidence_refs: list[dict[str, Any]]) -> None:
    if not evidence_refs:
        return
    errors: list[str] = []
    for index, reference in enumerate(evidence_refs, start=1):
        source_sha256 = str(reference.get("source_sha256") or "").strip().lower()
        if not _SHA256_PATTERN.fullmatch(source_sha256):
            errors.append(f"证据 {index} 缺少当前源文件的 SHA-256")
    errors.extend(validate_evidence_ownership(case_id, evidence_refs))
    if errors:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "FACT_EVIDENCE_INVALID",
                "message": "事实证据不属于当前项目、已失效或缺少不可变定位",
                "details": list(dict.fromkeys(errors))[:50],
            },
        )


@router.get("/api/annual-audit/{case_id}/facts")
def list_engagement_facts(
    case_id: int,
    identity: Identity = Depends(_require_report),
):
    _case_identity(case_id, identity)
    return {"case_id": case_id, "facts": repository.list_current_facts(case_id)}


@router.put("/api/annual-audit/{case_id}/facts/{fact_key:path}")
def put_engagement_fact(
    case_id: int,
    fact_key: str,
    payload: FactUpsertRequest,
    identity: Identity = Depends(_require_report),
):
    _case_identity(case_id, identity)
    _require_fact_status(identity, payload.status)
    normalized_key = fact_key.strip()
    if not repository.FACT_KEY_PATTERN.fullmatch(normalized_key):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_FACT_KEY", "message": "事实键必须是规范的点分标识符"},
        )
    if normalized_key in {"entity.legal_name", "entity.uscc"} or normalized_key.startswith("engagement."):
        raise HTTPException(
            status_code=409,
            detail={"code": "MASTER_FACT_IMMUTABLE", "message": "项目主数据事实不能通过附件事实接口覆盖"},
        )
    _validate_fact_evidence_refs(case_id, payload.evidence_refs)
    return repository.upsert_fact_version(
        engagement_id=case_id,
        fact_key=normalized_key,
        value=payload.value,
        display_value=payload.display_value,
        data_type=payload.data_type,
        status=payload.status,
        source_kind=payload.source_kind,
        source_ref=payload.source_ref,
        evidence_refs=payload.evidence_refs,
        actor_user_id=identity.user_id or "system",
        reviewed=payload.status != "candidate",
    )


@router.post(
    "/api/annual-audit/{case_id}/attachment-jobs",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_attachment_job(
    case_id: int,
    payload: CreateAttachmentJobRequest,
    identity: Identity = Depends(_require_report),
):
    _case_identity(case_id, identity)
    _require_delivery_level(identity, payload.delivery_level)
    from ai_hunter.annual_audit.attachments.job_service import (
        AttachmentJobError,
        create_attachment_job as create_job,
        dispatch_pending_outbox,
    )

    try:
        result = create_job(
            engagement_id=case_id,
            report_id=payload.report_id,
            request_scope=payload.generation_scope,
            delivery_level=payload.delivery_level,
            client_idempotency_key=payload.idempotency_key,
            requested_by=identity.user_id or "system",
        )
        dispatch_pending_outbox(limit=1)
        return result
    except AttachmentJobError as exc:
        raise _job_error(exc) from exc


@router.get("/api/annual-audit/{case_id}/attachment-jobs")
def attachment_job_history(
    case_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    identity: Identity = Depends(_require_report),
):
    _case_identity(case_id, identity)
    return {"case_id": case_id, "jobs": repository.list_jobs(case_id, limit=limit)}


@router.get("/api/annual-audit/{case_id}/attachment-jobs/{job_id}")
def attachment_job_detail(
    case_id: int,
    job_id: str,
    identity: Identity = Depends(_require_report),
):
    _case_identity(case_id, identity)
    job = repository.get_job(job_id=job_id, engagement_id=case_id)
    if job is None:
        raise HTTPException(status_code=404, detail="附件生成任务不存在")
    return job


@router.post(
    "/api/annual-audit/{case_id}/attachment-jobs/{job_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_attachment_job(
    case_id: int,
    job_id: str,
    identity: Identity = Depends(_require_report),
):
    _case_identity(case_id, identity)
    existing = repository.get_job(job_id=job_id, engagement_id=case_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="附件生成任务不存在")
    _require_delivery_level(identity, str(existing.get("delivery_level") or "review_draft"))
    if not repository.retry_failed_job(job_id):
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_NOT_RETRYABLE", "message": "当前任务没有可重试的失败项"},
        )
    from ai_hunter.annual_audit.attachments.job_service import dispatch_pending_outbox

    dispatch_pending_outbox(limit=1)
    return repository.get_job(job_id=job_id, engagement_id=case_id)


@router.post("/api/annual-audit/{case_id}/attachment-jobs/{job_id}/cancel")
def cancel_attachment_job(
    case_id: int,
    job_id: str,
    identity: Identity = Depends(_require_report),
):
    _case_identity(case_id, identity)
    existing = repository.get_job(job_id=job_id, engagement_id=case_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="附件生成任务不存在")
    _require_delivery_level(identity, str(existing.get("delivery_level") or "review_draft"))
    if not repository.cancel_queued_job(job_id):
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_NOT_CANCELLABLE", "message": "只有尚未开始的任务可以取消"},
        )
    return repository.get_job(job_id=job_id, engagement_id=case_id)


def _ticket_response(case_id: int, artifact_id: str, purpose: str, identity: Identity):
    _case_identity(case_id, identity)
    _require_full_artifact_visibility(identity)
    try:
        return issue_ticket(
            engagement_id=case_id,
            artifact_id=artifact_id,
            purpose=purpose,
            actor_user_id=identity.user_id or "system",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArtifactTicketError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/annual-audit/{case_id}/artifacts/{artifact_id}/download-ticket")
def artifact_download_ticket(
    case_id: int,
    artifact_id: str,
    identity: Identity = Depends(_require_report),
):
    return _ticket_response(case_id, artifact_id, "download", identity)


@router.get("/api/annual-audit/{case_id}/artifacts/{artifact_id}/preview-ticket")
def artifact_preview_ticket(
    case_id: int,
    artifact_id: str,
    identity: Identity = Depends(_require_report),
):
    return _ticket_response(case_id, artifact_id, "preview", identity)


def _resolve_range(header: str | None, size: int) -> tuple[int, int, int]:
    if not header:
        return 0, max(size - 1, 0), 200
    match = _RANGE_PATTERN.fullmatch(header.strip())
    if not match or size <= 0:
        raise HTTPException(status_code=416, detail="不支持的 Range 请求")
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise HTTPException(status_code=416, detail="无效的 Range 请求")
    if start_text:
        start = int(start_text)
        end = min(int(end_text), size - 1) if end_text else size - 1
    else:
        suffix = int(end_text)
        if suffix <= 0:
            raise HTTPException(status_code=416, detail="无效的 Range 请求")
        start = max(size - suffix, 0)
        end = size - 1
    if start >= size or start > end:
        raise HTTPException(
            status_code=416,
            detail="Range 超出文件范围",
            headers={"Content-Range": f"bytes */{size}"},
        )
    return start, end, 206


def _stream_minio(response, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    try:
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        response.close()
        response.release_conn()


@router.get("/api/artifact-access/{token}")
def consume_artifact_ticket(
    token: str,
    request: Request,
    identity: Identity = Depends(_require_report),
):
    try:
        claims = verify_ticket(token)
    except ArtifactTicketError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    case_id = int(claims["case"])
    artifact_id = str(claims["artifact"])
    purpose = str(claims["purpose"])
    _case_identity(case_id, identity)
    _require_full_artifact_visibility(identity)
    if str(claims.get("user") or "") != str(identity.user_id or "system"):
        raise HTTPException(status_code=403, detail="附件票据不属于当前用户")
    artifact = repository.get_artifact(
        engagement_id=case_id,
        artifact_id=artifact_id,
        purpose=purpose,
    )
    if artifact is None or not repository.redeem_ticket(
        str(claims["jti"]),
        purpose=purpose,
    ):
        raise HTTPException(status_code=403, detail="附件票据无效或已过期")
    storage_ref = str(artifact.get("access_ref") or "")
    minio = get_minio_service()
    try:
        stat = minio.stat_object(storage_ref)
        size = int(stat.size)
        start, end, response_status = _resolve_range(request.headers.get("range"), size)
        length = end - start + 1
        source = minio.open_object(storage_ref, offset=start, length=length)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="附件对象暂时不可用") from exc
    original_name = str(artifact.get("file_name") or "attachment")
    file_name = original_name.rsplit(".", 1)[0] + ".pdf" if purpose == "preview" else original_name
    disposition = "inline" if purpose == "preview" else "attachment"
    ascii_name = "attachment.pdf" if purpose == "preview" else "attachment" + str(artifact.get("extension") or "")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": (
            f'{disposition}; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(file_name, safe='')}"
        ),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if response_status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    media_type = "application/pdf" if purpose == "preview" else str(artifact.get("content_type") or "application/octet-stream")
    return StreamingResponse(
        _stream_minio(source),
        status_code=response_status,
        media_type=media_type,
        headers=headers,
    )


__all__ = ["router"]
