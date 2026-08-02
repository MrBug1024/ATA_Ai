"""Document-category dictionary and validation API client."""

from __future__ import annotations

from functools import lru_cache

import httpx

from ..graph.schemas import (
    CaseDocCategoryStatusModel,
    DocCategoryCatalogModel,
    DocCategoryDefinitionModel,
    ValidateDocCategoryRequestModel,
    ValidateDocCategoryResultModel,
)
from ..settings import get_settings
from .base import BaseAPIClient


DEFAULT_DOC_CATEGORIES = [
    {
        "code": "loan_contract",
        "name": "贷款合同",
        "description": "贷款主合同、借款合同、授信合同等。",
        "sort_order": 1,
        "enabled": True,
        "fields": [
            "principal",
            "interest",
            "penalty",
            "delayed_interest",
            "total_claim",
            "guarantee_type",
            "collateral_desc",
            "lien_priority",
            "court_name",
            "exec_case_no",
            "litigation_status",
            "guarantor_names",
        ],
    },
    {
        "code": "judgment",
        "name": "判决书",
        "description": "判决书、裁定书、执行文书等。",
        "sort_order": 2,
        "enabled": True,
        "fields": [
            "case_number",
            "court_name",
            "case_cause",
            "doc_type",
            "judgment_date",
            "plaintiff",
            "defendant",
            "claim_amount",
            "judgment_amount",
            "execution_status",
            "enforcement_deadline",
            "court_level",
            "case_type",
        ],
    },
    {
        "code": "financial_statement",
        "name": "财务报表",
        "description": "资产负债表、利润表、财务报表附注等。",
        "sort_order": 3,
        "enabled": True,
        "fields": [
            "report_period",
            "report_type",
            "other_receivables",
            "prepayments",
            "total_assets",
            "total_liabilities",
            "revenue",
            "operating_cost",
            "net_profit",
            "tax_reported_revenue",
            "tax_reported_cost",
        ],
    },
    {
        "code": "real_estate_cert",
        "name": "不动产权证",
        "description": "房产证、土地证、不动产权证等。",
        "sort_order": 4,
        "enabled": True,
        "fields": [
            "property_owner",
            "property_address",
            "real_estate_cert_no",
            "land_nature",
            "total_building_area",
            "land_use_area",
            "property_usage",
            "mortgage_status",
            "seal_status",
            "seal_expiry",
            "lease_status",
            "gross_value",
            "has_title_objection",
            "physical_occupation",
            "lien_priority",
            "sealing_court",
            "lease_annual_rent",
            "lease_start",
            "lease_end",
        ],
    },
    {
        "code": "mining_permit",
        "name": "采矿许可证",
        "description": "采矿权许可证及相关审批资料。",
        "sort_order": 5,
        "enabled": True,
        "fields": [
            "mine_name",
            "mine_location",
            "permit_expiry",
            "production_scale",
            "mineral_type",
            "mine_scale",
            "mining_status",
            "safety_permit_status",
            "env_approval_status",
            "mining_right_mortgage",
            "mining_right_sealed",
            "proved_reserves",
            "estimated_value",
            "eco_redline_status",
        ],
    },
    {
        "code": "bank_statement",
        "name": "银行流水",
        "description": "银行账户流水、回单等。",
        "sort_order": 6,
        "enabled": True,
        "fields": ["transactions"],
    },
    {
        "code": "guarantee_contract",
        "name": "担保合同",
        "description": "保证合同、抵押合同等。",
        "sort_order": 7,
        "enabled": True,
        "fields": [
            "guarantor_name",
            "guarantor_type",
            "guarantee_type",
            "guarantee_scope",
            "spouse_name",
        ],
    },
    {
        "code": "restructuring_plan",
        "name": "煤矿重整方案",
        "description": "重整计划、招募投资人方案等。",
        "sort_order": 8,
        "enabled": True,
        "fields": [
            "mine_name",
            "debtor_name",
            "administrator",
            "administrator_contact",
            "investor_name",
            "investor_contact",
            "total_debt",
            "secured_debt",
            "unsecured_debt",
            "employee_debt",
            "tax_debt",
            "proposed_recovery_rate",
            "asset_list_summary",
            "restructuring_timeline",
            "court_name",
            "case_number",
            "key_conditions",
        ],
    },
    {
        "code": "exploration_report",
        "name": "勘探报告",
        "description": "地质勘查、储量核实、勘探成果报告。",
        "sort_order": 9,
        "enabled": True,
        "fields": [
            "mine_name",
            "report_name",
            "report_date",
            "report_org",
            "mineral_type",
            "proved_reserves",
            "controlled_reserves",
            "inferred_resources",
            "total_reserves",
            "calorific_value",
            "ash_content_pct",
            "sulfur_content_pct",
            "coal_type",
        ],
    },
    {
        "code": "environmental_approval",
        "name": "环评批复",
        "description": "环评批复、环保验收意见等。",
        "sort_order": 10,
        "enabled": True,
        "fields": [
            "mine_name",
            "env_approval_status",
            "project_scale",
            "eco_redline_status",
        ],
    },
    {
        "code": "court_general_query",
        "name": "法院总对总",
        "description": "法院总对总查控结果。",
        "sort_order": 11,
        "enabled": True,
        "fields": [
            "target_name",
            "query_date",
            "bank_deposits",
            "real_estate_hits",
            "vehicle_hits",
            "securities_hits",
            "insurance_hits",
            "other_hits",
        ],
    },
    {
        "code": "lawyer_investigation",
        "name": "律师调查报告",
        "description": "律师现场调查、尽调访谈、调查结论。",
        "sort_order": 12,
        "enabled": True,
        "fields": [
            "investigator",
            "investigation_date",
            "physical_address_status",
            "employee_status",
            "asset_on_site",
            "lease_situation",
            "key_person_contacts",
            "related_party_findings",
            "asset_transfer_clues",
            "investigation_conclusion",
        ],
    },
    {
        "code": "mining_design_reclamation",
        "name": "开采设计与复垦",
        "description": "开采设计方案、复垦方案、生产设计资料。",
        "sort_order": 13,
        "enabled": True,
        "fields": [
            "mine_name",
            "designed_capacity",
            "mining_method",
            "current_status",
        ],
    },
]


class DocCategoryAPIClient(BaseAPIClient):
    """Wrappers around document-category endpoints on the tool server."""

    def get_doc_categories_sync(self) -> dict:
        return self.get_json_sync("/api/ingest/doc-categories")

    def get_case_doc_categories_sync(self, case_id: int) -> dict:
        return self.get_json_sync(f"/api/case/{case_id}/doc-categories")

    def validate_doc_category_sync(self, payload: dict) -> dict:
        try:
            return self.post_json_sync("/api/ingest/validate-doc-category", payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            return {
                "ok": False,
                "suspected_mismatch": True,
                "suspected_duplicate": False,
                "message": _extract_error_detail(exc.response),
            }


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or "卷宗类别校验失败。"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str) and detail.strip():
        return detail
    return "卷宗类别校验失败。"


class MockDocCategoryService:
    """Stable mock responses used before fastserver_api exposes the real endpoints."""

    def get_doc_categories(self) -> DocCategoryCatalogModel:
        categories = [DocCategoryDefinitionModel.model_validate(item) for item in DEFAULT_DOC_CATEGORIES]
        return DocCategoryCatalogModel(categories=categories)

    def get_case_doc_categories(self, case_id: int) -> CaseDocCategoryStatusModel:
        catalog = self.get_doc_categories()
        return CaseDocCategoryStatusModel(
            case_id=case_id,
            categories=[
                {
                    "code": item.code,
                    "name": item.name,
                    "uploaded": False,
                    "file_count": 0,
                    "record_count": 0,
                    "last_uploaded_at": None,
                }
                for item in catalog.categories
            ],
            missing_categories=[item.code for item in catalog.categories],
        )

    def validate_doc_category(self, payload: ValidateDocCategoryRequestModel | dict) -> ValidateDocCategoryResultModel:
        if isinstance(payload, dict):
            payload = ValidateDocCategoryRequestModel.model_validate(payload)
        category_map = {item["code"]: item["name"] for item in DEFAULT_DOC_CATEGORIES}
        if payload.doc_category not in category_map:
            return ValidateDocCategoryResultModel(
                ok=False,
                suspected_mismatch=True,
                message=f"未知卷宗类别: {payload.doc_category}",
            )
        return ValidateDocCategoryResultModel(
            ok=True,
            suspected_mismatch=False,
            suspected_duplicate=False,
            message=f"已按 {category_map[payload.doc_category]} 预校验，待 fastserver_api 联调后启用真实校验。",
        )


@lru_cache(maxsize=1)
def get_doc_category_api_client() -> DocCategoryAPIClient:
    settings = get_settings()
    return DocCategoryAPIClient(
        base_url=settings.doc_category_api_base_url or settings.unified_api_base_url,
        timeout_seconds=settings.audit_api_timeout_seconds,
        token=settings.audit_api_token,
    )


@lru_cache(maxsize=1)
def get_mock_doc_category_service() -> MockDocCategoryService:
    return MockDocCategoryService()
