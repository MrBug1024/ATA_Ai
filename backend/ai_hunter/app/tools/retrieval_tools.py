"""LangChain retrieval and knowledge tools backed by FastAPI or direct PostgreSQL."""

from langchain_core.tools import tool

from ..services.knowledge_api import get_knowledge_api_client
from ..services.retrieval_api import get_retrieval_api_client
from .summary_utils import build_tool_error, build_tool_result


@tool
def get_legal_writ(
    case_id: int,
    q: str | None = None,
    doc_type: str | None = None,
    date_from: str | None = None,
    limit: int = 20,
) -> str:
    """Retrieve legal writs for a case using filter or semantic search."""
    try:
        payload = {
            "case_id": case_id,
            "q": q,
            "doc_type": doc_type,
            "date_from": date_from,
            "limit": limit,
        }
        return build_tool_result(
            "get_legal_writ",
            get_retrieval_api_client().get_legal_writ_sync(payload),
            next_hint="如需更精准检索，请指定文书类型、时间或关键词。",
        )
    except Exception as exc:
        return build_tool_error("get_legal_writ", exc)


@tool
def query_wenshu_knowledge(question: str, limit: int = 5) -> str:
    """Query the Wenshu corpus directly from cpwsdata."""
    try:
        return build_tool_result(
            "query_wenshu_knowledge",
            get_knowledge_api_client().query_wenshu_sync(question, limit=limit),
            next_hint="如需继续扩检，请补充案由、关键词或裁判年份。",
        )
    except Exception as exc:
        return build_tool_error("query_wenshu_knowledge", exc)
