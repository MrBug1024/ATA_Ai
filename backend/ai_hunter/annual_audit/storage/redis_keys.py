"""Redis key construction with mandatory annual-audit namespacing."""

from __future__ import annotations

from ai_hunter.app.settings import Settings, get_settings

from .mysql import AnnualAuditStorageError


def annual_redis_key(*parts: object, settings: Settings | None = None) -> str:
    resolved = settings or get_settings()
    if resolved.business_domain != "annual_audit":
        raise AnnualAuditStorageError(
            "annual-audit Redis access requires BUSINESS_DOMAIN=annual_audit"
        )
    namespace = resolved.annual_redis_namespace.strip()
    if not namespace.startswith("ata:") or not namespace.endswith(":"):
        raise AnnualAuditStorageError("invalid annual-audit Redis namespace")
    normalized = [str(part).strip(":") for part in parts if str(part).strip(":")]
    if not normalized:
        raise ValueError("at least one Redis key part is required")
    return namespace + ":".join(normalized)

