"""Main LangGraph orchestration entrypoint."""

from langgraph.graph import END, START, StateGraph

from .checkpointer import get_checkpointer
from .nodes.corrections import extract_correction
from .nodes.clarify_route import clarify_route
from .nodes.create_tasks import create_tasks, should_create_tasks
from .nodes.finalize_answer import finalize_answer
from .nodes.hydrate_case_graph import hydrate_case_graph_context
from .nodes.ingest_files import should_ingest_files, summarize_ingest_result
from .nodes.memory import hydrate_memory_context, persist_conversation_memory
from .nodes.normalize_input import normalize_input
from .nodes.resolve_case import resolve_case_context
from .nodes.route_intent import classify_intent, execution_route_edge
from .nodes.run_drilldown_agent import build_drilldown_agent_node
from .state import AuditGraphState
from ..subgraphs.full_audit_graph import build_full_audit_graph
from ..subgraphs.ingest_graph import build_ingest_graph
from ..subgraphs.review_graph import build_review_graph
from ..subgraphs.business_line_graphs import audit_analysis_completion_edge, build_business_line_subgraphs


def build_audit_orchestrator_graph(checkpointer=None):
    """Compose the top-level graph with ingestion, drilldown, and re-audit branches."""
    graph = StateGraph(AuditGraphState)
    graph.add_node("normalize_input", normalize_input)
    graph.add_node("hydrate_memory_context", hydrate_memory_context)
    graph.add_node("resolve_case_context", resolve_case_context)
    graph.add_node("hydrate_case_graph_context", hydrate_case_graph_context)
    graph.add_node("ingest_graph", build_ingest_graph())
    graph.add_node("summarize_ingest_result", summarize_ingest_result)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("clarify_route", clarify_route)
    graph.add_node("extract_correction", extract_correction)
    graph.add_node("full_audit_graph", build_full_audit_graph())
    graph.add_node("review_graph", build_review_graph())
    graph.add_node("create_tasks", create_tasks)
    graph.add_node("drilldown_agent_graph", build_drilldown_agent_node())
    business_line_subgraphs = build_business_line_subgraphs()
    graph.add_node("operator_subgraph", business_line_subgraphs["operator"])
    graph.add_node("audit_analysis_subgraph", business_line_subgraphs["audit_analysis"])
    graph.add_node("supervision_subgraph", business_line_subgraphs["supervision"])
    graph.add_node("common_subgraph", business_line_subgraphs["common"])
    graph.add_node("finalize_answer", finalize_answer)
    graph.add_node("persist_conversation_memory", persist_conversation_memory)

    graph.add_edge(START, "normalize_input")
    graph.add_edge("normalize_input", "hydrate_memory_context")
    graph.add_edge("hydrate_memory_context", "resolve_case_context")
    graph.add_edge("resolve_case_context", "hydrate_case_graph_context")
    graph.add_conditional_edges(
        "hydrate_case_graph_context",
        should_ingest_files,
        {
            "ingest": "ingest_graph",
            "skip": "classify_intent",
        },
    )
    graph.add_edge("ingest_graph", "summarize_ingest_result")
    graph.add_edge("summarize_ingest_result", "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        execution_route_edge,
        {
            "full_audit": "full_audit_graph",
            "drilldown": "drilldown_agent_graph",
            "re_audit": "extract_correction",
            "review": "review_graph",
            "clarify": "clarify_route",
            "finalize": "finalize_answer",
            "operator_subgraph": "operator_subgraph",
            "audit_analysis_subgraph": "audit_analysis_subgraph",
            "supervision_subgraph": "supervision_subgraph",
            "common_subgraph": "common_subgraph",
        },
    )
    graph.add_edge("extract_correction", "full_audit_graph")
    graph.add_edge("review_graph", "finalize_answer")
    graph.add_conditional_edges(
        "full_audit_graph",
        should_create_tasks,
        {
            "create": "create_tasks",
            "skip": "finalize_answer",
        },
    )
    graph.add_edge("create_tasks", "finalize_answer")
    graph.add_edge("drilldown_agent_graph", "finalize_answer")
    graph.add_edge("operator_subgraph", "finalize_answer")
    graph.add_conditional_edges(
        "audit_analysis_subgraph",
        audit_analysis_completion_edge,
        {
            "create": "create_tasks",
            "finalize": "finalize_answer",
        },
    )
    graph.add_edge("supervision_subgraph", "finalize_answer")
    graph.add_edge("common_subgraph", "finalize_answer")
    graph.add_edge("clarify_route", "finalize_answer")
    graph.add_edge("finalize_answer", "persist_conversation_memory")
    graph.add_edge("persist_conversation_memory", END)

    if checkpointer is None:
        checkpointer = get_checkpointer()
    return graph.compile(checkpointer=checkpointer)
