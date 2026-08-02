"""Audit backend client for context fetch and document ingestion."""

from ..settings import get_settings
from .base import BaseAPIClient


class AuditAPIClient(BaseAPIClient):
    """Typed wrappers around the audit and ingestion endpoints."""

    async def get_full_context(self, case_id: int) -> dict:
        return await self.post_json("/api/audit/get_full_context", {"case_id": case_id})

    async def parse_document(self, payload: dict) -> dict:
        return await self.post_json("/api/ingest/parse-document", payload)

    def get_full_context_sync(self, case_id: int) -> dict:
        return self.post_json_sync("/api/audit/get_full_context", {"case_id": case_id})

    def parse_document_sync(self, payload: dict) -> dict:
        return self.post_json_sync("/api/ingest/parse-document", payload)

    def audit_delta_check_sync(self, case_id: int) -> dict:
        return self.post_json_sync("/api/audit/delta-check", {"case_id": case_id})

    def audit_valuation_squeeze_sync(self, case_id: int) -> dict:
        return self.post_json_sync("/api/audit/valuation-squeeze", {"case_id": case_id})

    def audit_deadline_scan_sync(self, case_id: int) -> dict:
        return self.post_json_sync("/api/audit/deadline-scan", {"case_id": case_id})

    def audit_behavioral_scan_sync(self, case_id: int) -> dict:
        return self.post_json_sync("/api/audit/behavioral-scan", {"case_id": case_id})

    def ingest_structured_fields_sync(
        self,
        case_id: int,
        debtor_id: int,
        doc_category: str,
        fields: dict,
    ) -> dict:
        return self.post_json_sync(
            "/api/ingest/structured-fields",
            {
                "case_id": case_id,
                "debtor_id": debtor_id,
                "doc_category": doc_category,
                "fields": fields,
            },
        )


def get_audit_api_client() -> AuditAPIClient:
    """Build the audit client from environment settings."""
    settings = get_settings()
    return AuditAPIClient(
        base_url=settings.audit_api_base_url or settings.unified_api_base_url,
        timeout_seconds=settings.audit_api_timeout_seconds,
        token=settings.audit_api_token,
    )
