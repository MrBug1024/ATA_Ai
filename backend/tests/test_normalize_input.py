from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from ai_hunter.app.graph.nodes.normalize_input import normalize_input


def test_normalize_input_clears_case_bound_state_when_query_switches_case():
    result = normalize_input(
        {
            "thread_id": "t-case-switch",
            "query": "案件210重新审计",
            "current_case_id": 116,
            "messages": [HumanMessage(content="案件116")],
            "memory_context": "user: 案件116",
            "full_context_json": '{"case_id": 116}',
            "report_part_b": "旧案件报告",
            "user_corrections": ["旧修正"],
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
            "current_case_id": 116,
            "messages": [HumanMessage(content="案件116")],
        }
    )

    assert result["case_switched"] is False
    assert result["messages"][0].content == "案件116"
