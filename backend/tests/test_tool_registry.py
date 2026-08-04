from ai_hunter.app.graph.capabilities import CAPABILITY_IDS
from ai_hunter.app.tools.registry import ALL_DRILLDOWN_TOOLS, CAPABILITY_TOOLSETS, tools_for_capability


def test_tool_registry_contains_only_annual_audit_tools():
    assert {tool.name for tool in ALL_DRILLDOWN_TOOLS} == {
        "get_annual_engagement",
        "get_annual_audit_context",
        "list_annual_material_requirements",
        "get_annual_material_status",
        "analyze_annual_data_readiness",
        "analyze_sales_receivables",
        "analyze_cash_and_bank",
        "search_annual_evidence",
        "list_annual_tasks",
    }


def test_capability_toolsets_are_scoped_and_unknown_is_safe():
    assert tuple(CAPABILITY_TOOLSETS) == CAPABILITY_IDS
    assert [tool.name for tool in tools_for_capability("case.profile")] == ["get_annual_engagement"]
    assert [tool.name for tool in tools_for_capability("task.query")] == ["list_annual_tasks"]
    assert {tool.name for tool in tools_for_capability("graph.query")} == {
        "get_annual_engagement",
        "get_annual_audit_context",
        "search_annual_evidence",
    }
    assert tools_for_capability("common.general") == []
    assert tools_for_capability("unknown") == []
