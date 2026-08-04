"""Annual-audit tool registry exposed to the chat agent."""

from ...annual_audit.tools import ALL_ANNUAL_TOOLS, ANNUAL_CAPABILITY_TOOLSETS
from ..graph.capabilities import CAPABILITY_SPECS


ALL_DRILLDOWN_TOOLS = ALL_ANNUAL_TOOLS

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
    """Return the smallest annual-audit toolset for one routed capability."""
    return list(ANNUAL_CAPABILITY_TOOLSETS.get(str(capability or ""), []))
