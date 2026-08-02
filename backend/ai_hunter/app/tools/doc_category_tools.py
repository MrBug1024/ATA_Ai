"""LangChain tools for document-category dictionary and validation."""

from langchain_core.tools import tool

from ..graph.schemas import ValidateDocCategoryRequestModel
from ..services.doc_category_api import (
    get_doc_category_api_client,
    get_mock_doc_category_service,
)
from ..settings import get_settings
from .summary_utils import build_tool_error, build_tool_result


def _use_mock() -> bool:
    return bool(get_settings().enable_doc_category_api_mock)


@tool
def get_doc_categories() -> str:
    """Fetch the standard document-category catalog used for case uploads."""
    try:
        if _use_mock():
            payload = get_mock_doc_category_service().get_doc_categories().model_dump()
        else:
            payload = get_doc_category_api_client().get_doc_categories_sync()
        return build_tool_result(
            "get_doc_categories",
            payload,
            next_hint="上传卷宗时请先选择 doc_category，同一批次只上传一种类别。",
        )
    except Exception as exc:
        return build_tool_error("get_doc_categories", exc)


@tool
def get_case_doc_category_status(case_id: int) -> str:
    """Fetch which document categories are already covered for a case."""
    try:
        if _use_mock():
            payload = get_mock_doc_category_service().get_case_doc_categories(case_id).model_dump()
        else:
            payload = get_doc_category_api_client().get_case_doc_categories_sync(case_id)
        return build_tool_result(
            "get_case_doc_category_status",
            payload,
            next_hint="可据此提示操作员继续补传缺失类别。",
        )
    except Exception as exc:
        return build_tool_error("get_case_doc_category_status", exc)


@tool
def validate_doc_category(case_id: int, doc_category: str, file_names: list[str], text_preview: str = "") -> str:
    """Run a lightweight validation before uploading one category batch."""
    try:
        request = ValidateDocCategoryRequestModel(
            case_id=case_id,
            doc_category=doc_category,
            file_names=file_names,
            text_preview=text_preview,
        )
        if _use_mock():
            payload = get_mock_doc_category_service().validate_doc_category(request).model_dump()
        else:
            payload = get_doc_category_api_client().validate_doc_category_sync(request.model_dump())
        return build_tool_result(
            "validate_doc_category",
            payload,
            next_hint="若类别疑似不匹配，请调整 doc_category 后再上传。",
        )
    except Exception as exc:
        return build_tool_error("validate_doc_category", exc)

