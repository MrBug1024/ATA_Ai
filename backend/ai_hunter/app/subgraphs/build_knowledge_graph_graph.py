"""Knowledge graph construction subgraph for traceable case evidence."""

from langgraph.graph import END, START, StateGraph

from ..graph.nodes.build_graph_summary import build_graph_summary
from ..graph.nodes.deduplicate_graph_items import deduplicate_graph_items
from ..graph.nodes.extract_entities_relations import extract_entities_relations
from ..graph.nodes.load_chunks import bind_annual_evidence_anchors, load_chunks
from ..graph.nodes.normalize_entities import normalize_entities
from ..graph.nodes.persist_graph import persist_graph
from ..graph.nodes.reconcile_graph_delta import reconcile_graph_delta
from ..graph.state import AuditGraphState


def build_knowledge_graph_graph():
    graph = StateGraph(AuditGraphState)
    graph.add_node("load_chunks", load_chunks)
    graph.add_node("bind_annual_evidence_anchors", bind_annual_evidence_anchors)
    graph.add_node("extract_entities_relations", extract_entities_relations)
    graph.add_node("normalize_entities", normalize_entities)
    graph.add_node("deduplicate_graph_items", deduplicate_graph_items)
    graph.add_node("persist_graph", persist_graph)
    graph.add_node("reconcile_graph_delta", reconcile_graph_delta)
    graph.add_node("build_graph_summary", build_graph_summary)

    graph.add_edge(START, "load_chunks")
    graph.add_edge("load_chunks", "bind_annual_evidence_anchors")
    graph.add_edge("bind_annual_evidence_anchors", "extract_entities_relations")
    graph.add_edge("extract_entities_relations", "normalize_entities")
    graph.add_edge("normalize_entities", "deduplicate_graph_items")
    graph.add_edge("deduplicate_graph_items", "persist_graph")
    graph.add_edge("persist_graph", "reconcile_graph_delta")
    graph.add_edge("reconcile_graph_delta", "build_graph_summary")
    graph.add_edge("build_graph_summary", END)
    return graph.compile()
