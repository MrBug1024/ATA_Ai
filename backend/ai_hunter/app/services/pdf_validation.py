"""Shared strict validation for PDF previews stored or returned by the API."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


class PdfValidationError(ValueError):
    pass


def validate_pdf_bytes(pdf_bytes: bytes) -> None:
    """Require a parseable, unencrypted PDF with valid non-empty page boxes."""

    if not pdf_bytes.startswith(b"%PDF-"):
        raise PdfValidationError("PDF signature is invalid")
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=True)
        if reader.is_encrypted:
            raise PdfValidationError("PDF is encrypted")
        if not reader.pages:
            raise PdfValidationError("PDF has no pages")
        if any(
            float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0
            for page in reader.pages
        ):
            raise PdfValidationError("PDF has an invalid page box")
    except PdfValidationError:
        raise
    except Exception as exc:
        raise PdfValidationError("PDF cannot be reopened in strict mode") from exc


__all__ = ["PdfValidationError", "validate_pdf_bytes"]
