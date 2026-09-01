"""Limited PDF renderer for AcroForm fields and explicit coordinate overlays."""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from ..content_schemas import (
    AttachmentContractError,
    AttachmentRenderError,
    BindingManifest,
    MissingRendererDependency,
    RenderResult,
    ResolvedDocumentPayload,
    SlotBinding,
    ensure_payload_matches_manifest,
    verify_source_template,
)


PDF_CONTENT_TYPE = "application/pdf"
PDF_CJK_FONT_NAME = "NotoSansCJKsc-Regular"
_PDF_FONT_ROOT_ENV = "ATTACHMENT_PDF_FONT_ROOT"
_PDF_CJK_FONT_RELATIVE_PATH = Path("opentype/noto/NotoSansCJK-Regular.ttc")
_PDF_CJK_FONT_SUBFONT_INDEX = 2
_FONT_REGISTRATION_LOCK = threading.Lock()


@dataclass(frozen=True)
class _DrawCommand:
    page_index: int
    text: str
    x: float
    y: float
    width: float
    height: float
    binding: SlotBinding


@dataclass(frozen=True)
class _Widget:
    page_index: int
    name: str
    field_type: str
    rect: tuple[float, float, float, float]
    current_value: str


def render_pdf(
    template_bytes: bytes,
    payload: ResolvedDocumentPayload,
    manifest: BindingManifest,
) -> RenderResult:
    """Fill a PDF without attempting free-form static-text replacement.

    ``pdf:acroform:<field>`` binds to a named form widget.  The value is drawn
    at the widget rectangle and widgets are removed, yielding a flattened PDF.
    ``pdf:overlay:<name>`` requires page/x/y coordinates in binding options.
    """

    ensure_payload_matches_manifest(payload, manifest)
    source_sha = verify_source_template(template_bytes, manifest)
    if not template_bytes.startswith(b"%PDF-"):
        raise AttachmentContractError("PDF template has an invalid header")
    try:
        reader = PdfReader(BytesIO(template_bytes), strict=True)
    except Exception as exc:
        raise AttachmentContractError("PDF template cannot be opened") from exc
    if reader.is_encrypted:
        raise AttachmentContractError("encrypted PDF templates are not supported")

    widgets = _collect_widgets(reader)
    commands: list[_DrawCommand] = []
    bound_fields: dict[str, tuple[str, SlotBinding]] = {}
    overlay_bindings: list[tuple[SlotBinding, Any]] = []
    for binding in manifest.slots:
        slot = payload.slot_map.get(binding.slot_id)
        if slot is None:
            continue
        format_name, target_kind, locator = binding.target.split(":", 2)
        if format_name != "pdf":
            raise AttachmentContractError(f"non-PDF target in PDF manifest: {binding.target}")
        if slot.kind == "table_rows":
            raise AttachmentContractError("PDF fields and overlays do not accept table_rows")
        value = _slot_text(slot.kind, slot.value)
        if target_kind in {"acroform", "form"}:
            if not locator:
                raise AttachmentContractError("PDF AcroForm field name is blank")
            bound_fields[locator] = (value, binding)
        elif target_kind == "overlay":
            overlay_bindings.append((binding, value))
        else:
            raise AttachmentContractError(f"unsupported PDF binding target: {binding.target}")

    known_fields = {widget.name for widget in widgets}
    missing_fields = sorted(set(bound_fields) - known_fields)
    if missing_fields:
        raise AttachmentContractError(
            f"PDF AcroForm fields were not found: {', '.join(missing_fields)}"
        )
    for widget in widgets:
        if widget.field_type == "/Sig":
            raise AttachmentContractError("PDF signature fields cannot be flattened by this renderer")
        text, binding = bound_fields.get(
            widget.name,
            (widget.current_value, _default_form_binding(widget.name)),
        )
        if not text:
            continue
        x1, y1, x2, y2 = widget.rect
        commands.append(
            _DrawCommand(
                page_index=widget.page_index,
                text=_button_value(text) if widget.field_type == "/Btn" else text,
                x=x1,
                y=y1,
                width=max(1.0, x2 - x1),
                height=max(1.0, y2 - y1),
                binding=binding,
            )
        )

    for binding, value in overlay_bindings:
        options = binding.options
        locator = binding.target.split(":", 2)[2]
        locator_parts = locator.split(":")
        try:
            if len(locator_parts) == 5:
                page_index = int(locator_parts[0]) - 1
                x = float(locator_parts[1])
                y = float(locator_parts[2])
                width = float(locator_parts[3])
                height = float(locator_parts[4])
            else:
                page_index = int(options["page"]) - 1
                x = float(options["x"])
                y = float(options["y"])
                width = float(options.get("width") or 0)
                height = float(options.get("height") or 0)
        except (KeyError, TypeError, ValueError) as exc:
            raise AttachmentContractError(
                f"PDF overlay {binding.slot_id} requires a page:x:y:width:height locator"
            ) from exc
        if page_index < 0 or page_index >= len(reader.pages):
            raise AttachmentContractError(f"PDF overlay page is out of range: {page_index + 1}")
        page = reader.pages[page_index]
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        width = width or float(options.get("width") or max(1.0, page_width - x))
        height = height or float(options.get("height") or max(1.0, page_height - y))
        if options.get("y_from_top"):
            y = page_height - y - height
        commands.append(
            _DrawCommand(
                page_index=page_index,
                text=str(value),
                x=x,
                y=y,
                width=width,
                height=height,
                binding=binding,
            )
        )

    for command in commands:
        rotation = int(reader.pages[command.page_index].get("/Rotate", 0) or 0) % 360
        if rotation:
            raise AttachmentContractError(
                "rotated PDF pages require an explicit transformed-coordinate profile"
            )

    overlay = _build_overlay(reader, commands)
    overlay_reader = PdfReader(BytesIO(overlay), strict=True)
    writer = PdfWriter()
    try:
        writer.clone_document_from_reader(reader)
        for page_index, page in enumerate(writer.pages):
            page.merge_page(overlay_reader.pages[page_index], over=True)
            _strip_widget_annotations(page)
        writer.root_object.pop(NameObject("/AcroForm"), None)
        output = BytesIO()
        writer.write(output)
        rendered = output.getvalue()
        reopened = PdfReader(BytesIO(rendered), strict=True)
        if len(reopened.pages) != len(reader.pages):
            raise AttachmentRenderError("rendered PDF page count changed unexpectedly")
    except AttachmentContractError:
        raise
    except Exception as exc:
        if isinstance(exc, AttachmentRenderError):
            raise
        raise AttachmentRenderError("PDF rendering or flattening failed") from exc

    return RenderResult(
        data=rendered,
        extension=".pdf",
        content_type=PDF_CONTENT_TYPE,
        source_template_sha256=source_sha,
        warnings=("AcroForm widgets were flattened into deterministic overlays",) if widgets else (),
    )


def _collect_widgets(reader: PdfReader) -> list[_Widget]:
    widgets: list[_Widget] = []
    for page_index, page in enumerate(reader.pages):
        for reference in page.get("/Annots", ()) or ():
            annotation = reference.get_object()
            if str(annotation.get("/Subtype") or "") != "/Widget":
                continue
            parent_ref = annotation.get("/Parent")
            parent = parent_ref.get_object() if parent_ref is not None else {}
            name = str(annotation.get("/T") or parent.get("/T") or "").strip()
            field_type = str(annotation.get("/FT") or parent.get("/FT") or "")
            rect_value = annotation.get("/Rect")
            if not name or rect_value is None or len(rect_value) != 4:
                raise AttachmentContractError("PDF contains an unnamed or unpositioned form widget")
            current = annotation.get("/V")
            if current is None:
                current = parent.get("/V")
            widgets.append(
                _Widget(
                    page_index=page_index,
                    name=name,
                    field_type=field_type,
                    rect=tuple(float(item) for item in rect_value),
                    current_value="" if current is None else str(current).lstrip("/"),
                )
            )
    return widgets


def _build_overlay(reader: PdfReader, commands: list[_DrawCommand]) -> bytes:
    try:
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise MissingRendererDependency("ReportLab is required for PDF overlays") from exc

    output = BytesIO()
    drawing = canvas.Canvas(output, pageCompression=1)
    by_page: dict[int, list[_DrawCommand]] = {}
    for command in commands:
        by_page.setdefault(command.page_index, []).append(command)
    for page_index, page in enumerate(reader.pages):
        page_size = (float(page.mediabox.width), float(page.mediabox.height))
        drawing.setPageSize(page_size)
        for command in by_page.get(page_index, ()):
            _draw_text(drawing, command)
        drawing.showPage()
    drawing.save()
    return output.getvalue()


def _draw_text(drawing, command: _DrawCommand) -> None:
    try:
        from reportlab.pdfbase import pdfmetrics
    except ImportError as exc:
        raise MissingRendererDependency("ReportLab is required for PDF overlays") from exc

    options = command.binding.options
    font_name = str(options.get("font_name") or "Helvetica")
    font_size = float(options.get("font_size") or 10.0)
    minimum_font_size = float(options.get("minimum_font_size") or 6.0)
    leading_factor = float(options.get("leading_factor") or 1.2)
    alignment = str(options.get("alignment") or "left").lower()
    max_lines = int(options.get("max_lines") or max(1, command.height // (font_size * leading_factor)))
    if any(ord(character) > 127 for character in command.text) and font_name != PDF_CJK_FONT_NAME:
        raise AttachmentContractError(
            f"PDF non-ASCII content requires the approved font: {PDF_CJK_FONT_NAME}"
        )
    _ensure_contract_font(font_name, pdfmetrics)

    while True:
        lines = _wrap_text(command.text, command.width, font_name, font_size, pdfmetrics)
        line_height = font_size * leading_factor
        fits = len(lines) <= max_lines and len(lines) * line_height <= command.height
        if fits:
            break
        if command.binding.overflow_policy == "truncate":
            lines = lines[:max_lines]
            if lines:
                lines[-1] = _truncate_line(lines[-1], command.width, font_name, font_size, pdfmetrics)
            break
        if command.binding.overflow_policy == "shrink_font" and font_size > minimum_font_size:
            font_size = max(minimum_font_size, font_size - 0.5)
            continue
        raise AttachmentRenderError(
            f"PDF content exceeds the declared overlay rectangle for slot {command.binding.slot_id}"
        )

    drawing.setFont(font_name, font_size)
    baseline = command.y + command.height - font_size
    for line in lines:
        text_width = pdfmetrics.stringWidth(line, font_name, font_size)
        if alignment == "center":
            x = command.x + max(0.0, (command.width - text_width) / 2)
        elif alignment == "right":
            x = command.x + max(0.0, command.width - text_width)
        else:
            x = command.x
        drawing.drawString(x, baseline, line)
        baseline -= font_size * leading_factor


def _ensure_contract_font(font_name: str, pdfmetrics: Any) -> None:
    try:
        pdfmetrics.getFont(font_name)
        return
    except KeyError:
        pass

    if font_name != PDF_CJK_FONT_NAME:
        raise AttachmentContractError(f"PDF contract font is not installed: {font_name}")

    font_root = Path(os.getenv(_PDF_FONT_ROOT_ENV, "/usr/share/fonts")).resolve()
    font_path = (font_root / _PDF_CJK_FONT_RELATIVE_PATH).resolve()
    try:
        font_path.relative_to(font_root)
    except ValueError as exc:
        raise AttachmentContractError("PDF contract font path escapes the configured font root") from exc
    if not font_path.is_file():
        raise AttachmentContractError(
            f"PDF contract font is not installed: {font_name}"
        )

    try:
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as exc:
        raise MissingRendererDependency("ReportLab TrueType font support is required") from exc

    with _FONT_REGISTRATION_LOCK:
        try:
            pdfmetrics.getFont(font_name)
            return
        except KeyError:
            pass
        try:
            pdfmetrics.registerFont(
                TTFont(
                    font_name,
                    str(font_path),
                    subfontIndex=_PDF_CJK_FONT_SUBFONT_INDEX,
                )
            )
        except Exception as exc:
            raise AttachmentContractError(
                f"PDF contract font cannot be registered: {font_name}"
            ) from exc


def _wrap_text(text: str, width: float, font_name: str, font_size: float, pdfmetrics) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        tokens = paragraph.split(" ") if " " in paragraph else list(paragraph)
        separator = " " if " " in paragraph else ""
        for token in tokens:
            candidate = token if not current else f"{current}{separator}{token}"
            if not current or pdfmetrics.stringWidth(candidate, font_name, font_size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = token
        lines.append(current)
    return lines or [""]


def _truncate_line(line: str, width: float, font_name: str, font_size: float, pdfmetrics) -> str:
    suffix = "..."
    result = line
    while result and pdfmetrics.stringWidth(f"{result}{suffix}", font_name, font_size) > width:
        result = result[:-1]
    return f"{result}{suffix}" if result != line else result


def _strip_widget_annotations(page) -> None:
    annotations = page.get("/Annots")
    if not annotations:
        return
    retained = [
        reference
        for reference in annotations
        if str(reference.get_object().get("/Subtype") or "") != "/Widget"
    ]
    if retained:
        annotations.clear()
        annotations.extend(retained)
    else:
        page.pop(NameObject("/Annots"), None)


def _slot_text(kind: str, value: Any) -> str:
    if kind == "narrative_blocks":
        return "\n".join(str(block.get("text") or "") for block in value)
    return "" if value is None else str(value)


def _button_value(value: str) -> str:
    return "" if value.strip().lower() in {"", "0", "false", "off", "no"} else "X"


def _default_form_binding(field_name: str) -> SlotBinding:
    return SlotBinding(
        slot_id=f"field.{hashlib.sha256(field_name.encode('utf-8')).hexdigest()[:16]}",
        target=f"pdf:acroform:{field_name}",
        value_type="scalar",
        required=False,
        missing_policy="empty",
        overflow_policy="shrink_font",
        options={},
    )


__all__ = ["PDF_CONTENT_TYPE", "render_pdf"]
