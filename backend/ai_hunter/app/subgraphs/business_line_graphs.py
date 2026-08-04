"""Registry-driven annual-audit business-line graphs."""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from ..graph.capabilities import (
    BUSINESS_LINE_IDS,
    BusinessLine,
    capability_node_name,
    capabilities_for_business_line,
    get_capability_spec,
)
from ..graph.nodes.create_tasks import should_create_tasks
from ..graph.nodes.read_only_capabilities import READ_ONLY_EXECUTOR_NODES, READ_ONLY_EXECUTOR_TOOL_NAMES
from ..graph.nodes.write_capabilities import WRITE_EXECUTOR_NODES, WRITE_EXECUTOR_TOOL_NAMES
from ..graph.state import AuditGraphState
from .business_line_executors import (
    SPECIALIZED_EXECUTOR_TOOL_NAMES,
    build_specialized_executor_node,
)


INVALID_ROUTE = "__invalid__"
EXECUTION_VERSION = "annual-audit-v1"


def _read_route_decision(state: AuditGraphState) -> dict:
    decision = state.get("route_decision") or {}
    if hasattr(decision, "model_dump"):
        return decision.model_dump()
    return decision if isinstance(decision, dict) else {}


def _entry_node(_state: AuditGraphState) -> dict:
    return {"business_line_plan": {}, "business_line_result": {}}


def _capability_edge(business_line: BusinessLine) -> Callable[[AuditGraphState], str]:
    valid_capabilities = set(capabilities_for_business_line(business_line))

    def route(state: AuditGraphState) -> str:
        decision = _read_route_decision(state)
        capability = str(decision.get("capability") or "")
        if decision.get("business_line") != business_line or capability not in valid_capabilities:
            return INVALID_ROUTE
        return capability

    return route


def _plan_node(business_line: BusinessLine, capability: str) -> Callable[[AuditGraphState], dict]:
    spec = get_capability_spec(capability)
    if spec is None:
        raise ValueError(f"unknown capability in business-line graph: {capability}")

    def plan(_state: AuditGraphState) -> dict:
        return {
            "business_line_plan": {
                "execution_version": EXECUTION_VERSION,
                "business_line": business_line,
                "capability": capability,
                "capability_node": capability_node_name(capability),
                "planned_executor": spec.business_line_executor or "clarify_route",
                "access_mode": spec.access_mode,
                "business_logic_executed": False,
            }
        }

    return plan


def _invalid_route_node(state: AuditGraphState) -> dict:
    decision = _read_route_decision(state)
    return {
        "business_line_plan": {
            "execution_version": EXECUTION_VERSION,
            "business_line": str(decision.get("business_line") or ""),
            "capability": str(decision.get("capability") or ""),
            "business_logic_executed": False,
            "error": "capability does not belong to this business line",
        }
    }


_CONTEXT_FIELD_BY_LINE = {
    "operator": "operator_context",
    "audit_analysis": "audit_context",
    "supervision": "supervision_context",
    "common": "common_context",
}


def _record_execution_node(business_line: BusinessLine, capability: str) -> Callable[[AuditGraphState], dict]:
    spec = get_capability_spec(capability)
    if spec is None or not spec.business_line_executor:
        raise ValueError(f"capability is not executable in business-line mode: {capability}")

    def record(state: AuditGraphState) -> dict:
        existing = state.get("business_line_result") or {}
        result = dict(existing) if isinstance(existing, dict) else {}
        if "ok" not in result:
            if capability in {"audit.full", "audit.reaudit"}:
                result["ok"] = bool(
                    state.get("final_report_ref")
                    or state.get("final_report_summary")
                    or state.get("final_report")
                )
            else:
                result["ok"] = bool(state.get("agent_output"))
        result = {
            **result,
            "execution_version": EXECUTION_VERSION,
            "business_line": business_line,
            "capability": capability,
            "executor": spec.business_line_executor,
            "access_mode": spec.access_mode,
            "read_only": spec.access_mode == "read",
        }
        status = "completed" if result.get("ok") else "degraded" if result.get("degraded") else "failed"
        summary = str(
            result.get("summary")
            or state.get("final_report_summary")
            or state.get("agent_output")
            or ""
        )[:600]
        context = {
            "execution_version": EXECUTION_VERSION,
            "business_line": business_line,
            "capability": capability,
            "executor": spec.business_line_executor,
            "access_mode": spec.access_mode,
            "status": status,
            "output_ref": str(state.get("final_report_ref") or ""),
            "summary": summary,
            "task_count": len(state.get("extracted_tasks") or []),
            "correction_count": len(state.get("correction_records") or []),
        }
        return {
            "business_line_result": result,
            _CONTEXT_FIELD_BY_LINE[business_line]: context,
        }

    return record


def audit_analysis_completion_edge(state: AuditGraphState) -> str:
    """Preserve post-audit task creation after the audit subgraph takes control."""
    decision = _read_route_decision(state)
    capability = str(decision.get("capability") or "")
    if capability in {"audit.full", "audit.reaudit"}:
        return "create" if should_create_tasks(state) == "create" else "finalize"
    return "finalize"


def build_business_line_graph(business_line: BusinessLine):
    if business_line not in BUSINESS_LINE_IDS:
        raise ValueError(f"unknown business line: {business_line}")

    graph = StateGraph(AuditGraphState)
    graph.add_node("resolve_capability", _entry_node)
    graph.add_node("invalid_route", _invalid_route_node)

    capability_nodes: dict[str, str] = {}
    for capability in capabilities_for_business_line(business_line):
        spec = get_capability_spec(capability)
        if spec is None:
            raise ValueError(f"unknown capability in business-line graph: {capability}")
        executor_name = spec.business_line_executor or ""
        actual_tool_names = READ_ONLY_EXECUTOR_TOOL_NAMES.get(
            executor_name,
            WRITE_EXECUTOR_TOOL_NAMES.get(
                executor_name,
                SPECIALIZED_EXECUTOR_TOOL_NAMES.get(executor_name, ()),
            ),
        )
        if not set(actual_tool_names).issubset(spec.tool_names):
            raise ValueError(f"business-line executor for {capability} uses unregistered tools")
        node_name = capability_node_name(capability)
        capability_nodes[capability] = node_name
        executor_node = READ_ONLY_EXECUTOR_NODES.get(executor_name)
        if executor_node is None:
            executor_node = WRITE_EXECUTOR_NODES.get(executor_name)
        if executor_node is None and executor_name:
            executor_node = build_specialized_executor_node(executor_name)
        graph.add_node(node_name, executor_node or _plan_node(business_line, capability))
        if executor_node is None:
            graph.add_edge(node_name, END)
        else:
            record_name = f"record_{capability.replace('.', '_')}"
            graph.add_node(record_name, _record_execution_node(business_line, capability))
            graph.add_edge(node_name, record_name)
            graph.add_edge(record_name, END)

    graph.add_edge(START, "resolve_capability")
    graph.add_conditional_edges(
        "resolve_capability",
        _capability_edge(business_line),
        {**capability_nodes, INVALID_ROUTE: "invalid_route"},
    )
    graph.add_edge("invalid_route", END)
    return graph.compile()


def build_operator_subgraph():
    return build_business_line_graph("operator")


def build_audit_analysis_subgraph():
    return build_business_line_graph("audit_analysis")


def build_supervision_subgraph():
    return build_business_line_graph("supervision")


def build_common_subgraph():
    return build_business_line_graph("common")


def build_business_line_subgraphs() -> dict[str, object]:
    return {
        "operator": build_operator_subgraph(),
        "audit_analysis": build_audit_analysis_subgraph(),
        "supervision": build_supervision_subgraph(),
        "common": build_common_subgraph(),
    }
