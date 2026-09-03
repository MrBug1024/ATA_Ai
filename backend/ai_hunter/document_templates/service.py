"""Application service for governed document template versions and files."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import PurePath
from typing import Any, Protocol
from uuid import UUID, uuid4

import httpx

from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.app.services.pdf_validation import PdfValidationError, validate_pdf_bytes
from ai_hunter.app.settings import Settings, get_settings

from .compiler import compile_template, inspect_template
from .compiler.models import TemplateCompilationError, sha256_bytes
from .compiler.security import safe_display_file_name
from .integrity import stable_template_content_hash
from .repository import (
    DocumentTemplateRepository,
    TemplateRevisionConflictError,
    TemplateValidationStateError,
)


BUSINESS_TYPE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "code": "annual_audit",
        "label": "年度审计",
        "generator_enabled": True,
        "supported_formats": [".docx", ".xlsx", ".md", ".pdf"],
        "required_profile": [
            "engagement",
            "entity_facts",
            "report_snapshot",
            "audit_program",
            "evidence_manifest",
        ],
    },
    {
        "code": "bookkeeping",
        "label": "代理记账",
        "generator_enabled": False,
        "supported_formats": [".docx", ".xlsx", ".md", ".pdf"],
        "required_profile": [],
    },
    {
        "code": "tax_service",
        "label": "税务服务",
        "generator_enabled": False,
        "supported_formats": [".docx", ".xlsx", ".md", ".pdf"],
        "required_profile": [],
    },
)
_BUSINESS_TYPES = {item["code"]: item for item in BUSINESS_TYPE_CATALOG}
_DOCUMENT_CODE = re.compile(r"^[a-z][a-z0-9_]{1,127}$")


class TemplateStorage(Protocol):
    def upload_template(
        self,
        *,
        template_version_id: str,
        template_file_id: str,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
        variant: str,
    ): ...

    def get_object_bytes(self, storage_ref: str) -> bytes: ...

    def delete_object(self, storage_ref: str) -> bool: ...


class TemplateServiceError(RuntimeError):
    code = "TEMPLATE_SERVICE_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class TemplateServiceValidationError(TemplateServiceError):
    code = "TEMPLATE_VALIDATION_FAILED"


class TemplateStorageError(TemplateServiceError):
    code = "TEMPLATE_STORAGE_UNAVAILABLE"


def _actor(value: str) -> str:
    return str(value or "system").strip() or "system"


def _business_type(code: str) -> dict[str, Any]:
    normalized = str(code or "").strip().lower()
    profile = _BUSINESS_TYPES.get(normalized)
    if profile is None:
        raise TemplateServiceValidationError(f"unsupported business_type: {normalized}")
    return profile


def _check_revision(record: dict[str, Any], expected: int) -> None:
    if int(record.get("revision") or 0) != int(expected):
        raise TemplateRevisionConflictError("template revision has changed; refresh and retry")


class DocumentTemplateService:
    def __init__(
        self,
        repository: DocumentTemplateRepository | None = None,
        storage: TemplateStorage | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or DocumentTemplateRepository(self.settings)
        self.storage = storage or get_minio_service()

    def list_business_types(self) -> dict[str, Any]:
        return {"items": [dict(item) for item in BUSINESS_TYPE_CATALOG]}

    def list_versions(self, **filters: Any) -> dict[str, Any]:
        business_type = str(filters.get("business_type") or "").strip().lower()
        if business_type:
            _business_type(business_type)
        template_status = str(filters.get("status") or "").strip().lower()
        if template_status and template_status not in {
            "draft",
            "validating",
            "ready",
            "active",
            "retired",
            "archived",
        }:
            raise TemplateServiceValidationError(f"unsupported template status: {template_status}")
        return self.repository.list_versions(**filters)

    def get_version(self, version_id: UUID | str) -> dict[str, Any]:
        return self.repository.get_version(version_id)

    def create_version(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        _business_type(str(payload.get("business_type") or ""))
        return self.repository.create_version(payload, actor=_actor(actor))

    def update_version(
        self, version_id: UUID | str, payload: dict[str, Any], *, actor: str
    ) -> dict[str, Any]:
        changes = dict(payload)
        revision = int(changes.pop("revision"))
        return self.repository.update_version(
            version_id, changes, revision=revision, actor=_actor(actor)
        )

    def clone_version(
        self, version_id: UUID | str, payload: dict[str, Any], *, actor: str
    ) -> dict[str, Any]:
        return self.repository.clone_version(
            version_id,
            actor=_actor(actor),
            name=payload.get("name"),
            description=payload.get("description"),
        )

    def delete_version(
        self, version_id: UUID | str, *, revision: int, actor: str
    ) -> dict[str, Any]:
        return self.repository.delete_version(
            version_id, revision=revision, actor=_actor(actor)
        )

    def upload_file(
        self,
        version_id: UUID | str,
        *,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
        document_code: str,
        display_name: str,
        sort_order: int,
        actor: str,
    ) -> dict[str, Any]:
        version = self.repository.get_version(version_id)
        if version["status"] != "draft":
            from .repository import TemplateImmutableError

            raise TemplateImmutableError("files can only be uploaded to a draft template version")
        normalized_code = str(document_code or "").strip().lower()
        if not _DOCUMENT_CODE.fullmatch(normalized_code):
            raise TemplateServiceValidationError("document_code must be a stable lowercase code")
        normalized_display = str(display_name or "").strip()
        if (
            not normalized_display
            or len(normalized_display) > 255
            or any(ord(character) < 32 for character in normalized_display)
            or any(character in '<>:"/\\|?*' for character in normalized_display)
        ):
            raise TemplateServiceValidationError("display_name is required and must not exceed 255 characters")
        try:
            normalized_name = safe_display_file_name(file_name)
        except ValueError as exc:
            raise TemplateServiceValidationError(str(exc)) from exc
        inspection = inspect_template(
            file_name=normalized_name,
            content_type=content_type,
            file_bytes=file_bytes,
            settings=self.settings,
        )
        if not inspection.ok:
            raise TemplateServiceValidationError(
                "template upload failed security inspection", details=inspection.to_dict()
            )
        business = _business_type(str(version["business_type"]))
        if inspection.extension not in business["supported_formats"]:
            raise TemplateServiceValidationError(
                f"{inspection.extension} is not supported for {version['business_type']}"
            )
        file_id = uuid4()
        try:
            uploaded = self.storage.upload_template(
                template_version_id=str(version_id),
                template_file_id=str(file_id),
                file_name=normalized_name,
                content_type=inspection.content_type,
                file_bytes=file_bytes,
                variant="source",
            )
        except Exception as exc:
            raise TemplateStorageError("template source upload failed") from exc
        try:
            return self.repository.add_file(
                {
                    "id": file_id,
                    "template_version_id": version_id,
                    "document_code": normalized_code,
                    "display_name": normalized_display,
                    "source_file_name": normalized_name,
                    "extension": inspection.extension,
                    "content_type": inspection.content_type,
                    "size_bytes": len(file_bytes),
                    "source_object_ref": uploaded.storage_ref,
                    "source_sha256": inspection.source_sha256,
                    "inspection_report": inspection.to_dict(),
                    "status": "mapping",
                    "sort_order": int(sort_order),
                },
                actor=_actor(actor),
            )
        except Exception:
            self._cleanup_storage_refs(uploaded.storage_ref)
            raise

    def update_file(
        self, file_id: UUID | str, payload: dict[str, Any], *, actor: str
    ) -> dict[str, Any]:
        changes = dict(payload)
        revision = int(changes.pop("revision"))
        return self.repository.update_file(
            file_id, changes, revision=revision, actor=_actor(actor)
        )

    def delete_file(self, file_id: UUID | str, *, revision: int, actor: str) -> dict[str, Any]:
        return self.repository.delete_file(file_id, revision=revision, actor=_actor(actor))

    def inspect_file(self, file_id: UUID | str, *, actor: str) -> dict[str, Any]:
        record = self.repository.get_file(file_id)
        try:
            source = self.storage.get_object_bytes(record["source_object_ref"])
        except Exception as exc:
            raise TemplateStorageError("template source read failed") from exc
        inspection = inspect_template(
            file_name=record["source_file_name"],
            content_type=record["content_type"],
            file_bytes=source,
            settings=self.settings,
        )
        if inspection.source_sha256 != record["source_sha256"]:
            inspection.add_error("SOURCE_OBJECT_CHANGED", "stored source object SHA no longer matches metadata")
        return self.repository.record_inspection(
            file_id,
            revision=int(record["revision"]),
            inspection_report=inspection.to_dict(),
            actor=_actor(actor),
        )

    def _preview_bytes(self, record: dict[str, Any], compiled_bytes: bytes) -> bytes | None:
        extension = str(record["extension"])
        if extension == ".pdf":
            self._validate_preview_pdf(compiled_bytes)
            return compiled_bytes
        gotenberg_url = str(getattr(self.settings, "attachment_gotenberg_url", "") or "").rstrip("/")
        if not gotenberg_url:
            return None
        timeout = int(getattr(self.settings, "attachment_gotenberg_timeout_seconds", 120) or 120)
        if extension in {".docx", ".xlsx"}:
            endpoint = f"{gotenberg_url}/forms/libreoffice/convert"
            files = {
                "files": (
                    record["source_file_name"],
                    compiled_bytes,
                    record["content_type"],
                )
            }
        elif extension == ".md":
            endpoint = f"{gotenberg_url}/forms/chromium/convert/html"
            markdown_text = compiled_bytes.decode("utf-8")
            page = (
                "<!doctype html><html><head><meta charset='utf-8'></head>"
                f"<body><pre>{html.escape(markdown_text)}</pre></body></html>"
            ).encode("utf-8")
            files = {"files": ("index.html", page, "text/html; charset=utf-8")}
        else:
            return None
        max_preview_bytes = (
            max(1, int(getattr(self.settings, "attachment_preview_max_mb", 200) or 200))
            * 1024
            * 1024
        )
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                with client.stream("POST", endpoint, files=files) as response:
                    response.raise_for_status()
                    declared_size = int(response.headers.get("content-length") or 0)
                    if declared_size > max_preview_bytes:
                        raise TemplateServiceValidationError(
                            "template preview exceeds the configured size limit"
                        )
                    chunks: list[bytes] = []
                    received = 0
                    for chunk in response.iter_bytes():
                        received += len(chunk)
                        if received > max_preview_bytes:
                            raise TemplateServiceValidationError(
                                "template preview exceeds the configured size limit"
                            )
                        chunks.append(chunk)
                    preview = b"".join(chunks)
        except Exception:
            # A preview is an optional convenience in template administration.
            # Source/compiled template validation happens independently below.
            return None
        if not preview.startswith(b"%PDF-"):
            return None
        try:
            self._validate_preview_pdf(preview)
        except TemplateServiceValidationError:
            return None
        return preview

    @staticmethod
    def _validate_preview_pdf(preview: bytes) -> None:
        try:
            validate_pdf_bytes(preview)
        except PdfValidationError as exc:
            raise TemplateServiceValidationError(
                "template preview failed PDF reopen validation"
            ) from exc

    def _cleanup_storage_refs(self, *storage_refs: str) -> None:
        delete_object = getattr(self.storage, "delete_object", None)
        if not callable(delete_object):
            return
        for storage_ref in storage_refs:
            if not storage_ref:
                continue
            try:
                delete_object(storage_ref)
            except Exception:
                pass

    def compile_file(
        self,
        file_id: UUID | str,
        *,
        revision: int,
        binding_manifest: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        record = self.repository.get_file(file_id)
        _check_revision(record, revision)
        try:
            source = self.storage.get_object_bytes(record["source_object_ref"])
        except Exception as exc:
            raise TemplateStorageError("template source read failed") from exc
        inspection = inspect_template(
            file_name=record["source_file_name"],
            content_type=record["content_type"],
            file_bytes=source,
            settings=self.settings,
        )
        if inspection.source_sha256 != record["source_sha256"]:
            inspection.add_error("SOURCE_OBJECT_CHANGED", "stored source object SHA no longer matches metadata")
        if not inspection.ok:
            self.repository.record_inspection(
                file_id,
                revision=revision,
                inspection_report=inspection.to_dict(),
                actor=_actor(actor),
            )
            raise TemplateServiceValidationError(
                "template compile failed security inspection", details=inspection.to_dict()
            )
        try:
            compiled = compile_template(
                file_bytes=source,
                inspection=inspection,
                document_code=record["document_code"],
                binding_manifest=binding_manifest,
            )
        except TemplateCompilationError as exc:
            raise TemplateServiceValidationError(
                exc.message, details={"code": exc.code, **exc.details}
            ) from exc
        compiled_ref = ""
        preview_ref = ""
        try:
            compiled_upload = self.storage.upload_template(
                template_version_id=str(record["template_version_id"]),
                template_file_id=str(record["id"]),
                file_name=record["source_file_name"],
                content_type=record["content_type"],
                file_bytes=compiled.content,
                variant="compiled",
            )
            compiled_ref = str(compiled_upload.storage_ref)
            preview = self._preview_bytes(
                record, compiled.synthetic_content or compiled.content
            )
            preview_upload = None
            if preview is not None:
                preview_upload = self.storage.upload_template(
                    template_version_id=str(record["template_version_id"]),
                    template_file_id=str(record["id"]),
                    file_name=f"{PurePath(record['source_file_name']).stem}.pdf",
                    content_type="application/pdf",
                    file_bytes=preview,
                    variant="preview",
                )
                preview_ref = str(preview_upload.storage_ref)
        except TemplateServiceError:
            self._cleanup_storage_refs(compiled_ref, preview_ref)
            raise
        except Exception as exc:
            self._cleanup_storage_refs(compiled_ref, preview_ref)
            raise TemplateStorageError("compiled template upload failed") from exc
        report = inspection.to_dict()
        report["compilation"] = compiled.compilation_report
        report["mapping_confirmation"] = {
            "status": "confirmed",
            "confirmed_by": _actor(actor),
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        }
        report["renderer_environment"] = {
            "renderer_image_digest": str(
                getattr(self.settings, "attachment_renderer_image_digest", "") or ""
            ),
            "font_manifest_version": str(
                getattr(self.settings, "attachment_font_manifest_version", "") or ""
            ),
        }
        report["preview"] = {
            "status": "passed" if preview is not None else "not_configured",
            "sha256": sha256_bytes(preview) if preview is not None else "",
        }
        try:
            return self.repository.record_compilation(
                file_id,
                revision=revision,
                binding_manifest=compiled.binding_manifest,
                compiled_object_ref=compiled_ref,
                compiled_sha256=compiled.compiled_sha256,
                renderer_profile=compiled.renderer_profile,
                inspection_report=report,
                preview_object_ref=preview_ref,
                preview_sha256=sha256_bytes(preview) if preview is not None else "",
                actor=_actor(actor),
            )
        except Exception:
            self._cleanup_storage_refs(compiled_ref, preview_ref)
            raise

    def validate_version(
        self, version_id: UUID | str, *, revision: int, actor: str
    ) -> dict[str, Any]:
        version = self.repository.get_version(version_id)
        _check_revision(version, revision)
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        files = list(version.get("files") or [])
        if not files:
            blockers.append({"code": "TEMPLATE_FILES_REQUIRED", "message": "template version has no files"})
        profile = _business_type(str(version["business_type"]))
        display_names: set[str] = set()
        file_results: list[dict[str, Any]] = []
        for item in files:
            code = str(item.get("document_code") or "")
            file_blockers: list[dict[str, str]] = []
            file_warnings: list[dict[str, str]] = []

            def block(gate_code: str, message: str) -> None:
                gate = {"code": gate_code, "message": f"{code}: {message}"}
                blockers.append(gate)
                file_blockers.append(gate)

            def warn(gate_code: str, message: str) -> None:
                gate = {"code": gate_code, "message": f"{code}: {message}"}
                warnings.append(gate)
                file_warnings.append(gate)

            if item.get("extension") not in profile["supported_formats"]:
                block("FORMAT_NOT_SUPPORTED", "format is not supported")
            if item.get("status") != "ready":
                block("FILE_NOT_READY", "file is not ready")
            if not item.get("compiled_object_ref") or not item.get("compiled_sha256"):
                block("COMPILED_TEMPLATE_MISSING", "compiled template is missing")
            if not (item.get("binding_manifest") or {}).get("slots"):
                block("BINDING_MANIFEST_MISSING", "binding manifest has no slots")
            inspection = item.get("inspection_report") or {}
            synthetic = (inspection.get("compilation") or {}).get("synthetic_render") or {}
            if (
                not inspection.get("ok")
                or synthetic.get("status") != "passed"
                or (inspection.get("compilation") or {}).get("unresolved_placeholders")
            ):
                block("FILE_VALIDATION_FAILED", "inspection or synthetic render gate failed")
            confirmation = inspection.get("mapping_confirmation") or {}
            if confirmation.get("status") != "confirmed" or not confirmation.get("confirmed_by"):
                block("MAPPING_CONFIRMATION_REQUIRED", "slot mapping is not confirmed")
            if bool(getattr(self.settings, "attachment_clamav_required", False)) and (
                (inspection.get("antivirus") or {}).get("status") != "passed"
            ):
                block("ANTIVIRUS_REQUIRED", "required antivirus result is missing or stale")
            display_key = str(item.get("display_name") or "").casefold()
            if display_key in display_names:
                block("DUPLICATE_DISPLAY_NAME", "file display names must be unique")
            display_names.add(display_key)
            if not item.get("preview_object_ref"):
                warn("PREVIEW_MISSING", "stored PDF preview is unavailable")

            current_preview_sha256 = ""
            try:
                source = self.storage.get_object_bytes(str(item.get("source_object_ref") or ""))
                compiled_object = self.storage.get_object_bytes(
                    str(item.get("compiled_object_ref") or "")
                )
            except Exception:
                block("TEMPLATE_OBJECT_UNAVAILABLE", "source or compiled object is unavailable")
            else:
                if sha256_bytes(source) != item.get("source_sha256"):
                    block("SOURCE_SHA_MISMATCH", "stored source object SHA does not match metadata")
                if sha256_bytes(compiled_object) != item.get("compiled_sha256"):
                    block("COMPILED_SHA_MISMATCH", "stored compiled object SHA does not match metadata")
                current_inspection = inspect_template(
                    file_name=str(item.get("source_file_name") or ""),
                    content_type=str(item.get("content_type") or ""),
                    file_bytes=source,
                    settings=self.settings,
                )
                if not current_inspection.ok:
                    block("CURRENT_SECURITY_INSPECTION_FAILED", "current security inspection failed")
                else:
                    try:
                        current_compilation = compile_template(
                            file_bytes=source,
                            inspection=current_inspection,
                            document_code=code,
                            binding_manifest=item.get("binding_manifest") or {},
                        )
                    except TemplateCompilationError as exc:
                        block(exc.code, exc.message)
                    else:
                        if current_compilation.compiled_sha256 != item.get("compiled_sha256"):
                            block(
                                "COMPILED_TEMPLATE_STALE",
                                "current compiler output differs from the approved compiled SHA",
                            )
                        try:
                            current_preview = self._preview_bytes(
                                item,
                                current_compilation.synthetic_content
                                or current_compilation.content,
                            )
                        except TemplateServiceValidationError as exc:
                            warn("PREVIEW_VALIDATION_FAILED", str(exc))
                        else:
                            if current_preview is None:
                                warn("PREVIEW_RENDERER_UNAVAILABLE", "current preview renderer is unavailable")
                            else:
                                current_preview_sha256 = sha256_bytes(current_preview)

            preview_ref = str(item.get("preview_object_ref") or "")
            if preview_ref:
                try:
                    stored_preview = self.storage.get_object_bytes(preview_ref)
                    self._validate_preview_pdf(stored_preview)
                except Exception:
                    warn("STORED_PREVIEW_INVALID", "stored PDF preview cannot be read or reopened")
                else:
                    if sha256_bytes(stored_preview) != item.get("preview_sha256"):
                        warn("PREVIEW_SHA_MISMATCH", "stored preview SHA does not match metadata")

            file_results.append(
                {
                    "file_id": str(item.get("id") or ""),
                    "document_code": code,
                    "passed": not file_blockers,
                    "current_preview_sha256": current_preview_sha256,
                    "blockers": file_blockers,
                    "warnings": file_warnings,
                }
            )
        content_sha256 = stable_template_content_hash(version)
        report = {
            "validation_version": "document-template-activation-gate-v1",
            "passed": not blockers,
            "business_type": version["business_type"],
            "file_count": len(files),
            "ready_file_count": sum(1 for item in files if item.get("status") == "ready"),
            "content_sha256": content_sha256,
            "blockers": blockers,
            "warnings": warnings,
            "files": file_results,
            "renderer_image_digest": str(
                getattr(self.settings, "attachment_renderer_image_digest", "") or ""
            ),
            "font_manifest_version": str(
                getattr(self.settings, "attachment_font_manifest_version", "") or ""
            ),
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "validated_by": _actor(actor),
        }
        return self.repository.record_validation(
            version_id,
            revision=revision,
            validation_report=report,
            content_sha256=content_sha256,
            passed=not blockers,
            actor=_actor(actor),
        )

    def set_activation(
        self,
        version_id: UUID | str,
        *,
        revision: int,
        active: bool,
        actor: str,
    ) -> dict[str, Any]:
        if active:
            version = self.repository.get_version(version_id)
            _check_revision(version, revision)
            if version.get("status") != "active":
                report = version.get("validation_report") or {}
                if (
                    not report.get("passed")
                    or report.get("content_sha256") != version.get("content_sha256")
                ):
                    raise TemplateValidationStateError(
                        "template must pass current content validation before activation"
                    )
        return self.repository.set_activation(
            version_id,
            revision=revision,
            active=active,
            actor=_actor(actor),
        )

    def get_preview(self, file_id: UUID | str) -> tuple[bytes, str]:
        record = self.repository.get_file(file_id)
        preview_ref = str(record.get("preview_object_ref") or "")
        if not preview_ref:
            raise TemplateServiceValidationError("template preview is not available")
        try:
            preview = self.storage.get_object_bytes(preview_ref)
        except Exception as exc:
            raise TemplateStorageError("template preview read failed") from exc
        if not preview.startswith(b"%PDF-"):
            raise TemplateStorageError("stored template preview is not a PDF")
        expected_sha256 = str(record.get("preview_sha256") or "")
        if expected_sha256 and sha256_bytes(preview) != expected_sha256:
            raise TemplateStorageError("stored template preview SHA does not match metadata")
        self._validate_preview_pdf(preview)
        return preview, f"{PurePath(record['source_file_name']).stem}.pdf"

    def get_active_template_snapshot(
        self, business_type: str = "annual_audit"
    ) -> dict[str, Any] | None:
        _business_type(business_type)
        snapshot = self.repository.get_active_template_snapshot(business_type)
        if snapshot is None:
            return None
        files = []
        for item in snapshot.get("files") or []:
            files.append(
                {
                    "id": str(item["id"]),
                    "document_code": item["document_code"],
                    "display_name": item["display_name"],
                    "source_file_name": item["source_file_name"],
                    "extension": item["extension"],
                    "content_type": item["content_type"],
                    "size_bytes": int(item["size_bytes"]),
                    "source_object_ref": item["source_object_ref"],
                    "source_sha256": item["source_sha256"],
                    "compiled_object_ref": item["compiled_object_ref"],
                    "compiled_sha256": item["compiled_sha256"],
                    "renderer_profile": item["renderer_profile"],
                    "binding_manifest": item["binding_manifest"],
                    "preview_object_ref": item.get("preview_object_ref") or "",
                    "preview_sha256": item.get("preview_sha256") or "",
                    "sort_order": int(item.get("sort_order") or 0),
                    "revision": int(item["revision"]),
                }
            )
        return {
            "family_id": str(snapshot["family_id"]),
            "business_type": snapshot["business_type"],
            "scope_type": snapshot["scope_type"],
            "scope_key": snapshot["scope_key"],
            "family_revision": int(snapshot["family_revision"]),
            "version_id": str(snapshot["version_id"]),
            "version_no": int(snapshot["version_no"]),
            "version_label": snapshot["version_label"],
            "version_revision": int(snapshot["version_revision"]),
            "contract_version": snapshot["contract_version"],
            "content_sha256": snapshot["content_sha256"],
            "manifest": snapshot["manifest"],
            "validation_report": snapshot["validation_report"],
            "files": files,
        }


_SERVICE: DocumentTemplateService | None = None


def get_document_template_service() -> DocumentTemplateService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = DocumentTemplateService()
    return _SERVICE


__all__ = [
    "BUSINESS_TYPE_CATALOG",
    "DocumentTemplateService",
    "TemplateServiceError",
    "TemplateServiceValidationError",
    "TemplateStorageError",
    "get_document_template_service",
]
