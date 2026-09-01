"""DOCX slot discovery and manifest compilation."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from typing import Any

from defusedxml import ElementTree

from .common import (
    compilation_report,
    normalize_binding_manifest,
    validate_jinja_loop_contract,
)
from .jinja_security import analyze_jinja_template
from .models import CompiledTemplate, TemplateCompilationError, TemplateInspection


_CONTENT_CONTROL = re.compile(
    r"<w:tag\b[^>]*\bw:val=[\"']([^\"']+)[\"']", re.IGNORECASE
)
_BOOKMARK = re.compile(
    r"<w:bookmarkStart\b[^>]*\bw:name=[\"']([^\"']+)[\"']", re.IGNORECASE
)


def _word_xml_payloads(file_bytes: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
        return [
            (name, archive.read(name))
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ]


def _visible_text(payload: bytes) -> str:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return ""
    paragraphs = [node for node in root.iter() if node.tag.endswith("}p")]
    if paragraphs:
        return "\n".join(
            "".join(
                str(text.text or "")
                for text in paragraph.iter()
                if text.tag.endswith("}t")
            )
            for paragraph in paragraphs
        )
    return "".join(
        str(node.text or "") for node in root.iter() if node.tag.endswith("}t")
    )


def inspect_docx(inspection: TemplateInspection, file_bytes: bytes) -> None:
    variables: set[str] = set()
    controls: set[str] = set()
    bookmarks: set[str] = set()
    part_names: list[str] = []
    visible_parts: list[str] = []
    try:
        payloads = _word_xml_payloads(file_bytes)
    except (OSError, zipfile.BadZipFile):
        inspection.add_error("DOCX_UNREADABLE", "DOCX package cannot be reopened")
        return
    for name, payload in payloads:
        part_names.append(name)
        decoded = payload.decode("utf-8", errors="ignore")
        visible = _visible_text(payload)
        visible_parts.append(visible)
        controls.update(value.strip() for value in _CONTENT_CONTROL.findall(decoded) if value.strip())
        bookmarks.update(
            value.strip()
            for value in _BOOKMARK.findall(decoded)
            if value.strip() and not value.startswith("_")
        )
    jinja_report = analyze_jinja_template(
        "\n".join(visible_parts), docxtpl_extensions=True
    )
    variables = set(jinja_report.get("undeclared_variables") or [])
    if not jinja_report.get("ok"):
        inspection.threats.append("unsafe_jinja_expression")
    inspection.threats = sorted(set(inspection.threats))
    inspection.format_details.update(
        {
            "word_parts": sorted(part_names),
            "jinja_variables": sorted(variables),
            "jinja_security": jinja_report,
            "content_controls": sorted(controls),
            "bookmarks": sorted(bookmarks),
            "has_comments": any(name == "word/comments.xml" for name in part_names),
        }
    )
    slots = []
    for value in sorted(variables):
        slots.append({"target": f"docx:jinja:{value}", "suggested_slot_id": value})
    for value in sorted(controls):
        slots.append({"target": f"docx:content-control:{value}", "suggested_slot_id": value})
    for value in sorted(bookmarks):
        slots.append({"target": f"docx:bookmark:{value}", "suggested_slot_id": value})
    inspection.suggested_mapping = {"slots": slots}
    if not slots:
        inspection.add_warning(
            "NO_EXECUTABLE_DOCX_SLOTS",
            "DOCX has no safe Jinja variables, tagged content controls, or bookmarks",
        )


def compile_docx(
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
        extension=".docx",
    )
    details = inspection.format_details
    variables = set(details.get("jinja_variables") or [])
    controls = set(details.get("content_controls") or [])
    bookmarks = set(details.get("bookmarks") or [])
    resolved: list[str] = []
    for slot in manifest["slots"]:
        target = str(slot["target"])
        parts = target.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            raise TemplateCompilationError("INVALID_DOCX_TARGET", f"invalid DOCX target: {target}")
        target_type, value = parts[1], parts[2]
        available = {
            "jinja": variables,
            "content-control": controls,
            "bookmark": bookmarks,
        }.get(target_type)
        if available is None:
            raise TemplateCompilationError(
                "UNSUPPORTED_DOCX_TARGET", f"unsupported DOCX target type: {target_type}"
            )
        if value not in available:
            raise TemplateCompilationError(
                "DOCX_TARGET_NOT_FOUND", f"DOCX target does not exist: {target}"
            )
        resolved.append(target)
    bound_jinja = {
        target.split(":", 2)[2]
        for target in resolved
        if target.startswith("docx:jinja:")
    }
    if bound_jinja != variables:
        missing = sorted(variables - bound_jinja)
        extra = sorted(bound_jinja - variables)
        raise TemplateCompilationError(
            "DOCX_JINJA_BINDINGS_INCOMPLETE",
            "DOCX Jinja variables must exactly match confirmed bindings",
            details={"unbound_variables": missing, "unknown_bindings": extra},
        )
    validate_jinja_loop_contract(
        manifest,
        details.get("jinja_security") or {},
        format_name="docx",
    )
    profile = "docxtpl" if any(target.startswith("docx:jinja:") for target in resolved) else "docx_slots"
    report = compilation_report(
        extension=".docx",
        manifest=manifest,
        target_report={"resolved_targets": resolved, "status": "passed"},
    )
    return CompiledTemplate(
        content=file_bytes,
        renderer_profile=profile,
        binding_manifest=manifest,
        compilation_report=report,
    )


__all__ = ["compile_docx", "inspect_docx"]
