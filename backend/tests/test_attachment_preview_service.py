from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from ai_hunter.annual_audit.attachments import preview_service
from ai_hunter.annual_audit.attachments.preview_service import (
    PreviewConversionError,
    convert_to_pdf,
)


def _valid_pdf() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=(300, 400))
    document.drawString(20, 360, "Preview")
    document.showPage()
    document.save()
    return output.getvalue()


def _encrypted_pdf() -> bytes:
    reader = PdfReader(BytesIO(_valid_pdf()), strict=True)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _empty_pdf() -> bytes:
    output = BytesIO()
    PdfWriter().write(output)
    return output.getvalue()


def _invalid_page_box_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=0, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _settings(**changes):
    values = {
        "attachment_gotenberg_url": "http://gotenberg:3000",
        "attachment_gotenberg_timeout_seconds": 10,
        "attachment_preview_required": True,
        "attachment_preview_max_mb": 1,
    }
    values.update(changes)
    return SimpleNamespace(**values)


class _Response:
    def __init__(self, chunks: list[bytes], *, declared_size: int | str = 0) -> None:
        self._chunks = chunks
        self.headers = {"content-length": str(declared_size)} if declared_size else {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):
        yield from self._chunks


class _Client:
    response: _Response

    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream(self, method: str, url: str, **_kwargs):
        assert method == "POST"
        assert url.startswith("http://gotenberg:3000/forms/")
        return self.response


@pytest.mark.parametrize(
    "pdf_bytes",
    [b"%PDF-not-a-document", _encrypted_pdf(), _empty_pdf(), _invalid_page_box_pdf()],
)
def test_pdf_passthrough_requires_strict_reopen_unencrypted_nonempty(pdf_bytes: bytes) -> None:
    with pytest.raises(PreviewConversionError, match="strict validation"):
        convert_to_pdf(
            file_name="preview.pdf",
            content_type="application/pdf",
            file_bytes=pdf_bytes,
            settings=_settings(),
        )


def test_gotenberg_response_is_streamed_and_strictly_validated(monkeypatch) -> None:
    pdf_bytes = _valid_pdf()
    _Client.response = _Response([pdf_bytes[:32], pdf_bytes[32:]])
    monkeypatch.setattr(preview_service.httpx, "Client", _Client)

    result = convert_to_pdf(
        file_name="report.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_bytes=b"docx",
        settings=_settings(),
    )

    assert result == pdf_bytes


def test_gotenberg_declared_or_streamed_size_cannot_exceed_limit(monkeypatch) -> None:
    monkeypatch.setattr(preview_service.httpx, "Client", _Client)
    _Client.response = _Response([], declared_size=1024 * 1024 + 1)
    with pytest.raises(PreviewConversionError, match="size limit"):
        convert_to_pdf(
            file_name="report.docx",
            content_type="application/docx",
            file_bytes=b"docx",
            settings=_settings(),
        )

    _Client.response = _Response([], declared_size="invalid")
    with pytest.raises(PreviewConversionError, match="Content-Length"):
        convert_to_pdf(
            file_name="report.docx",
            content_type="application/docx",
            file_bytes=b"docx",
            settings=_settings(),
        )

    _Client.response = _Response([b"x" * (1024 * 1024), b"y"])
    with pytest.raises(PreviewConversionError, match="size limit"):
        convert_to_pdf(
            file_name="report.docx",
            content_type="application/docx",
            file_bytes=b"docx",
            settings=_settings(),
        )
