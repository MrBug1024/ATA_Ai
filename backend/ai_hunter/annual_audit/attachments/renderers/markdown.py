"""Sandboxed Markdown template rendering with a strict JSON-only context."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from jinja2 import StrictUndefined, nodes
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..content_schemas import (
    AttachmentContractError,
    AttachmentRenderError,
    BindingManifest,
    RenderResult,
    ResolvedDocumentPayload,
    ensure_payload_matches_manifest,
    verify_source_template,
)


MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"
DEFAULT_FILTERS = frozenset({"default", "join", "length", "lower", "replace", "trim", "upper"})
_RAW_HTML_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
_EXTERNAL_URL_RE = re.compile(r"(?:https?|ftp)://", re.IGNORECASE)


class _StrictSandbox(SandboxedEnvironment):
    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        return False

    def is_safe_callable(self, obj: Any) -> bool:
        return False


def render_markdown(
    template_bytes: bytes,
    payload: ResolvedDocumentPayload,
    manifest: BindingManifest,
    *,
    allowed_filters: set[str] | frozenset[str] = DEFAULT_FILTERS,
    max_output_bytes: int = 5 * 1024 * 1024,
    max_collection_items: int = 10_000,
) -> RenderResult:
    ensure_payload_matches_manifest(payload, manifest)
    source_sha = verify_source_template(template_bytes, manifest)
    try:
        template_text = template_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AttachmentContractError("Markdown templates must be UTF-8") from exc
    _reject_unsafe_markdown(template_text, label="template")

    environment = _StrictSandbox(
        undefined=StrictUndefined,
        autoescape=False,
        loader=None,
        enable_async=False,
    )
    environment.globals.clear()
    environment.filters = {
        name: value
        for name, value in environment.filters.items()
        if name in allowed_filters
    }
    try:
        parsed = environment.parse(template_text)
    except TemplateError as exc:
        raise AttachmentContractError("Markdown template syntax is invalid") from exc
    _validate_ast(parsed, set(allowed_filters))

    context: dict[str, Any] = {}
    for binding in manifest.slots:
        format_name, target_kind, variable = binding.target.split(":", 2)
        if (
            format_name not in {"md", "markdown"}
            or target_kind not in {"jinja", "variable"}
            or not variable
        ):
            raise AttachmentContractError(f"unsupported Markdown binding target: {binding.target}")
        slot = payload.slot_map.get(binding.slot_id)
        if slot is None:
            continue
        _set_nested(context, variable, _markdown_value(slot.kind, slot.value))
    _validate_context_size(context, max_collection_items=max_collection_items)

    try:
        rendered = environment.from_string(template_text).render(context)
    except TemplateError as exc:
        raise AttachmentRenderError("sandboxed Markdown rendering failed") from exc
    _reject_unsafe_markdown(rendered, label="rendered Markdown")
    data = rendered.encode("utf-8")
    if len(data) > max_output_bytes:
        raise AttachmentRenderError("rendered Markdown exceeds the configured output limit")
    return RenderResult(
        data=data,
        extension=".md",
        content_type=MARKDOWN_CONTENT_TYPE,
        source_template_sha256=source_sha,
    )


def _validate_ast(parsed: nodes.Template, allowed_filters: set[str]) -> None:
    forbidden_types = (
        nodes.Include,
        nodes.Import,
        nodes.FromImport,
        nodes.Extends,
        nodes.Call,
        nodes.Macro,
    )
    for node in parsed.find_all(forbidden_types):
        raise AttachmentContractError(
            f"Markdown template uses forbidden Jinja construct: {type(node).__name__}"
        )
    for node in parsed.find_all(nodes.Filter):
        if node.name not in allowed_filters:
            raise AttachmentContractError(f"Markdown template filter is not allowed: {node.name}")
    if sum(1 for _ in parsed.find_all(nodes.For)) > 50:
        raise AttachmentContractError("Markdown template contains too many loops")
    _validate_scoped_mapping_access(parsed)


def _validate_scoped_mapping_access(parsed: nodes.Template) -> None:
    def safe_key(value: Any) -> bool:
        return bool(
            isinstance(value, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", value)
            and not value.startswith("_")
            and "__" not in value
        )

    def visit(node: nodes.Node, locals_in_scope: set[str]) -> None:
        if isinstance(node, nodes.For):
            if not isinstance(node.target, nodes.Name) or not isinstance(node.iter, nodes.Name):
                raise AttachmentContractError(
                    "Markdown loops require one local name and one bound collection"
                )
            alias = node.target.name
            source = node.iter.name
            if not safe_key(alias) or not safe_key(source):
                raise AttachmentContractError("Markdown loop identifiers are unsafe")
            visit(node.iter, locals_in_scope)
            nested_scope = {*locals_in_scope, alias}
            for child in node.body:
                visit(child, nested_scope)
            for child in node.else_:
                visit(child, locals_in_scope)
            if node.test is not None:
                visit(node.test, nested_scope)
            return
        if isinstance(node, nodes.Getattr):
            if (
                isinstance(node.node, nodes.Name)
                and node.node.name in locals_in_scope
                and safe_key(node.attr)
            ):
                return
            raise AttachmentContractError(
                "Markdown attribute access is limited to loop-local mapping keys"
            )
        if isinstance(node, nodes.Getitem):
            if (
                isinstance(node.node, nodes.Name)
                and node.node.name in locals_in_scope
                and isinstance(node.arg, nodes.Const)
                and safe_key(node.arg.value)
            ):
                return
            raise AttachmentContractError(
                "Markdown item access is limited to loop-local constant mapping keys"
            )
        for child in node.iter_child_nodes():
            visit(child, locals_in_scope)

    visit(parsed, set())


def _reject_unsafe_markdown(value: str, *, label: str) -> None:
    if _RAW_HTML_RE.search(value):
        raise AttachmentContractError(f"{label} contains raw HTML")
    if _EXTERNAL_URL_RE.search(value):
        raise AttachmentContractError(f"{label} contains an external URL")


def _set_nested(context: dict[str, Any], dotted_name: str, value: Any) -> None:
    parts = [part for part in dotted_name.split(".") if part]
    if not parts:
        raise AttachmentContractError("Markdown target variable is blank")
    cursor = context
    for part in parts[:-1]:
        existing = cursor.setdefault(part, {})
        if not isinstance(existing, dict):
            raise AttachmentContractError(f"overlapping Markdown target: {dotted_name}")
        cursor = existing
    if parts[-1] in cursor:
        raise AttachmentContractError(f"duplicate Markdown target: {dotted_name}")
    cursor[parts[-1]] = value


def _markdown_value(kind: str, value: Any) -> Any:
    if kind == "narrative_blocks":
        return [dict(block) for block in value]
    if kind == "table_rows":
        return [dict(row) for row in value]
    return value


def _validate_context_size(
    value: Any,
    *,
    max_collection_items: int,
    depth: int = 0,
) -> None:
    if depth > 20:
        raise AttachmentContractError("Markdown context nesting exceeds the configured limit")
    if isinstance(value, Mapping):
        if len(value) > max_collection_items:
            raise AttachmentContractError("Markdown context mapping exceeds the configured limit")
        for item in value.values():
            _validate_context_size(
                item,
                max_collection_items=max_collection_items,
                depth=depth + 1,
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > max_collection_items:
            raise AttachmentContractError("Markdown context sequence exceeds the configured limit")
        for item in value:
            _validate_context_size(
                item,
                max_collection_items=max_collection_items,
                depth=depth + 1,
            )
        return
    if not (value is None or isinstance(value, (str, int, float, bool))):
        raise AttachmentContractError(
            f"Markdown context contains a non-JSON value: {type(value).__name__}"
        )


__all__ = ["DEFAULT_FILTERS", "MARKDOWN_CONTENT_TYPE", "render_markdown"]
