"""Isolated Gotenberg client for PDF previews."""

from __future__ import annotations

from html import escape
from pathlib import Path

import httpx

from ai_hunter.app.services.pdf_validation import PdfValidationError, validate_pdf_bytes
from ai_hunter.app.settings import Settings, get_settings


class PreviewConversionError(RuntimeError):
    pass


def _max_preview_bytes(settings: Settings) -> int:
    return max(1, int(settings.attachment_preview_max_mb)) * 1024 * 1024


def _validated_preview(pdf_bytes: bytes, *, max_bytes: int) -> bytes:
    if len(pdf_bytes) > max_bytes:
        raise PreviewConversionError("PDF preview exceeds the configured size limit")
    try:
        validate_pdf_bytes(pdf_bytes)
    except PdfValidationError as exc:
        raise PreviewConversionError("PDF preview failed strict validation") from exc
    return pdf_bytes


def _read_pdf_response(response: httpx.Response, *, max_bytes: int) -> bytes:
    try:
        declared_size = int(response.headers.get("content-length") or 0)
    except (TypeError, ValueError) as exc:
        raise PreviewConversionError("PDF preview has an invalid Content-Length") from exc
    if declared_size > max_bytes:
        raise PreviewConversionError("PDF preview exceeds the configured size limit")
    chunks: list[bytes] = []
    received = 0
    for chunk in response.iter_bytes():
        received += len(chunk)
        if received > max_bytes:
            raise PreviewConversionError("PDF preview exceeds the configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def convert_to_pdf(
    *,
    file_name: str,
    content_type: str,
    file_bytes: bytes,
    settings: Settings | None = None,
) -> bytes | None:
    """Convert a supported deliverable to PDF without exposing any URL input."""

    resolved = settings or get_settings()
    suffix = Path(file_name).suffix.lower()
    max_bytes = _max_preview_bytes(resolved)
    if suffix == ".pdf":
        return _validated_preview(file_bytes, max_bytes=max_bytes)
    base_url = resolved.attachment_gotenberg_url.strip().rstrip("/")
    if not base_url:
        if resolved.attachment_preview_required:
            raise PreviewConversionError("Gotenberg is required but not configured")
        return None
    timeout = httpx.Timeout(float(resolved.attachment_gotenberg_timeout_seconds))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            if suffix in {".docx", ".xlsx"}:
                request = client.stream(
                    "POST",
                    f"{base_url}/forms/libreoffice/convert",
                    files={"files": (Path(file_name).name, file_bytes, content_type)},
                    data={"pdfa": "PDF/A-2b"},
                )
            elif suffix == ".md":
                markdown_text = file_bytes.decode("utf-8", errors="strict")
                html = (
                    "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
                    "<style>body{font-family:sans-serif;white-space:pre-wrap;line-height:1.6;"
                    "font-size:12pt;margin:24mm}pre{white-space:pre-wrap}</style></head>"
                    f"<body><pre>{escape(markdown_text)}</pre></body></html>"
                ).encode("utf-8")
                request = client.stream(
                    "POST",
                    f"{base_url}/forms/chromium/convert/html",
                    files={"files": ("index.html", html, "text/html")},
                )
            else:
                raise PreviewConversionError(f"preview conversion does not support {suffix}")
            with request as response:
                response.raise_for_status()
                pdf_bytes = _read_pdf_response(response, max_bytes=max_bytes)
    except PreviewConversionError:
        raise
    except (httpx.HTTPError, UnicodeError) as exc:
        raise PreviewConversionError("preview conversion failed") from exc
    return _validated_preview(pdf_bytes, max_bytes=max_bytes)


__all__ = ["PreviewConversionError", "convert_to_pdf"]
