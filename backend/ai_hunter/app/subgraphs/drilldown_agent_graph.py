from langgraph.graph import END, START, StateGraph

from ..graph.nodes.run_drilldown_agent import run_drilldown_agent
from ..graph.state import AuditGraphState


def build_drilldown_agent_graph():
    graph = StateGraph(AuditGraphState)
    graph.add_node("run_drilldown_agent", run_drilldown_agent)
    graph.add_edge(START, "run_drilldown_agent")
    graph.add_edge("run_drilldown_agent", END)
    return graph.compile()
