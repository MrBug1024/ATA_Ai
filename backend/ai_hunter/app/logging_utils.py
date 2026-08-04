"""Application logging setup and small helpers for request-scoped log fields."""

from __future__ import annotations

import logging
import re
from logging.config import dictConfig
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any
from uuid import uuid4

from .settings import get_settings


_LOGGING_CONFIGURED = False


class RequestContextFilter(logging.Filter):
    """Ensure common request-scoped log fields always exist on log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        if not hasattr(record, "thread_id"):
            record.thread_id = "-"
        if not hasattr(record, "case_id"):
            record.case_id = "-"
        return True


class DailySuffixFileHandler(TimedRotatingFileHandler):
    """Timed rotating handler with `name.YYYY-MM-DD.log` archive naming."""

    def __init__(self, filename: str, backup_count: int, encoding: str = "utf-8") -> None:
        super().__init__(
            filename=filename,
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding=encoding,
        )
        self.suffix = "%Y-%m-%d"
        self.extMatch = re.compile(r"^\d{4}-\d{2}-\d{2}(\.\w+)?$", re.ASCII)

    def rotation_filename(self, default_name: str) -> str:
        """Rename `app.log.YYYY-MM-DD` into `app.YYYY-MM-DD.log`."""
        path = Path(default_name)
        parts = path.name.split(".")
        if len(parts) >= 3:
            stem = ".".join(parts[:-2])
            date_part = parts[-1]
            return str(path.with_name(f"{stem}.{date_part}.log"))
        return default_name

    def getFilesToDelete(self) -> list[str]:
        """Delete archived files that match the custom `name.YYYY-MM-DD.log` pattern."""
        dir_name, base_name = str(Path(self.baseFilename).parent), Path(self.baseFilename).name
        stem = base_name[:-4] if base_name.endswith(".log") else base_name
        pattern = re.compile(rf"^{re.escape(stem)}\.\d{{4}}-\d{{2}}-\d{{2}}\.log$")
        result: list[str] = []

        for entry in Path(dir_name).iterdir():
            if pattern.match(entry.name):
                result.append(str(entry))

        result.sort()
        if len(result) <= self.backupCount:
            return []
        return result[: len(result) - self.backupCount]


def configure_logging() -> None:
    """Configure root logging once for the application process."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    settings = get_settings()
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    app_log_file = log_dir / settings.log_app_file_name
    access_log_file = log_dir / settings.log_access_file_name

    def can_write(path: Path) -> bool:
        """Return whether a file handler can be opened in this runtime."""

        try:
            with path.open("a", encoding="utf-8"):
                pass
            return True
        except OSError:
            return False

    formatter = (
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        if not settings.log_include_request_fields
        else "%(asctime)s | %(levelname)s | %(name)s | %(message)s | "
        "request_id=%(request_id)s | thread_id=%(thread_id)s | case_id=%(case_id)s"
    )

    handlers: dict[str, dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "filters": ["request_context"],
        }
    }
    root_handlers = ["console"]
    access_handlers = ["console"]
    if can_write(app_log_file):
        handlers["app_file"] = {
            "()": DailySuffixFileHandler,
            "formatter": "default",
            "filters": ["request_context"],
            "filename": str(app_log_file),
            "backup_count": settings.log_file_backup_count,
            "encoding": "utf-8",
        }
        root_handlers.append("app_file")
    if can_write(access_log_file):
        handlers["access_file"] = {
            "()": DailySuffixFileHandler,
            "formatter": "default",
            "filters": ["request_context"],
            "filename": str(access_log_file),
            "backup_count": settings.log_file_backup_count,
            "encoding": "utf-8",
        }
        access_handlers.append("access_file")

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": formatter,
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "filters": {
                "request_context": {
                    "()": RequestContextFilter,
                }
            },
            "handlers": handlers,
            "root": {
                "level": settings.log_level.upper(),
                "handlers": root_handlers,
            },
            "loggers": {
                "ai_hunter.access": {
                    "level": settings.log_level.upper(),
                    "handlers": access_handlers,
                    "propagate": False,
                }
            },
        }
    )
    _LOGGING_CONFIGURED = True


def build_request_logger(
    name: str,
    *,
    request_id: str = "-",
    thread_id: str = "-",
    case_id: int | str = "-",
) -> logging.LoggerAdapter:
    """Create a logger adapter carrying request-scoped fields."""
    logger = logging.getLogger(name)
    return logging.LoggerAdapter(
        logger,
        {
            "request_id": request_id,
            "thread_id": thread_id,
            "case_id": case_id,
        },
    )


def make_request_id() -> str:
    """Generate a short request ID for access and business logs."""
    return uuid4().hex[:12]


def preview_text(value: Any, max_chars: int | None = None) -> str:
    """Render a compact preview string for log messages."""
    settings = get_settings()
    limit = max_chars or settings.log_payload_preview_chars
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated)"
