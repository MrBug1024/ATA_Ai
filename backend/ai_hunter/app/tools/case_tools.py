"""LangChain case and enterprise tools backed by the FastAPI service."""

from langchain_core.tools import tool

from ..services.audit_api import get_audit_api_client
from ..services.case_api import get_case_api_client
from ..services.enterprise_api import get_enterprise_api_client
from .summary_utils import build_tool_error, build_tool_result


@tool
def fetch_enterprise(case_id: int, company_name: str, depth: int = 2) -> str:
    """Fetch enterprise penetration data for a company within the current case."""
    try:
        return build_tool_result(
            "fetch_enterprise",
            get_enterprise_api_client().fetch_enterprise_sync(case_id, company_name, depth),
            next_hint="如需继续穿透，请指定主体、层级或关联关系类型。",
        )
    except Exception as exc:
        return build_tool_error("fetch_enterprise", exc)


@tool
def create_case(
    case_name: str,
    debtor_name: str,
    case_type: str = "破产重整",
    debtor_uscc: str | None = None,
) -> str:
    """Create a case and its debtor seed record."""
    try:
        payload = {
            "case_name": case_name,
            "debtor_name": debtor_name,
            "case_type": case_type,
            "debtor_uscc": debtor_uscc,
        }
        return build_tool_result(
            "create_case",
            get_case_api_client().create_case_sync(payload),
            next_hint="如需继续补材料，可继续调用 parse_document 或 ingest_structured_fields。",
        )
    except Exception as exc:
        return build_tool_error("create_case", exc)


@tool
def parse_document(
    text: str,
    case_id: int | None = None,
    debtor_id: int | None = None,
    debtor_name: str | None = None,
    case_name: str | None = None,
    source_filename: str | None = None,
    max_workers: int = 2,
) -> str:
    """Submit aggregated document text for parsing and ingestion."""
    try:
        payload = {
            "case_id": case_id,
            "debtor_id": debtor_id,
            "debtor_name": debtor_name,
            "case_name": case_name,
            "text": text,
            "source_filename": source_filename,
            "max_workers": max_workers,
        }
        return build_tool_result(
            "parse_document",
            get_audit_api_client().parse_document_sync(payload),
            next_hint="如需继续入库，请指定文档类别或补充结构化字段。",
        )
    except Exception as exc:
        return build_tool_error("parse_document", exc)


@tool
def ingest_structured_fields(case_id: int, debtor_id: int, doc_category: str, fields: dict) -> str:
    """Ingest structured fields into the backend storage tables."""
    try:
        return build_tool_result(
            "ingest_structured_fields",
            get_audit_api_client().ingest_structured_fields_sync(
                case_id=case_id,
                debtor_id=debtor_id,
                doc_category=doc_category,
                fields=fields,
            ),
            next_hint="如需继续补录，请指定下一类文档或字段。",
        )
    except Exception as exc:
        return build_tool_error("ingest_structured_fields", exc)
