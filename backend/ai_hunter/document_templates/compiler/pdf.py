"""Limited PDF AcroForm and fixed-overlay template compilation."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from .common import compilation_report, normalize_binding_manifest
from .models import CompiledTemplate, TemplateCompilationError, TemplateInspection


_OVERLAY_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_DANGEROUS_PDF_KEYS = {
    "/AA",
    "/EmbeddedFile",
    "/EmbeddedFiles",
    "/JavaScript",
    "/JS",
    "/Launch",
    "/OpenAction",
    "/RichMedia",
    "/URI",
    "/XFA",
}


def _dangerous_keys(value: Any, *, depth: int = 0, seen: set[int] | None = None) -> set[str]:
    if depth > 32:
        return {"/TraversalDepthLimit"}
    seen = seen or set()
    try:
        value = value.get_object()
    except Exception:
        pass
    object_id = id(value)
    if object_id in seen:
        return set()
    seen.add(object_id)
    found: set[str] = set()
    if isinstance(value, dict):
        if len(value) > 2_000:
            found.add("/TraversalItemLimit")
        for key, item in list(value.items())[:2000]:
            key_text = str(key)
            if key_text in _DANGEROUS_PDF_KEYS:
                found.add(key_text)
            found.update(_dangerous_keys(item, depth=depth + 1, seen=seen))
    elif isinstance(value, (list, tuple)):
        if len(value) > 2_000:
            found.add("/TraversalItemLimit")
        for item in list(value)[:2000]:
            found.update(_dangerous_keys(item, depth=depth + 1, seen=seen))
    return found


def inspect_pdf(inspection: TemplateInspection, file_bytes: bytes) -> None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(file_bytes), strict=True)
    except Exception:
        inspection.add_error("PDF_UNREADABLE", "pypdf cannot reopen the PDF")
        return
    if reader.is_encrypted:
        inspection.threats.append("encrypted_or_password_protected_content")
        fields: dict[str, Any] = {}
        page_count = 0
        page_sizes: list[dict[str, float]] = []
    else:
        try:
            fields = dict(reader.get_fields() or {})
        except Exception:
            fields = {}
        try:
            root = reader.trailer.get("/Root") or {}
            dangerous = _dangerous_keys(root)
        except Exception:
            dangerous = set()
        if dangerous:
            inspection.threats.extend(f"pdf_active_content:{key}" for key in sorted(dangerous))
        page_count = len(reader.pages)
        page_sizes = [
            {
                "width": float(page.mediabox.width),
                "height": float(page.mediabox.height),
            }
            for page in reader.pages
        ]
    inspection.threats = sorted(set(inspection.threats))
    inspection.format_details.update(
        {
            "page_count": page_count,
            "page_sizes": page_sizes,
            "acroform_fields": sorted(str(name) for name in fields),
            "acroform_field_types": {
                str(name): str((field or {}).get("/FT") or "")
                for name, field in fields.items()
                if isinstance(field, dict)
            },
            "has_acroform": bool(fields),
        }
    )
    inspection.suggested_mapping = {
        "slots": [
            {"target": f"pdf:acroform:{name}", "suggested_slot_id": str(name).lower()}
            for name in sorted(fields)
        ]
    }
    if not fields:
        inspection.add_warning(
            "PDF_COORDINATE_CONTRACT_REQUIRED",
            "PDF has no AcroForm fields; every dynamic slot needs an approved overlay contract",
        )


def compile_pdf(
    *,
    file_bytes: bytes,
    inspection: TemplateInspection,
    document_code: str,
    binding_manifest: dict[str, Any],
) -> CompiledTemplate:
    manifest = normalize_binding_manifest(
        binding_manifest,
        document_code=document_code,
        source_sha256=inspection.source_sha256,
        extension=".pdf",
    )
    fields = set(inspection.format_details.get("acroform_fields") or [])
    field_types = dict(inspection.format_details.get("acroform_field_types") or {})
    page_count = int(inspection.format_details.get("page_count") or 0)
    page_sizes = list(inspection.format_details.get("page_sizes") or [])
    resolved: list[str] = []
    target_types: set[str] = set()
    for slot in manifest["slots"]:
        target = str(slot["target"])
        parts = target.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            raise TemplateCompilationError("INVALID_PDF_TARGET", f"invalid PDF target: {target}")
        target_type, value = parts[1], parts[2]
        if target_type == "acroform":
            if value not in fields:
                raise TemplateCompilationError(
                    "PDF_FIELD_NOT_FOUND", f"PDF AcroForm field does not exist: {value}"
                )
            if field_types.get(value) == "/Sig":
                raise TemplateCompilationError(
                    "PDF_SIGNATURE_FIELD_UNSUPPORTED",
                    f"PDF signature field cannot be used as a content slot: {value}",
                )
        elif target_type == "overlay":
            if not _OVERLAY_NAME.fullmatch(value):
                raise TemplateCompilationError(
                    "INVALID_PDF_OVERLAY", f"invalid PDF overlay target: {target}"
                )
            options = slot.get("options") or {}
            try:
                page = int(options["page"])
                x = float(options["x"])
                y = float(options["y"])
                width = float(options["width"])
                height = float(options["height"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TemplateCompilationError(
                    "PDF_OVERLAY_COORDINATES_REQUIRED",
                    f"overlay slot {slot['slot_id']} requires numeric page/x/y/width/height options",
                ) from exc
            if page < 1 or page > page_count or min(x, y) < 0 or min(width, height) <= 0:
                raise TemplateCompilationError(
                    "INVALID_PDF_OVERLAY", f"invalid PDF overlay bounds: {target}"
                )
            page_size = page_sizes[page - 1] if page <= len(page_sizes) else {}
            if (
                float(page_size.get("width") or 0) > 0
                and x + width > float(page_size["width"])
            ) or (
                float(page_size.get("height") or 0) > 0
                and y + height > float(page_size["height"])
            ):
                raise TemplateCompilationError(
                    "PDF_OVERLAY_OUT_OF_PAGE",
                    f"overlay slot {slot['slot_id']} exceeds the selected PDF page",
                )
            if not str(options.get("font_name") or "").strip():
                raise TemplateCompilationError(
                    "PDF_OVERLAY_FONT_REQUIRED", f"overlay slot {slot['slot_id']} requires font_name"
                )
            if float(options.get("font_size") or 0) <= 0 or int(options.get("max_lines") or 0) <= 0:
                raise TemplateCompilationError(
                    "PDF_OVERLAY_BOUNDS_REQUIRED",
                    f"overlay slot {slot['slot_id']} requires font_size and max_lines",
                )
            if str(slot.get("overflow_policy") or "") not in {"error", "shrink_font", "truncate"}:
                raise TemplateCompilationError(
                    "PDF_OVERLAY_OVERFLOW_REQUIRED",
                    f"overlay slot {slot['slot_id']} requires an explicit overflow_policy",
                )
        else:
            raise TemplateCompilationError(
                "UNSUPPORTED_PDF_TARGET", f"unsupported PDF target type: {target_type}"
            )
        target_types.add(target_type)
        resolved.append(target)
    renderer_profile = "pdf_acroform" if target_types == {"acroform"} else "pdf_overlay"
    report = compilation_report(
        extension=".pdf",
        manifest=manifest,
        target_report={"resolved_targets": resolved, "status": "passed"},
    )
    return CompiledTemplate(
        content=file_bytes,
        renderer_profile=renderer_profile,
        binding_manifest=manifest,
        compilation_report=report,
    )


__all__ = ["compile_pdf", "inspect_pdf"]
