import pytest

from ai_hunter.app.graph.capabilities import CAPABILITY_SPECS, capability_node_name
from ai_hunter.app.subgraphs.business_line_graphs import (
    build_business_line_graph,
    build_business_line_subgraphs,
)


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return '{"summary":"ok","key_facts":{"source":"fake"},"truncated":false,"next_hint":""}'


def _replace_read_tools(monkeypatch):
    import ai_hunter.app.graph.nodes.read_only_capabilities as read_nodes

    for name in (
        "get_case_profile",
        "get_case_doc_category_status",
        "get_doc_categories",
        "query_wenshu_knowledge",
        "manage_tasks",
        "audit_deadline_scan",
    ):
        monkeypatch.setattr(read_nodes, name, _FakeTool(name))


def _replace_specialized_executors(monkeypatch):
    capability_by_executor = {
        "full_audit_graph": "audit.full",
        "reaudit_graph": "audit.reaudit",
        "review_graph": "recovery.review",
        "audit_drilldown_agent": "audit.drilldown",
        "graph_query_agent": "graph.query",
    }

    def build(executor_name):
        capability = capability_by_executor[executor_name]

        def execute(_state):
            result = {
                "business_line_result": {"capability": capability, "ok": True},
            }
            if capability in {"audit.full", "audit.reaudit", "recovery.review"}:
                result.update(
                    {
                        "final_report_ref": f"final_report:{capability}",
                        "final_report_summary": f"{capability} completed",
                    }
                )
            else:
                result["agent_output"] = f"{capability} completed"
            return result

        return execute

    monkeypatch.setattr(
        "ai_hunter.app.subgraphs.business_line_graphs.build_specialized_executor_node",
        build,
    )


def _replace_write_executors(monkeypatch):
    import ai_hunter.app.subgraphs.business_line_graphs as line_graphs

    capability_by_executor = {
        "create_case_command": "case.create",
        "record_material_upload_command": "material.upload",
        "write_task_command": "task.write",
    }
    for executor_name, capability in capability_by_executor.items():
        monkeypatch.setitem(
            line_graphs.WRITE_EXECUTOR_NODES,
            executor_name,
            lambda _state, capability=capability: {
                "agent_output": f"{capability} completed",
                "business_line_result": {"capability": capability, "ok": True},
            },
        )


def test_all_business_line_subgraphs_compile_and_route_each_capability(monkeypatch):
    _replace_read_tools(monkeypatch)
    _replace_specialized_executors(monkeypatch)
    _replace_write_executors(monkeypatch)
    graphs = build_business_line_subgraphs()

    assert set(graphs) == {"operator", "audit_analysis", "supervision", "common"}
    for capability, spec in CAPABILITY_SPECS.items():
        result = graphs[spec.business_line].invoke(
            {
                "current_case_id": 116,
                "query": "查看案件116",
                "trace_items": [
                    {
                        "citation_id": "1",
                        "claim_id": 31,
                        "claim_text": "测试断言",
                        "evidences": [{"chunk_id": "c1", "file_id": 1, "page_no": 1, "quote_text": "测试原文"}],
                    }
                ],
                "route_decision": {"business_line": spec.business_line, "capability": capability},
            }
        )
        if spec.business_line_executor:
            assert result["business_line_result"]["capability"] == capability
            assert result["business_line_result"]["read_only"] is (spec.access_mode == "read")
            assert result["business_line_result"]["ok"] is True
            assert result["business_line_plan"] == {}
            context_field = {
                "operator": "operator_context",
                "audit_analysis": "audit_context",
                "supervision": "supervision_context",
                "common": "common_context",
            }[spec.business_line]
            assert result[context_field]["capability"] == capability
            assert result[context_field]["status"] == "completed"
        else:
            plan = result["business_line_plan"]
            assert plan == {
                "phase": "2.5.4",
                "business_line": spec.business_line,
                "capability": capability,
                "capability_node": capability_node_name(capability),
                "planned_executor": spec.executor,
                "access_mode": spec.access_mode,
                "shadow_only": True,
                "business_logic_executed": False,
            }


def test_business_line_subgraph_rejects_cross_line_capability_without_execution():
    result = build_business_line_graph("operator").invoke(
        {"route_decision": {"business_line": "audit_analysis", "capability": "audit.full"}}
    )

    assert result["business_line_plan"]["error"] == "capability does not belong to this business line"
    assert result["business_line_plan"]["business_logic_executed"] is False


def test_business_line_result_identity_is_enforced_by_registry(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.subgraphs.business_line_graphs.build_specialized_executor_node",
        lambda _executor_name: lambda _state: {
            "final_report_ref": "final_report:test",
            "business_line_result": {
                "ok": True,
                "business_line": "common",
                "capability": "common.general",
                "executor": "unknown",
                "read_only": True,
            },
        },
    )

    result = build_business_line_graph("audit_analysis").invoke(
        {"route_decision": {"business_line": "audit_analysis", "capability": "audit.full"}}
    )

    assert result["business_line_result"]["business_line"] == "audit_analysis"
    assert result["business_line_result"]["capability"] == "audit.full"
    assert result["business_line_result"]["executor"] == "full_audit_graph"
    assert result["business_line_result"]["read_only"] is False


def test_business_line_subgraph_rejects_unknown_line():
    with pytest.raises(ValueError, match="unknown business line"):
        build_business_line_graph("unknown")
