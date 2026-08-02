"""Enterprise lookup wrappers for the tool service."""

from ..settings import get_settings
from .base import BaseAPIClient


class EnterpriseAPIClient(BaseAPIClient):
    """Wrappers around enterprise ingestion and whiteglove-like data fetches."""

    async def fetch_enterprise(self, case_id: int, company_name: str, depth: int = 2) -> dict:
        return await self.post_json(
            "/api/ingest/enterprise",
            {"case_id": case_id, "company_name": company_name, "depth": depth},
        )

    async def get_whiteglove(self, case_id: int) -> dict:
        return await self.get_json(f"/api/case/{case_id}/whiteglove")

    async def get_fund_flow(self, case_id: int) -> dict:
        return await self.get_json(f"/api/case/{case_id}/fund-flow")

    def fetch_enterprise_sync(self, case_id: int, company_name: str, depth: int = 2) -> dict:
        return self.post_json_sync(
            "/api/ingest/enterprise",
            {"case_id": case_id, "company_name": company_name, "depth": depth},
        )

    def get_whiteglove_sync(self, case_id: int) -> dict:
        return self.get_json_sync(f"/api/case/{case_id}/whiteglove")

    def get_fund_flow_sync(self, case_id: int) -> dict:
        return self.get_json_sync(f"/api/case/{case_id}/fund-flow")


def get_enterprise_api_client() -> EnterpriseAPIClient:
    """Build the enterprise client from environment settings."""
    settings = get_settings()
    return EnterpriseAPIClient(
        base_url=settings.enterprise_api_base_url or settings.unified_api_base_url,
        timeout_seconds=settings.audit_api_timeout_seconds,
        token=settings.audit_api_token,
    )
