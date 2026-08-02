"""LangChain tools backed by the FastAPI audit service."""

from langchain_core.tools import tool

from ..services.audit_api import get_audit_api_client
from ..services.case_api import get_case_api_client
from ..services.enterprise_api import get_enterprise_api_client
from .summary_utils import build_tool_error, build_tool_result


@tool
def get_case_profile(case_id: int) -> str:
    """Fetch the case profile for a given case ID."""
    try:
        return build_tool_result(
            "get_case_profile",
            get_case_api_client().get_case_profile_sync(case_id),
            next_hint="如需继续下钻，可指定资产、保证人或裁判文书方向。",
        )
    except Exception as exc:
        return build_tool_error("get_case_profile", exc)


@tool
def get_whiteglove_analysis(case_id: int) -> str:
    """Fetch whiteglove relationship analysis for a given case ID."""
    try:
        return build_tool_result(
            "get_whiteglove_analysis",
            get_enterprise_api_client().get_whiteglove_sync(case_id),
            next_hint="如需继续追查，请指定关注主体或关联路径。",
        )
    except Exception as exc:
        return build_tool_error("get_whiteglove_analysis", exc)


@tool
def get_fund_flow(case_id: int) -> str:
    """Fetch the fund-flow topology for a given case ID."""
    try:
        return build_tool_result(
            "get_fund_flow",
            get_enterprise_api_client().get_fund_flow_sync(case_id),
            next_hint="如需继续分析资金路径，请指定账户、主体或时间范围。",
        )
    except Exception as exc:
        return build_tool_error("get_fund_flow", exc)


@tool
def audit_delta_check(case_id: int) -> str:
    """Run the delta-check audit engine for a given case ID."""
    try:
        return build_tool_result(
            "audit_delta_check",
            get_audit_api_client().audit_delta_check_sync(case_id),
            next_hint="如需继续核查，请指定差额来源或目标资产。",
        )
    except Exception as exc:
        return build_tool_error("audit_delta_check", exc)


@tool
def audit_valuation_squeeze(case_id: int) -> str:
    """Run the valuation-squeeze audit engine for a given case ID."""
    try:
        return build_tool_result(
            "audit_valuation_squeeze",
            get_audit_api_client().audit_valuation_squeeze_sync(case_id),
            next_hint="如需继续压估，请指定资产类型或估值对象。",
        )
    except Exception as exc:
        return build_tool_error("audit_valuation_squeeze", exc)


@tool
def audit_deadline_scan(case_id: int) -> str:
    """Run the deadline-scan audit engine for a given case ID."""
    try:
        return build_tool_result(
            "audit_deadline_scan",
            get_audit_api_client().audit_deadline_scan_sync(case_id),
            next_hint="如需继续查看期限风险，请指定节点、法院或程序阶段。",
        )
    except Exception as exc:
        return build_tool_error("audit_deadline_scan", exc)


@tool
def audit_behavioral_scan(case_id: int) -> str:
    """Run the behavioral-scan audit engine for a given case ID."""
    try:
        return build_tool_result(
            "audit_behavioral_scan",
            get_audit_api_client().audit_behavioral_scan_sync(case_id),
            next_hint="如需继续下钻，请指定异常行为对象或时间段。",
        )
    except Exception as exc:
        return build_tool_error("audit_behavioral_scan", exc)
