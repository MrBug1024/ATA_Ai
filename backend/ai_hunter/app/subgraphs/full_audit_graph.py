from langgraph.graph import END, START, StateGraph

from ..graph.nodes.fetch_full_context import fetch_full_context
from ..graph.nodes.compute_metrics import compute_metrics_node
from ..graph.nodes.generate_sections import build_all_section_nodes
from ..graph.nodes.reconcile_report import reconcile_report_and_extract_tasks
from ..graph.report_sections import SECTIONS, section_node_name
from ..graph.state import AuditGraphState


def build_full_audit_graph():
    """八段式：fetch_full_context → compute_metrics → [8 段专家子 agent 并行] → reconcile。"""
    graph = StateGraph(AuditGraphState)
    graph.add_node("fetch_full_context", fetch_full_context)
    graph.add_node("compute_metrics", compute_metrics_node)
    for name, node in build_all_section_nodes().items():
        graph.add_node(name, node)
    graph.add_node("reconcile_report_and_extract_tasks", reconcile_report_and_extract_tasks)

    graph.add_edge(START, "fetch_full_context")
    graph.add_edge("fetch_full_context", "compute_metrics")
    # 并行扇出：compute_metrics → 8 段；扇入：8 段 → reconcile（等全部完成）
    for section in SECTIONS:
        node_name = section_node_name(section["id"])
        graph.add_edge("compute_metrics", node_name)
        graph.add_edge(node_name, "reconcile_report_and_extract_tasks")
    graph.add_edge("reconcile_report_and_extract_tasks", END)
    return graph.compile()
