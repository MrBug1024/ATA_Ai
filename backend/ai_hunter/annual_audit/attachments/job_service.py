"""Durable attachment job orchestration over frozen IDs and SHA-256 snapshots."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_hunter.annual_audit.engagement_repository import get_engagement
from ai_hunter.annual_audit.execution_service import (
    get_execution_snapshot,
    validate_evidence_ownership,
)
from ai_hunter.app.repositories.conversation_message_repo import get_conversation_message_repo
from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.app.settings import Settings, get_settings
from ai_hunter.document_templates.service import get_document_template_service
from pydantic import ValidationError

from . import repository
from .agent_graph import (
    prepare_attachment,
    semantic_slot_bindings,
    validate_semantic_manifest_facts,
)
from .content_schemas import AttachmentContractError, BindingManifest
from .context_service import build_generation_context_snapshot, canonical_json_bytes
from .fact_registry import ConflictedFactError, FactRecord, FactRegistry, MissingFactError
from .financial_statements import adapt_financial_statement_snapshot
from .model_composer import (
    SemanticCompositionError,
    build_attachment_model_manifest,
    require_attachment_model_credentials,
)


GENERATION_POLICY_VERSION = "annual-attachment-v1"
ALLOWED_EXTENSIONS = frozenset({".docx", ".xlsx", ".md", ".pdf"})


class AttachmentJobError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = list(details or [])


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _master_fact_records(engagement: dict[str, Any]) -> list[FactRecord]:
    values = {
        "entity.legal_name": engagement.get("entity_name"),
        "entity.uscc": engagement.get("entity_uscc"),
        "engagement.fiscal_year": engagement.get("fiscal_year"),
        "engagement.period_start": engagement.get("period_start"),
        "engagement.period_end": engagement.get("period_end"),
        "engagement.code": engagement.get("engagement_code"),
    }
    return [
        FactRecord(
            fact_key=key,
            value=value,
            display_value=str(value),
            status="approved",
            source_kind="project_master",
            source_ref={"engagement_id": int(engagement["id"])},
            revision=1,
            reviewed_by="system",
        )
        for key, value in values.items()
        if value not in (None, "")
    ]


def _fact_registry(
    engagement: dict[str, Any],
    fact_rows: list[dict[str, Any]],
) -> FactRegistry:
    records: list[FactRecord | dict[str, Any]] = [*_master_fact_records(engagement)]
    records.extend(
        {
            "fact_key": item["fact_key"],
            "value": item.get("value"),
            "display_value": item.get("display_value"),
            "data_type": item.get("data_type") or "auto",
            "status": item.get("status") or "candidate",
            "source_kind": item.get("source_kind") or "material_extraction",
            "source_ref": item.get("source_ref") or {},
            "evidence_refs": item.get("evidence_refs") or [],
            "revision": int(item.get("revision") or 1),
            "is_current": bool(item.get("is_current", True)),
            "reviewed_by": item.get("reviewed_by"),
        }
        for item in fact_rows
        if item.get("fact_key")
    )
    return FactRegistry(records)


def _flatten_findings(fact_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for key in ("sales_receivables", "cash_and_bank"):
        section = fact_snapshot.get(key)
        if isinstance(section, dict):
            findings.extend(
                dict(item)
                for item in section.get("findings") or []
                if isinstance(item, dict)
            )
    return findings


def _load_generation_context(
    *,
    engagement_id: int,
    report: dict[str, Any],
    settings: Settings,
) -> tuple[Any, FactRegistry]:
    engagement = get_engagement(engagement_id, settings=settings)
    fact_rows = repository.list_current_facts(engagement_id, settings=settings)
    registry = _fact_registry(engagement, fact_rows)
    execution = get_execution_snapshot(engagement_id, settings=settings)
    fact_snapshot = dict(report.get("fact_snapshot") or {})
    fact_snapshot_sha = _sha256(canonical_json_bytes(fact_snapshot))
    reviews_value = execution.get("reviews") or []
    reviews = reviews_value if isinstance(reviews_value, list) else [reviews_value]
    statement_adaptation = adapt_financial_statement_snapshot(
        fact_snapshot.get("financial_statements")
    )
    # Local workpaper analyses are not complete financial statements.  Only a
    # value that passes the explicit report-snapshot contract reaches templates.
    financial_statements = statement_adaptation.context or {}
    statement_validation = statement_adaptation.validation_snapshot()
    if statement_adaptation.context is not None:
        evidence_errors = validate_evidence_ownership(
            engagement_id,
            [
                reference.model_dump(mode="json")
                for reference in statement_adaptation.context.evidence_manifest.values()
            ],
            settings=settings,
        )
        if evidence_errors:
            financial_statements = {}
            statement_validation = {
                "status": "invalid",
                "blockers": [
                    {
                        "code": "FINANCIAL_STATEMENT_EVIDENCE_INVALID",
                        "field": "financial_statements.evidence",
                        "message": "财务报表证据不属于当前项目或缺少有效定位",
                    }
                ],
            }
    snapshot = build_generation_context_snapshot(
        engagement={
            "engagement_id": engagement_id,
            "engagement_code": engagement.get("engagement_code") or "",
            "case_name": engagement.get("case_name") or "",
            "project_name": engagement.get("case_name") or "",
            "entity_name": engagement.get("entity_name") or "",
            "entity_uscc": engagement.get("entity_uscc") or "",
            "fiscal_year": engagement.get("fiscal_year"),
            "period_start": engagement.get("period_start"),
            "period_end": engagement.get("period_end"),
            "status": engagement.get("status") or "",
        },
        entity_facts=registry.frozen_snapshot(),
        report={
            "id": int(report["id"]),
            "version": int(report["report_version"]),
            "fact_snapshot_sha256": fact_snapshot_sha,
            "opinion_type": str(fact_snapshot.get("opinion_type") or ""),
            "status": str(report.get("status") or "draft"),
        },
        financial_statements=financial_statements,
        financial_statement_validation=statement_validation,
        audit_program=list(execution.get("program") or []),
        findings=_flatten_findings(fact_snapshot),
        corrections=list(fact_snapshot.get("corrections") or []),
        reviews=reviews,
        release_gate=dict(execution.get("release_gate") or {}),
        materials=list(fact_snapshot.get("material_sources") or []),
        evidence_manifest={
            "citation_plan_entries": list(fact_snapshot.get("citation_plan_entries") or []),
            "citation_plan_summary": dict(fact_snapshot.get("citation_plan_summary") or {}),
        },
        policy_binding=dict(execution.get("policy_binding") or {}),
        generation_policy_version=GENERATION_POLICY_VERSION,
    )
    return snapshot, registry


def _validate_template_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    report = snapshot.get("validation_report") or {}
    if not report.get("passed"):
        raise AttachmentJobError(
            "TEMPLATE_VALIDATION_FAILED",
            "激活模板的当前校验报告未通过",
            status_code=422,
        )
    files = [dict(item) for item in snapshot.get("files") or []]
    if not files:
        raise AttachmentJobError(
            "TEMPLATE_VALIDATION_FAILED",
            "激活模板版本没有可交付文件",
            status_code=422,
        )
    seen_codes: set[str] = set()
    for item in files:
        code = str(item.get("document_code") or "")
        extension = str(item.get("extension") or "").lower()
        if not code or code in seen_codes:
            raise AttachmentJobError("TEMPLATE_VALIDATION_FAILED", "模板文件业务编码为空或重复")
        seen_codes.add(code)
        if extension not in ALLOWED_EXTENSIONS:
            raise AttachmentJobError("TEMPLATE_VALIDATION_FAILED", f"不支持模板格式：{extension}")
        if not item.get("compiled_object_ref") or len(str(item.get("compiled_sha256") or "")) != 64:
            raise AttachmentJobError("TEMPLATE_VALIDATION_FAILED", f"模板 {code} 没有冻结的编译文件")
        if not (item.get("binding_manifest") or {}).get("slots"):
            raise AttachmentJobError("TEMPLATE_VALIDATION_FAILED", f"模板 {code} 没有槽位合同")
    return sorted(files, key=lambda item: (int(item.get("sort_order") or 0), item["id"]))


def _preflight_template_context(
    files: list[dict[str, Any]],
    *,
    context: Any,
    registry: FactRegistry,
) -> None:
    """Reject an incomplete active template version before durable work."""

    manifests: list[tuple[dict[str, Any], BindingManifest]] = []
    for item in files:
        document_code = str(item.get("document_code") or "template")
        try:
            manifest = BindingManifest.model_validate(item.get("binding_manifest") or {})
        except ValidationError as exc:
            raise AttachmentJobError(
                "GENERATION_CONTEXT_BLOCKED",
                f"模板 {document_code} 的绑定合同无效：{exc}",
                status_code=409,
            ) from exc
        manifests.append((item, manifest))

    validation = getattr(context, "financial_statement_validation", {})
    validation_status = (
        str(validation.get("status") or "") if isinstance(validation, dict) else ""
    )
    if validation_status in {"missing", "invalid"}:
        validation_blockers = [
            dict(value)
            for value in validation.get("blockers") or []
            if isinstance(value, dict)
        ]
        code = (
            "FINANCIAL_STATEMENTS_MISSING"
            if validation_status == "missing"
            else "FINANCIAL_STATEMENTS_INVALID"
        )
        dependent_files = [
            item
            for item, manifest in manifests
            if any(
                str(binding.source or "")
                .strip()
                .removeprefix("document.")
                .startswith("financial_statements.")
                for binding in manifest.slots
            )
        ]
        if dependent_files:
            details = [
                {
                    "document_code": str(item.get("document_code") or "template"),
                    "display_name": str(
                        item.get("display_name")
                        or item.get("document_code")
                        or "template"
                    ),
                    "code": code,
                    "message": (
                        "缺少经确认的完整财务报表结构化输入"
                        if validation_status == "missing"
                        else "财务报表结构化输入未通过合同或勾稽校验"
                    ),
                    "blockers": validation_blockers,
                }
                for item in dependent_files
            ]
            raise AttachmentJobError(
                "FINANCIAL_STATEMENTS_BLOCKED",
                "激活模板版本含依赖尚未就绪财务报表的文件，整包未受理",
                status_code=409,
                details=details,
            )

    for item, manifest in manifests:
        document_code = str(item.get("document_code") or "template")
        try:
            validate_semantic_manifest_facts(manifest, registry)
            deterministic_slots = tuple(
                binding
                for binding in manifest.slots
                if binding.composition_mode == "deterministic"
            )
            if deterministic_slots:
                prepare_attachment(
                    manifest.model_copy(update={"slots": list(deterministic_slots)}),
                    context,
                    registry,
                )
        except MissingFactError as exc:
            raise AttachmentJobError(
                "REQUIRED_FACT_MISSING",
                f"模板 {document_code} 缺少必填事实：{exc}",
                status_code=409,
            ) from exc
        except ConflictedFactError as exc:
            raise AttachmentJobError(
                "FACT_CONFLICTED",
                f"模板 {document_code} 存在未解决的事实冲突：{exc}",
                status_code=409,
            ) from exc
        except (AttachmentContractError, ValidationError) as exc:
            raise AttachmentJobError(
                "GENERATION_CONTEXT_BLOCKED",
                f"模板 {document_code} 与当前冻结上下文不兼容：{exc}",
                status_code=409,
            ) from exc


def _validate_create_request_contract(
    *,
    thread_id: str,
    assistant_turn_id: str,
    request_scope: str,
    delivery_level: str,
) -> tuple[str, str, str, str]:
    normalized_thread_id = str(thread_id or "").strip()
    normalized_assistant_turn_id = str(assistant_turn_id or "").strip()
    normalized_scope = str(request_scope or "").strip()
    normalized_level = str(delivery_level or "").strip()
    if normalized_scope != "all_active_template_files":
        raise AttachmentJobError(
            "UNSUPPORTED_GENERATION_SCOPE",
            "附件生成范围必须为 all_active_template_files",
        )
    if normalized_level not in {"review_draft", "final_candidate", "issued"}:
        raise AttachmentJobError(
            "UNSUPPORTED_DELIVERY_LEVEL",
            "附件交付级别不受支持",
        )
    if bool(normalized_thread_id) != bool(normalized_assistant_turn_id):
        raise AttachmentJobError(
            "CONVERSATION_BINDING_INCOMPLETE",
            "thread_id 与 assistant_turn_id 必须同时提供",
        )
    return (
        normalized_thread_id,
        normalized_assistant_turn_id,
        normalized_scope,
        normalized_level,
    )


def _create_job_with_outbox_or_cleanup(
    *,
    job: dict[str, Any],
    items: list[dict[str, Any]],
    context_storage_ref: str,
    minio: Any,
    settings: Settings,
) -> tuple[dict[str, Any], bool]:
    try:
        return repository.create_job_with_outbox(
            job=job,
            items=items,
            settings=settings,
        )
    except Exception as exc:
        if isinstance(exc, AttachmentJobError):
            raise
        # A PostgreSQL commit can succeed while a later response/read fails.
        # Delete the newly uploaded context only after a separate durable-row
        # lookup proves that this job was not committed. An unavailable lookup
        # intentionally leaves an orphan for retention review instead of
        # breaking a persisted job that still references the object.
        job_persisted: bool | None
        try:
            job_persisted = (
                repository.get_job_by_id(
                    str(job["id"]),
                    include_internal=True,
                    settings=settings,
                )
                is not None
            )
        except Exception:
            job_persisted = None
        if job_persisted is False:
            try:
                minio.delete_object(context_storage_ref)
            except Exception:
                pass
        if isinstance(exc, repository.AttachmentIdempotencyConflictError):
            raise AttachmentJobError(
                "IDEMPOTENCY_KEY_REUSED",
                "幂等键已用于另一组冻结输入",
                status_code=409,
            ) from exc
        raise AttachmentJobError(
            "ATTACHMENT_JOB_PERSIST_FAILED",
            "持久化附件任务失败",
            status_code=503,
        ) from exc


def _job_ref(
    job_id: str,
    engagement_id: int,
    report: dict[str, Any],
    template: dict[str, Any],
    delivery_level: str,
    assistant_turn_id: str,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "case_id": engagement_id,
        "assistant_turn_id": assistant_turn_id,
        "report_id": int(report["id"]),
        "report_version": int(report["report_version"]),
        "template_version_id": str(template["version_id"]),
        "template_version_label": str(template.get("version_label") or ""),
        "delivery_level": delivery_level,
    }


def create_attachment_job(
    *,
    engagement_id: int,
    report_id: int,
    thread_id: str = "",
    assistant_turn_id: str = "",
    request_scope: str = "all_active_template_files",
    delivery_level: str = "review_draft",
    client_idempotency_key: str = "",
    requested_by: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    (
        thread_id,
        assistant_turn_id,
        request_scope,
        delivery_level,
    ) = _validate_create_request_contract(
        thread_id=thread_id,
        assistant_turn_id=assistant_turn_id,
        request_scope=request_scope,
        delivery_level=delivery_level,
    )
    resolved = settings or get_settings()
    report = repository.get_report_version(engagement_id, report_id, settings=resolved)
    if report is None:
        raise AttachmentJobError("REPORT_NOT_FOUND", "指定的冻结报告版本不存在", status_code=404)
    if not report.get("is_latest"):
        raise AttachmentJobError(
            "REPORT_SNAPSHOT_STALE",
            "报告已产生更新版本，请基于最新冻结报告重新生成附件",
            status_code=409,
        )
    template = get_document_template_service().get_active_template_snapshot("annual_audit")
    if template is None:
        raise AttachmentJobError(
            "NO_ACTIVE_TEMPLATE",
            "年度审计当前没有已激活模板",
            status_code=409,
        )
    files = _validate_template_snapshot(template)
    context, registry = _load_generation_context(
        engagement_id=engagement_id,
        report=report,
        settings=resolved,
    )
    _preflight_template_context(files, context=context, registry=registry)
    try:
        model_manifest = build_attachment_model_manifest(files, settings=resolved)
    except (SemanticCompositionError, ValidationError) as exc:
        code = getattr(exc, "code", "ATTACHMENT_MODEL_CONFIG_INVALID")
        raise AttachmentJobError(code, str(exc), status_code=503) from exc
    gate_status = str(context.release_gate.get("gate_status") or "")
    if (
        delivery_level in {"final_candidate", "issued"}
        and gate_status != "ready_for_signature"
    ):
        raise AttachmentJobError(
            "RELEASE_GATE_BLOCKED",
            "项目复核或签发门禁尚未达到 ready",
            status_code=409,
        )
    if delivery_level == "issued":
        raise AttachmentJobError(
            "ISSUED_REQUIRES_SIGNING",
            "正式附件必须通过现有人工签字和签发流程固化",
            status_code=409,
        )
    context_bytes = context.canonical_bytes()
    context_sha = _sha256(context_bytes)
    canonical_input = canonical_json_bytes(
        {
            "engagement_id": engagement_id,
            "report_id": report_id,
            "report_version": report["report_version"],
            "template_version_id": template["version_id"],
            "template_content_sha256": template["content_sha256"],
            "fact_snapshot_sha256": context_sha,
            "request_scope": request_scope,
            "delivery_level": delivery_level,
            "model_manifest": model_manifest,
        }
    )
    fingerprint = _sha256(canonical_input)
    request_key_hash = (
        _sha256(client_idempotency_key.encode("utf-8"))
        if client_idempotency_key
        else ""
    )
    existing_for_key = repository.get_job_by_request_key(
        engagement_id=engagement_id,
        request_idempotency_key_hash=request_key_hash,
        include_internal=True,
        settings=resolved,
    )
    if existing_for_key is not None:
        if str(existing_for_key.get("input_fingerprint") or "") != fingerprint:
            raise AttachmentJobError(
                "IDEMPOTENCY_KEY_REUSED",
                "幂等键已用于另一组冻结输入",
                status_code=409,
            )
        existing = repository.get_job(
            job_id=str(existing_for_key["id"]),
            engagement_id=engagement_id,
            settings=resolved,
        )
        if existing is None:
            raise AttachmentJobError(
                "ATTACHMENT_JOB_NOT_FOUND",
                "幂等附件任务读取失败",
                status_code=503,
            )
        ref = _job_ref(
            str(existing["id"]),
            engagement_id,
            report,
            template,
            delivery_level,
            assistant_turn_id,
        )
        if thread_id and assistant_turn_id:
            try:
                get_conversation_message_repo().merge_assistant_graph_context(
                    thread_id,
                    assistant_turn_id,
                    {"attachment_job": ref},
                )
            except Exception:
                pass
        return {**existing, "attachment_job": ref}
    existing_internal = repository.get_job_by_fingerprint(
        engagement_id=engagement_id,
        input_fingerprint=fingerprint,
        include_internal=True,
        settings=resolved,
    )
    if existing_internal is not None:
        if (
            existing_internal.get("status") in {"queued", "running"}
            and request_key_hash
            and str(existing_internal.get("request_idempotency_key_hash") or "")
            not in {"", request_key_hash}
        ):
            raise AttachmentJobError(
                "GENERATION_IN_PROGRESS",
                "相同冻结输入已有附件任务正在生成",
                status_code=423,
            )
        existing = repository.get_job(
            job_id=str(existing_internal["id"]),
            engagement_id=engagement_id,
            settings=resolved,
        )
        if existing is None:
            raise AttachmentJobError(
                "ATTACHMENT_JOB_NOT_FOUND",
                "幂等附件任务读取失败",
                status_code=503,
            )
        ref = _job_ref(
            str(existing["id"]),
            engagement_id,
            report,
            template,
            delivery_level,
            assistant_turn_id,
        )
        if thread_id and assistant_turn_id:
            try:
                get_conversation_message_repo().merge_assistant_graph_context(
                    thread_id,
                    assistant_turn_id,
                    {"attachment_job": ref},
                )
            except Exception:
                pass
        return {**existing, "attachment_job": ref}

    try:
        require_attachment_model_credentials(model_manifest, settings=resolved)
    except SemanticCompositionError as exc:
        raise AttachmentJobError(exc.code, str(exc), status_code=503) from exc

    minio = get_minio_service()
    job_id = str(uuid4())
    try:
        stored_context = minio.upload_attachment_blob(
            project_id=engagement_id,
            blob_id=job_id,
            category="contexts",
            file_name="generation-context.json",
            content_type="application/json",
            file_bytes=context_bytes,
        )
    except Exception as exc:
        raise AttachmentJobError(
            "OBJECT_STORAGE_UNAVAILABLE",
            "冻结附件生成上下文失败",
            status_code=503,
        ) from exc
    items = [
        {
            "id": str(uuid4()),
            "template_file_id": str(item["id"]),
            "document_code": item["document_code"],
            "display_name": item["display_name"],
            "extension": item["extension"],
            "source_template_sha256": item["source_sha256"],
            "compiled_template_sha256": item["compiled_sha256"],
            "binding_manifest": item["binding_manifest"],
        }
        for item in files
    ]
    renderer_manifest = {
        "docxtpl": _version("docxtpl"),
        "python-docx": _version("python-docx"),
        "openpyxl": _version("openpyxl"),
        "Jinja2": _version("Jinja2"),
        "pypdf": _version("pypdf"),
        "reportlab": _version("reportlab"),
        "image_digest": resolved.attachment_renderer_image_digest,
        "font_manifest_version": resolved.attachment_font_manifest_version,
    }
    job, created = _create_job_with_outbox_or_cleanup(
        job={
            "id": job_id,
            "engagement_id": engagement_id,
            "report_id": report_id,
            "report_version": report["report_version"],
            "thread_id": thread_id or None,
            "assistant_turn_id": assistant_turn_id or None,
            "template_family_id": template["family_id"],
            "template_version_id": template["version_id"],
            "template_snapshot": {**template, "files": files},
            "template_content_sha256": template["content_sha256"],
            "fact_snapshot_ref": stored_context.storage_ref,
            "fact_snapshot_sha256": context_sha,
            "input_fingerprint": fingerprint,
            "request_idempotency_key_hash": (
                request_key_hash
            ),
            "request_scope": request_scope,
            "delivery_level": delivery_level,
            "model_manifest": {
                **model_manifest,
                "client_request_hash": request_key_hash,
            },
            "renderer_manifest": renderer_manifest,
            "requested_by": requested_by or "system",
        },
        items=items,
        context_storage_ref=stored_context.storage_ref,
        minio=minio,
        settings=resolved,
    )
    if not created:
        # A concurrent request won the fingerprint race after this request had
        # already written its unique job-id context object. No durable row can
        # reference this losing object's ref, so it is safe to compensate now.
        try:
            minio.delete_object(stored_context.storage_ref)
        except Exception:
            pass
    actual_job_id = str(job["id"])
    ref = _job_ref(
        actual_job_id,
        engagement_id,
        report,
        template,
        delivery_level,
        assistant_turn_id,
    )
    if thread_id and assistant_turn_id:
        try:
            get_conversation_message_repo().merge_assistant_graph_context(
                thread_id,
                assistant_turn_id,
                {"attachment_job": ref},
            )
        except Exception:
            # The report graph can create a job before the assistant row exists;
            # memory persistence carries the same ref in that path.
            pass
    return {**job, "attachment_job": ref}


def dispatch_pending_outbox(
    *,
    limit: int = 50,
    settings: Settings | None = None,
) -> int:
    resolved = settings or get_settings()
    dispatched = 0
    events = repository.claim_pending_outbox(
        limit=limit,
        stale_after_seconds=max(60, resolved.attachment_job_stale_seconds),
        settings=resolved,
    )
    for event in events:
        try:
            if not resolved.attachment_worker_eager and not resolved.attachment_celery_broker_url.strip():
                raise RuntimeError("attachment Celery broker is not configured")
            from ai_hunter.app.workers.attachment_tasks import generate_attachment_job

            generate_attachment_job.apply_async(
                args=[str(event["job_id"])],
                queue=resolved.attachment_celery_queue,
            )
            if repository.mark_outbox_result(
                int(event["id"]),
                attempt_count=int(event["attempt_count"]),
                published=True,
                settings=resolved,
            ):
                dispatched += 1
        except Exception as exc:
            repository.mark_outbox_result(
                int(event["id"]),
                attempt_count=int(event["attempt_count"]),
                published=False,
                error=f"{type(exc).__name__}: {exc}",
                settings=resolved,
            )
    return dispatched


def process_attachment_job(job_id: str, *, settings: Settings | None = None) -> str:
    """Process a frozen job. The full renderer pipeline is defined below."""

    resolved = settings or get_settings()
    lease_token = str(uuid4())
    if not repository.claim_job_for_processing(
        job_id,
        lease_token=lease_token,
        stale_after_seconds=max(60, resolved.attachment_job_stale_seconds),
        settings=resolved,
    ):
        snapshot = repository.get_job_by_id(job_id, settings=resolved)
        return str((snapshot or {}).get("status") or "missing")
    _process_claimed_job(job_id, lease_token=lease_token, settings=resolved)
    snapshot = repository.get_job_by_id(job_id, settings=resolved)
    return str((snapshot or {}).get("status") or "missing")


def _process_claimed_job(
    job_id: str,
    *,
    lease_token: str,
    settings: Settings,
) -> None:
    # Imports are local so API startup does not require every renderer binary.
    from .worker_pipeline import run_claimed_job

    run_claimed_job(job_id, lease_token=lease_token, settings=settings)


__all__ = [
    "AttachmentJobError",
    "GENERATION_POLICY_VERSION",
    "create_attachment_job",
    "dispatch_pending_outbox",
    "process_attachment_job",
]
