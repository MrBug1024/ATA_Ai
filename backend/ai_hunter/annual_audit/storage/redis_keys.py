"""Redis key construction with mandatory annual-audit namespacing."""

from __future__ import annotations

from ai_hunter.app.settings import Settings, get_settings
from ai_hunter.platform_core import scoped_redis_key

from .errors import AnnualAuditStorageError


def annual_redis_key(*parts: object, settings: Settings | None = None) -> str:
    resolved = settings or get_settings()
    if resolved.business_domain != "annual_audit":
        raise AnnualAuditStorageError(
            "annual-audit Redis access requires BUSINESS_DOMAIN=annual_audit"
        )
    normalized = [str(part).strip(":") for part in parts if str(part).strip(":")]
    if not normalized:
        raise ValueError("at least one Redis key part is required")
    try:
        return scoped_redis_key(resolved, normalized[0], *normalized[1:])
    except ValueError as exc:
        raise AnnualAuditStorageError(str(exc)) from exc
