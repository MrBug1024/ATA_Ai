"""Tools that resolve evidence exclusively from the current case materials."""

from langchain_core.tools import tool

from ..services.case_evidence import rank_case_evidence
from ..services.kg_service import get_kg_service
from .summary_utils import build_tool_error, build_tool_result


@tool
def resolve_case_evidence(case_id: int, query: str = "", limit: int = 5) -> str:
    """Find original evidence anchors in one case's uploaded materials only."""
    try:
        traces = get_kg_service().fetch_case_evidence_traces(case_id, query_text=query, limit=limit)
        items = rank_case_evidence(traces, query, limit=limit)
        return build_tool_result(
            "resolve_case_evidence",
            {
                "source_scope": "case_material",
                "case_binding": True,
                "reference_only": False,
                "case_id": case_id,
                "match_count": len(items),
                "results": items,
            },
            next_hint="可按角标、断言或关键词继续缩小范围。",
        )
    except Exception as exc:
        return build_tool_error("resolve_case_evidence", exc)
