"""Deterministic worker pipeline for one already-claimed attachment job.

The Celery message carries only a job ID.  Every other input is reloaded from
the immutable snapshots stored when the job was created and checked against
its recorded SHA-256 before any renderer is invoked.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid5

from pydantic import ValidationError

from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.app.settings import Settings
from ai_hunter.document_templates.integrity import (
    canonical_json_sha256,
    stable_template_content_hash,
)

from . import repository
from .agent_graph import (
    fact_registry_from_context,
    prepare_attachment,
    semantic_slot_bindings,
)
from .content_schemas import AttachmentContractError, BindingManifest
from .context_service import GenerationContextSnapshot, canonical_json_bytes
from .fact_registry import ConflictedFactError, MissingFactError
from .model_composer import (
    SemanticCompositionError,
    build_frozen_attachment_composer,
    validate_frozen_model_manifest,
)
from .preview_service import PreviewConversionError, convert_to_pdf
from .provenance import build_prepared_provenance_manifest, provenance_bytes
from .quality_service import (
    AttachmentQualityError,
    require_quality,
    sanitize_output_filename,
    validate_rendered_artifact,
)
from .renderers import RENDERERS


_OBJECT_REF_RE = re.compile(r"\bminio://\S+", re.IGNORECASE)
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\r\n\t]+")


class AttachmentWorkerError(RuntimeError):
    """Focused pipeline error suitable for durable, sanitized job state."""

    def __init__(self, code: str, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


def run_claimed_job(job_id: str, *, lease_token: str, settings: Settings) -> bool:
    """Render and atomically publish every pending item in a claimed job."""

    try:
        job, context, template_files = _load_frozen_inputs(
            job_id,
            lease_token=lease_token,
            settings=settings,
        )
    except Exception as exc:
        error = _focused_error(exc, stage="freezing_context")
        repository.transition_job(
            job_id=job_id,
            expected_statuses={"running"},
            status="failed",
            stage=error.stage,
            progress=5,
            error_code=error.code,
            error_summary=_safe_error_summary(error),
            lease_token=lease_token,
            lease_seconds=settings.attachment_job_stale_seconds,
            settings=settings,
        )
        return False

    items = list(job.get("items") or [])
    expected = max(1, int(job.get("expected_item_count") or len(items) or 1))
    completed = sum(1 for item in items if item.get("status") == "succeeded")
    for item in items:
        if item.get("status") == "succeeded":
            continue
        item_id = str(item["id"])
        if not repository.claim_item(
            job_id=job_id,
            item_id=item_id,
            stage="composing_payload",
            lease_token=lease_token,
            settings=settings,
        ):
            continue
        progress = min(85, 10 + int((completed / expected) * 75))
        repository.transition_job(
            job_id=job_id,
            expected_statuses={"running"},
            status="running",
            stage="composing_payload",
            progress=progress,
            lease_token=lease_token,
            lease_seconds=settings.attachment_job_stale_seconds,
            settings=settings,
        )
        try:
            _process_item(
                job=job,
                item=item,
                template_file=template_files[str(item["template_file_id"])],
                context=context,
                lease_token=lease_token,
                settings=settings,
            )
        except Exception as exc:
            error = _focused_error(exc, stage=_error_stage(exc))
            repository.fail_item(
                job_id=job_id,
                item_id=item_id,
                stage=error.stage,
                error_code=error.code,
                error_summary=_safe_error_summary(error),
                lease_token=lease_token,
                settings=settings,
            )
            return False
        completed += 1

    repository.transition_job(
        job_id=job_id,
        expected_statuses={"running"},
        status="running",
        stage="publishing",
        progress=95,
        lease_token=lease_token,
        lease_seconds=settings.attachment_job_stale_seconds,
        settings=settings,
    )
    published = repository.publish_job_if_complete(
        job_id=job_id,
        actor_user_id=str(job.get("requested_by") or "system"),
        lease_token=lease_token,
        settings=settings,
    )
    if not published:
        repository.transition_job(
            job_id=job_id,
            expected_statuses={"running"},
            status="failed",
            stage="publishing",
            progress=95,
            error_code="ATOMIC_PUBLISH_INCOMPLETE",
            error_summary="附件项或校验产物数量与冻结任务不一致",
            lease_token=lease_token,
            lease_seconds=settings.attachment_job_stale_seconds,
            settings=settings,
        )
    return published


def _load_frozen_inputs(
    job_id: str,
    *,
    lease_token: str,
    settings: Settings,
) -> tuple[dict[str, Any], GenerationContextSnapshot, dict[str, dict[str, Any]]]:
    job = repository.get_job_by_id(job_id, include_internal=True, settings=settings)
    if (
        job is None
        or job.get("status") != "running"
        or str(job.get("lease_token") or "") != lease_token
    ):
        raise AttachmentWorkerError("JOB_NOT_CLAIMED", "附件任务未处于运行状态", stage="freezing_context")
    minio = get_minio_service()
    context_bytes = minio.get_object_bytes(str(job.get("fact_snapshot_ref") or ""))
    if _sha256(context_bytes) != str(job.get("fact_snapshot_sha256") or ""):
        raise AttachmentWorkerError(
            "CONTEXT_SHA_MISMATCH",
            "冻结生成上下文校验失败",
            stage="freezing_context",
        )
    try:
        context = GenerationContextSnapshot.model_validate(json.loads(context_bytes))
    except (json.JSONDecodeError, UnicodeError, ValidationError) as exc:
        raise AttachmentWorkerError(
            "CONTEXT_INVALID",
            "冻结生成上下文无法解析",
            stage="freezing_context",
        ) from exc
    if context.snapshot_sha256 != str(job.get("fact_snapshot_sha256") or ""):
        raise AttachmentWorkerError(
            "CONTEXT_CANONICAL_SHA_MISMATCH",
            "冻结生成上下文的规范化摘要不一致",
            stage="freezing_context",
        )

    snapshot = job.get("template_snapshot")
    if not isinstance(snapshot, dict):
        raise AttachmentWorkerError(
            "TEMPLATE_SNAPSHOT_INVALID",
            "冻结模板快照不存在",
            stage="freezing_context",
        )
    _assert_template_snapshot_integrity(job, snapshot)
    files = {
        str(item.get("id")): dict(item)
        for item in snapshot.get("files") or []
        if isinstance(item, dict) and item.get("id")
    }
    if len(files) != int(job.get("expected_item_count") or 0):
        raise AttachmentWorkerError(
            "TEMPLATE_SNAPSHOT_INCOMPLETE",
            "冻结模板文件数量与任务不一致",
            stage="freezing_context",
        )
    for item in job.get("items") or []:
        template_file = files.get(str(item.get("template_file_id") or ""))
        if template_file is None:
            raise AttachmentWorkerError(
                "TEMPLATE_FILE_NOT_FROZEN",
                "任务项引用的模板文件不在冻结快照中",
                stage="freezing_context",
            )
        _assert_item_identity(item, template_file)
    try:
        manifests = [
            BindingManifest.model_validate(item.get("binding_manifest") or {})
            for item in files.values()
        ]
        validate_frozen_model_manifest(job.get("model_manifest") or {}, manifests)
    except ValidationError as exc:
        raise AttachmentWorkerError(
            "BINDING_MANIFEST_INVALID",
            "冻结模板绑定清单不符合运行时合同",
            stage="freezing_context",
        ) from exc
    except SemanticCompositionError as exc:
        raise AttachmentWorkerError(
            exc.code,
            str(exc),
            stage="freezing_context",
        ) from exc
    return job, context, files


def _assert_item_identity(item: dict[str, Any], template_file: dict[str, Any]) -> None:
    checks = {
        "document_code": str(item.get("document_code") or ""),
        "extension": str(item.get("extension") or "").lower(),
        "source_sha256": str(item.get("source_template_sha256") or ""),
        "compiled_sha256": str(item.get("compiled_template_sha256") or ""),
    }
    frozen = {
        "document_code": str(template_file.get("document_code") or ""),
        "extension": str(template_file.get("extension") or "").lower(),
        "source_sha256": str(template_file.get("source_sha256") or ""),
        "compiled_sha256": str(template_file.get("compiled_sha256") or ""),
    }
    if checks != frozen:
        raise AttachmentWorkerError(
            "TEMPLATE_IDENTITY_MISMATCH",
            "任务项与冻结模板身份不一致",
            stage="freezing_context",
        )
    item_manifest = item.get("binding_manifest")
    snapshot_manifest = template_file.get("binding_manifest")
    if not isinstance(item_manifest, dict) or not isinstance(snapshot_manifest, dict):
        raise AttachmentWorkerError(
            "TEMPLATE_BINDING_MANIFEST_INVALID",
            "任务项或冻结模板的绑定清单不是对象",
            stage="freezing_context",
        )
    if not hmac.compare_digest(
        canonical_json_sha256(item_manifest),
        canonical_json_sha256(snapshot_manifest),
    ):
        raise AttachmentWorkerError(
            "TEMPLATE_BINDING_MANIFEST_MISMATCH",
            "任务项与冻结模板的绑定清单不一致",
            stage="freezing_context",
        )


def _assert_template_snapshot_integrity(
    job: dict[str, Any], snapshot: dict[str, Any]
) -> None:
    expected = str(job.get("template_content_sha256") or "").strip().lower()
    actual = stable_template_content_hash(snapshot)
    if len(expected) != 64 or not hmac.compare_digest(expected, actual):
        raise AttachmentWorkerError(
            "TEMPLATE_SNAPSHOT_SHA_MISMATCH",
            "冻结模板快照摘要校验失败",
            stage="freezing_context",
        )


def _process_item(
    *,
    job: dict[str, Any],
    item: dict[str, Any],
    template_file: dict[str, Any],
    context: GenerationContextSnapshot,
    lease_token: str,
    settings: Settings,
) -> None:
    minio = get_minio_service()
    compiled_bytes = minio.get_object_bytes(str(template_file.get("compiled_object_ref") or ""))
    if _sha256(compiled_bytes) != str(item.get("compiled_template_sha256") or ""):
        raise AttachmentWorkerError(
            "COMPILED_TEMPLATE_SHA_MISMATCH",
            "编译模板摘要校验失败",
            stage="loading_template",
        )
    source_bytes = minio.get_object_bytes(str(template_file.get("source_object_ref") or ""))
    if _sha256(source_bytes) != str(item.get("source_template_sha256") or ""):
        raise AttachmentWorkerError(
            "SOURCE_TEMPLATE_SHA_MISMATCH",
            "原始模板摘要校验失败",
            stage="loading_template",
        )
    try:
        manifest = BindingManifest.model_validate(item.get("binding_manifest") or {})
    except ValidationError as exc:
        raise AttachmentWorkerError(
            "BINDING_MANIFEST_INVALID",
            "冻结模板绑定清单不符合运行时合同",
            stage="composing_payload",
        ) from exc
    if manifest.source_template_sha256 != _sha256(source_bytes):
        raise AttachmentWorkerError(
            "BINDING_SOURCE_SHA_MISMATCH",
            "绑定清单与原始模板摘要不一致",
            stage="composing_payload",
        )

    composer = _attachment_composer_for_item(
        manifest=manifest,
        job=job,
        settings=settings,
    )
    prepared = prepare_attachment(
        manifest,
        context,
        fact_registry_from_context(context),
        composer=composer,
    )
    extension = str(item.get("extension") or "").lower()
    renderer = RENDERERS.get(extension)
    if renderer is None:
        raise AttachmentWorkerError(
            "RENDERER_NOT_AVAILABLE",
            "冻结模板格式没有可用渲染器",
            stage="rendering",
        )
    # The admin binding contract is tied to the immutable source template,
    # while execution is tied to the separately frozen compiled template.
    # Renderers receive an execution copy with the compiled SHA after both
    # identities have been checked above.
    execution_manifest = manifest.model_copy(
        update={"source_template_sha256": str(item["compiled_template_sha256"])}
    )
    render_result = renderer(compiled_bytes, prepared.resolved_payload, execution_manifest)
    file_name = sanitize_output_filename(
        _project_name(context),
        str(item.get("display_name") or item.get("document_code") or "附件"),
        extension,
    )
    quality = require_quality(
        validate_rendered_artifact(
            render_result,
            file_name=file_name,
            manifest=execution_manifest,
            template_bytes=compiled_bytes,
            payload=prepared.resolved_payload,
        )
    )

    artifact_id = str(uuid5(UUID(str(job["id"])), str(item["id"])))
    payload_bytes = canonical_json_bytes(
        {
            "schema_version": "1.0",
            "context_snapshot_sha256": prepared.context_snapshot_sha256,
            "document_payload": prepared.document_payload,
            "resolved_payload": prepared.resolved_payload,
        }
    )
    uploaded_refs: list[str] = []
    fenced_item_id = _lease_fenced_blob_id(str(item["id"]), lease_token)
    fenced_artifact_id = _lease_fenced_blob_id(artifact_id, lease_token)
    try:
        payload_upload = minio.upload_attachment_blob(
            project_id=int(job["engagement_id"]),
            blob_id=fenced_item_id,
            category="payloads",
            file_name=f"{item['document_code']}-payload.json",
            content_type="application/json",
            file_bytes=payload_bytes,
        )
        uploaded_refs.append(payload_upload.storage_ref)
        artifact_upload = minio.upload_attachment_blob(
            project_id=int(job["engagement_id"]),
            blob_id=fenced_artifact_id,
            category="artifacts",
            file_name=file_name,
            content_type=render_result.content_type,
            file_bytes=render_result.data,
        )
        uploaded_refs.append(artifact_upload.storage_ref)
        preview_bytes = convert_to_pdf(
            file_name=file_name,
            content_type=render_result.content_type,
            file_bytes=render_result.data,
            settings=settings,
        )
        preview_ref: str | None = None
        preview_sha: str | None = None
        if preview_bytes is not None:
            preview_upload = minio.upload_derived_blob(
                project_id=int(job["engagement_id"]),
                blob_id=fenced_artifact_id,
                file_name=f"{PurePath(file_name).stem}.pdf",
                content_type="application/pdf",
                file_bytes=preview_bytes,
            )
            preview_ref = preview_upload.storage_ref
            preview_sha = _sha256(preview_bytes)
            uploaded_refs.append(preview_ref)

        provenance = build_prepared_provenance_manifest(
            artifact_id=artifact_id,
            prepared=prepared,
            render_result=render_result,
            quality_report=quality,
            template_version_id=str(job["template_version_id"]),
            template_file_id=str(item["template_file_id"]),
            source_template_sha256=str(item["source_template_sha256"]),
            compiled_template_sha256=str(item["compiled_template_sha256"]),
            renderer={
                **dict(job.get("renderer_manifest") or {}),
                "profile": str(template_file.get("renderer_profile") or ""),
            },
            model=dict(job.get("model_manifest") or {}),
        )
        manifest_bytes = provenance_bytes(provenance)
        manifest_upload = minio.upload_attachment_blob(
            project_id=int(job["engagement_id"]),
            blob_id=fenced_artifact_id,
            category="manifests",
            file_name="provenance.json",
            content_type="application/json",
            file_bytes=manifest_bytes,
        )
        uploaded_refs.append(manifest_upload.storage_ref)
        repository.complete_item(
            job_id=str(job["id"]),
            item_id=str(item["id"]),
            payload_ref=payload_upload.storage_ref,
            payload_sha256=_sha256(payload_bytes),
            quality_report=quality.model_dump(mode="json"),
            lease_token=lease_token,
            artifact={
                "id": artifact_id,
                "engagement_id": int(job["engagement_id"]),
                "report_id": int(job["report_id"]),
                "template_version_id": str(job["template_version_id"]),
                "template_file_id": str(item["template_file_id"]),
                "document_code": str(item["document_code"]),
                "display_name": str(item["display_name"]),
                "file_name": file_name,
                "extension": extension,
                "content_type": render_result.content_type,
                "file_size": len(render_result.data),
                "sha256": render_result.output_sha256,
                "object_ref": artifact_upload.storage_ref,
                "preview_ref": preview_ref,
                "preview_sha256": preview_sha,
                "provenance_manifest_ref": manifest_upload.storage_ref,
                "provenance_sha256": _sha256(manifest_bytes),
                "delivery_level": str(job.get("delivery_level") or "review_draft"),
                "created_by": str(job.get("requested_by") or "system"),
            },
            settings=settings,
        )
    except Exception:
        _cleanup_uploaded_refs(minio, uploaded_refs)
        raise


def _attachment_composer_for_item(
    *,
    manifest: BindingManifest,
    job: dict[str, Any],
    settings: Settings,
) -> Any | None:
    if not semantic_slot_bindings(manifest):
        return None
    try:
        return build_frozen_attachment_composer(
            model_manifest=job.get("model_manifest") or {},
            settings=settings,
        )
    except SemanticCompositionError as exc:
        raise AttachmentWorkerError(
            exc.code,
            str(exc),
            stage="composing_payload",
        ) from exc


def _lease_fenced_blob_id(blob_id: str, lease_token: str) -> str:
    return f"{blob_id}-{lease_token}"


def _cleanup_uploaded_refs(minio: Any, storage_refs: list[str]) -> None:
    for storage_ref in reversed(storage_refs):
        try:
            minio.delete_object(storage_ref)
        except Exception:
            pass


def _project_name(context: GenerationContextSnapshot) -> str:
    engagement = context.engagement
    explicit = str(engagement.get("project_name") or engagement.get("case_name") or "").strip()
    if explicit:
        return explicit
    entity = str(engagement.get("entity_name") or "年度审计").strip()
    year = str(engagement.get("fiscal_year") or "").strip()
    return f"{entity}{year}年度审计项目"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _error_stage(exc: Exception) -> str:
    if isinstance(exc, AttachmentWorkerError):
        return exc.stage
    if isinstance(exc, AttachmentQualityError):
        return "validating"
    if isinstance(exc, PreviewConversionError):
        return "previewing"
    if isinstance(exc, (AttachmentContractError, ValidationError)):
        return "composing_payload"
    return "rendering"


def _focused_error(exc: Exception, *, stage: str) -> AttachmentWorkerError:
    if isinstance(exc, AttachmentWorkerError):
        return exc
    if isinstance(exc, AttachmentQualityError):
        return AttachmentWorkerError("QUALITY_GATE_FAILED", str(exc), stage=stage)
    if isinstance(exc, PreviewConversionError):
        return AttachmentWorkerError("PREVIEW_CONVERSION_FAILED", str(exc), stage=stage)
    if isinstance(exc, MissingFactError):
        return AttachmentWorkerError("REQUIRED_FACT_MISSING", str(exc), stage=stage)
    if isinstance(exc, ConflictedFactError):
        return AttachmentWorkerError("FACT_CONFLICTED", str(exc), stage=stage)
    if isinstance(exc, SemanticCompositionError):
        return AttachmentWorkerError(exc.code, str(exc), stage=stage)
    if isinstance(exc, (AttachmentContractError, ValidationError)):
        return AttachmentWorkerError("ATTACHMENT_CONTRACT_FAILED", str(exc), stage=stage)
    return AttachmentWorkerError("ATTACHMENT_RENDER_FAILED", type(exc).__name__, stage=stage)


def _safe_error_summary(exc: Exception) -> str:
    value = _OBJECT_REF_RE.sub("[object]", str(exc))
    value = _WINDOWS_PATH_RE.sub("[path]", value)
    value = " ".join(value.split())
    return value[:1024] or type(exc).__name__


__all__ = ["AttachmentWorkerError", "run_claimed_job"]
