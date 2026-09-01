"""Annual-engagement ACL lookups used by the unchanged platform tenancy layer."""

from __future__ import annotations

from typing import Any

from ai_hunter.app.auth.identity import Identity
from ai_hunter.app.settings import Settings, get_settings

from .storage import postgres_connection


def get_engagement_access_record(
    identity: Identity,
    engagement_id: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    if int(engagement_id or 0) <= 0:
        return None
    resolved = settings or get_settings()
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  e.id AS case_id,
                  e.company_id,
                  e.owner_user_id AS owner_id,
                  EXISTS (
                    SELECT 1 FROM ata_project_member pm
                    WHERE pm.engagement_id = e.id AND pm.user_id = %s
                  ) AS is_member
                FROM audit_engagement e
                WHERE e.id = %s AND e.deleted_at IS NULL
                """,
                (identity.user_id or "", engagement_id),
            )
            row = cursor.fetchone()
    return dict(row) if row else None


def list_accessible_engagement_ids(
    identity: Identity,
    *,
    settings: Settings | None = None,
) -> list[int]:
    resolved = settings or get_settings()
    where = ["e.deleted_at IS NULL"]
    params: list[Any] = []
    if not identity.is_super_admin:
        where.append("e.company_id = %s")
        params.append(identity.company_id)
        if not identity.is_company_admin:
            where.append(
                """
                (
                  e.owner_user_id = %s
                  OR EXISTS (
                    SELECT 1 FROM ata_project_member pm
                    WHERE pm.engagement_id = e.id AND pm.user_id = %s
                  )
                )
                """
            )
            params.extend([identity.user_id, identity.user_id])
    with postgres_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT e.id FROM audit_engagement e WHERE {' AND '.join(where)}",
                tuple(params),
            )
            return [int(row["id"]) for row in cursor.fetchall()]


__all__ = ["get_engagement_access_record", "list_accessible_engagement_ids"]
