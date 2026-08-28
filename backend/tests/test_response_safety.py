import ai_hunter.annual_audit.evidence_service as evidence_service

from ai_hunter.app.graph.nodes import finalize_answer, memory
from ai_hunter.app.response_safety import (
    LEGACY_UNAVAILABLE_RESPONSE,
    filter_stream_debug_text,
    friendly_no_result_response,
    is_internal_debug_response,
    sanitize_user_response,
)


def test_machine_summary_is_not_treated_as_user_prose():
    value = "intent=drilldown | case_id=2 | report_generated chars=6"

    assert is_internal_debug_response(value)
    assert sanitize_user_response(value, fallback=LEGACY_UNAVAILABLE_RESPONSE) == LEGACY_UNAVAILABLE_RESPONSE


def test_split_machine_summary_is_suppressed_before_streaming_to_user():
    state = {}

    assert filter_stream_debug_text("intent", state) == ""
    assert filter_stream_debug_text("=drilldown | case_id=2", state) == ""
    assert filter_stream_debug_text(" | report_generated chars=6", state) == ""
    assert state["suppressed"] is True


def test_normal_stream_text_is_released_after_small_prefix_buffer():
    state = {}

    text = "已完成年度审计分析，正在整理可展示的审计结果。"
    assert filter_stream_debug_text(text, state) == text
    assert state["decided"] is True


def test_finalize_answer_always_creates_a_friendly_fallback(monkeypatch):
    captured = {}

    def fake_finalize(state, answer):
        captured["answer"] = answer
        return {"final_report": answer}

    monkeypatch.setattr(evidence_service, "finalize_annual_answer", fake_finalize)

    result = finalize_answer.finalize_answer(
        {
            "current_case_id": 2,
            "route_decision": {"capability": "audit.full"},
        }
    )

    assert result["final_report"] == captured["answer"]
    assert captured["answer"] == friendly_no_result_response(
        {"current_case_id": 2, "route_decision": {"capability": "audit.full"}}
    )
    assert "intent=" not in captured["answer"]


def test_memory_persistence_never_falls_back_to_internal_summary(monkeypatch):
    captured = {}

    class FakeRepo:
        def append_messages(self, thread_id, entries):
            captured["thread_id"] = thread_id
            captured["entries"] = entries

    monkeypatch.setattr(memory, "get_conversation_message_repo", lambda: FakeRepo())
    monkeypatch.setattr(memory, "resolve_final_report", lambda _state: "")
    monkeypatch.setattr(memory, "resolve_trace_items", lambda _state: [])
    monkeypatch.setattr(
        memory,
        "resolve_citation_coverage",
        lambda _state: {"total_claims": 0, "cited_claims": 0},
    )
    monkeypatch.setattr(
        memory,
        "resolve_unresolved_graph_items",
        lambda _state: {"unresolved_relations": [], "unresolved_claims": []},
    )

    memory.persist_conversation_memory(
        {
            "thread_id": "thread-safe",
            "client_turn_id": "turn-safe",
            "query": "执行年度审计，生成底稿",
            "current_case_id": 2,
            "route_decision": {"capability": "audit.full"},
            "messages": [],
        }
    )

    answer = captured["entries"][1]["content"]
    assert answer == friendly_no_result_response(
        {"current_case_id": 2, "route_decision": {"capability": "audit.full"}}
    )
    assert not is_internal_debug_response(answer)
