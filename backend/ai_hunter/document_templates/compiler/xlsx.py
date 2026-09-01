"""XLSX named-range, table, and fixed-range template compilation."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from typing import Any

from defusedxml import ElementTree

from .common import compilation_report, normalize_binding_manifest
from .models import CompiledTemplate, TemplateCompilationError, TemplateInspection


_CELL = re.compile(r"^(?:'([^']+)'|([^!]+))!\$?[A-Z]{1,3}\$?[1-9][0-9]*$")
_RANGE = re.compile(
    r"^(?:'([^']+)'|([^!]+))!\$?[A-Z]{1,3}\$?[1-9][0-9]*:\$?[A-Z]{1,3}\$?[1-9][0-9]*$"
)
_EXTERNAL_FORMULA = re.compile(
    r"(?:\[[^\]]+\][^!\r\n]*!|(?:https?|ftp|file)://)", re.IGNORECASE
)
_DDE_FORMULA = re.compile(r"(?:^|[=+\-(,])\s*(?:dde|cmd|powershell)?[^\r\n]*\|[^\r\n]*!", re.IGNORECASE)


def _root(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    return ElementTree.fromstring(archive.read(name))


def inspect_xlsx(inspection: TemplateInspection, file_bytes: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            workbook = _root(archive, "xl/workbook.xml")
            sheets = [
                str(node.attrib.get("name") or "")
                for node in workbook.iter()
                if node.tag.endswith("}sheet") and node.attrib.get("name")
            ]
            defined_names = {
                str(node.attrib.get("name") or "")
                for node in workbook.iter()
                if node.tag.endswith("}definedName") and node.attrib.get("name")
            }
            tables: set[str] = set()
            table_refs: dict[str, str] = {}
            formula_count = 0
            unsafe_formula_types: set[str] = set()
            for name in archive.namelist():
                lowered = name.lower()
                if lowered.startswith("xl/tables/") and lowered.endswith(".xml"):
                    table = _root(archive, name)
                    table_name = str(
                        table.attrib.get("displayName") or table.attrib.get("name") or ""
                    )
                    if table_name:
                        tables.add(table_name)
                        table_refs[table_name] = str(table.attrib.get("ref") or "")
                elif lowered.startswith("xl/worksheets/") and lowered.endswith(".xml"):
                    sheet = _root(archive, name)
                    formulas = [
                        str(node.text or "")
                        for node in sheet.iter()
                        if node.tag.endswith("}f")
                    ]
                    formula_count += len(formulas)
                    if any(_EXTERNAL_FORMULA.search(formula) for formula in formulas):
                        unsafe_formula_types.add("xlsx_external_formula_reference")
                    if any(_DDE_FORMULA.search(formula) for formula in formulas):
                        unsafe_formula_types.add("xlsx_dde_formula")
    except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError):
        inspection.add_error("XLSX_UNREADABLE", "XLSX package cannot be reopened")
        return

    try:
        from openpyxl import load_workbook

        workbook_object = load_workbook(BytesIO(file_bytes), read_only=False, data_only=False, keep_links=False)
        workbook_object.close()
    except Exception:
        inspection.add_error("XLSX_OPENPYXL_REOPEN_FAILED", "openpyxl cannot reopen the workbook")
        return
    inspection.threats.extend(sorted(unsafe_formula_types))
    inspection.threats = sorted(set(inspection.threats))
    inspection.format_details.update(
        {
            "sheets": sheets,
            "defined_names": sorted(defined_names),
            "tables": sorted(tables),
            "table_refs": table_refs,
            "formula_count": formula_count,
        }
    )
    suggestions = [
        {"target": f"xlsx:named-range:{name}", "suggested_slot_id": name.lower()}
        for name in sorted(defined_names)
        if not name.startswith("_xlnm.")
    ]
    suggestions.extend(
        {"target": f"xlsx:table:{name}", "suggested_slot_id": name.lower()}
        for name in sorted(tables)
    )
    inspection.suggested_mapping = {"slots": suggestions}
    if not suggestions:
        inspection.add_warning(
            "NO_EXECUTABLE_XLSX_SLOTS",
            "XLSX has no named ranges or Excel tables; fixed ranges require explicit mapping",
        )


def _sheet_from_address(value: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.fullmatch(value)
    if not match:
        return None
    return str(match.group(1) or match.group(2) or "")


def compile_xlsx(
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
        extension=".xlsx",
    )
    sheets = set(inspection.format_details.get("sheets") or [])
    defined_names = set(inspection.format_details.get("defined_names") or [])
    tables = set(inspection.format_details.get("tables") or [])
    resolved: list[str] = []
    for slot in manifest["slots"]:
        target = str(slot["target"])
        parts = target.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            raise TemplateCompilationError("INVALID_XLSX_TARGET", f"invalid XLSX target: {target}")
        target_type, value = parts[1], parts[2]
        if target_type == "named-range":
            valid = value in defined_names
        elif target_type == "table":
            valid = value in tables
        elif target_type == "cell":
            sheet_name = _sheet_from_address(value, _CELL)
            valid = bool(sheet_name and sheet_name in sheets)
        elif target_type == "range":
            sheet_name = _sheet_from_address(value, _RANGE)
            valid = bool(sheet_name and sheet_name in sheets)
        else:
            raise TemplateCompilationError(
                "UNSUPPORTED_XLSX_TARGET", f"unsupported XLSX target type: {target_type}"
            )
        if not valid:
            raise TemplateCompilationError(
                "XLSX_TARGET_NOT_FOUND", f"XLSX target does not exist: {target}"
            )
        if slot.get("value_type") == "table_rows" and target_type not in {"table", "range"}:
            raise TemplateCompilationError(
                "XLSX_TABLE_TARGET_REQUIRED", f"table_rows slot {slot['slot_id']} needs a table or range"
            )
        resolved.append(target)
    report = compilation_report(
        extension=".xlsx",
        manifest=manifest,
        target_report={"resolved_targets": resolved, "status": "passed"},
    )
    return CompiledTemplate(
        content=file_bytes,
        renderer_profile="openpyxl",
        binding_manifest=manifest,
        compilation_report=report,
    )


__all__ = ["compile_xlsx", "inspect_xlsx"]
