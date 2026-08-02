"""Central registry of the drilldown tools exposed to the agent."""

from ..graph.capabilities import CAPABILITY_SPECS
from .audit_tools import (
    audit_behavioral_scan,
    audit_deadline_scan,
    audit_delta_check,
    audit_valuation_squeeze,
    get_case_profile,
    get_fund_flow,
    get_whiteglove_analysis,
)
from .case_tools import create_case, fetch_enterprise, ingest_structured_fields, parse_document
from .doc_category_tools import get_case_doc_category_status, get_doc_categories, validate_doc_category
from .evidence_tools import resolve_case_evidence
from .retrieval_tools import query_wenshu_knowledge
from .task_tools import create_task_batch, manage_tasks


ALL_DRILLDOWN_TOOLS = [
    get_doc_categories,
    get_case_doc_category_status,
    validate_doc_category,
    get_case_profile,
    resolve_case_evidence,
    get_whiteglove_analysis,
    create_case,
    ingest_structured_fields,
    create_task_batch,
    fetch_enterprise,
    manage_tasks,
    parse_document,
    audit_behavioral_scan,
    audit_valuation_squeeze,
    audit_delta_check,
    audit_deadline_scan,
    get_fund_flow,
    query_wenshu_knowledge,
]

_TOOL_BY_NAME = {tool.name: tool for tool in ALL_DRILLDOWN_TOOLS}
_UNKNOWN_REGISTERED_TOOLS = {
    name for spec in CAPABILITY_SPECS.values() for name in spec.tool_names if name not in _TOOL_BY_NAME
}
if _UNKNOWN_REGISTERED_TOOLS:
    raise ValueError(f"capability registry references unknown tools: {sorted(_UNKNOWN_REGISTERED_TOOLS)}")

CAPABILITY_TOOLSETS = {
    code: [_TOOL_BY_NAME[name] for name in spec.tool_names]
    for code, spec in CAPABILITY_SPECS.items()
}


def tools_for_capability(capability: str) -> list:
    """Return the smallest registered toolset suitable for one routed capability."""
    return list(CAPABILITY_TOOLSETS.get(str(capability or ""), []))
