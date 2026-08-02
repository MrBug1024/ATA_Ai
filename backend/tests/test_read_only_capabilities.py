import json

import pytest

import ai_hunter.app.graph.nodes.read_only_capabilities as read_nodes
from ai_hunter.app.graph.capabilities import CAPABILITY_SPECS
from ai_hunter.app.graph.nodes.write_capabilities import WRITE_EXECUTOR_TOOL_NAMES
from ai_hunter.app.subgraphs.business_line_executors import SPECIALIZED_EXECUTOR_TOOL_NAMES


class FakeTool:
    def __init__(self, name: str):
        self.name = name
        self.calls = []

    def invoke(self, payload):
        self.calls.append(payload)
        return json.dumps(
            {
                "summary": f"{self.name} ok",
                "key_facts": {"case_id": payload.get("case_id", 0)},
                "truncated": False,
                "next_hint": "",
            },
            ensure_ascii=False,
        )


@pytest.mark.parametrize(
    ("function_name", "tool_name", "capability", "expected_args"),
    (
        ("query_case_profile", "get_case_profile", "case.profile", {"case_id": 116}),
        (
            "query_material_status",
            "get_case_doc_category_status",
            "material.status",
            {"case_id": 116},
        ),
        ("query_tasks", "manage_tasks", "task.query", {"action": "list", "case_id": 116}),
        ("query_deadline", "audit_deadline_scan", "deadline.query", {"case_id": 116}),
    ),
)
def test_single_tool_read_nodes_use_deterministic_arguments(
    monkeypatch,
    function_name,
    tool_name,
    capability,
    expected_args,
):
    fake = FakeTool(tool_name)
    monkeypatch.setattr(read_nodes, tool_name, fake)

    result = getattr(read_nodes, function_name)(
        {
            "query": "查看案件116的证据原文",
            "current_case_id": 116,
            "route_decision": {"capability": capability, "case_id": 116},
        }
    )

    assert fake.calls == [expected_args]
    assert result["business_line_result"]["capability"] == capability
    assert result["business_line_result"]["read_only"] is True
    assert result["business_line_result"]["ok"] is True
    assert fake.name in result["agent_output"]


def test_material_validation_only_reads_catalog_and_case_status(monkeypatch):
    catalog = FakeTool("get_doc_categories")
    status = FakeTool("get_case_doc_category_status")
    monkeypatch.setattr(read_nodes, "get_doc_categories", catalog)
    monkeypatch.setattr(read_nodes, "get_case_doc_category_status", status)

    result = read_nodes.query_material_validation(
        {"current_case_id": 116, "route_decision": {"capability": "material.validate", "case_id": 116}}
    )

    assert catalog.calls == [{}]
    assert status.calls == [{"case_id": 116}]
    assert result["business_line_result"]["ok"] is True
    assert len(result["business_line_result"]["tool_calls"]) == 2


def test_query_evidence_reads_only_current_case_trace_items(monkeypatch):
    class FakeKgService:
        def fetch_case_evidence_traces(self, case_id, *, query_text, limit):
            assert (case_id, query_text, limit) == (116, "查看采矿权证据原文", 5)
            return [
                {
                    "citation_id": "",
                    "claim_id": 31,
                    "claim_text": "晨光煤矿存在采矿权",
                    "evidences": [
                        {
                            "chunk_id": "chunk-31",
                            "file_id": 5,
                            "file_name": "二债会资料.pdf",
                            "page_no": 4,
                            "quote_text": "采矿权未办理抵押登记",
                            "bbox_list": [],
                        }
                    ],
                }
            ]

    monkeypatch.setattr(read_nodes, "get_kg_service", lambda: FakeKgService())
    result = read_nodes.query_evidence(
        {
            "query": "查看采矿权证据原文",
            "current_case_id": 116,
        }
    )

    business_result = result["business_line_result"]
    assert business_result["ok"] is True
    assert business_result["tool_calls"] == []
    assert business_result["source_scope"] == "case_material"
    assert business_result["case_binding"] is True
    assert business_result["reference_only"] is False
    assert business_result["evidence_items"][0]["chunk_id"] == "chunk-31"


def test_query_evidence_without_case_trace_returns_explicit_empty_state(monkeypatch):
    class EmptyKgService:
        def fetch_case_evidence_traces(self, _case_id, *, query_text, limit):
            assert (query_text, limit) == ("查看本案证据", 5)
            return []

    monkeypatch.setattr(read_nodes, "get_kg_service", lambda: EmptyKgService())
    result = read_nodes.query_evidence({"query": "查看本案证据", "current_case_id": 116})

    assert result["business_line_result"]["ok"] is False
    assert result["business_line_result"]["error"] == "case_evidence_not_found"
    assert result["business_line_result"]["tool_calls"] == []


def test_query_caselaw_is_external_reference_only(monkeypatch):
    tool = FakeTool("query_wenshu_knowledge")
    monkeypatch.setattr(read_nodes, "query_wenshu_knowledge", tool)

    result = read_nodes.query_caselaw({"query": "找采矿权抵押无效的相似案例"})

    assert tool.calls == [{"question": "找采矿权抵押无效的相似案例", "limit": 5}]
    assert result["business_line_result"]["source_scope"] == "external_caselaw"
    assert result["business_line_result"]["case_binding"] is False
    assert result["business_line_result"]["reference_only"] is True
    assert "不代表当前案件事实" in result["agent_output"]


def test_read_node_without_case_id_does_not_call_tool(monkeypatch):
    fake = FakeTool("manage_tasks")
    monkeypatch.setattr(read_nodes, "manage_tasks", fake)

    result = read_nodes.query_tasks({"route_decision": {"capability": "task.query"}})

    assert fake.calls == []
    assert result["agent_output"] == "请先提供要查询的案件编号。"
    assert result["business_line_result"]["error"] == "missing_case_id"
    assert result["business_line_result"]["tool_calls"] == []


def test_read_node_normalizes_tool_error_without_raising(monkeypatch):
    class ErrorTool(FakeTool):
        def invoke(self, payload):
            self.calls.append(payload)
            return json.dumps(
                {
                    "summary": "audit_deadline_scan 调用失败。",
                    "key_facts": {"error": "service unavailable"},
                    "truncated": False,
                    "next_hint": "请稍后重试。",
                },
                ensure_ascii=False,
            )

    fake = ErrorTool("audit_deadline_scan")
    monkeypatch.setattr(read_nodes, "audit_deadline_scan", fake)

    result = read_nodes.query_deadline({"current_case_id": 116})

    assert result["business_line_result"]["ok"] is False
    assert "调用失败" in result["agent_output"]


def test_business_line_executor_tools_are_registered_for_each_capability():
    executor_tools = {
        **read_nodes.READ_ONLY_EXECUTOR_TOOL_NAMES,
        **WRITE_EXECUTOR_TOOL_NAMES,
        **SPECIALIZED_EXECUTOR_TOOL_NAMES,
    }
    for spec in CAPABILITY_SPECS.values():
        if not spec.business_line_executor:
            continue
        assert spec.business_line_executor in executor_tools
        actual_tools = executor_tools[spec.business_line_executor]
        assert set(actual_tools).issubset(spec.tool_names)
