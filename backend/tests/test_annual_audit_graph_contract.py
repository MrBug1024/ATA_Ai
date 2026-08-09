import json

from langgraph.checkpoint.memory import MemorySaver

from ai_hunter.app.graph.capabilities import CAPABILITY_IDS, CAPABILITY_SPECS
from ai_hunter.app.graph.main import build_audit_orchestrator_graph
from ai_hunter.app.graph.nodes import read_only_capabilities as read_nodes


EXPECTED_CAPABILITIES = {
    "case.create",
    "case.profile",
    "material.upload",
    "material.status",
    "material.validate",
    "audit.full",
    "audit.reaudit",
    "audit.drilldown",
    "audit.workflow",
    "evidence.resolve",
    "graph.query",
    "task.query",
    "task.write",
    "common.general",
    "clarify",
}


def test_capability_registry_contains_only_annual_audit_capabilities():
    assert set(CAPABILITY_IDS) == EXPECTED_CAPABILITIES
    assert all(spec.business_line in {"operator", "audit_analysis", "supervision", "common"}
               for spec in CAPABILITY_SPECS.values())


def test_main_graph_compiles_with_annual_report_and_chat_nodes():
    compiled = build_audit_orchestrator_graph(checkpointer=MemorySaver())
    node_names = set(compiled.get_graph().nodes)
    assert "ingest_graph" in node_names
    assert {"operator_subgraph", "audit_analysis_subgraph", "supervision_subgraph"} <= node_names


class _Tool:
    def __init__(self):
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return json.dumps({"summary": "年度审计项目已加载", "key_facts": {"case_id": 7}})


def test_project_profile_read_uses_annual_engagement_tool(monkeypatch):
    tool = _Tool()
    monkeypatch.setattr(read_nodes, "get_annual_engagement", tool)
    result = read_nodes.query_case_profile({"current_case_id": 7})
    assert tool.calls == [{"case_id": 7}]
    assert result["business_line_result"]["capability"] == "case.profile"
    assert result["business_line_result"]["ok"] is True


def test_material_validation_uses_annual_requirements_status_and_readiness(monkeypatch):
    requirements = _Tool()
    status = _Tool()
    readiness = _Tool()
    monkeypatch.setattr(read_nodes, "list_annual_material_requirements", requirements)
    monkeypatch.setattr(read_nodes, "get_annual_material_status", status)
    monkeypatch.setattr(read_nodes, "analyze_annual_data_readiness", readiness)
    result = read_nodes.query_material_validation({"current_case_id": 7})
    assert requirements.calls == [{}]
    assert status.calls == [{"case_id": 7}]
    assert readiness.calls == [{"case_id": 7}]
    assert result["business_line_result"]["ok"] is True
