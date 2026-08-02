from ai_hunter.app.graph.capabilities import CAPABILITY_IDS
from ai_hunter.app.tools.registry import ALL_DRILLDOWN_TOOLS, CAPABILITY_TOOLSETS, tools_for_capability


def test_drilldown_tool_registry_has_18_tools():
    assert len(ALL_DRILLDOWN_TOOLS) == 18


def test_capability_toolsets_are_scoped_and_unknown_is_safe():
    assert tuple(CAPABILITY_TOOLSETS) == CAPABILITY_IDS
    assert [tool.name for tool in tools_for_capability("case.profile")] == ["get_case_profile"]
    assert [tool.name for tool in tools_for_capability("task.query")] == ["manage_tasks"]
    assert {tool.name for tool in tools_for_capability("graph.query")} == {
        "fetch_enterprise",
        "get_fund_flow",
        "get_whiteglove_analysis",
        "query_wenshu_knowledge",
    }
    assert tools_for_capability("common.general") == []
    assert tools_for_capability("unknown") == []
