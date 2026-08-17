import asyncio
import hashlib
import json
import logging

import pytest
from fastapi import HTTPException

from ai_hunter.app.api.routes_chat import (
    ChatRequest,
    _build_final_response,
    _build_graph_input,
    _merge_response_final_state,
    _require_existing_annual_engagement,
    _stream_chat_events,
)
from ai_hunter.app.api import routes_chat
from ai_hunter.app.graph.nodes import memory
from ai_hunter.app.main import create_app
from ai_hunter.annual_audit.engagement_repository import EngagementNotFoundError


def test_nonexistent_annual_engagement_is_rejected_before_chat_execution(monkeypatch):
    def missing_engagement(_case_id):
        raise EngagementNotFoundError("missing")

    monkeypatch.setattr(
        "ai_hunter.annual_audit.engagement_repository.get_engagement",
        missing_engagement,
    )

    with pytest.raises(HTTPException) as exc_info:
        _require_existing_annual_engagement(10, allow_unbound=False)

    assert exc_info.value.status_code == 404
    assert "不存在" in str(exc_info.value.detail)


def test_case_creation_request_remains_unbound_for_preflight(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.annual_audit.engagement_repository.get_engagement",
        lambda _case_id: (_ for _ in ()).throw(AssertionError("must not query")),
    )

    _require_existing_annual_engagement(0, allow_unbound=True)


def test_missing_thread_detail_uses_safe_audit_history_guidance(monkeypatch):
    class FakeConversationService:
        def get_thread_detail(self, _thread_id):
            return None

    monkeypatch.setattr(
        routes_chat,
        "get_conversation_service",
        lambda: FakeConversationService(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes_chat.get_thread_detail("other-tenant-thread", identity=None))

    assert exc_info.value.status_code == 404
    detail = str(exc_info.value.detail)
    assert "当前年审存储中不可用" in detail
    assert "不能作为审计依据" in detail
    assert "other-tenant-thread" not in detail


def test_chat_input_keeps_audited_entity_fields_in_graph_state():
    payload = ChatRequest(
        thread_id="annual-thread-1",
        query="分析收入截止性",
        current_case_id=7,
        current_entity_id=7,
        current_entity_name="示例制造有限公司",
        stream=False,
    )
    graph_input = _build_graph_input(payload)
    assert graph_input["current_case_id"] == 7
    assert graph_input["current_entity_id"] == 7
    assert graph_input["current_entity_name"] == "示例制造有限公司"


def test_chat_openapi_exposes_single_annual_audit_contract():
    schema = create_app().openapi()
    paths = set(schema["paths"])
    assert "/chat/invoke" in paths
    assert "/chat/upload-files" in paths
    assert "/evidence/resolve" in paths
    assert "/api/audit/get_full_context" in paths


def test_chat_schema_rejects_blank_thread_id():
    try:
        ChatRequest(thread_id="   ")
    except ValueError:
        return
    raise AssertionError("blank thread_id must be rejected")


def test_stream_terminal_state_overrides_previous_turn_before_final_contract():
    payload = ChatRequest(
        thread_id="annual-thread-stream",
        query="查看银行存款异常",
        current_case_id=7,
        stream=True,
        client_turn_id="client-turn-2",
    )
    checkpoint_state = {
        "current_case_id": 7,
        "final_report_ref": "payload:prior",
        "final_report": "prior answer",
        "assistant_message_id": "prior_assistant",
        "trace_items": [{"citation_id": "1", "claim_id": 99, "evidences": []}],
        "citation_coverage": {"total_claims": 1},
    }
    terminal_update = {
        "current_case_id": 7,
        "final_report_ref": "payload:response-2",
        "final_report": "current answer\n\n### 证据索引\n- [[cite:1]] cash bank exception",
        "assistant_message_id": "response_2_assistant",
        "trace_items": [],
        "citation_coverage": {},
        "response_analysis_runs": [
            {
                "tool_name": "analyze_cash_and_bank",
                "analysis_type": "cash_and_bank",
                "analysis_run_id": 42,
            }
        ],
    }

    final_state = _merge_response_final_state(checkpoint_state, terminal_update)
    response = _build_final_response(payload, final_state)

    assert response.final_report_ref == "payload:response-2"
    assert response.final_report.startswith("current answer")
    assert response.assistant_message_id == "response_2_assistant"
    assert response.trace_items == []
    assert response.citation_coverage.total_claims == 0
    assert response.response_analysis_runs == [
        {
            "tool_name": "analyze_cash_and_bank",
            "analysis_type": "cash_and_bank",
            "analysis_run_id": 42,
        }
    ]


def test_persisted_assistant_message_uses_current_response_ref_and_trace_snapshot(monkeypatch):
    captured = {}

    class FakeRepo:
        def append_messages(self, thread_id, entries):
            captured["thread_id"] = thread_id
            captured["entries"] = entries

        def get_max_assistant_version(self, *_args):
            return 0

    trace_items = [
        {
            "citation_id": "1",
            "claim_id": 701,
            "claim_type": "exception",
            "claim_text": "cash bank exception",
            "evidences": [],
        }
    ]
    monkeypatch.setattr(memory, "get_conversation_message_repo", lambda: FakeRepo())
    monkeypatch.setattr(memory, "resolve_final_report", lambda state: state["final_report"])
    monkeypatch.setattr(memory, "resolve_trace_items", lambda _state: trace_items)
    monkeypatch.setattr(
        memory,
        "resolve_citation_coverage",
        lambda _state: {"total_claims": 1, "cited_claims": 1},
    )
    monkeypatch.setattr(
        memory,
        "resolve_unresolved_graph_items",
        lambda _state: {"unresolved_relations": [], "unresolved_claims": []},
    )

    result = memory.persist_conversation_memory(
        {
            "thread_id": "thread-persist",
            "client_turn_id": "turn-current",
            "query": "cash bank",
            "current_case_id": 7,
            "messages": [],
            "final_report_ref": "payload:response-current",
            "final_report": "current answer\n\n### 证据索引\n- [[cite:1]] cash bank exception",
            "trace_items": trace_items,
            "response_analysis_runs": [
                {
                    "tool_name": "analyze_cash_and_bank",
                    "analysis_type": "cash_and_bank",
                    "analysis_run_id": 66,
                }
            ],
        }
    )

    expected_id = f"{hashlib.sha256(b'thread-persist:turn-current').hexdigest()[:16]}_assistant"
    assistant_entry = captured["entries"][1]
    assert captured["thread_id"] == "thread-persist"
    assert assistant_entry["id"] == expected_id
    assert assistant_entry["final_report_ref"] == "payload:response-current"
    assert assistant_entry["graph_context"]["trace_items"] == trace_items
    assert assistant_entry["graph_context"]["response_analysis_runs"] == [
        {
            "tool_name": "analyze_cash_and_bank",
            "analysis_type": "cash_and_bank",
            "analysis_run_id": 66,
        }
    ]
    assert result["assistant_message_id"] == expected_id


def test_turns_restore_each_assistant_versions_own_evidence_snapshot(monkeypatch):
    """A refreshed thread must not assign a later reply's citations to an earlier one."""

    class FakeRepo:
        def get_turns(self, _thread_id):
            return [
                {
                    "turn_id": "turn-1",
                    "user": {
                        "content": "generate the audit report",
                        "created_at": "2026-08-14T10:00:00+08:00",
                        "uploaded_files": [],
                    },
                    "assistants": [
                        {
                            "content": "first response [[cite:1]]",
                            "created_at": "2026-08-14T10:01:00+08:00",
                            "final_report_ref": "report:first",
                            "intent": "full_audit",
                            "case_id": 7,
                            "version": 1,
                            "graph_context": {
                                "route_decision": {
                                    "business_line": "audit_analysis",
                                    "capability": "audit.full",
                                    "confidence": 0.92,
                                    "source": "rule",
                                },
                                "trace_items": [
                                    {
                                        "citation_id": "1",
                                        "claim_id": 701,
                                        "claim_type": "risk_signal",
                                        "claim_text": "first claim",
                                        "evidences": [],
                                    }
                                ],
                                "citation_coverage": {
                                    "total_claims": 1,
                                    "cited_claims": 1,
                                    "coverage_ratio": 1,
                                },
                                "response_analysis_runs": [
                                    {
                                        "tool_name": "analyze_cash_and_bank",
                                        "analysis_type": "cash_and_bank",
                                        "analysis_run_id": 88,
                                    }
                                ],
                                "unresolved_relations": [{"relation_key": "r-first"}],
                                "unresolved_claims": [{"claim_text": "first unresolved"}],
                            },
                        },
                        {
                            "content": "regenerated response",
                            "created_at": "2026-08-14T10:02:00+08:00",
                            "final_report_ref": "report:second",
                            "intent": "full_audit",
                            "case_id": 7,
                            "version": 2,
                            "graph_context": {},
                        },
                    ],
                }
            ]

    monkeypatch.setattr(routes_chat, "get_conversation_message_repo", lambda: FakeRepo())
    monkeypatch.setattr(routes_chat, "visible_report_sections", lambda _identity: set())

    response = asyncio.run(routes_chat.get_thread_turns("thread-history", identity=None))
    first, second = response.turns[0].assistants

    assert first.final_report_ref == "report:first"
    assert first.trace_items[0].claim_id == 701
    assert first.citation_coverage.cited_claims == 1
    assert first.unresolved_relations[0].relation_key == "r-first"
    assert first.unresolved_claims[0].claim_text == "first unresolved"
    assert first.route_decision is not None
    assert first.route_decision.capability == "audit.full"
    assert first.response_analysis_runs == [
        {
            "tool_name": "analyze_cash_and_bank",
            "analysis_type": "cash_and_bank",
            "analysis_run_id": 88,
        }
    ]
    assert second.final_report_ref == "report:second"
    assert second.trace_items == []
    assert second.citation_coverage.total_claims == 0
    assert second.response_analysis_runs is None
    assert second.unresolved_relations == []
    assert second.unresolved_claims == []


def test_sse_final_uses_terminal_response_not_stale_checkpoint(monkeypatch):
    class Snapshot:
        values = {
            "current_case_id": 7,
            "final_report_ref": "payload:prior",
            "final_report": "prior answer",
            "assistant_message_id": "prior_assistant",
            "trace_items": [{"citation_id": "1", "claim_id": 99, "evidences": []}],
            "citation_coverage": {"total_claims": 1},
        }

    class FakeStreamingGraph:
        async def astream_events(self, *_args, **_kwargs):
            yield {
                "event": "on_chain_end",
                "name": "finalize_answer",
                "metadata": {"langgraph_node": "finalize_answer"},
                "data": {
                    "output": {
                        "current_case_id": 7,
                        "final_report_ref": "payload:response-current",
                        "final_report": "current answer\n\n### 证据索引\n- [[cite:1]] cash bank exception",
                        "trace_items": [],
                        "citation_coverage": {},
                        "response_analysis_runs": [
                            {
                                "tool_name": "analyze_cash_and_bank",
                                "analysis_type": "cash_and_bank",
                                "analysis_run_id": 42,
                            }
                        ],
                    }
                },
            }
            yield {
                "event": "on_chain_end",
                "name": "persist_conversation_memory",
                "metadata": {"langgraph_node": "persist_conversation_memory"},
                "data": {"output": {"assistant_message_id": "current_assistant"}},
            }

        async def aget_state(self, _config):
            return Snapshot()

    async def fake_ensure_async_graph():
        return FakeStreamingGraph()

    monkeypatch.setattr(
        "ai_hunter.app.api.routes_chat._ensure_async_graph",
        fake_ensure_async_graph,
    )
    payload = ChatRequest(
        thread_id="annual-thread-sse",
        query="cash bank",
        current_case_id=7,
        stream=True,
        client_turn_id="stream-turn",
    )

    async def collect():
        return [
            frame
            async for frame in _stream_chat_events(
                payload,
                logging.LoggerAdapter(logging.getLogger("test"), {}),
                "postgresql://unused",
            )
        ]

    frames = asyncio.run(collect())
    final_frame = next(frame for frame in frames if frame.startswith("event: final"))
    final_payload = json.loads(final_frame.split("\n", 2)[1].removeprefix("data: "))

    assert final_payload["final_report_ref"] == "payload:response-current"
    assert final_payload["final_report"].startswith("current answer")
    assert final_payload["assistant_message_id"] == "current_assistant"
    assert final_payload["trace_items"] == []
    assert final_payload["response_analysis_runs"] == [
        {
            "tool_name": "analyze_cash_and_bank",
            "analysis_type": "cash_and_bank",
            "analysis_run_id": 42,
        }
    ]
