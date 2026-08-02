import base64
import re
import time
from io import BytesIO

import httpx
import pytest
from pypdf import PdfReader, PdfWriter

from ai_hunter.app.services.ocr_service import OCRPDFChunk, OCRPayload, OCRService


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"text": "ok", "message": "success"}


class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse()


def test_ocr_service_adds_auth_headers(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        client = _FakeClient(**kwargs)
        captured["client"] = client
        return client

    monkeypatch.setattr("ai_hunter.app.services.ocr_service.httpx.Client", fake_client)

    service = OCRService()
    service.api_key = "secret-key"

    result = service.parse_pdf_sync(
        file_name="demo.pdf",
        file_content="JVBERi0xLjQK",
        content_type="application/pdf",
    )

    assert result["text"] == "ok"
    _, request_kwargs = captured["client"].calls[0]
    assert request_kwargs["headers"]["Authorization"] == "Bearer secret-key"
    assert request_kwargs["headers"]["X-API-Key"] == "secret-key"


def test_pdf_page_threshold_splits_and_merges_layout_in_original_order(monkeypatch):
    service = OCRService()
    service.pdf_split_enabled = True
    service.pdf_split_threshold_mb = 100
    service.pdf_split_threshold_pages = 3
    service.pdf_chunk_max_mb = 100
    service.pdf_chunk_max_pages = 2
    service.pdf_chunk_concurrency = 2
    service.max_parallel = 2
    service.pdf_chunk_max_retries = 0
    calls = []

    def fake_parse_sync(payload, **kwargs):
        match = re.search(r"pages-(\d+)-(\d+)", payload.filename)
        assert match is not None
        start_page = int(match.group(1))
        end_page = int(match.group(2))
        page_count = len(PdfReader(BytesIO(payload.file_bytes)).pages)
        calls.append((start_page, end_page))
        if start_page == 1:
            time.sleep(0.03)
        return {
            "text": f"pages-{start_page}-{end_page}",
            "message": "success",
            "pages": [{"page_idx": index, "width": 600, "height": 800} for index in range(page_count)],
            "blocks": [{"page_idx": index, "text": f"page-{start_page + index}"} for index in range(page_count)],
            "page_width": 600,
            "page_height": 800,
        }

    monkeypatch.setattr(service, "_parse_sync", fake_parse_sync)
    result = service.parse_pdf_with_layout_sync(
        file_name="seven-pages.pdf",
        file_content=base64.b64encode(_build_pdf(7)).decode(),
        content_type="application/pdf",
    )

    assert sorted(calls) == [(1, 2), (3, 4), (5, 6), (7, 7)]
    assert result["chunk_count"] == 4
    assert result["text"].split("\n\n") == ["pages-1-2", "pages-3-4", "pages-5-6", "pages-7-7"]
    assert [page["page_idx"] for page in result["pages"]] == list(range(7))
    assert [block["page_idx"] for block in result["blocks"]] == list(range(7))


def test_pdf_size_threshold_triggers_split(monkeypatch):
    service = OCRService()
    service.pdf_split_enabled = True
    service.pdf_split_threshold_mb = 1
    service.pdf_split_threshold_pages = 100
    service.pdf_chunk_max_mb = 4
    service.pdf_chunk_max_pages = 5
    pdf_bytes = _build_pdf(2) + (b"\0" * 1024 * 1024)

    chunks = service._build_pdf_chunks(
        OCRPayload("large-bytes.pdf", pdf_bytes, "application/pdf"),
        force=False,
    )

    assert len(chunks) == 1
    assert chunks[0].page_range == "1-2"


def test_pdf_chunk_max_bytes_splits_candidate_pages(monkeypatch):
    service = OCRService()
    service.pdf_split_enabled = True
    service.pdf_split_threshold_mb = 100
    service.pdf_split_threshold_pages = 1
    service.pdf_chunk_max_mb = 1
    service.pdf_chunk_max_pages = 5
    monkeypatch.setattr(
        "ai_hunter.app.services.ocr_service._serialize_pdf_pages",
        lambda reader, page_indices: b"x" * (600_000 * len(page_indices)),
    )

    chunks = service._build_pdf_chunks(
        OCRPayload("byte-limited.pdf", _build_pdf(3), "application/pdf"),
        force=False,
    )

    assert [chunk.page_range for chunk in chunks] == ["1-1", "2-2", "3-3"]


def test_pdf_single_page_over_chunk_limit_fails(monkeypatch):
    service = OCRService()
    service.pdf_split_enabled = True
    service.pdf_split_threshold_pages = 1
    service.pdf_chunk_max_mb = 1
    monkeypatch.setattr(
        "ai_hunter.app.services.ocr_service._serialize_pdf_pages",
        lambda reader, page_indices: b"x" * (2 * 1024 * 1024),
    )

    with pytest.raises(ValueError, match="OCR_SINGLE_PAGE_TOO_LARGE.*page=1"):
        service._build_pdf_chunks(
            OCRPayload("oversized-page.pdf", _build_pdf(1), "application/pdf"),
            force=False,
        )


def test_small_pdf_timeout_falls_back_to_chunks_once(monkeypatch):
    service = OCRService()
    service.pdf_split_enabled = True
    service.pdf_split_threshold_mb = 100
    service.pdf_split_threshold_pages = 100
    service.pdf_chunk_max_mb = 100
    service.pdf_chunk_max_pages = 1
    service.pdf_chunk_concurrency = 1
    service.pdf_chunk_max_retries = 0
    calls = []

    def fake_parse_sync(payload, **kwargs):
        calls.append(payload.filename)
        if payload.filename == "small.pdf":
            raise httpx.ReadTimeout("whole request timed out")
        return {"text": payload.filename, "message": "success"}

    monkeypatch.setattr(service, "_parse_sync", fake_parse_sync)
    result = service.parse_pdf_sync(
        file_name="small.pdf",
        file_content=base64.b64encode(_build_pdf(2)).decode(),
        content_type="application/pdf",
    )

    assert calls[0] == "small.pdf"
    assert len(calls) == 3
    assert result["segmented"] is True
    assert result["chunk_count"] == 2


def test_pdf_chunk_retries_only_retryable_failure(monkeypatch):
    service = OCRService()
    service.pdf_chunk_max_retries = 2
    monkeypatch.setattr("ai_hunter.app.services.ocr_service.time.sleep", lambda seconds: None)
    responses = [
        {"text": "", "message": 'HTTP 500: {"error":"The operation timed out."}'},
        {"text": "", "message": "HTTP 500: temporary"},
        {"text": "ok", "message": "success"},
    ]
    monkeypatch.setattr(service, "_parse_sync", lambda payload, **kwargs: responses.pop(0))
    chunk = OCRPDFChunk(0, 0, 1, OCRPayload("part.pdf", _build_pdf(1), "application/pdf"))

    result = service._parse_pdf_chunk_with_retries(chunk, preserve_layout=False)

    assert result["text"] == "ok"
    assert responses == []


def test_pdf_chunk_does_not_retry_non_retryable_failure(monkeypatch):
    service = OCRService()
    service.pdf_chunk_max_retries = 2
    calls = []

    def fake_parse_sync(payload, **kwargs):
        calls.append(payload.filename)
        return {"text": "", "message": "HTTP 401: Unauthorized"}

    monkeypatch.setattr(service, "_parse_sync", fake_parse_sync)
    chunk = OCRPDFChunk(0, 4, 5, OCRPayload("part.pdf", _build_pdf(1), "application/pdf"))

    with pytest.raises(RuntimeError, match="pages=5-5 attempts=1"):
        service._parse_pdf_chunk_with_retries(chunk, preserve_layout=False)
    assert calls == ["part.pdf"]


def test_pdf_chunk_read_timeout_does_not_retry(monkeypatch):
    service = OCRService()
    service.pdf_chunk_max_retries = 2
    calls = []

    def fake_parse_sync(payload, **kwargs):
        calls.append(payload.filename)
        raise httpx.ReadTimeout("response still pending")

    monkeypatch.setattr(service, "_parse_sync", fake_parse_sync)
    chunk = OCRPDFChunk(0, 0, 2, OCRPayload("part.pdf", _build_pdf(2), "application/pdf"))

    with pytest.raises(RuntimeError, match="pages=1-2 attempts=1"):
        service._parse_pdf_chunk_with_retries(chunk, preserve_layout=False)
    assert calls == ["part.pdf"]


def test_pdf_sequential_chunks_stop_after_first_failure(monkeypatch):
    service = OCRService()
    service.pdf_chunk_concurrency = 1
    service.max_parallel = 5
    calls = []
    chunks = [
        OCRPDFChunk(0, 0, 1, OCRPayload("page-1.pdf", _build_pdf(1), "application/pdf")),
        OCRPDFChunk(1, 1, 2, OCRPayload("page-2.pdf", _build_pdf(1), "application/pdf")),
    ]

    def fake_parse_chunk(chunk, **kwargs):
        calls.append(chunk.page_range)
        raise RuntimeError("first page failed")

    monkeypatch.setattr(service, "_parse_pdf_chunk_with_retries", fake_parse_chunk)

    with pytest.raises(RuntimeError, match="first page failed"):
        service._parse_pdf_chunks_sync(chunks, preserve_layout=False)
    assert calls == ["1-1"]


def test_pdf_split_disabled_keeps_whole_file_behavior(monkeypatch):
    service = OCRService()
    service.pdf_split_enabled = False
    calls = []

    def fake_parse_sync(payload, **kwargs):
        calls.append(payload.filename)
        return {"text": "whole", "message": "success"}

    monkeypatch.setattr(service, "_parse_sync", fake_parse_sync)
    result = service.parse_pdf_sync(
        file_name="whole.pdf",
        file_content=base64.b64encode(_build_pdf(12)).decode(),
        content_type="application/pdf",
    )

    assert result["text"] == "whole"
    assert calls == ["whole.pdf"]


def _build_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
