"""Run the unified API with ``python -m ai_hunter``."""

import uvicorn

from .app.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ai_hunter.app.main:app",
        host=settings.app_host,
        port=settings.app_port,
    )


if __name__ == "__main__":
    main()
