"""Shared HTTP client helpers for the FastAPI tool server."""

import logging
import time

import httpx

from ..logging_utils import preview_text


LOGGER = logging.getLogger(__name__)


class BaseAPIClient:
    """Small wrapper that offers both sync and async JSON helpers."""

    def __init__(self, base_url: str, timeout_seconds: int = 60, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.token = token

    def build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def post_json(self, path: str, payload: dict, params: dict | None = None) -> dict:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    params=params,
                    headers=self.build_headers(),
                )
                response.raise_for_status()
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.info(
                    "http_post_ok base_url=%s path=%s status_code=%s duration_ms=%s response_preview=%s",
                    self.base_url,
                    path,
                    response.status_code,
                    duration_ms,
                    preview_text(response.text, 160),
                )
                return response.json()
            except Exception:
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.exception(
                    "http_post_failed base_url=%s path=%s duration_ms=%s payload_preview=%s",
                    self.base_url,
                    path,
                    duration_ms,
                    preview_text(payload),
                )
                raise

    async def get_json(self, path: str, params: dict | None = None) -> dict:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.get(
                    f"{self.base_url}{path}",
                    params=params,
                    headers=self.build_headers(),
                )
                response.raise_for_status()
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.info(
                    "http_get_ok base_url=%s path=%s status_code=%s duration_ms=%s response_preview=%s",
                    self.base_url,
                    path,
                    response.status_code,
                    duration_ms,
                    preview_text(response.text, 160),
                )
                return response.json()
            except Exception:
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.exception(
                    "http_get_failed base_url=%s path=%s duration_ms=%s params_preview=%s",
                    self.base_url,
                    path,
                    duration_ms,
                    preview_text(params),
                )
                raise

    def post_json_sync(self, path: str, payload: dict, params: dict | None = None) -> dict:
        started_at = time.perf_counter()
        with httpx.Client(timeout=self.timeout_seconds) as client:
            try:
                response = client.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    params=params,
                    headers=self.build_headers(),
                )
                response.raise_for_status()
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.info(
                    "http_post_sync_ok base_url=%s path=%s status_code=%s duration_ms=%s response_preview=%s",
                    self.base_url,
                    path,
                    response.status_code,
                    duration_ms,
                    preview_text(response.text, 160),
                )
                return response.json()
            except Exception:
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.exception(
                    "http_post_sync_failed base_url=%s path=%s duration_ms=%s payload_preview=%s",
                    self.base_url,
                    path,
                    duration_ms,
                    preview_text(payload),
                )
                raise

    def get_json_sync(self, path: str, params: dict | None = None) -> dict:
        started_at = time.perf_counter()
        with httpx.Client(timeout=self.timeout_seconds) as client:
            try:
                response = client.get(
                    f"{self.base_url}{path}",
                    params=params,
                    headers=self.build_headers(),
                )
                response.raise_for_status()
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.info(
                    "http_get_sync_ok base_url=%s path=%s status_code=%s duration_ms=%s response_preview=%s",
                    self.base_url,
                    path,
                    response.status_code,
                    duration_ms,
                    preview_text(response.text, 160),
                )
                return response.json()
            except Exception:
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                LOGGER.exception(
                    "http_get_sync_failed base_url=%s path=%s duration_ms=%s params_preview=%s",
                    self.base_url,
                    path,
                    duration_ms,
                    preview_text(params),
                )
                raise
