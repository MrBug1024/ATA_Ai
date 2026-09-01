"""Container-level upload validation for untrusted template files."""

from __future__ import annotations

import re
import socket
import struct
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .models import TemplateInspection, TemplateSecurityLimits, sha256_bytes


SUPPORTED_CONTENT_TYPES: dict[str, frozenset[str]] = {
    ".docx": frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ),
    ".xlsx": frozenset(
        {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    ),
    ".md": frozenset({"text/markdown", "text/x-markdown", "text/plain"}),
    ".pdf": frozenset({"application/pdf"}),
}

OOXML_REQUIRED_ENTRIES = {
    ".docx": frozenset({"[Content_Types].xml", "_rels/.rels", "word/document.xml"}),
    ".xlsx": frozenset({"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"}),
}

_FORBIDDEN_ZIP_PATH_MARKERS = (
    "vbaproject.bin",
    "xl/macrosheets/",
    "xl/dialogsheets/",
    "xl/connections.xml",
    "xl/querytables/",
    "activex/",
    "embeddings/",
    "oleobject",
    "externallinks/",
    "customui/",
)
_FORBIDDEN_XML_PATTERNS = (
    (re.compile(rb"targetmode\s*=\s*[\"']external[\"']", re.IGNORECASE), "external_relationship"),
    (re.compile(rb"\bddeauto\b|\bdde\s+", re.IGNORECASE), "dde_field"),
    (re.compile(rb"<[^>]*(?:oleobject|activex)", re.IGNORECASE), "embedded_active_content"),
    (re.compile(rb"javascript\s*:", re.IGNORECASE), "javascript_link"),
    (re.compile(rb"macroenabled", re.IGNORECASE), "macro_enabled_content_type"),
)
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")
_MAX_XML_DEPTH = 256


def normalized_extension(file_name: str) -> str:
    normalized_name = str(file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in normalized_name:
        return ""
    return f".{normalized_name.rsplit('.', 1)[-1].lower()}"


def safe_display_file_name(file_name: str) -> str:
    raw = str(file_name or "").strip()
    normalized = raw.replace("\\", "/").rsplit("/", 1)[-1]
    if (
        not normalized
        or normalized in {".", ".."}
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError("invalid template file name")
    return normalized


def _safe_zip_path(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        bool(normalized)
        and "\x00" not in normalized
        and not path.is_absolute()
        and ".." not in path.parts
        and not re.match(r"^[A-Za-z]:", normalized)
    )


def _validate_xml_payload(payload: bytes) -> str:
    depth = 0
    max_depth = 0
    try:
        for event, _ in ElementTree.iterparse(BytesIO(payload), events=("start", "end")):
            if event == "start":
                depth += 1
                max_depth = max(max_depth, depth)
                if max_depth > _MAX_XML_DEPTH:
                    return "xml_depth_limit"
            else:
                depth = max(0, depth - 1)
    except (DefusedXmlException, ElementTree.ParseError, OSError, ValueError):
        return "unsafe_or_invalid_xml"
    return ""


def _inspect_zip(
    inspection: TemplateInspection,
    file_bytes: bytes,
    limits: TemplateSecurityLimits,
) -> None:
    try:
        archive = zipfile.ZipFile(BytesIO(file_bytes))
    except (OSError, zipfile.BadZipFile):
        inspection.add_error("INVALID_OOXML_CONTAINER", "OOXML template is not a valid ZIP container")
        return

    with archive:
        entries = archive.infolist()
        inspection.format_details["zip_entry_count"] = len(entries)
        if len(entries) > limits.max_zip_entries:
            inspection.add_error("ZIP_ENTRY_LIMIT", "OOXML container has too many ZIP entries")
            return

        normalized_names = [entry.filename.replace("\\", "/") for entry in entries]
        names = set(normalized_names)
        if len(names) != len(normalized_names):
            inspection.add_error("ZIP_DUPLICATE_ENTRY", "OOXML container has duplicate ZIP entries")
        missing = sorted(OOXML_REQUIRED_ENTRIES[inspection.extension] - names)
        if missing:
            inspection.add_error(
                "OOXML_REQUIRED_ENTRY_MISSING",
                f"OOXML container is missing required entries: {', '.join(missing)}",
            )

        total_uncompressed = 0
        xml_bytes = 0
        forbidden_paths: set[str] = set()
        forbidden_xml: set[str] = set()
        encrypted_entries: list[str] = []
        for entry in entries:
            normalized_name = entry.filename.replace("\\", "/")
            lowered_name = normalized_name.lower()
            if not _safe_zip_path(normalized_name):
                inspection.add_error("ZIP_PATH_TRAVERSAL", "OOXML container has an unsafe entry path")
                continue
            if entry.flag_bits & 0x1:
                encrypted_entries.append(normalized_name)
            if entry.file_size > limits.max_entry_bytes:
                inspection.add_error("ZIP_ENTRY_SIZE_LIMIT", "OOXML entry exceeds the size limit")
            total_uncompressed += entry.file_size
            if total_uncompressed > limits.max_uncompressed_bytes:
                inspection.add_error(
                    "ZIP_UNCOMPRESSED_LIMIT", "OOXML uncompressed size exceeds the limit"
                )
            ratio = entry.file_size / max(entry.compress_size, 1)
            if entry.file_size > 4096 and ratio > limits.max_compression_ratio:
                inspection.add_error("ZIP_COMPRESSION_RATIO", "OOXML compression ratio is unsafe")
            if any(marker in lowered_name for marker in _FORBIDDEN_ZIP_PATH_MARKERS):
                forbidden_paths.add(normalized_name)
            if not (lowered_name.endswith(".xml") or lowered_name.endswith(".rels")):
                continue
            xml_bytes += entry.file_size
            if entry.file_size > limits.max_xml_bytes or xml_bytes > limits.max_xml_bytes:
                inspection.add_error("XML_SIZE_LIMIT", "OOXML XML payload exceeds the limit")
                continue
            try:
                payload = archive.read(entry)
            except (RuntimeError, zipfile.BadZipFile):
                inspection.add_error("ZIP_ENTRY_UNREADABLE", "OOXML contains an unreadable entry")
                continue
            xml_error = _validate_xml_payload(payload)
            if xml_error == "xml_depth_limit":
                inspection.add_error("XML_DEPTH_LIMIT", "OOXML XML nesting exceeds the limit")
            elif xml_error:
                inspection.add_error("XML_UNSAFE", "OOXML contains unsafe or invalid XML")
            for pattern, threat in _FORBIDDEN_XML_PATTERNS:
                if pattern.search(payload):
                    forbidden_xml.add(threat)

        inspection.format_details["zip_uncompressed_bytes"] = total_uncompressed
        inspection.format_details["xml_bytes"] = xml_bytes
        if encrypted_entries:
            inspection.threats.append("encrypted_or_password_protected_content")
            inspection.format_details["encrypted_entries"] = encrypted_entries[:20]
        if forbidden_paths:
            inspection.threats.extend(sorted({"macro_or_embedded_content"}))
            inspection.format_details["forbidden_entries"] = sorted(forbidden_paths)[:50]
        inspection.threats.extend(sorted(forbidden_xml))


def inspect_container(
    *,
    file_name: str,
    content_type: str,
    file_bytes: bytes,
    limits: TemplateSecurityLimits,
) -> TemplateInspection:
    extension = normalized_extension(file_name)
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    inspection = TemplateInspection(
        extension=extension,
        content_type=normalized_type,
        size_bytes=len(file_bytes),
        source_sha256=sha256_bytes(file_bytes),
    )
    try:
        safe_name = safe_display_file_name(file_name)
    except ValueError as exc:
        inspection.add_error("INVALID_FILE_NAME", str(exc))
    else:
        if safe_name != str(file_name or "").strip():
            inspection.add_error("UNSAFE_FILE_NAME", "template file name must not contain a path")

    if extension not in SUPPORTED_CONTENT_TYPES:
        inspection.add_error("UNSUPPORTED_EXTENSION", "only .docx, .xlsx, .md, and .pdf are supported")
        return inspection
    if normalized_type not in SUPPORTED_CONTENT_TYPES[extension]:
        inspection.add_error(
            "CONTENT_TYPE_MISMATCH",
            f"content type {normalized_type or '<empty>'} does not match {extension}",
        )
    if not file_bytes:
        inspection.add_error("EMPTY_FILE", "template file is empty")
        return inspection
    if len(file_bytes) > limits.max_file_bytes:
        inspection.add_error("FILE_SIZE_LIMIT", "template file exceeds the configured size limit")
        return inspection

    if extension in OOXML_REQUIRED_ENTRIES:
        signature_matches = file_bytes.startswith(_ZIP_SIGNATURES)
        inspection.signature = "zip-ooxml" if signature_matches else "unknown"
        if not signature_matches:
            inspection.add_error("SIGNATURE_MISMATCH", "OOXML file does not have a ZIP signature")
            return inspection
        _inspect_zip(inspection, file_bytes, limits)
    elif extension == ".pdf":
        inspection.signature = "pdf" if file_bytes.startswith(b"%PDF-") else "unknown"
        if not file_bytes.startswith(b"%PDF-"):
            inspection.add_error("SIGNATURE_MISMATCH", "PDF file does not have a PDF signature")
    else:
        inspection.signature = "utf-8-text"
        try:
            file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            inspection.add_error("MARKDOWN_ENCODING", "Markdown templates must be UTF-8")
        if b"\x00" in file_bytes:
            inspection.add_error("MARKDOWN_BINARY_CONTENT", "Markdown template contains binary data")

    inspection.threats = sorted(set(inspection.threats))
    return inspection


def scan_with_clamav(
    file_bytes: bytes,
    *,
    host: str,
    port: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Scan bytes with clamd's INSTREAM protocol without writing a temp file."""

    with socket.create_connection((host, port), timeout=timeout_seconds) as connection:
        connection.settimeout(timeout_seconds)
        connection.sendall(b"zINSTREAM\x00")
        view = memoryview(file_bytes)
        for offset in range(0, len(view), 1024 * 1024):
            chunk = view[offset : offset + 1024 * 1024]
            connection.sendall(struct.pack(">I", len(chunk)))
            connection.sendall(chunk)
        connection.sendall(struct.pack(">I", 0))
        chunks: list[bytes] = []
        while True:
            block = connection.recv(4096)
            if not block:
                break
            chunks.append(block)
            if b"\x00" in block or b"\n" in block:
                break
    response = b"".join(chunks).decode("utf-8", errors="replace").strip("\x00\r\n ")
    if response.endswith(" OK"):
        return {"status": "passed", "engine": "clamav", "response": response}
    if " FOUND" in response:
        signature = response.rsplit(" FOUND", 1)[0].split(":", 1)[-1].strip()
        return {
            "status": "infected",
            "engine": "clamav",
            "signature": signature,
            "response": response,
        }
    raise RuntimeError(f"unexpected ClamAV response: {response or '<empty>'}")


def apply_antivirus_gate(
    inspection: TemplateInspection,
    file_bytes: bytes,
    *,
    host: str,
    port: int,
    timeout_seconds: int,
    required: bool,
) -> None:
    normalized_host = str(host or "").strip()
    if not normalized_host:
        inspection.antivirus = {"status": "not_configured", "required": required}
        if required:
            inspection.add_error("ANTIVIRUS_REQUIRED", "ClamAV is required but not configured")
        else:
            inspection.add_warning("ANTIVIRUS_SKIPPED", "ClamAV scan was not configured")
        return
    try:
        inspection.antivirus = scan_with_clamav(
            file_bytes,
            host=normalized_host,
            port=port,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        inspection.antivirus = {"status": "unavailable", "required": required}
        if required:
            inspection.add_error("ANTIVIRUS_UNAVAILABLE", "ClamAV scan is unavailable")
        else:
            inspection.add_warning("ANTIVIRUS_UNAVAILABLE", "ClamAV scan is unavailable")
        inspection.antivirus["error_type"] = type(exc).__name__
        return
    if inspection.antivirus.get("status") == "infected":
        inspection.threats.append("malware_detected")
        inspection.threats = sorted(set(inspection.threats))


__all__ = [
    "OOXML_REQUIRED_ENTRIES",
    "SUPPORTED_CONTENT_TYPES",
    "apply_antivirus_gate",
    "inspect_container",
    "normalized_extension",
    "safe_display_file_name",
    "scan_with_clamav",
]
