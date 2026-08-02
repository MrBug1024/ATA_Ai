"""OCR service adapter used by the ingest graph for PDF and image extraction."""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader, PdfWriter

from ..settings import get_settings


LOGGER = logging.getLogger(__name__)
_REMOTE_OCR_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}
_REMOTE_OCR_SEMAPHORES_LOCK = threading.Lock()


@dataclass
class OCRPayload:
    """Normalized file payload sent to the OCR service."""

    filename: str
    file_bytes: bytes
    content_type: str


@dataclass(frozen=True)
class OCRPDFChunk:
    """One deterministic PDF page range sent as an independent OCR request."""

    index: int
    start_page: int
    end_page: int
    payload: OCRPayload

    @property
    def page_range(self) -> str:
        return f"{self.start_page + 1}-{self.end_page}"


class OCRService:
    """Wrap the remote OCR endpoint with sync and async helpers."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.ocr_base_url.rstrip("/")
        self.api_key = settings.ocr_api_key.strip()
        self.timeout_seconds = settings.ocr_timeout_seconds
        self.verify_ssl = settings.ocr_verify_ssl
        self.backend = settings.ocr_backend
        self.lang_list = settings.ocr_lang_list
        self.table_enable_pdf = settings.ocr_table_enable_pdf
        self.table_enable_image = settings.ocr_table_enable_image
        self.auto_rotate_pdf = settings.ocr_auto_rotate_pdf
        self.auto_rotate_image = settings.ocr_auto_rotate_image
        self.max_parallel = max(1, int(settings.ocr_max_parallel or 1))
        self.pdf_split_enabled = settings.ocr_pdf_split_enabled
        self.pdf_split_threshold_mb = max(1, int(settings.ocr_pdf_split_threshold_mb or 1))
        self.pdf_split_threshold_pages = max(1, int(settings.ocr_pdf_split_threshold_pages or 1))
        self.pdf_chunk_max_mb = max(1, int(settings.ocr_pdf_chunk_max_mb or 1))
        self.pdf_chunk_max_pages = max(1, int(settings.ocr_pdf_chunk_max_pages or 1))
        self.pdf_chunk_concurrency = max(1, int(settings.ocr_pdf_chunk_concurrency or 1))
        self.pdf_chunk_timeout_seconds = max(1, int(settings.ocr_pdf_chunk_timeout_seconds or 1))
        self.pdf_chunk_max_retries = max(0, int(settings.ocr_pdf_chunk_max_retries or 0))

    def parse_pdf_sync(
        self,
        *,
        file_url: str = "",
        file_name: str = "",
        file_content: str = "",
        content_type: str = "",
    ) -> dict:
        """Parse one PDF file into markdown text."""
        payload = self._build_payload(
            file_url=file_url,
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
            default_filename="document.pdf",
            default_content_type="application/pdf",
        )
        return self._parse_pdf_payload_sync(payload, preserve_layout=False)

    def parse_image_sync(
        self,
        *,
        file_url: str = "",
        file_name: str = "",
        file_content: str = "",
        content_type: str = "",
    ) -> dict:
        """Parse one image file into markdown text."""
        payload = self._build_payload(
            file_url=file_url,
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
            default_filename="image.png",
            default_content_type="image/png",
        )
        return self._parse_sync(
            payload,
            table_enable=self.table_enable_image,
            auto_rotate=self.auto_rotate_image,
        )

    def parse_pdf_with_layout_sync(
        self,
        *,
        file_url: str = "",
        file_name: str = "",
        file_content: str = "",
        content_type: str = "",
    ) -> dict:
        """Parse one PDF file and preserve page/layout metadata for traceable chunking."""
        payload = self._build_payload(
            file_url=file_url,
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
            default_filename="document.pdf",
            default_content_type="application/pdf",
        )
        return self._parse_pdf_payload_sync(payload, preserve_layout=True)

    def parse_image_with_layout_sync(
        self,
        *,
        file_url: str = "",
        file_name: str = "",
        file_content: str = "",
        content_type: str = "",
    ) -> dict:
        """Parse one image file and preserve page/layout metadata for traceable chunking."""
        payload = self._build_payload(
            file_url=file_url,
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
            default_filename="image.png",
            default_content_type="image/png",
        )
        return self._parse_sync(
            payload,
            table_enable=self.table_enable_image,
            auto_rotate=self.auto_rotate_image,
            preserve_layout=True,
        )

    async def parse_pdf(
        self,
        *,
        file_url: str = "",
        file_name: str = "",
        file_content: str = "",
        content_type: str = "",
    ) -> dict:
        """Run PDF OCR in a worker so sync and async callers share split behavior."""
        return await asyncio.to_thread(
            self.parse_pdf_sync,
            file_url=file_url,
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
        )

    async def parse_image(
        self,
        *,
        file_url: str = "",
        file_name: str = "",
        file_content: str = "",
        content_type: str = "",
    ) -> dict:
        """Run image OCR in a worker so all remote calls share one concurrency limit."""
        return await asyncio.to_thread(
            self.parse_image_sync,
            file_url=file_url,
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
        )

    def _build_payload(
        self,
        *,
        file_url: str,
        file_name: str,
        file_content: str,
        content_type: str,
        default_filename: str,
        default_content_type: str,
    ) -> OCRPayload:
        """Resolve one OCR file source from URL or base64 content."""
        normalized_name = (file_name or "").strip() or default_filename
        normalized_type = (content_type or "").strip()

        if file_content.strip():
            file_bytes, inferred_type = self._decode_inline_content(file_content)
            normalized_type = normalized_type or inferred_type or default_content_type
            normalized_name = self._ensure_filename_extension(
                normalized_name,
                normalized_type,
                default_filename=default_filename,
            )
            return OCRPayload(
                filename=normalized_name,
                file_bytes=file_bytes,
                content_type=self._normalize_content_type(normalized_type, normalized_name, default_content_type),
            )

        if not file_url.strip():
            raise ValueError("missing file_url or base64 file_content")

        with httpx.Client(
            follow_redirects=True,
            timeout=60,
            verify=self.verify_ssl,
        ) as client:
            response = client.get(file_url)
            response.raise_for_status()
            file_bytes = response.content
            normalized_type = normalized_type or response.headers.get("Content-Type", "")

        if not file_name.strip():
            normalized_name = file_url.split("?")[0].split("/")[-1] or default_filename
        normalized_name = self._ensure_filename_extension(
            normalized_name,
            normalized_type,
            default_filename=default_filename,
        )
        return OCRPayload(
            filename=normalized_name,
            file_bytes=file_bytes,
            content_type=self._normalize_content_type(normalized_type, normalized_name, default_content_type),
        )

    def _parse_sync(
        self,
        payload: OCRPayload,
        *,
        table_enable: bool,
        auto_rotate: bool,
        preserve_layout: bool = False,
        timeout_seconds: int | None = None,
    ) -> dict:
        """Send one OCR request synchronously and normalize its response."""
        remote_slot = _get_remote_ocr_semaphore(self.max_parallel)
        with remote_slot:
            with httpx.Client(
                timeout=timeout_seconds or self.timeout_seconds,
                verify=self.verify_ssl,
            ) as client:
                response = client.post(
                    f"{self.base_url}/api/parse/sync",
                    files={"file": (payload.filename, payload.file_bytes, payload.content_type)},
                    headers=self._build_headers(),
                    data={
                        "backend": self.backend,
                        "lang_list": self.lang_list,
                        "formula_enable": "false",
                        "table_enable": str(table_enable).lower(),
                        "auto_rotate": str(auto_rotate).lower(),
                    },
                )
                return self._normalize_ocr_response(response, preserve_layout=preserve_layout)

    def _parse_pdf_payload_sync(self, payload: OCRPayload, *, preserve_layout: bool) -> dict:
        """Choose whole-file or segmented PDF OCR and apply one timeout fallback."""
        chunks = self._build_pdf_chunks(payload, force=False)
        if chunks:
            return self._parse_pdf_chunks_sync(chunks, preserve_layout=preserve_layout)

        try:
            result = self._parse_sync(
                payload,
                table_enable=self.table_enable_pdf,
                auto_rotate=self.auto_rotate_pdf,
                preserve_layout=preserve_layout,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if not self.pdf_split_enabled:
                raise
            LOGGER.warning("ocr_pdf_whole_request_fallback file=%s error=%s", payload.filename, exc)
            chunks = self._build_pdf_chunks(payload, force=True)
            return self._parse_pdf_chunks_sync(chunks, preserve_layout=preserve_layout)

        if self.pdf_split_enabled and _is_retryable_ocr_result(result):
            LOGGER.warning(
                "ocr_pdf_whole_result_fallback file=%s message=%s",
                payload.filename,
                str(result.get("message", ""))[:240],
            )
            chunks = self._build_pdf_chunks(payload, force=True)
            return self._parse_pdf_chunks_sync(chunks, preserve_layout=preserve_layout)
        return result

    def _build_pdf_chunks(self, payload: OCRPayload, *, force: bool) -> list[OCRPDFChunk]:
        """Build deterministic page ranges constrained by page count and serialized size."""
        if not self.pdf_split_enabled:
            return []
        threshold_bytes = self.pdf_split_threshold_mb * 1024 * 1024
        try:
            reader = PdfReader(BytesIO(payload.file_bytes), strict=False)
            page_count = len(reader.pages)
        except Exception as exc:
            if force or len(payload.file_bytes) >= threshold_bytes:
                raise ValueError(f"OCR_PDF_SPLIT_FAILED file={payload.filename}: {exc}") from exc
            return []

        should_split = (
            force
            or len(payload.file_bytes) >= threshold_bytes
            or page_count >= self.pdf_split_threshold_pages
        )
        if not should_split or page_count <= 0:
            return []

        max_bytes = self.pdf_chunk_max_mb * 1024 * 1024
        page_groups: list[tuple[list[int], bytes]] = []
        current_pages: list[int] = []
        current_bytes = b""
        for page_index in range(page_count):
            candidate_pages = [*current_pages, page_index]
            if len(candidate_pages) > self.pdf_chunk_max_pages:
                page_groups.append((current_pages, current_bytes))
                current_pages = [page_index]
                current_bytes = _serialize_pdf_pages(reader, current_pages)
            else:
                candidate_bytes = _serialize_pdf_pages(reader, candidate_pages)
                if current_pages and len(candidate_bytes) > max_bytes:
                    page_groups.append((current_pages, current_bytes))
                    current_pages = [page_index]
                    current_bytes = _serialize_pdf_pages(reader, current_pages)
                else:
                    current_pages = candidate_pages
                    current_bytes = candidate_bytes
            if len(current_bytes) > max_bytes and len(current_pages) == 1:
                raise ValueError(
                    "OCR_SINGLE_PAGE_TOO_LARGE "
                    f"file={payload.filename} page={current_pages[0] + 1} "
                    f"bytes={len(current_bytes)} limit={max_bytes}"
                )
        if current_pages:
            page_groups.append((current_pages, current_bytes))

        stem = Path(payload.filename).stem or "document"
        chunks = [
            OCRPDFChunk(
                index=index,
                start_page=pages[0],
                end_page=pages[-1] + 1,
                payload=OCRPayload(
                    filename=(
                        f"{stem}.part-{index + 1:03d}.pages-{pages[0] + 1:04d}-{pages[-1] + 1:04d}.pdf"
                    ),
                    file_bytes=chunk_bytes,
                    content_type="application/pdf",
                ),
            )
            for index, (pages, chunk_bytes) in enumerate(page_groups)
        ]
        LOGGER.info(
            "ocr_pdf_split file=%s bytes=%s pages=%s chunks=%s ranges=%s",
            payload.filename,
            len(payload.file_bytes),
            page_count,
            len(chunks),
            [chunk.page_range for chunk in chunks],
        )
        return chunks

    def _parse_pdf_chunks_sync(
        self,
        chunks: list[OCRPDFChunk],
        *,
        preserve_layout: bool,
    ) -> dict:
        """OCR independent page ranges concurrently and merge them in original order."""
        if not chunks:
            raise ValueError("OCR_PDF_SPLIT_FAILED: no chunks generated")
        max_workers = max(
            1,
            min(self.pdf_chunk_concurrency, self.max_parallel, len(chunks)),
        )
        if max_workers == 1:
            results = [
                (
                    chunk,
                    self._parse_pdf_chunk_with_retries(
                        chunk,
                        preserve_layout=preserve_layout,
                    ),
                )
                for chunk in chunks
            ]
            return _merge_pdf_chunk_results(results, preserve_layout=preserve_layout)

        results: list[tuple[OCRPDFChunk, dict]] = []
        failures: list[tuple[OCRPDFChunk, Exception]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    self._parse_pdf_chunk_with_retries,
                    chunk,
                    preserve_layout=preserve_layout,
                ): chunk
                for chunk in chunks
            }
            for future in as_completed(future_map):
                chunk = future_map[future]
                try:
                    results.append((chunk, future.result()))
                except Exception as exc:
                    failures.append((chunk, exc))
                    for pending in future_map:
                        if pending is not future:
                            pending.cancel()
        if failures:
            failures.sort(key=lambda item: item[0].index)
            raise RuntimeError("; ".join(str(exc) for _, exc in failures))
        results.sort(key=lambda item: item[0].index)
        return _merge_pdf_chunk_results(results, preserve_layout=preserve_layout)

    def _parse_pdf_chunk_with_retries(
        self,
        chunk: OCRPDFChunk,
        *,
        preserve_layout: bool,
    ) -> dict:
        """Retry only one failed page range and retain a precise terminal error."""
        attempts = self.pdf_chunk_max_retries + 1
        attempt_count = 0
        last_error = "OCR未返回内容"
        for attempt in range(1, attempts + 1):
            attempt_count = attempt
            try:
                result = self._parse_sync(
                    chunk.payload,
                    table_enable=self.table_enable_pdf,
                    auto_rotate=self.auto_rotate_pdf,
                    preserve_layout=preserve_layout,
                    timeout_seconds=self.pdf_chunk_timeout_seconds,
                )
            except httpx.ReadTimeout as exc:
                last_error = str(exc) or exc.__class__.__name__
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = str(exc) or exc.__class__.__name__
            else:
                if str(result.get("text", "") or "").strip():
                    return result
                last_error = str(result.get("message", "") or "OCR未返回内容")
                if not _is_retryable_ocr_result(result):
                    break
            if attempt < attempts:
                LOGGER.warning(
                    "ocr_pdf_chunk_retry file=%s pages=%s attempt=%s/%s error=%s",
                    chunk.payload.filename,
                    chunk.page_range,
                    attempt,
                    attempts,
                    last_error[:240],
                )
                time.sleep(min(attempt, 2))
        raise RuntimeError(
            "OCR_PDF_CHUNK_FAILED "
            f"pages={chunk.page_range} attempts={attempt_count}: {last_error}"
        )

    def _build_headers(self) -> dict[str, str]:
        """Build optional OCR auth headers from environment settings."""
        if not self.api_key:
            return {}
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
        }

    def _normalize_ocr_response(self, response: httpx.Response, *, preserve_layout: bool = False) -> dict:
        """Convert raw OCR HTTP responses into the local `{text, message}` shape."""
        if response.status_code != 200:
            return {
                "text": "",
                "message": f"HTTP {response.status_code}: {response.text}",
                "pages": [],
                "blocks": [],
                "page_width": 0,
                "page_height": 0,
                "raw_response": {},
            }
        data = response.json()
        if data.get("status") == "failed":
            return {
                "text": "",
                "message": f"OCR失败: {data.get('error') or 'unknown error'}",
                "pages": [],
                "blocks": [],
                "page_width": 0,
                "page_height": 0,
                "raw_response": data if preserve_layout else {},
            }
        text = data.get("markdown") or data.get("text") or ""
        result = {
            "text": text,
            "message": data.get("message") or "success",
        }
        if preserve_layout:
            result.update(self._extract_layout_fields(data))
        return result

    def _extract_layout_fields(self, data: dict) -> dict:
        """Normalize layout-like OCR fields without binding the code to one exact upstream schema."""
        pages = data.get("pages")
        if not isinstance(pages, list):
            pages = []

        blocks = data.get("blocks")
        if not isinstance(blocks, list):
            blocks = []
        if not blocks:
            fallback_blocks = data.get("content_list")
            if isinstance(fallback_blocks, list):
                blocks = fallback_blocks

        page_width = 0
        page_height = 0
        if pages and isinstance(pages[0], dict):
            page_width = int(pages[0].get("width") or pages[0].get("page_width") or 0)
            page_height = int(pages[0].get("height") or pages[0].get("page_height") or 0)

        return {
            "pages": pages,
            "blocks": blocks,
            "page_width": page_width,
            "page_height": page_height,
            "raw_response": data,
        }

    def _decode_inline_content(self, file_content: str) -> tuple[bytes, str]:
        """Decode inline base64 payloads from upload metadata."""
        raw_content = file_content.strip()
        inferred_type = ""
        if raw_content.startswith("data:") and ";base64," in raw_content:
            header, encoded = raw_content.split(",", 1)
            inferred_type = header.split(";", 1)[0][5:]
            return base64.b64decode(encoded), inferred_type
        return base64.b64decode(raw_content), inferred_type

    def _ensure_filename_extension(
        self,
        file_name: str,
        content_type: str,
        *,
        default_filename: str,
    ) -> str:
        """Patch missing filename extensions so multipart OCR uploads stay explicit."""
        normalized_name = file_name or default_filename
        if "." in normalized_name:
            return normalized_name
        extension = mimetypes.guess_extension(content_type or "") or ""
        if not extension and "." in default_filename:
            extension = default_filename[default_filename.rfind(".") :]
        return f"{normalized_name}{extension or ''}"

    def _normalize_content_type(
        self,
        content_type: str,
        file_name: str,
        default_content_type: str,
    ) -> str:
        """Backfill content type when upstream uploads only provide octet-stream."""
        normalized_type = (content_type or "").strip()
        if normalized_type and normalized_type != "application/octet-stream":
            return normalized_type
        guessed_type, _ = mimetypes.guess_type(file_name)
        return guessed_type or default_content_type


def get_ocr_service() -> OCRService:
    """Build the OCR service adapter from environment settings."""
    return OCRService()


def _get_remote_ocr_semaphore(limit: int) -> threading.BoundedSemaphore:
    normalized_limit = max(1, int(limit or 1))
    with _REMOTE_OCR_SEMAPHORES_LOCK:
        semaphore = _REMOTE_OCR_SEMAPHORES.get(normalized_limit)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(normalized_limit)
            _REMOTE_OCR_SEMAPHORES[normalized_limit] = semaphore
        return semaphore


def _serialize_pdf_pages(reader: PdfReader, page_indices: list[int]) -> bytes:
    writer = PdfWriter()
    for page_index in page_indices:
        writer.add_page(reader.pages[page_index])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _is_retryable_ocr_result(result: dict) -> bool:
    message = str(result.get("message", "") or "").lower()
    return (
        message.startswith("http 5")
        or "operation timed out" in message
        or "read operation timed out" in message
        or "timeout" in message
    )


def _merge_pdf_chunk_results(
    results: list[tuple[OCRPDFChunk, dict]],
    *,
    preserve_layout: bool,
) -> dict:
    texts: list[str] = []
    pages: list[dict] = []
    blocks: list[dict] = []
    chunk_summaries: list[dict] = []
    page_width = 0
    page_height = 0

    for chunk, result in results:
        text = str(result.get("text", "") or "").strip()
        if text:
            texts.append(text)
        if not preserve_layout:
            continue
        page_width = page_width or int(result.get("page_width", 0) or 0)
        page_height = page_height or int(result.get("page_height", 0) or 0)
        chunk_pages = [item for item in result.get("pages", []) if isinstance(item, dict)]
        for local_index, page in enumerate(chunk_pages):
            normalized_page = dict(page)
            if "page_idx" in normalized_page:
                normalized_page["page_idx"] = int(normalized_page.get("page_idx", 0) or 0) + chunk.start_page
            else:
                normalized_page["page_idx"] = chunk.start_page + local_index
            if "page_no" in normalized_page:
                normalized_page["page_no"] = int(normalized_page.get("page_no", 0) or 0) + chunk.start_page
            pages.append(normalized_page)
        for block in result.get("blocks", []):
            if not isinstance(block, dict):
                continue
            normalized_block = dict(block)
            normalized_block["page_idx"] = int(normalized_block.get("page_idx", 0) or 0) + chunk.start_page
            if "page_no" in normalized_block:
                normalized_block["page_no"] = int(normalized_block.get("page_no", 0) or 0) + chunk.start_page
            blocks.append(normalized_block)
        chunk_summaries.append(
            {
                "index": chunk.index,
                "pages": chunk.page_range,
                "text_chars": len(text),
                "page_count": len(chunk_pages),
                "block_count": len(result.get("blocks", []) or []),
            }
        )

    merged = {
        "text": "\n\n".join(texts),
        "message": "success",
        "segmented": True,
        "chunk_count": len(results),
    }
    if preserve_layout:
        merged.update(
            {
                "pages": pages,
                "blocks": blocks,
                "page_width": page_width,
                "page_height": page_height,
                "raw_response": {
                    "segmented": True,
                    "chunk_count": len(results),
                    "chunks": chunk_summaries,
                },
            }
        )
    return merged
