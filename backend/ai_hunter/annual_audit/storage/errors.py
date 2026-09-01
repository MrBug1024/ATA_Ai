"""Storage errors safe to expose outside the annual-audit persistence layer."""


class AnnualAuditStorageError(RuntimeError):
    """Raised when annual-audit PostgreSQL storage cannot be used safely."""

