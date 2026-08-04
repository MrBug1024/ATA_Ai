"""Run the unified API with ``python -m ai_hunter``."""

import asyncio
import sys

import uvicorn

from .app.settings import get_settings


def configure_event_loop_policy() -> None:
    """Use the psycopg-compatible selector loop for Windows async I/O."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def selector_event_loop_factory() -> asyncio.AbstractEventLoop:
    """Return the selector loop required by psycopg async connections on Windows."""
    return asyncio.SelectorEventLoop()


def uvicorn_loop_setting() -> str:
    """Override Uvicorn's explicit Windows Proactor factory when necessary."""
    if sys.platform == "win32":
        return "ai_hunter.__main__:selector_event_loop_factory"
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
