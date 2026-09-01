"""Public dispatcher for safe template inspection and compilation."""

from __future__ import annotations

from typing import Any, Callable

from .docx import compile_docx, inspect_docx
from .markdown import compile_markdown, inspect_markdown
from .models import (
    CompiledTemplate,
    TemplateCompilationError,
    TemplateInspection,
    TemplateSecurityLimits,
)
from .pdf import compile_pdf, inspect_pdf
from .security import apply_antivirus_gate, inspect_container
from .xlsx import compile_xlsx, inspect_xlsx


_INSPECTORS: dict[str, Callable[[TemplateInspection, bytes], None]] = {
    ".docx": inspect_docx,
    ".xlsx": inspect_xlsx,
    ".md": inspect_markdown,
    ".pdf": inspect_pdf,
}
_COMPILERS: dict[str, Callable[..., CompiledTemplate]] = {
    ".docx": compile_docx,
    ".xlsx": compile_xlsx,
    ".md": compile_markdown,
    ".pdf": compile_pdf,
}


def _synthetic_slot_value(slot: dict[str, Any]) -> Any:
    slot_id = str(slot["slot_id"])
    value_type = str(slot["value_type"])
    if value_type == "scalar":
        return f"ATA synthetic value for {slot_id}"
    if value_type == "narrative_blocks":
        return [
            {
                "block_id": "synthetic.paragraph",
                "kind": "paragraph",
                "text": f"ATA synthetic narrative for {slot_id}",
                "evidence_refs": [],
            }
        ]
    options = slot.get("options") or {}
    columns = options.get("columns")
    if not isinstance(columns, list) or not columns:
        column_map = options.get("column_map") or {}
        columns = list(column_map.values()) if isinstance(column_map, dict) else []
    if not columns:
        raise TemplateCompilationError(
            "TABLE_COLUMN_CONTRACT_REQUIRED",
            f"table_rows slot {slot_id} has no deterministic column contract",
        )
    return [{str(column): f"ATA synthetic {column}" for column in columns}]


def _run_synthetic_render(
    compiled: CompiledTemplate,
    *,
    inspection: TemplateInspection,
    document_code: str,
) -> CompiledTemplate:
    try:
        from ai_hunter.annual_audit.attachments.content_schemas import (
            BindingManifest,
            ResolvedDocumentPayload,
            ResolvedSlotPayload,
        )
        from ai_hunter.annual_audit.attachments.renderers import RENDERERS

        manifest = BindingManifest.model_validate(compiled.binding_manifest)
        payload = ResolvedDocumentPayload(
            document_code=document_code,
            slots=[
                ResolvedSlotPayload(
                    slot_id=slot["slot_id"],
                    kind=slot["value_type"],
                    value=_synthetic_slot_value(slot),
                )
                for slot in compiled.binding_manifest["slots"]
            ],
        )
        rendered = RENDERERS[inspection.extension](compiled.content, payload, manifest)
    except TemplateCompilationError:
        raise
    except Exception as exc:
        raise TemplateCompilationError(
            "SYNTHETIC_RENDER_FAILED",
            "template failed the deterministic runtime synthetic render gate",
            details={"error_type": type(exc).__name__, "message": str(exc)[:500]},
        ) from exc

    rendered_inspection = inspect_template(
        file_name=f"synthetic{inspection.extension}",
        content_type=rendered.content_type,
        file_bytes=rendered.data,
        antivirus=False,
        limits=TemplateSecurityLimits(
            max_file_bytes=max(len(rendered.data) + 1, 50 * 1024 * 1024),
            max_zip_entries=max(
                int(inspection.format_details.get("zip_entry_count") or 0) + 100,
                2_000,
            ),
            max_uncompressed_bytes=max(
                int(inspection.format_details.get("zip_uncompressed_bytes") or 0) * 2,
                250 * 1024 * 1024,
            ),
            max_entry_bytes=100 * 1024 * 1024,
            max_compression_ratio=200,
            max_xml_bytes=max(
                int(inspection.format_details.get("xml_bytes") or 0) * 2,
                20 * 1024 * 1024,
            ),
        ),
    )
    if not rendered_inspection.ok:
        raise TemplateCompilationError(
            "SYNTHETIC_RENDER_REOPEN_FAILED",
            "synthetic render could not be safely reopened by the format inspector",
            details=rendered_inspection.to_dict(),
        )
    unresolved: list[str] = []
    if inspection.extension in {".docx", ".md"}:
        unresolved = list(
            rendered_inspection.format_details.get("jinja_variables") or []
        )
    if unresolved:
        raise TemplateCompilationError(
            "SYNTHETIC_RENDER_UNRESOLVED_PLACEHOLDER",
            "synthetic render left unresolved Jinja variables",
            details={"unresolved_variables": unresolved},
        )

    report = dict(compiled.compilation_report)
    report["synthetic_render"] = {
        "status": "passed",
        "method": "runtime-renderer-and-format-reopen",
        "output_sha256": rendered.output_sha256,
        "size_bytes": len(rendered.data),
        "modified_parts": list(rendered.modified_parts),
        "warnings": list(rendered.warnings),
        "reopen_signature": rendered_inspection.signature,
    }
    report["unresolved_placeholders"] = []
    return CompiledTemplate(
        content=compiled.content,
        renderer_profile=compiled.renderer_profile,
        binding_manifest=compiled.binding_manifest,
        compilation_report=report,
        synthetic_content=rendered.data,
    )


def inspect_template(
    *,
    file_name: str,
    content_type: str,
    file_bytes: bytes,
    settings: Any | None = None,
    limits: TemplateSecurityLimits | None = None,
    antivirus: bool = True,
) -> TemplateInspection:
    if settings is None:
        from ai_hunter.app.settings import get_settings

        settings = get_settings()
    resolved_limits = limits or TemplateSecurityLimits.from_settings(settings)
    inspection = inspect_container(
        file_name=file_name,
        content_type=content_type,
        file_bytes=file_bytes,
        limits=resolved_limits,
    )
    if antivirus:
        apply_antivirus_gate(
            inspection,
            file_bytes,
            host=str(getattr(settings, "attachment_clamav_host", "") or ""),
            port=int(getattr(settings, "attachment_clamav_port", 3310) or 3310),
            timeout_seconds=int(
                getattr(settings, "attachment_clamav_timeout_seconds", 30) or 30
            ),
            required=bool(getattr(settings, "attachment_clamav_required", False)),
        )
    inspector = _INSPECTORS.get(inspection.extension)
    if inspector is not None and not inspection.errors:
        inspector(inspection, file_bytes)
    inspection.threats = sorted(set(inspection.threats))
    return inspection


def compile_template(
    *,
    file_bytes: bytes,
    inspection: TemplateInspection,
    document_code: str,
    binding_manifest: dict[str, Any],
) -> CompiledTemplate:
    if not inspection.ok:
        raise TemplateCompilationError(
            "TEMPLATE_INSPECTION_FAILED",
            "template cannot be compiled until its security inspection passes",
            details=inspection.to_dict(),
        )
    compiler = _COMPILERS.get(inspection.extension)
    if compiler is None:
        raise TemplateCompilationError(
            "UNSUPPORTED_EXTENSION", f"unsupported template extension: {inspection.extension}"
        )
    compiled = compiler(
        file_bytes=file_bytes,
        inspection=inspection,
        document_code=document_code,
        binding_manifest=binding_manifest,
    )
    compiled = _run_synthetic_render(
        compiled,
        inspection=inspection,
        document_code=document_code,
    )
    reopened = inspect_container(
        file_name=f"compiled{inspection.extension}",
        content_type=inspection.content_type,
        file_bytes=compiled.content,
        limits=TemplateSecurityLimits(
            max_file_bytes=max(len(compiled.content) + 1, 1024),
            max_zip_entries=max(
                int(inspection.format_details.get("zip_entry_count") or 0) + 10, 100
            ),
            max_uncompressed_bytes=max(
                int(inspection.format_details.get("zip_uncompressed_bytes") or 0) + 1024,
                1024 * 1024,
            ),
            max_entry_bytes=max(
                int(inspection.format_details.get("zip_uncompressed_bytes") or 0) + 1024,
                100 * 1024 * 1024,
            ),
            max_compression_ratio=200,
            max_xml_bytes=max(
                int(inspection.format_details.get("xml_bytes") or 0) + 1024,
                1024 * 1024,
            ),
        ),
    )
    if not reopened.ok:
        raise TemplateCompilationError(
            "COMPILED_TEMPLATE_REOPEN_FAILED",
            "compiled template failed deterministic container reopen validation",
            details=reopened.to_dict(),
        )
    return compiled


__all__ = [
    "CompiledTemplate",
    "TemplateCompilationError",
    "TemplateInspection",
    "TemplateSecurityLimits",
    "compile_template",
    "inspect_template",
]
