"""Factories for annual-audit specialized business-line executors."""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from ..graph.nodes.corrections import extract_correction
from ..graph.nodes.run_drilldown_agent import build_capability_agent_node
from ..graph.state import AuditGraphState
from ...annual_audit.report_graph import build_annual_report_graph


SPECIALIZED_EXECUTOR_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "full_audit_graph": (),
    "reaudit_graph": (),
    "attachment_delivery_graph": (),
    "annual_audit_drilldown_agent": (
        "get_annual_engagement",
        "get_annual_audit_context",
        "analyze_annual_data_readiness",
        "analyze_sales_receivables",
        "analyze_cash_and_bank",
    ),
    "graph_query_agent": (
        "get_annual_engagement",
        "get_annual_audit_context",
        "search_annual_evidence",
    ),
}


def build_domain_full_audit_graph():
    """Build the annual workpaper and report implementation."""

    return build_annual_report_graph()


def build_reaudit_graph():
    """Persist the correction overlay, then regenerate the full report."""
    graph = StateGraph(AuditGraphState)
    graph.add_node("extract_correction", extract_correction)
    graph.add_node("full_audit_graph", build_domain_full_audit_graph())
    graph.add_edge(START, "extract_correction")
    graph.add_edge("extract_correction", "full_audit_graph")
    graph.add_edge("full_audit_graph", END)
    return graph.compile()


def build_attachment_delivery_graph():
    from ...annual_audit.attachments.delivery_graph import build_attachment_delivery_graph as build

    return build()


SPECIALIZED_EXECUTOR_FACTORIES: dict[str, Callable[[], object]] = {
    "full_audit_graph": build_domain_full_audit_graph,
    "reaudit_graph": build_reaudit_graph,
    "attachment_delivery_graph": build_attachment_delivery_graph,
    "annual_audit_drilldown_agent": lambda: build_capability_agent_node("audit.drilldown"),
    "graph_query_agent": lambda: build_capability_agent_node("graph.query"),
}


def build_specialized_executor_node(executor_name: str):
    factory = SPECIALIZED_EXECUTOR_FACTORIES.get(str(executor_name or ""))
    if factory is None:
        raise ValueError(f"unknown specialized business-line executor: {executor_name}")
    return factory()
