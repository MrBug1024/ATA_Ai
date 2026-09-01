"""Superadmin-managed document template governance API."""

from __future__ import annotations

import re
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from ai_hunter.document_templates.repository import (
    TemplateConflictError,
    TemplateImmutableError,
    TemplateNotFoundError,
    TemplateRepositoryError,
    TemplateRevisionConflictError,
    TemplateValidationStateError,
)
from ai_hunter.document_templates.schemas import (
    RevisionRequest,
    TemplateActivationRequest,
    TemplateBusinessTypeListResponse,
    TemplateCompileRequest,
    TemplateDeleteResponse,
    TemplateFileResponse,
    TemplateFileUpdateRequest,
    TemplateVersionCloneRequest,
    TemplateVersionCreateRequest,
    TemplateVersionListResponse,
    TemplateVersionResponse,
    TemplateVersionUpdateRequest,
)
from ai_hunter.document_templates.service import (
    TemplateServiceError,
    TemplateServiceValidationError,
    TemplateStorageError,
    get_document_template_service,
)

from ..auth.identity import Identity, get_current_identity
from ..auth.permissions import require_module
from ..settings import get_settings


router = APIRouter(prefix="/api/admin", tags=["attachment-templates"])

_INTERNAL_ERROR_DETAIL_KEYS = frozenset(
    {
        "context_ref",
        "credential",
        "error_type",
        "exception",
        "lease_token",
        "message",
        "model_key",
        "object_ref",
        "password",
        "payload_ref",
        "provenance_manifest_ref",
        "provider_key",
        "secret",
        "storage_ref",
        "token",
        "trace",
        "traceback",
    }
)
_INTERNAL_STORAGE_URI = re.compile(r"\b(?:minio|s3|file)://[^\s\"']+", re.IGNORECASE)


def _is_internal_error_detail_key(value: object) -> bool:
    key = str(value).strip().lower()
    return key in _INTERNAL_ERROR_DETAIL_KEYS or key.endswith(
        (
            "_api_key",
            "_context_ref",
            "_credential",
            "_lease_token",
            "_object_ref",
            "_password",
            "_payload_ref",
            "_provenance_ref",
            "_provider_key",
            "_secret",
            "_storage_ref",
            "_token",
        )
    )


def require_template_superadmin(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    if not identity.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="global attachment templates can only be changed by a superadmin",
        )
    return identity


def _public_error_details(value: object, *, root: bool = True) -> object:
    if isinstance(value, dict):
        return {
            str(key): _public_error_details(item, root=False)
            for key, item in value.items()
            if not _is_internal_error_detail_key(key)
            or (not root and str(key).strip().lower() == "message")
        }
    if isinstance(value, list):
        return [_public_error_details(item, root=False) for item in value]
    if isinstance(value, tuple):
        return [_public_error_details(item, root=False) for item in value]
    if isinstance(value, str):
        return _INTERNAL_STORAGE_URI.sub("[redacted]", value)
    return value


def _error_detail(exc: Exception) -> dict[str, object]:
    details = _public_error_details(dict(getattr(exc, "details", {}) or {}))
    message = "template request is invalid" if isinstance(exc, ValueError) else str(exc)
    return {
        "code": str(getattr(exc, "code", "TEMPLATE_ERROR")),
        "message": _INTERNAL_STORAGE_URI.sub("[redacted]", message)[:1024],
        "details": details,
    }


def _raise_template_http_error(exc: Exception) -> None:
    if isinstance(exc, TemplateNotFoundError):
        raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc
    if isinstance(
        exc,
        (
            TemplateConflictError,
            TemplateImmutableError,
            TemplateRevisionConflictError,
            TemplateValidationStateError,
        ),
    ):
        raise HTTPException(status_code=409, detail=_error_detail(exc)) from exc
    if isinstance(exc, TemplateServiceValidationError):
        raise HTTPException(status_code=422, detail=_error_detail(exc)) from exc
    if isinstance(exc, (TemplateStorageError, TemplateRepositoryError)):
        raise HTTPException(status_code=503, detail=_error_detail(exc)) from exc
    if isinstance(exc, (TemplateServiceError, ValueError)):
        raise HTTPException(status_code=422, detail=_error_detail(exc)) from exc
    raise exc


@router.get(
    "/template-business-types",
    response_model=TemplateBusinessTypeListResponse,
    summary="List governed template business types",
)
def list_template_business_types(
    _: Identity = Depends(require_module("admin")),
) -> dict:
    return get_document_template_service().list_business_types()


@router.get(
    "/template-versions",
    response_model=TemplateVersionListResponse,
    summary="List document template versions",
)
def list_template_versions(
    business_type: str = Query(default=""),
    template_status: str = Query(default="", alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_archived: bool = Query(default=False),
    _: Identity = Depends(require_module("admin")),
) -> dict:
    try:
        return get_document_template_service().list_versions(
            business_type=business_type.strip().lower(),
            status=template_status.strip().lower(),
            page=page,
            page_size=page_size,
            include_archived=include_archived,
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.post(
    "/template-versions",
    response_model=TemplateVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the next draft version",
)
def create_template_version(
    payload: TemplateVersionCreateRequest,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().create_version(
            payload.model_dump(), actor=identity.user_id
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.get(
    "/template-versions/{version_id}",
    response_model=TemplateVersionResponse,
    summary="Get a template version and its files",
)
def get_template_version(
    version_id: UUID,
    _: Identity = Depends(require_module("admin")),
) -> dict:
    try:
        return get_document_template_service().get_version(version_id)
    except Exception as exc:
        _raise_template_http_error(exc)


@router.patch(
    "/template-versions/{version_id}",
    response_model=TemplateVersionResponse,
    summary="Edit draft template metadata",
)
def update_template_version(
    version_id: UUID,
    payload: TemplateVersionUpdateRequest,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().update_version(
            version_id,
            payload.model_dump(exclude_none=True),
            actor=identity.user_id,
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.post(
    "/template-versions/{version_id}/clone",
    response_model=TemplateVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone any immutable version into the next draft",
)
def clone_template_version(
    version_id: UUID,
    payload: TemplateVersionCloneRequest,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().clone_version(
            version_id,
            payload.model_dump(exclude_none=True),
            actor=identity.user_id,
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.delete(
    "/template-versions/{version_id}",
    response_model=TemplateDeleteResponse,
    summary="Delete an unused draft template version",
)
def delete_template_version(
    version_id: UUID,
    revision: int = Query(gt=0),
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().delete_version(
            version_id, revision=revision, actor=identity.user_id
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.post(
    "/template-versions/{version_id}/files",
    response_model=TemplateFileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and inspect one template file",
)
async def upload_template_file(
    version_id: UUID,
    file: UploadFile = File(...),
    document_code: str = Form(...),
    display_name: str = Form(...),
    sort_order: int = Form(default=0, ge=0, le=100000),
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    settings = get_settings()
    max_bytes = max(1, int(settings.attachment_template_max_mb)) * 1024 * 1024
    file_bytes = await file.read(max_bytes + 1)
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={"code": "FILE_SIZE_LIMIT", "message": "template file exceeds the size limit"},
        )
    try:
        return get_document_template_service().upload_file(
            version_id,
            file_name=file.filename or "",
            content_type=file.content_type or "",
            file_bytes=file_bytes,
            document_code=document_code,
            display_name=display_name,
            sort_order=sort_order,
            actor=identity.user_id,
        )
    except Exception as exc:
        _raise_template_http_error(exc)
    finally:
        await file.close()


@router.patch(
    "/template-files/{file_id}",
    response_model=TemplateFileResponse,
    summary="Edit a draft file's business mapping",
)
def update_template_file(
    file_id: UUID,
    payload: TemplateFileUpdateRequest,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().update_file(
            file_id,
            payload.model_dump(exclude_none=True),
            actor=identity.user_id,
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.delete(
    "/template-files/{file_id}",
    response_model=TemplateDeleteResponse,
    summary="Delete a file from a draft version",
)
def delete_template_file(
    file_id: UUID,
    revision: int = Query(gt=0),
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().delete_file(
            file_id, revision=revision, actor=identity.user_id
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.post(
    "/template-files/{file_id}/inspect",
    response_model=TemplateFileResponse,
    summary="Reinspect an uploaded template file",
)
def inspect_template_file(
    file_id: UUID,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().inspect_file(file_id, actor=identity.user_id)
    except Exception as exc:
        _raise_template_http_error(exc)


@router.post(
    "/template-files/{file_id}/compile",
    response_model=TemplateFileResponse,
    summary="Compile an approved slot mapping",
)
def compile_template_file(
    file_id: UUID,
    payload: TemplateCompileRequest,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().compile_file(
            file_id,
            revision=payload.revision,
            binding_manifest=payload.binding_manifest,
            actor=identity.user_id,
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.get(
    "/template-files/{file_id}/preview",
    response_class=Response,
    summary="Read the activation preview PDF",
)
def preview_template_file(
    file_id: UUID,
    _: Identity = Depends(require_module("admin")),
) -> Response:
    try:
        content, file_name = get_document_template_service().get_preview(file_id)
    except TemplateServiceValidationError as exc:
        raise HTTPException(status_code=409, detail=_error_detail(exc)) from exc
    except Exception as exc:
        _raise_template_http_error(exc)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(file_name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/template-versions/{version_id}/validate",
    response_model=TemplateVersionResponse,
    summary="Run all activation gates",
)
def validate_template_version(
    version_id: UUID,
    payload: RevisionRequest,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().validate_version(
            version_id, revision=payload.revision, actor=identity.user_id
        )
    except Exception as exc:
        _raise_template_http_error(exc)


@router.put(
    "/template-versions/{version_id}/activation",
    response_model=TemplateVersionResponse,
    summary="Atomically activate or retire a template version",
)
def activate_template_version(
    version_id: UUID,
    payload: TemplateActivationRequest,
    identity: Identity = Depends(require_template_superadmin),
) -> dict:
    try:
        return get_document_template_service().set_activation(
            version_id,
            revision=payload.revision,
            active=payload.active,
            actor=identity.user_id,
            preview_confirmations=[
                item.model_dump(mode="json") for item in payload.preview_confirmations
            ],
        )
    except Exception as exc:
        _raise_template_http_error(exc)


__all__ = ["require_template_superadmin", "router"]
