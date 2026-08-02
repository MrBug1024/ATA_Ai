from langgraph.graph import END, START, StateGraph

from ..graph.nodes.fetch_review_context import fetch_review_context
from ..graph.nodes.generate_review_sections import build_all_review_section_nodes
from ..graph.nodes.reconcile_review import reconcile_review
from ..graph.review_sections import REVIEW_SECTIONS, review_section_node_name
from ..graph.state import AuditGraphState


def build_review_graph():
    """AI 复盘：fetch_review_context(拉数据+确定性对账) → [3 段复盘专家并行] → reconcile_review。"""
    graph = StateGraph(AuditGraphState)
    graph.add_node("fetch_review_context", fetch_review_context)
    for name, node in build_all_review_section_nodes().items():
        graph.add_node(name, node)
    graph.add_node("reconcile_review", reconcile_review)

    graph.add_edge(START, "fetch_review_context")
    # 并行扇出：fetch → 3 段；扇入：3 段 → reconcile（等全部完成）
    for section in REVIEW_SECTIONS:
        node_name = review_section_node_name(section["id"])
        graph.add_edge("fetch_review_context", node_name)
        graph.add_edge(node_name, "reconcile_review")
    graph.add_edge("reconcile_review", END)
    return graph.compile()
