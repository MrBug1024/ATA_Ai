"""Run the unified API with ``python -m ai_hunter``."""

import asyncio
import sys

import uvicorn

from .app.settings import get_settings


def configure_event_loop_policy() -> None:
    """Use the psycopg-compatible selector loop for Windows async I/O."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def uvicorn_loop_setting() -> str:
    """Keep the configured Selector policy when Uvicorn creates its loop."""

    if sys.platform == "win32":
        return "asyncio"
    return "auto"


def main() -> None:
    configure_event_loop_policy()
    settings = get_settings()
    uvicorn.run(
        "ai_hunter.app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        loop=uvicorn_loop_setting(),
    )


if __name__ == "__main__":
    main()
