"""Recover trustworthy file metadata before annual-audit ingestion.

Persisted upload batches can outlive the client that supplied their filename.
When a filename is reduced to ``.bin`` (or an older payload carries a stale
``extension`` field), use only deterministic MIME and byte signatures to
recover a parser-safe filename.  Unknown binary inputs intentionally remain
unchanged and continue through the existing document OCR path.
"""

from __future__ import annotations

from collections.abc import Mapping
from email.header import decode_header, make_header
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile, is_zipfile


TEXT_EXTENSIONS = {".txt"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
CSV_EXTENSIONS = {".csv"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
DOCUMENT_OCR_EXTENSIONS = {".pdf", ".doc", ".docx", ".et", ".ett"}
KNOWN_INGEST_EXTENSIONS = (
    TEXT_EXTENSIONS
    | MARKDOWN_EXTENSIONS
    | CSV_EXTENSIONS
    | SPREADSHEET_EXTENSIONS
    | IMAGE_EXTENSIONS
    | DOCUMENT_OCR_EXTENSIONS
)

_AMBIGUOUS_NAME_EXTENSIONS = {"", ".bin", ".blob", ".dat", ".tmp", ".unknown"}
_CONTENT_TYPE_EXTENSIONS = {
    "application/csv": ".csv",
    "application/json": ".txt",
    "application/markdown": ".md",
    "application/msword": ".doc",
    "application/pdf": ".pdf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-excel.sheet.macroenabled.12": ".xlsm",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/xml": ".txt",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/x-markdown": ".md",
    "text/xml": ".txt",
}
_DEFAULT_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".txt": "text/plain",
    ".webp": "image/webp",
    ".xls": "application/vnd.ms-excel",
    ".xlsm": "application/vnd.ms-excel.sheet.macroenabled.12",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def has_known_ingest_extension(extension: object) -> bool:
    """Return whether an extension has a deterministic annual-ingest route."""

    return _normalize_extension(extension) in KNOWN_INGEST_EXTENSIONS


def normalize_ingest_file_item(
    file_item: Mapping[str, Any],
    *,
    file_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Return a copy with a reliable filename, extension, MIME type and file type.

    The filename wins over a stale extension field when it already has a known
    extension.  MIME and signatures are considered only for ambiguous names,
    which keeps user-supplied, supported filenames stable.
    """

    normalized = dict(file_item)
    file_name = _normalized_file_name(file_item.get("name"))
    name_extension = _normalize_extension(Path(file_name).suffix)
    supplied_extension = _normalize_extension(file_item.get("extension"))
    content_type = _normalize_content_type(file_item.get("content_type"))

    named_extension = _first_known_extension(name_extension, supplied_extension)
    extension = named_extension
    signature_extension = _extension_from_file_bytes(file_bytes) if file_bytes is not None else ""
    signature_used = not named_extension and bool(signature_extension and signature_extension != ".txt")
    if signature_used:
        extension = signature_extension
    if not extension:
        extension = _extension_from_content_type(content_type)
    if not extension and signature_extension:
        extension = signature_extension
    if not extension:
        extension = name_extension or supplied_extension

    normalized["name"] = _repair_file_name(file_name, name_extension, extension)
    normalized["extension"] = extension
    if (
        not content_type
        or content_type == "application/octet-stream"
        or (signature_used and _extension_from_content_type(content_type) != extension)
    ):
        inferred_content_type = _DEFAULT_CONTENT_TYPES.get(extension, "")
        if inferred_content_type:
            normalized["content_type"] = inferred_content_type
    else:
        normalized["content_type"] = content_type

    if extension in IMAGE_EXTENSIONS:
        normalized["type"] = "image"
    elif not str(normalized.get("type") or "").strip():
        normalized["type"] = "document"
    return normalized


def _normalized_file_name(value: object) -> str:
    raw_name = str(value or "").strip()
    try:
        decoded_name = str(make_header(decode_header(raw_name)))
    except (LookupError, UnicodeError, ValueError):
        decoded_name = raw_name
    name = Path(decoded_name).name
    return name or "uploaded-file"


def _normalize_extension(value: object) -> str:
    extension = str(value or "").strip().lower()
    if extension and not extension.startswith("."):
        return f".{extension}"
    return extension


def _normalize_content_type(value: object) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _first_known_extension(*extensions: str) -> str:
    for extension in extensions:
        if extension in KNOWN_INGEST_EXTENSIONS:
            return extension
    return ""


def _extension_from_content_type(content_type: str) -> str:
    if content_type.startswith("image/"):
        return {
            "image/bmp": ".bmp",
            "image/gif": ".gif",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/tiff": ".tiff",
            "image/webp": ".webp",
        }.get(content_type, "")
    return _CONTENT_TYPE_EXTENSIONS.get(content_type, "")


def _extension_from_file_bytes(file_bytes: bytes) -> str:
    """Infer only signatures that identify a supported ingest parser."""

    if file_bytes.startswith(b"%PDF-"):
        return ".pdf"
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if file_bytes.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP":
        return ".webp"
    if file_bytes.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if is_zipfile(BytesIO(file_bytes)):
        try:
            with ZipFile(BytesIO(file_bytes)) as archive:
                names = {entry.filename.lower() for entry in archive.infolist()}
        except BadZipFile:
            names = set()
        if any(name.startswith("xl/") for name in names):
            return ".xlsm" if any(name.endswith("vbaproject.bin") for name in names) else ".xlsx"
        if any(name.startswith("word/") for name in names):
            return ".docx"
    if _looks_like_utf8_text(file_bytes):
        return ".txt"
    return ""


def _looks_like_utf8_text(file_bytes: bytes) -> bool:
    if not file_bytes:
        return True
    if b"\x00" in file_bytes:
        return False
    try:
        decoded = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return False
    control_count = sum(
        1
        for character in decoded
        if ord(character) < 32 and character not in {"\n", "\r", "\t", "\f"}
    )
    return control_count <= max(1, len(decoded) // 100)


def _repair_file_name(file_name: str, name_extension: str, extension: str) -> str:
    if not extension or name_extension not in _AMBIGUOUS_NAME_EXTENSIONS:
        return file_name
    if name_extension:
        return f"{file_name[:-len(name_extension)]}{extension}"
    return f"{file_name}{extension}"
