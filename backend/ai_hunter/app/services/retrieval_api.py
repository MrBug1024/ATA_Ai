"""Retrieval wrappers for legal-writ style lookups."""

from ..services.case_api import get_case_api_client
from ..services.knowledge_api import get_knowledge_api_client
from ..settings import get_settings
from .base import BaseAPIClient


class RetrievalAPIClient(BaseAPIClient):
    async def get_legal_writ(self, payload: dict) -> dict:
        case_id = payload["case_id"]
        params = {
            key: value
            for key, value in payload.items()
            if key != "case_id" and value is not None
        }
        return await self.get_json(f"/api/case/{case_id}/legal-writ", params=params)

    def get_legal_writ_sync(self, payload: dict) -> dict:
        case_id = payload["case_id"]
        params = {
            key: value
            for key, value in payload.items()
            if key != "case_id" and value is not None
        }
        try:
            return self.get_json_sync(f"/api/case/{case_id}/legal-writ", params=params)
        except Exception:
            debtor_name = None
            try:
                profile = get_case_api_client().get_case_profile_sync(case_id)
                debtor_name = (
                    profile.get("debtor_name")
                    or profile.get("name")
                    or profile.get("debtor", {}).get("name")
                )
            except Exception:
                debtor_name = None

            return get_knowledge_api_client().query_case_legal_writ_sync(
                debtor_name=debtor_name,
                q=payload.get("q"),
                doc_type=payload.get("doc_type"),
                date_from=payload.get("date_from"),
                limit=payload.get("limit"),
            )


def get_retrieval_api_client() -> RetrievalAPIClient:
    """Build the retrieval client from environment settings."""
    settings = get_settings()
    return RetrievalAPIClient(
        base_url=settings.case_api_base_url or settings.unified_api_base_url,
        timeout_seconds=settings.audit_api_timeout_seconds,
        token=settings.audit_api_token,
    )
