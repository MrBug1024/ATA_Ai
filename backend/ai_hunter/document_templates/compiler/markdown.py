"""Sandbox-oriented Markdown template inspection and compilation."""

from __future__ import annotations

import re
from typing import Any

from .common import (
    compilation_report,
    normalize_binding_manifest,
    validate_jinja_loop_contract,
)
from .jinja_security import analyze_jinja_template
from .models import CompiledTemplate, TemplateCompilationError, TemplateInspection


_RAW_HTML = re.compile(r"<\s*/?\s*[A-Za-z!][^>]*>")
_EXTERNAL_LINK = re.compile(r"\b(?:https?|ftp|file|data|mailto):", re.IGNORECASE)


def inspect_markdown(inspection: TemplateInspection, file_bytes: bytes) -> None:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return
    jinja_report = analyze_jinja_template(text)
    variables = sorted(set(jinja_report.get("undeclared_variables") or []))
    if not jinja_report.get("ok"):
        inspection.threats.append("unsafe_jinja_expression")
    if _RAW_HTML.search(text):
        inspection.threats.append("raw_html")
    if _EXTERNAL_LINK.search(text):
        inspection.threats.append("external_link")
    inspection.threats = sorted(set(inspection.threats))
    inspection.format_details.update(
        {
            "jinja_variables": variables,
            "jinja_security": jinja_report,
            "character_count": len(text),
        }
    )
    inspection.suggested_mapping = {
        "slots": [
            {"target": f"md:jinja:{name}", "suggested_slot_id": name}
            for name in variables
        ]
    }
    if not variables:
        inspection.add_warning("NO_EXECUTABLE_MD_SLOTS", "Markdown has no Jinja variables or loops")


def compile_markdown(
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
        extension=".md",
    )
    available = set(inspection.format_details.get("jinja_variables") or [])
    resolved: list[str] = []
    for slot in manifest["slots"]:
        target = str(slot["target"])
        parts = target.split(":", 2)
        if len(parts) != 3 or parts[1] != "jinja" or parts[2] not in available:
            raise TemplateCompilationError(
                "MARKDOWN_TARGET_NOT_FOUND", f"Markdown variable target does not exist: {target}"
            )
        resolved.append(target)
    bound_variables = {target.split(":", 2)[2] for target in resolved}
    if bound_variables != available:
        raise TemplateCompilationError(
            "MARKDOWN_JINJA_BINDINGS_INCOMPLETE",
            "Markdown Jinja variables must exactly match confirmed bindings",
            details={
                "unbound_variables": sorted(available - bound_variables),
                "unknown_bindings": sorted(bound_variables - available),
            },
        )
    validate_jinja_loop_contract(
        manifest,
        inspection.format_details.get("jinja_security") or {},
        format_name="md",
    )
    report = compilation_report(
        extension=".md",
        manifest=manifest,
        target_report={"resolved_targets": resolved, "status": "passed"},
    )
    return CompiledTemplate(
        content=file_bytes,
        renderer_profile="jinja_sandbox",
        binding_manifest=manifest,
        compilation_report=report,
    )


__all__ = ["compile_markdown", "inspect_markdown"]
