"""HTTP middleware for request/response access logging."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware

from .logging_utils import build_request_logger, make_request_id


def access_log_path(path: str) -> str:
    """Remove bearer-like path parameters before they reach access logs."""

    if str(path or "").startswith("/api/artifact-access/"):
        return "/api/artifact-access/{token}"
    return str(path or "")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a request ID and emit one access log line per HTTP request."""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id") or make_request_id()
        request.state.request_id = request_id
        started_at = time.perf_counter()
        logged_path = access_log_path(request.url.path)

        # Extract thread_id from paths like /chat/threads/{id}/messages
        thread_id = "-"
        path_parts = request.url.path.strip("/").split("/")
        if (
            len(path_parts) >= 3
            and path_parts[0] == "chat"
            and path_parts[1] == "threads"
        ):
            thread_id = path_parts[2]

        logger = build_request_logger(
            "ai_hunter.access",
            request_id=request_id,
            thread_id=thread_id,
        )
        logger.info("request_started method=%s path=%s", request.method, logged_path)

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.exception(
                "request_failed method=%s path=%s duration_ms=%s",
                request.method,
                logged_path,
                duration_ms,
            )
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed method=%s path=%s status_code=%s duration_ms=%s",
            request.method,
            logged_path,
            response.status_code,
            duration_ms,
        )
        return response
