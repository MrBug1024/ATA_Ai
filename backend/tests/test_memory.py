from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from ai_hunter.app.graph.heavy_state import put_heavy_payload
from ai_hunter.app.graph.nodes.memory import hydrate_memory_context, persist_conversation_memory
from ai_hunter.app.graph.state import merge_conversation_log
from ai_hunter.app.settings import get_settings


def test_merge_conversation_log_deduplicates_by_id():
    existing = [
        {"role": "user", "content": "hello", "id": "turn1_user"},
        {"role": "assistant", "content": "hi", "id": "turn1_assistant"},
    ]
    new = [
        {"role": "user", "content": "hello", "id": "turn1_user"},
        {"role": "assistant", "content": "hi", "id": "turn1_assistant"},
        {"role": "user", "content": "world", "id": "turn2_user"},
    ]
    merged = merge_conversation_log(existing, new)
    assert len(merged) == 3
    assert merged[0]["id"] == "turn1_user"
    assert merged[1]["id"] == "turn1_assistant"
    assert merged[2]["id"] == "turn2_user"


def test_hydrate_memory_context_uses_recent_messages():
    result = hydrate_memory_context(
        {
            "messages": [
                HumanMessage(content="案件1"),
                AIMessage(content="intent=full_audit | case_id=1"),
            ]
        }
    )
    assert "user: 案件1" in result["memory_context"]
    assert "assistant: intent=full_audit | case_id=1" in result["memory_context"]


def test_persist_conversation_memory_stores_summary_not_full_report():
    result = persist_conversation_memory(
        {
            "query": "案件1",
            "intent": "full_audit",
            "route_decision": {
                "business_line": "audit_analysis",
                "capability": "audit.full",
                "intent": "full_audit",
                "confidence": 0.99,
                "source": "rule",
            },
            "current_case_id": 1,
            "current_debtor_name": "测试公司",
            "final_report_ref": put_heavy_payload("final_report", {"text": "x" * 5000}),
            "final_report": "",
        }
    )
    messages = result["messages"]
    assert len(messages) == 3
    assert isinstance(messages[0], RemoveMessage)
    assert messages[0].id == REMOVE_ALL_MESSAGES
    assert messages[1].content == "案件1"
    assert "report_generated chars=5000" in messages[2].content
    assert "x" * 100 not in messages[2].content

    # conversation_log entries carry deterministic ids
    log = result["conversation_log"]
    assert len(log) == 2
    assert log[0]["role"] == "user"
    assert log[0]["content"] == "案件1"
    assert log[0]["id"].endswith("_user")
    assert log[1]["role"] == "assistant"
    assert log[1]["id"].endswith("_assistant")
    # Same query + same answer => same deterministic id across retries
    assert log[0]["id"] == log[1]["id"].replace("_assistant", "_user")
    # full_answer resolves from heavy payload, so the log stores the real report text
    assert log[1]["content"] == "x" * 5000


def test_persist_conversation_memory_snapshots_graph_context():
    """issue #8: assistant 消息须随身携带图谱快照，刷新历史会话才不丢角标/覆盖率/未决。"""
    result = persist_conversation_memory(
        {
            "query": "案件116出审计报告",
            "intent": "full_audit",
            "route_decision": {
                "business_line": "audit_analysis",
                "capability": "audit.full",
                "intent": "full_audit",
                "confidence": 0.99,
                "source": "rule",
            },
            "current_case_id": 116,
            "final_report_ref": put_heavy_payload("final_report", {"text": "报告正文"}),
            "final_report": "",
            "trace_items": [
                {"citation_id": "1", "claim_id": 31, "claim_text": "债务人是晨光煤矿", "evidences": []}
            ],
            "citation_coverage": {
                "total_claims": 3,
                "cited_claims": 2,
                "uncited_claims": 1,
                "coverage_ratio": 0.67,
                "missing_items": [],
            },
            "unresolved_relations": [{"relation_key": "guarantee:A:B"}],
            "unresolved_claims": [{"claim_key": "valuation:X"}],
        }
    )
    log = result["conversation_log"]
    assistant_entry = next(e for e in log if e["role"] == "assistant")
    gc = assistant_entry["graph_context"]
    assert gc["route_decision"]["capability"] == "audit.full"
    assert gc["trace_items"][0]["claim_id"] == 31
    assert gc["citation_coverage"]["cited_claims"] == 2
    assert gc["unresolved_relations"][0]["relation_key"] == "guarantee:A:B"
    assert gc["unresolved_claims"][0]["claim_key"] == "valuation:X"
    # user 条目不带图谱快照
    user_entry = next(e for e in log if e["role"] == "user")
    assert "graph_context" not in user_entry


def test_persist_conversation_memory_rolls_old_messages_into_summary():
    settings = get_settings()
    original_max_tokens = settings.langgraph_memory_max_tokens
    settings.langgraph_memory_max_tokens = 80
    long_history = [
        HumanMessage(content=f"用户问题{i} " + ("x" * 80))
        if i % 2 == 0
        else AIMessage(content=f"助手回答{i} " + ("y" * 80))
        for i in range(20)
    ]
    try:
        result = persist_conversation_memory(
            {
                "query": "查看最新进展",
                "intent": "drilldown",
                "current_case_id": 116,
                "messages": long_history,
                "memory_summary": "早期摘要",
            }
        )

        assert result["memory_summary"].startswith("早期摘要") or result["memory_summary"].startswith("...")
        assert "用户问题" in result["memory_summary"] or "助手回答" in result["memory_summary"]
        assert isinstance(result["messages"][0], RemoveMessage)
    finally:
        settings.langgraph_memory_max_tokens = original_max_tokens


def test_hydrate_memory_context_includes_summary_and_recent_window():
    result = hydrate_memory_context(
        {
            "memory_summary": "案件116聚焦矿权估值",
            "messages": [
                HumanMessage(content="继续说万海隆"),
                AIMessage(content="intent=drilldown | case_id=116 | agent=已说明关联路径"),
            ],
        }
    )

    assert "[历史摘要]" in result["memory_context"]
    assert "案件116聚焦矿权估值" in result["memory_context"]
    assert "[最近对话]" in result["memory_context"]
