"""Factories for Phase 2.5.3 specialized business-line executors."""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from ..graph.nodes.corrections import extract_correction
from ..graph.nodes.run_drilldown_agent import build_capability_agent_node
from ..graph.state import AuditGraphState
from .full_audit_graph import build_full_audit_graph
from .review_graph import build_review_graph


SPECIALIZED_EXECUTOR_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "full_audit_graph": (),
    "reaudit_graph": (),
    "review_graph": (),
    "audit_drilldown_agent": (
        "get_case_profile",
        "audit_behavioral_scan",
        "audit_valuation_squeeze",
        "audit_delta_check",
        "audit_deadline_scan",
    ),
    "graph_query_agent": (
        "fetch_enterprise",
        "get_fund_flow",
        "get_whiteglove_analysis",
        "query_wenshu_knowledge",
    ),
}


def build_reaudit_graph():
    """Persist the correction overlay, then regenerate the full report."""
    graph = StateGraph(AuditGraphState)
    graph.add_node("extract_correction", extract_correction)
    graph.add_node("full_audit_graph", build_full_audit_graph())
    graph.add_edge(START, "extract_correction")
    graph.add_edge("extract_correction", "full_audit_graph")
    graph.add_edge("full_audit_graph", END)
    return graph.compile()


SPECIALIZED_EXECUTOR_FACTORIES: dict[str, Callable[[], object]] = {
    "full_audit_graph": build_full_audit_graph,
    "reaudit_graph": build_reaudit_graph,
    "review_graph": build_review_graph,
    "audit_drilldown_agent": lambda: build_capability_agent_node("audit.drilldown"),
    "graph_query_agent": lambda: build_capability_agent_node("graph.query"),
}


def build_specialized_executor_node(executor_name: str):
    factory = SPECIALIZED_EXECUTOR_FACTORIES.get(str(executor_name or ""))
    if factory is None:
        raise ValueError(f"unknown specialized business-line executor: {executor_name}")
    return factory()
