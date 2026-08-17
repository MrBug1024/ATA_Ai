from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from ai_hunter.app.graph.nodes.normalize_input import normalize_input


def test_normalize_input_clears_case_bound_state_when_query_switches_case():
    result = normalize_input(
        {
            "thread_id": "t-case-switch",
            "query": "年审项目210重新审计",
            "current_case_id": 7,
            "messages": [HumanMessage(content="年审项目7")],
            "memory_context": "user: 年审项目7",
            "full_context_json": '{"case_id": 7}',
            "report_part_b": "上一版年度审计报告",
            "user_corrections": ["上一版事实更正"],
        }
    )

    assert result["case_switched"] is True
    assert isinstance(result["messages"][0], RemoveMessage)
    assert result["messages"][0].id == REMOVE_ALL_MESSAGES
    assert result["current_case_id"] == 210
    assert result["memory_context"] == ""
    assert result["full_context_json"] == ""
    assert result["report_part_b"] == ""
    assert result["user_corrections"] == []


def test_normalize_input_keeps_state_when_case_does_not_change():
    result = normalize_input(
        {
            "thread_id": "t-no-switch",
            "query": "查看任务",
            "current_case_id": 7,
            "messages": [HumanMessage(content="年审项目7")],
        }
    )

    assert result["case_switched"] is False
    assert result["messages"][0].content == "年审项目7"


def test_normalize_input_clears_previous_response_evidence_for_same_case():
    result = normalize_input(
        {
            "thread_id": "t-same-case-new-turn",
            "query": "查看银行存款异常",
            "current_case_id": 7,
            "final_report_ref": "payload:prior-turn",
            "final_report": "上一轮回答\n\n### 证据索引\n- [1] 旧断言",
            "assistant_message_id": "prior_assistant",
            "trace_items": [{"citation_id": "1", "claim_id": 99, "evidences": []}],
            "citation_coverage": {"total_claims": 1},
            "unresolved_claims": [{"claim_id": 99}],
            "agent_output": "旧回答",
        }
    )

    assert result["case_switched"] is False
    assert result["final_report_ref"] == ""
    assert result["final_report"] == ""
    assert result["assistant_message_id"] == ""
    assert result["trace_items"] == []
    assert result["citation_coverage"] == {}
    assert result["unresolved_claims"] == []
    assert result["agent_output"] == ""
