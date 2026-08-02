"""Case and case-adjacent HTTP wrappers."""

from typing import TYPE_CHECKING

from ..settings import get_settings
from .base import BaseAPIClient

if TYPE_CHECKING:
    from ..auth.identity import Identity


def tenant_params_from_identity(identity: "Identity | None") -> dict:
    """Build the tenant context expected by NpaDemo case APIs."""
    if identity is None:
        return {}
    params = {
        "company_id": identity.company_id,
        "user_id": identity.user_id,
        "is_company_admin": identity.is_company_admin,
        "is_super_admin": identity.is_super_admin,
    }
    return {key: value for key, value in params.items() if value not in ("", None)}


def stamp_case_payload(payload: dict, identity: "Identity | None") -> dict:
    """Stamp case creation payload with tenant ownership fields."""
    data = dict(payload or {})
    if identity is None:
        return data
    if identity.company_id:
        data["company_id"] = identity.company_id
    if identity.user_id:
        if not (identity.is_company_admin or identity.is_super_admin):
            data["owner_id"] = identity.user_id
        else:
            data.setdefault("owner_id", identity.user_id)
        data["created_by"] = identity.user_id
    return data


class CaseAPIClient(BaseAPIClient):
    """Wrappers around case creation and read APIs."""

    async def create_case(self, payload: dict, *, identity: "Identity | None" = None) -> dict:
        return await self.post_json("/api/ingest/case", stamp_case_payload(payload, identity))

    async def get_case_profile(self, case_id: int, *, identity: "Identity | None" = None) -> dict:
        return await self.get_json(
            f"/api/case/{case_id}/profile",
            params=tenant_params_from_identity(identity),
        )

    async def list_cases(self, params: dict | None = None, *, identity: "Identity | None" = None) -> dict:
        query = dict(params or {})
        query.update(tenant_params_from_identity(identity))
        return await self.get_json("/api/cases", params=query)

    async def list_case_parties(
        self,
        case_id: int,
        *,
        status: str | None = None,
        identity: "Identity | None" = None,
    ) -> dict:
        query = tenant_params_from_identity(identity)
        if status:
            query["status"] = status
        return await self.get_json(f"/api/cases/{case_id}/parties", params=query)

    async def upsert_case_party(
        self,
        case_id: int,
        payload: dict,
        *,
        identity: "Identity | None" = None,
    ) -> dict:
        return await self.post_json(
            f"/api/cases/{case_id}/parties",
            dict(payload or {}),
            params=tenant_params_from_identity(identity),
        )

    def create_case_sync(self, payload: dict, *, identity: "Identity | None" = None) -> dict:
        return self.post_json_sync("/api/ingest/case", stamp_case_payload(payload, identity))

    def get_case_profile_sync(self, case_id: int, *, identity: "Identity | None" = None) -> dict:
        return self.get_json_sync(
            f"/api/case/{case_id}/profile",
            params=tenant_params_from_identity(identity),
        )

    def list_cases_sync(self, params: dict | None = None, *, identity: "Identity | None" = None) -> dict:
        query = dict(params or {})
        query.update(tenant_params_from_identity(identity))
        return self.get_json_sync("/api/cases", params=query)

    def list_case_parties_sync(
        self,
        case_id: int,
        *,
        status: str | None = None,
        identity: "Identity | None" = None,
    ) -> dict:
        query = tenant_params_from_identity(identity)
        if status:
            query["status"] = status
        return self.get_json_sync(f"/api/cases/{case_id}/parties", params=query)

    def upsert_case_party_sync(
        self,
        case_id: int,
        payload: dict,
        *,
        identity: "Identity | None" = None,
    ) -> dict:
        return self.post_json_sync(
            f"/api/cases/{case_id}/parties",
            dict(payload or {}),
            params=tenant_params_from_identity(identity),
        )


def get_case_api_client() -> CaseAPIClient:
    """Build the case client from environment settings."""
    settings = get_settings()
    return CaseAPIClient(
        base_url=settings.case_api_base_url or settings.unified_api_base_url,
        timeout_seconds=settings.audit_api_timeout_seconds,
        token=settings.audit_api_token,
    )
