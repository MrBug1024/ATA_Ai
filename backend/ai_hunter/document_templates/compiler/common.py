"""Shared binding-manifest validation used by all format compilers."""

from __future__ import annotations

import copy
import re
from typing import Any

from .models import TemplateCompilationError, canonical_json, sha256_bytes


_SLOT_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_SOURCE = re.compile(
    r"^document\.[a-z][a-z0-9_]*(?:\[\])?(?:\.[a-z][a-z0-9_]*(?:\[\])?)*$"
)
_VALUE_TYPES = {"scalar", "narrative_blocks", "table_rows"}
_SCALAR_VALUE_ALIASES = {"text", "fact", "date", "amount", "image", "boolean"}
_STYLE_POLICIES = {
    "inherit_template",
    "clone_prototype_row",
    "explicit",
}
_MISSING_POLICIES = {"block", "omit_slot", "omit_sentence", "empty"}
_OVERFLOW_POLICIES = {
    "error",
    "continue_paragraphs",
    "extend_rows",
    "truncate",
    "shrink_font",
}
_DEFAULT_FORBIDDEN_OUTPUT = (
    "[[cite:",
    "evidence_id",
    "chunk_id",
    "claim_id",
    "minio://",
)
_TOP_LEVEL_FIELDS = {
    "contract_version",
    "document_code",
    "source_template_sha256",
    "slots",
    "fixed_regions",
    "forbidden_output_patterns",
    "allowed_modified_parts",
    "binding_sha256",
}
_SLOT_FIELDS = {
    "slot_id",
    "target",
    "source",
    "value_type",
    "style_policy",
    "required",
    "missing_policy",
    "overflow_policy",
    "options",
}
_LEGACY_OPTION_FIELDS = {
    "allow_multiple",
    "columns",
    "font_name",
    "font_size",
    "height",
    "leading_factor",
    "max_lines",
    "minimum_font_size",
    "page",
    "width",
    "x",
    "y",
    "y_from_top",
}


def normalize_binding_manifest(
    raw_manifest: dict[str, Any],
    *,
    document_code: str,
    source_sha256: str,
    extension: str,
) -> dict[str, Any]:
    if not isinstance(raw_manifest, dict):
        raise TemplateCompilationError("INVALID_BINDING_MANIFEST", "binding manifest must be an object")
    manifest = copy.deepcopy(raw_manifest)
    unknown_manifest_fields = sorted(set(manifest) - _TOP_LEVEL_FIELDS)
    if unknown_manifest_fields:
        raise TemplateCompilationError(
            "UNKNOWN_BINDING_MANIFEST_FIELD",
            f"binding manifest contains unsupported fields: {', '.join(unknown_manifest_fields)}",
        )
    contract_version = str(manifest.get("contract_version") or "1.0").strip()
    if contract_version != "1.0":
        raise TemplateCompilationError(
            "UNSUPPORTED_CONTRACT_VERSION", "only binding contract version 1.0 is supported"
        )
    declared_code = str(manifest.get("document_code") or document_code).strip().lower()
    if declared_code != document_code:
        raise TemplateCompilationError(
            "DOCUMENT_CODE_MISMATCH", "binding manifest document_code does not match the template file"
        )
    declared_sha = str(manifest.get("source_template_sha256") or source_sha256).strip().lower()
    if declared_sha != source_sha256:
        raise TemplateCompilationError(
            "SOURCE_TEMPLATE_CHANGED", "binding manifest is bound to a different source template SHA"
        )
    slots = manifest.get("slots")
    if not isinstance(slots, list) or not slots:
        raise TemplateCompilationError(
            "SLOTS_REQUIRED", "binding manifest must declare at least one executable slot"
        )

    normalized_slots: list[dict[str, Any]] = []
    slot_ids: set[str] = set()
    targets: set[str] = set()
    for index, raw_slot in enumerate(slots):
        if not isinstance(raw_slot, dict):
            raise TemplateCompilationError(
                "INVALID_SLOT", f"slot at index {index} must be an object"
            )
        slot = copy.deepcopy(raw_slot)
        unknown_slot_fields = sorted(
            set(slot) - _SLOT_FIELDS - _LEGACY_OPTION_FIELDS
        )
        if unknown_slot_fields:
            raise TemplateCompilationError(
                "UNKNOWN_SLOT_FIELD",
                f"slot at index {index} contains unsupported fields: {', '.join(unknown_slot_fields)}",
            )
        slot_id = str(slot.get("slot_id") or "").strip()
        if not _SLOT_ID.fullmatch(slot_id):
            raise TemplateCompilationError(
                "INVALID_SLOT_ID", f"slot at index {index} has an invalid slot_id"
            )
        if slot_id in slot_ids:
            raise TemplateCompilationError("DUPLICATE_SLOT_ID", f"duplicate slot_id: {slot_id}")
        slot_ids.add(slot_id)
        target = str(slot.get("target") or "").strip()
        if not target.startswith(f"{extension.removeprefix('.')}:"):
            raise TemplateCompilationError(
                "INVALID_SLOT_TARGET", f"slot {slot_id} target does not match {extension}"
            )
        if target in targets:
            raise TemplateCompilationError("DUPLICATE_SLOT_TARGET", f"duplicate slot target: {target}")
        targets.add(target)
        value_type = str(slot.get("value_type") or "scalar").strip()
        if value_type in _SCALAR_VALUE_ALIASES:
            value_type = "scalar"
        if value_type not in _VALUE_TYPES:
            raise TemplateCompilationError(
                "INVALID_VALUE_TYPE", f"slot {slot_id} has unsupported value_type {value_type}"
            )
        style_policy = str(slot.get("style_policy") or "inherit_template").strip()
        if style_policy == "fixed_contract":
            style_policy = "explicit"
        if style_policy not in _STYLE_POLICIES:
            raise TemplateCompilationError(
                "INVALID_STYLE_POLICY", f"slot {slot_id} has unsupported style_policy"
            )
        required = bool(slot.get("required", False))
        missing_policy = str(slot.get("missing_policy") or ("block" if required else "empty"))
        missing_policy = {
            "leave_blank": "empty",
            "display_unavailable": "empty",
            "omit_block": "omit_slot",
        }.get(missing_policy, missing_policy)
        if missing_policy not in _MISSING_POLICIES:
            raise TemplateCompilationError(
                "INVALID_MISSING_POLICY", f"slot {slot_id} has unsupported missing_policy"
            )
        if required and missing_policy != "block":
            raise TemplateCompilationError(
                "REQUIRED_SLOT_MUST_BLOCK", f"required slot {slot_id} must use missing_policy=block"
            )
        overflow_policy = str(slot.get("overflow_policy") or "error").strip()
        overflow_policy = {
            "block": "error",
            "continue_pages": "continue_paragraphs",
            "expand_rows": "extend_rows",
            "shrink_to_min": "shrink_font",
        }.get(overflow_policy, overflow_policy)
        if overflow_policy not in _OVERFLOW_POLICIES:
            raise TemplateCompilationError(
                "INVALID_OVERFLOW_POLICY",
                f"slot {slot_id} has unsupported overflow_policy",
            )
        options = slot.get("options") or {}
        if not isinstance(options, dict):
            raise TemplateCompilationError(
                "INVALID_SLOT_OPTIONS", f"slot {slot_id} options must be an object"
            )
        options = copy.deepcopy(options)
        composition_mode = options.get("composition_mode", "deterministic")
        if composition_mode not in {"deterministic", "semantic"}:
            raise TemplateCompilationError(
                "INVALID_COMPOSITION_MODE",
                f"slot {slot_id} has unsupported composition_mode",
            )
        source = str(slot.get("source") or "").strip()
        if (composition_mode != "semantic" or source) and not _SOURCE.fullmatch(source):
            raise TemplateCompilationError(
                "INVALID_SLOT_SOURCE",
                f"slot {slot_id} source must be a document-scoped structured path",
            )
        for field in _LEGACY_OPTION_FIELDS:
            if field in slot:
                options[field] = slot[field]
        if value_type == "table_rows":
            columns = options.get("columns")
            column_map = options.get("column_map")
            columns_valid = (
                isinstance(columns, list)
                and bool(columns)
                and all(isinstance(item, str) and item.strip() for item in columns)
            )
            column_map_valid = (
                isinstance(column_map, dict)
                and bool(column_map)
                and all(
                    isinstance(key, str)
                    and key.strip()
                    and isinstance(value, str)
                    and value.strip()
                    for key, value in column_map.items()
                )
            )
            if not columns_valid and not column_map_valid:
                raise TemplateCompilationError(
                    "TABLE_COLUMN_CONTRACT_REQUIRED",
                    f"table_rows slot {slot_id} requires options.columns or options.column_map",
                )
        normalized_slots.append(
            {
                "slot_id": slot_id,
                "target": target,
                "source": source,
                "value_type": value_type,
                "style_policy": style_policy,
                "required": required,
                "missing_policy": missing_policy,
                "overflow_policy": overflow_policy,
                "options": options,
            }
        )

    fixed_regions = manifest.get("fixed_regions") or []
    if not isinstance(fixed_regions, list) or not all(
        isinstance(item, str) and item.strip() for item in fixed_regions
    ):
        raise TemplateCompilationError("INVALID_FIXED_REGIONS", "fixed_regions must be a string list")
    patterns = manifest.get("forbidden_output_patterns") or []
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        raise TemplateCompilationError(
            "INVALID_FORBIDDEN_PATTERNS", "forbidden_output_patterns must be a string list"
        )
    forbidden = list(dict.fromkeys([*patterns, *_DEFAULT_FORBIDDEN_OUTPUT]))
    allowed_modified_parts = manifest.get("allowed_modified_parts") or []
    if not isinstance(allowed_modified_parts, list) or not all(
        isinstance(item, str) and item.strip() for item in allowed_modified_parts
    ):
        raise TemplateCompilationError(
            "INVALID_ALLOWED_MODIFIED_PARTS",
            "allowed_modified_parts must be a string list",
        )
    normalized = {
        "contract_version": contract_version,
        "document_code": document_code,
        "source_template_sha256": source_sha256,
        "slots": normalized_slots,
        "fixed_regions": [item.strip() for item in fixed_regions],
        "forbidden_output_patterns": forbidden,
        "allowed_modified_parts": [item.strip() for item in allowed_modified_parts],
    }
    normalized["binding_sha256"] = sha256_bytes(
        canonical_json(normalized).encode("utf-8")
    )
    return normalized


def compilation_report(
    *,
    extension: str,
    manifest: dict[str, Any],
    target_report: dict[str, Any],
) -> dict[str, Any]:
    binding_sha256 = str(manifest.get("binding_sha256") or "")
    return {
        "compiler_version": "document-template-compiler-v1",
        "extension": extension,
        "slot_count": len(manifest.get("slots") or []),
        "required_slot_count": sum(
            1 for slot in manifest.get("slots") or [] if bool(slot.get("required"))
        ),
        "binding_sha256": binding_sha256,
        "target_validation": target_report,
        "synthetic_render": {
            "status": "pending",
            "method": "runtime-renderer",
        },
        "unresolved_placeholders": [],
    }


def validate_jinja_loop_contract(
    manifest: dict[str, Any],
    jinja_report: dict[str, Any],
    *,
    format_name: str,
) -> None:
    bindings = {
        str(slot["target"]): slot
        for slot in manifest.get("slots") or []
    }
    for loop in jinja_report.get("loop_accesses") or []:
        source = str(loop.get("source") or "")
        target = f"{format_name}:jinja:{source}"
        binding = bindings.get(target)
        if binding is None or binding.get("value_type") != "table_rows":
            raise TemplateCompilationError(
                "JINJA_LOOP_TABLE_BINDING_REQUIRED",
                f"Jinja loop source {source} requires a table_rows binding",
            )
        options = binding.get("options") or {}
        columns = options.get("columns")
        if isinstance(columns, list):
            declared_keys = {str(item) for item in columns}
        else:
            column_map = options.get("column_map") or {}
            declared_keys = (
                {str(item) for item in column_map.values()}
                if isinstance(column_map, dict)
                else set()
            )
        accessed_keys = {str(item) for item in loop.get("accessed_keys") or []}
        undeclared_keys = sorted(accessed_keys - declared_keys)
        if undeclared_keys:
            raise TemplateCompilationError(
                "JINJA_LOOP_COLUMN_NOT_DECLARED",
                f"Jinja loop source {source} accesses undeclared table columns",
                details={"undeclared_columns": undeclared_keys},
            )


__all__ = [
    "compilation_report",
    "normalize_binding_manifest",
    "validate_jinja_loop_contract",
]
