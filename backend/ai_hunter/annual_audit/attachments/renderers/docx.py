"""Deterministic DOCX rendering through explicit template bindings."""

from __future__ import annotations

import hashlib
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeElementTree
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

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


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
_DOCX_FILTERS = frozenset(
    {"default", "join", "length", "lower", "replace", "trim", "upper"}
)


class _StrictDocxSandbox(SandboxedEnvironment):
    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        return False

    def is_safe_callable(self, obj: Any) -> bool:
        return False

ET.register_namespace("w", _WORD_NS)


def render_docx(
    template_bytes: bytes,
    payload: ResolvedDocumentPayload,
    manifest: BindingManifest,
) -> RenderResult:
    """Render an approved DOCX template without fuzzy text replacement.

    Supported targets are ``docx:jinja:<variable>`` and
    ``docx:content-control:<tag>``.  Jinja rendering uses docxtpl when the
    dependency is installed.  Content-control replacement is intentionally
    limited to scalar/narrative text and preserves the surrounding OOXML.
    """

    ensure_payload_matches_manifest(payload, manifest)
    source_sha = verify_source_template(template_bytes, manifest)
    _assert_docx_container(template_bytes)

    bindings = [(binding, payload.slot_map.get(binding.slot_id)) for binding in manifest.slots]
    output = template_bytes

    content_control_bindings = [
        (binding, slot)
        for binding, slot in bindings
        if binding.target.startswith("docx:content-control:") and slot is not None
    ]
    if content_control_bindings:
        output = _render_content_controls(output, content_control_bindings)

    bookmark_bindings = [
        (binding, slot)
        for binding, slot in bindings
        if binding.target.startswith("docx:bookmark:") and slot is not None
    ]
    if bookmark_bindings:
        output = _render_bookmarks(output, bookmark_bindings)

    jinja_bindings = [
        (binding, slot)
        for binding, slot in bindings
        if binding.target.startswith("docx:jinja:") and slot is not None
    ]
    if jinja_bindings:
        output = _render_docxtpl(output, jinja_bindings)

    supported = {"jinja", "content-control", "bookmark"}
    unsupported = sorted(
        binding.target
        for binding in manifest.slots
        if binding.target.split(":", 2)[0] != "docx"
        or binding.target.split(":", 2)[1] not in supported
    )
    if unsupported:
        raise AttachmentContractError(
            f"unsupported DOCX binding targets: {', '.join(unsupported)}"
        )

    _assert_docx_container(output)
    try:
        from docx import Document

        Document(BytesIO(output))
    except Exception as exc:
        raise AttachmentRenderError("rendered DOCX cannot be reopened") from exc

    modified_parts = tuple(_changed_zip_parts(template_bytes, output))
    if manifest.allowed_modified_parts:
        allowed = set(manifest.allowed_modified_parts)
        unexpected = sorted(set(modified_parts) - allowed)
        if unexpected:
            raise AttachmentRenderError(
                f"DOCX renderer modified undeclared package parts: {', '.join(unexpected)}"
            )
    return RenderResult(
        data=output,
        extension=".docx",
        content_type=DOCX_CONTENT_TYPE,
        source_template_sha256=source_sha,
        modified_parts=modified_parts,
    )


def _render_docxtpl(
    template_bytes: bytes,
    bindings: list[tuple[SlotBinding, Any]],
) -> bytes:
    try:
        from docxtpl import DocxTemplate
    except ImportError as exc:
        raise MissingRendererDependency(
            "docxtpl is required for docx:jinja bindings"
        ) from exc

    context: dict[str, Any] = {}
    for binding, slot in bindings:
        variable = binding.target.split(":", 2)[2].strip()
        if not variable:
            raise AttachmentContractError("DOCX Jinja target variable is blank")
        _set_nested(context, variable, _docx_value(slot.kind, slot.value))

    try:
        with tempfile.TemporaryDirectory(prefix="ata-docx-render-") as temp_dir:
            source = Path(temp_dir) / "template.docx"
            target = Path(temp_dir) / "rendered.docx"
            source.write_bytes(template_bytes)
            document = DocxTemplate(str(source))
            environment = _StrictDocxSandbox(
                undefined=StrictUndefined,
                autoescape=True,
                loader=None,
                enable_async=False,
            )
            environment.globals.clear()
            environment.filters = {
                name: function
                for name, function in environment.filters.items()
                if name in _DOCX_FILTERS
            }
            document.render(context, jinja_env=environment, autoescape=True)
            document.save(str(target))
            return target.read_bytes()
    except AttachmentContractError:
        raise
    except Exception as exc:
        raise AttachmentRenderError("docxtpl rendering failed") from exc


def _render_content_controls(
    template_bytes: bytes,
    bindings: list[tuple[SlotBinding, Any]],
) -> bytes:
    source = BytesIO(template_bytes)
    output = BytesIO()
    found: dict[str, int] = {binding.slot_id: 0 for binding, _ in bindings}

    try:
        with zipfile.ZipFile(source, "r") as archive, zipfile.ZipFile(output, "w") as rendered:
            for info in archive.infolist():
                data = archive.read(info.filename)
                if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                    data = _replace_controls_in_part(data, bindings, found)
                rendered.writestr(info, data)
    except zipfile.BadZipFile as exc:
        raise AttachmentRenderError("invalid DOCX ZIP container") from exc

    for binding, _ in bindings:
        count = found[binding.slot_id]
        allow_multiple = bool(binding.options.get("allow_multiple", False))
        if count == 0:
            raise AttachmentContractError(
                f"DOCX content control tag was not found: {binding.target.split(':', 2)[2]}"
            )
        if count > 1 and not allow_multiple:
            raise AttachmentContractError(
                f"DOCX content control tag is ambiguous ({count} matches): "
                f"{binding.target.split(':', 2)[2]}"
            )
    return output.getvalue()


def _render_bookmarks(
    template_bytes: bytes,
    bindings: list[tuple[SlotBinding, Any]],
) -> bytes:
    source = BytesIO(template_bytes)
    output = BytesIO()
    found: dict[str, int] = {binding.slot_id: 0 for binding, _ in bindings}
    try:
        with zipfile.ZipFile(source, "r") as archive, zipfile.ZipFile(output, "w") as rendered:
            for info in archive.infolist():
                data = archive.read(info.filename)
                if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                    data = _replace_bookmarks_in_part(data, bindings, found)
                rendered.writestr(info, data)
    except zipfile.BadZipFile as exc:
        raise AttachmentRenderError("invalid DOCX ZIP container") from exc
    for binding, _ in bindings:
        count = found[binding.slot_id]
        if count == 0:
            raise AttachmentContractError(
                f"DOCX bookmark was not found: {binding.target.split(':', 2)[2]}"
            )
        if count > 1:
            raise AttachmentContractError(
                f"DOCX bookmark is ambiguous ({count} matches): "
                f"{binding.target.split(':', 2)[2]}"
            )
    return output.getvalue()


def _replace_bookmarks_in_part(
    xml_bytes: bytes,
    bindings: list[tuple[SlotBinding, Any]],
    found: dict[str, int],
) -> bytes:
    try:
        root = SafeElementTree.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise AttachmentRenderError("DOCX contains invalid WordprocessingML") from exc
    by_name = {
        binding.target.split(":", 2)[2]: (binding, slot)
        for binding, slot in bindings
    }
    parent_map = {child: parent for parent in root.iter() for child in parent}
    changed = False
    for start in list(root.iter(_q("bookmarkStart"))):
        name = start.attrib.get(_q("name"), "")
        item = by_name.get(name)
        if item is None:
            continue
        binding, slot = item
        if slot.kind == "table_rows":
            raise AttachmentContractError("DOCX bookmarks do not accept table_rows payloads")
        bookmark_id = start.attrib.get(_q("id"), "")
        end = next(
            (
                candidate
                for candidate in root.iter(_q("bookmarkEnd"))
                if candidate.attrib.get(_q("id"), "") == bookmark_id
            ),
            None,
        )
        parent = parent_map.get(start)
        if end is None or parent is None or parent_map.get(end) is not parent:
            raise AttachmentContractError(
                f"DOCX bookmark must have start/end siblings in one container: {name}"
            )
        start_index = list(parent).index(start)
        end_index = list(parent).index(end)
        if end_index <= start_index:
            raise AttachmentContractError(f"DOCX bookmark has an invalid range: {name}")
        for child in list(parent)[start_index + 1 : end_index]:
            parent.remove(child)
        run = ET.Element(_q("r"))
        text = ET.SubElement(run, _q("t"))
        text.set(f"{{{_XML_NS}}}space", "preserve")
        text.text = str(_docx_value(slot.kind, slot.value))
        parent.insert(start_index + 1, run)
        found[binding.slot_id] += 1
        changed = True
    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _replace_controls_in_part(
    xml_bytes: bytes,
    bindings: list[tuple[SlotBinding, Any]],
    found: dict[str, int],
) -> bytes:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise AttachmentRenderError("DOCX contains invalid WordprocessingML") from exc

    by_tag = {
        binding.target.split(":", 2)[2]: (binding, slot)
        for binding, slot in bindings
    }
    changed = False
    for control in root.iter(_q("sdt")):
        properties = control.find(_q("sdtPr"))
        if properties is None:
            continue
        tag_element = properties.find(_q("tag"))
        if tag_element is None:
            continue
        tag = tag_element.attrib.get(_q("val"), "")
        item = by_tag.get(tag)
        if item is None:
            continue
        binding, slot = item
        if slot.kind == "table_rows":
            raise AttachmentContractError(
                "table_rows require a docxtpl loop; a text content control is not sufficient"
            )
        content = control.find(_q("sdtContent"))
        if content is None:
            raise AttachmentContractError(f"DOCX content control {tag!r} has no content")
        _replace_control_text(content, str(_docx_value(slot.kind, slot.value)))
        found[binding.slot_id] += 1
        changed = True
    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _replace_control_text(content: ET.Element, value: str) -> None:
    text_nodes = list(content.iter(_q("t")))
    if text_nodes:
        text_nodes[0].text = value
        text_nodes[0].set(f"{{{_XML_NS}}}space", "preserve")
        for node in text_nodes[1:]:
            node.text = ""
        return
    paragraph = next(content.iter(_q("p")), None)
    if paragraph is None:
        paragraph = ET.SubElement(content, _q("p"))
    run = ET.SubElement(paragraph, _q("r"))
    text = ET.SubElement(run, _q("t"))
    text.set(f"{{{_XML_NS}}}space", "preserve")
    text.text = value


def _docx_value(kind: str, value: Any) -> Any:
    if kind == "narrative_blocks":
        return "\n".join(str(block.get("text") or "") for block in value)
    return value


def _set_nested(context: dict[str, Any], dotted_name: str, value: Any) -> None:
    parts = [part for part in dotted_name.split(".") if part]
    if not parts:
        raise AttachmentContractError("DOCX Jinja target variable is blank")
    cursor = context
    for part in parts[:-1]:
        existing = cursor.setdefault(part, {})
        if not isinstance(existing, dict):
            raise AttachmentContractError(f"overlapping DOCX Jinja target: {dotted_name}")
        cursor = existing
    if parts[-1] in cursor:
        raise AttachmentContractError(f"duplicate DOCX Jinja target: {dotted_name}")
    cursor[parts[-1]] = value


def _assert_docx_container(data: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(data), "r") as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise AttachmentContractError("DOCX template is not a valid ZIP container") from exc
    required = {"[Content_Types].xml", "word/document.xml", "_rels/.rels"}
    missing = sorted(required - names)
    if missing:
        raise AttachmentContractError(
            f"DOCX template is missing required package parts: {', '.join(missing)}"
        )


def _changed_zip_parts(before: bytes, after: bytes) -> list[str]:
    before_hashes = _zip_hashes(before)
    after_hashes = _zip_hashes(after)
    return sorted(
        name
        for name in set(before_hashes) | set(after_hashes)
        if before_hashes.get(name) != after_hashes.get(name)
    )


def _zip_hashes(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(BytesIO(data), "r") as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
        }


def _q(local_name: str) -> str:
    return f"{{{_WORD_NS}}}{local_name}"


__all__ = ["DOCX_CONTENT_TYPE", "render_docx"]
