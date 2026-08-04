"""Annual-audit tools exposed to the shared chat orchestrator."""

from langchain_core.tools import tool

from ai_hunter.app.tools.summary_utils import build_tool_error, build_tool_result

from .analysis_service import data_readiness, run_cash_and_bank, run_sales_receivables
from .document_repository import get_case_doc_categories, list_doc_categories
from .engagement_repository import get_engagement_profile
from .task_repository import manage_tasks


@tool
def get_annual_engagement(case_id: int) -> str:
    """Fetch one annual-audit engagement profile from isolated storage."""

    try:
        return build_tool_result(
            "get_annual_engagement",
            get_engagement_profile(case_id),
            next_hint="可继续核查资料完整性、审计循环、证据图谱或生成底稿与报告。",
        )
    except Exception as exc:
        return build_tool_error("get_annual_engagement", exc)


@tool
def list_annual_material_requirements() -> str:
    """List annual-audit material categories and required items."""

    try:
        return build_tool_result(
            "list_annual_material_requirements",
            list_doc_categories(),
        )
    except Exception as exc:
        return build_tool_error("list_annual_material_requirements", exc)


@tool
def get_annual_material_status(case_id: int) -> str:
    """Return uploaded and missing material categories for an engagement."""

    try:
        return build_tool_result(
            "get_annual_material_status",
            get_case_doc_categories(case_id),
        )
    except Exception as exc:
        return build_tool_error("get_annual_material_status", exc)


@tool
def list_annual_tasks(case_id: int) -> str:
    """List audit procedures and follow-up tasks for an engagement."""

    try:
        return build_tool_result(
            "list_annual_tasks",
            manage_tasks({"case_id": case_id, "action": "list"}),
        )
    except Exception as exc:
        return build_tool_error("list_annual_tasks", exc)


@tool
def get_annual_audit_context(case_id: int) -> str:
    """Fetch the annual engagement, audit period and current data readiness."""

    try:
        return build_tool_result(
            "get_annual_audit_context",
            get_engagement_profile(case_id),
            next_hint=(
                "根据资料完整性继续分析；缺少报表、科目余额表、序时账、"
                "应收明细或银行流水时，应明确向用户索取。"
            ),
        )
    except Exception as exc:
        return build_tool_error("get_annual_audit_context", exc)


@tool
def analyze_annual_data_readiness(case_id: int) -> str:
    """Check which structured annual-audit data sets are ready or missing."""

    try:
        return build_tool_result(
            "analyze_annual_data_readiness",
            data_readiness(case_id),
        )
    except Exception as exc:
        return build_tool_error("analyze_annual_data_readiness", exc)


@tool
def analyze_sales_receivables(case_id: int) -> str:
    """Analyze revenue trend/cutoff plus receivable aging and concentration."""

    try:
        return build_tool_result(
            "analyze_sales_receivables",
            run_sales_receivables(case_id),
        )
    except Exception as exc:
        return build_tool_error("analyze_sales_receivables", exc)


@tool
def analyze_cash_and_bank(case_id: int) -> str:
    """Run deterministic large, period-end, duplicate and unusual bank-flow rules."""

    try:
        return build_tool_result(
            "analyze_cash_and_bank",
            run_cash_and_bank(case_id),
        )
    except Exception as exc:
        return build_tool_error("analyze_cash_and_bank", exc)


ANNUAL_CAPABILITY_TOOLSETS = {
    "case.profile": [get_annual_engagement],
    "material.status": [get_annual_material_status],
    "material.validate": [
        get_annual_engagement,
        list_annual_material_requirements,
        get_annual_material_status,
        analyze_annual_data_readiness,
    ],
    "audit.drilldown": [
        get_annual_engagement,
        get_annual_audit_context,
        analyze_annual_data_readiness,
        analyze_sales_receivables,
        analyze_cash_and_bank,
    ],
    "graph.query": [get_annual_engagement, get_annual_audit_context],
    "task.query": [list_annual_tasks],
}


ALL_ANNUAL_TOOLS = []
_registered_tool_names: set[str] = set()
for _toolset in ANNUAL_CAPABILITY_TOOLSETS.values():
    for _tool in _toolset:
        if _tool.name not in _registered_tool_names:
            ALL_ANNUAL_TOOLS.append(_tool)
            _registered_tool_names.add(_tool.name)
