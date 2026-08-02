from decimal import Decimal
import hashlib
import json
import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ai_hunter.app.main import create_app
from ai_hunter.app.api.routes_chat import (
    _dehydrate_node_payload,
    _require_pre_graph_write_module,
    _require_route_module,
    _run_graph_with_logging,
    _split_tagged_reasoning,
    _split_tagged_reasoning_stream,
    _sse_event,
)
from ai_hunter.app.auth.identity import Identity, get_current_identity
from ai_hunter.app.settings import get_settings

EXPECTED_PAGE_IMAGE_URL = "https://minio.gshbzw.com/derived/page-2.png"


def test_chat_options_returns_cors_headers():
    client = TestClient(create_app())
    response = client.options(
        "/chat/invoke",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_chat_invoke_returns_json(monkeypatch):
    class FakeGraph:
        def invoke(self, payload, config=None):
            return {
                "current_case_id": 116,
                "current_debtor_id": 76,
                "current_debtor_name": "钟山区老鹰山镇晨光煤矿",
                "final_report_ref": "final_report:demo-1",
                "final_report": "最终报告",
                "trace_items": [
                    {
                        "citation_id": "1",
                        "claim_id": 31,
                        "claim_type": "risk_signal",
                        "claim_text": "存在关联担保",
                        "confidence": 0.91,
                        "evidences": [
                            {
                                "chunk_id": "chunk-1",
                                "file_id": 101,
                                "page_no": 2,
                                "quote_text": "证据",
                                "page_image_ref": "minio://derived/page-2.png",
                            }
                        ],
                    }
                ],
                "unresolved_relations": [
                    {
                        "relation_temp_id": "relation_2",
                        "relation_key": "relation-key-2",
                        "relation_type": "guarantee",
                        "relation_label": "担保关系",
                        "from_entity_temp_id": "entity_missing",
                        "to_entity_temp_id": "entity_1",
                        "missing_dependencies": ["from_entity"],
                        "reason": "missing_entity_reference",
                        "evidence_chunk_ids": ["chunk-2"],
                    }
                ],
                "unresolved_claims": [
                    {
                        "claim_type": "relation_fact",
                        "claim_text": "甲为乙提供担保",
                        "entity_name": "甲公司",
                        "entity_key": "entity-key-x",
                        "entity_temp_id": "entity_missing",
                        "relation_key": "relation-key-2",
                        "relation_temp_id": "relation_2",
                        "missing_dependencies": ["entity", "relation"],
                        "reason": "missing_graph_reference",
                        "evidence_chunk_ids": ["chunk-2"],
                    }
                ],
                "citation_coverage": {
                    "total_claims": 1,
                    "cited_claims": 1,
                    "uncited_claims": 0,
                    "coverage_ratio": 1.0,
                    "missing_items": [],
                },
                "parse_summary": "补充材料已入库。",
                "intent": "full_audit",
                "route_decision": {
                    "business_line": "audit_analysis",
                    "capability": "audit.full",
                    "confidence": 0.99,
                    "source": "rule",
                    "case_id": 116,
                },
                "memory_context": "历史摘要",
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_chat.graph", FakeGraph())

    client = TestClient(create_app())
    response = client.post(
        "/chat/invoke",
        json={
            "thread_id": "demo-1",
            "query": "案件116出具完整审计报告",
            "current_case_id": 116,
            # 默认已改为流式（stream=True），这里显式关掉以覆盖 JSON 一次性返回路径。
            "stream": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "demo-1"
    assert body["intent"] == "full_audit"
    assert body["route_decision"]["business_line"] == "audit_analysis"
    assert body["route_decision"]["capability"] == "audit.full"
    assert body["route_decision"]["intent"] == "full_audit"
    assert body["final_report_ref"] == "final_report:demo-1"
    assert body["final_report"] == "最终报告"
    assert body["trace_items"][0]["citation_id"] == "1"
    assert body["trace_items"][0]["claim_text"] == "存在关联担保"
    assert body["trace_items"][0]["evidences"][0]["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["unresolved_relations"][0]["relation_key"] == "relation-key-2"
    assert body["unresolved_claims"][0]["claim_text"] == "甲为乙提供担保"
    assert body["citation_coverage"]["coverage_ratio"] == 1.0


def _cached_task_write_row(thread_id: str, client_turn_id: str) -> dict:
    turn_id = hashlib.sha256(f"{thread_id}:{client_turn_id}".encode()).hexdigest()[:16]
    return {
        "turn_id": f"{turn_id}_assistant",
        "content": "任务 489 已完成。",
        "intent": "drilldown",
        "case_id": 133,
        "final_report_ref": "",
        "graph_context": {
            "route_decision": {
                "route_version": "v2",
                "business_line": "supervision",
                "capability": "task.write",
                "intent": "drilldown",
                "confidence": 0.99,
                "needs_clarification": False,
                "source": "rule",
                "case_id": 133,
                "action": "complete",
                "target_id": "489",
            },
            "trace_items": [],
            "citation_coverage": {},
            "unresolved_relations": [],
            "unresolved_claims": [],
        },
    }


def test_chat_invoke_cached_json_preserves_route_audit(monkeypatch):
    from contextlib import asynccontextmanager

    thread_id = "cached-json-thread"
    client_turn_id = "cached-json-turn"

    class FakeRepo:
        def get_messages(self, requested_thread_id):
            assert requested_thread_id == thread_id
            return [_cached_task_write_row(thread_id, client_turn_id)]

    class FailGraph:
        def invoke(self, payload, config=None):
            raise AssertionError("cached request must not execute the graph")

    @asynccontextmanager
    async def fake_thread_lock(dsn, requested_thread_id):
        assert requested_thread_id == thread_id
        yield

    monkeypatch.setattr("ai_hunter.app.api.routes_chat.get_conversation_message_repo", lambda: FakeRepo())
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.thread_advisory_lock", fake_thread_lock)
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.graph", FailGraph())

    response = TestClient(create_app()).post(
        "/chat/invoke",
        json={
            "thread_id": thread_id,
            "query": "完成任务489",
            "current_case_id": 133,
            "client_turn_id": client_turn_id,
            "stream": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["current_case_id"] == 133
    assert body["intent"] == "drilldown"
    assert body["final_report"] == "任务 489 已完成。"
    assert body["route_decision"]["business_line"] == "supervision"
    assert body["route_decision"]["capability"] == "task.write"
    assert body["route_decision"]["target_id"] == "489"


def test_chat_invoke_cached_sse_preserves_route_audit(monkeypatch):
    from contextlib import asynccontextmanager

    thread_id = "cached-sse-thread"
    client_turn_id = "cached-sse-turn"

    class FakeRepo:
        def get_messages(self, requested_thread_id):
            assert requested_thread_id == thread_id
            return [_cached_task_write_row(thread_id, client_turn_id)]

    @asynccontextmanager
    async def fake_thread_lock(dsn, requested_thread_id):
        assert requested_thread_id == thread_id
        yield

    monkeypatch.setattr("ai_hunter.app.api.routes_chat.get_conversation_message_repo", lambda: FakeRepo())
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.thread_advisory_lock", fake_thread_lock)

    response = TestClient(create_app()).post(
        "/chat/invoke",
        json={
            "thread_id": thread_id,
            "query": "完成任务489",
            "current_case_id": 133,
            "client_turn_id": client_turn_id,
            "stream": True,
        },
    )

    assert response.status_code == 200
    frames = {}
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: "))
        frames[event] = data
    assert frames["start"]["cached"] is True
    assert frames["final"]["current_case_id"] == 133
    assert frames["final"]["intent"] == "drilldown"
    assert frames["final"]["route_decision"]["capability"] == "task.write"
    assert frames["final"]["route_decision"]["target_id"] == "489"
    assert frames["done"]["thread_id"] == thread_id


def test_route_decision_is_preserved_in_sse_node_payload():
    decision = {
        "business_line": "supervision",
        "capability": "task.query",
        "intent": "drilldown",
        "confidence": 0.95,
        "source": "rule",
    }

    compact = _dehydrate_node_payload("classify_intent", {"intent": "drilldown", "route_decision": decision})

    assert compact["route_decision"] == decision


def test_route_shadow_is_not_exposed_in_sse_node_payload():
    compact = _dehydrate_node_payload(
        "classify_intent",
        {
            "intent": "drilldown",
            "route_shadow": {
                "configured_mode": "business_line",
                "active_mode": "legacy",
                "write_shadow_blocked": True,
            },
        },
    )

    assert "route_shadow" not in compact


def test_business_line_internal_context_is_not_exposed_in_sse_node_payload():
    compact = _dehydrate_node_payload(
        "audit_analysis_subgraph",
        {
            "route_decision": {"business_line": "audit_analysis", "capability": "graph.query"},
            "agent_output": "图谱查询完成",
            "business_line_result": {"ok": True, "tool_calls": [{"raw": "internal"}]},
            "audit_context": {"status": "completed", "output_ref": "private:ref"},
        },
    )

    assert compact["route_decision"]["capability"] == "graph.query"
    assert "business_line_result" not in compact
    assert "audit_context" not in compact


def test_route_module_authorization_uses_capability(monkeypatch):
    identity = Identity(user_id="u_graph", roles=["graph_reader"], authenticated=True)
    checked = []

    def fake_has_module(_identity, module):
        checked.append(module)
        return module == "graph"

    monkeypatch.setattr("ai_hunter.app.api.routes_chat.has_module", fake_has_module)

    _require_route_module(
        identity,
        {"intent": "drilldown", "route_decision": {"capability": "graph.query"}},
    )

    assert checked == ["graph"]


def test_upload_permission_is_rejected_before_graph_execution(monkeypatch):
    identity = Identity(user_id="u_progress", roles=["progress_only"], authenticated=True)
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.has_module", lambda _identity, module: module != "report")

    from ai_hunter.app.api.routes_chat import ChatRequest

    payload = ChatRequest(
        thread_id="upload-denied",
        query="上传案件116材料",
        current_case_id=116,
        uploaded_files=[{"name": "sample.txt", "content": "sample"}],
    )

    with pytest.raises(HTTPException) as exc_info:
        _require_pre_graph_write_module(identity, payload)

    assert exc_info.value.status_code == 403
    assert "material.upload" in exc_info.value.detail


def test_sync_route_module_denial_stops_before_business_line_read(monkeypatch):
    import ai_hunter.app.api.routes_chat as routes_chat

    executed = []

    class FakeGraph:
        def stream(self, payload, config=None, stream_mode=None):
            yield "values", payload
            yield "updates", {
                "classify_intent": {
                    "intent": "drilldown",
                    "route_decision": {"capability": "evidence.resolve"},
                }
            }
            executed.append("query_evidence")
            yield "updates", {"audit_analysis_subgraph": {"agent_output": "should not run"}}

    monkeypatch.setattr(routes_chat, "graph", FakeGraph())
    monkeypatch.setattr(routes_chat, "has_module", lambda _identity, module: module != "graph")

    with pytest.raises(HTTPException) as exc_info:
        _run_graph_with_logging(
            {"thread_id": "permission-stop", "query": "查看证据"},
            "permission-stop",
            logging.getLogger("test"),
            Identity(user_id="u_assistant", roles=["project_assistant"], authenticated=True),
        )

    assert exc_info.value.status_code == 403
    assert executed == []


def test_sse_route_module_denial_stops_before_business_line_read(monkeypatch):
    from contextlib import asynccontextmanager
    import ai_hunter.app.api.routes_chat as routes_chat

    executed = []

    class FakeAsyncGraph:
        async def astream_events(self, payload, config=None, version=None):
            yield {
                "event": "on_chain_end",
                "name": "classify_intent",
                "data": {
                    "output": {
                        "intent": "drilldown",
                        "route_decision": {"capability": "evidence.resolve"},
                    }
                },
            }
            executed.append("query_evidence")
            yield {
                "event": "on_chain_end",
                "name": "audit_analysis_subgraph",
                "data": {"output": {"agent_output": "should not run"}},
            }

    async def fake_ensure_async_graph():
        return FakeAsyncGraph()

    @asynccontextmanager
    async def fake_thread_lock(dsn, thread_id):
        yield

    monkeypatch.setattr(routes_chat, "_ensure_async_graph", fake_ensure_async_graph)
    monkeypatch.setattr(routes_chat, "thread_advisory_lock", fake_thread_lock)
    monkeypatch.setattr(routes_chat, "has_module", lambda _identity, module: module != "graph")
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="u_assistant",
        roles=["project_assistant"],
        authenticated=True,
    )

    with TestClient(app).stream(
        "POST",
        "/chat/invoke",
        json={"thread_id": "permission-sse-stop", "query": "查看案件116证据原文", "current_case_id": 116},
        headers={"accept": "text/event-stream"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: error" in body
    assert '"status_code": 403' in body
    assert "event: done" not in body
    assert executed == []


def test_split_tagged_reasoning_separates_think_from_content():
    assert _split_tagged_reasoning("正文") == [("content", "正文")]
    assert _split_tagged_reasoning("<think>推理</think>正文") == [("reasoning", "推理"), ("content", "正文")]
    assert _split_tagged_reasoning("A<think>R</think>B") == [("content", "A"), ("reasoning", "R"), ("content", "B")]


def test_split_tagged_reasoning_stream_handles_split_tags():
    state = {"mode": "content", "buffer": ""}
    chunks = ["A", "<think>", "R1", "</thi", "nk>B", "<thi", "nk>R2</think>", "C"]
    parts = []
    for chunk in chunks:
        parts.extend(_split_tagged_reasoning_stream(chunk, state))

    assert parts == [
        ("content", "A"),
        ("reasoning", "R1"),
        ("content", "B"),
        ("reasoning", "R2"),
        ("content", "C"),
    ]
    assert not any("<think>" in text or "</think>" in text for _, text in parts)


def test_chat_invoke_streams_sse(monkeypatch):
    # SSE 走的是 astream_events（异步事件协议）+ 独立编译的 async 图，
    # 不是被 monkeypatch 的 sync ``graph``。因此这里 mock ``_ensure_async_graph``，
    # 并把 ``thread_advisory_lock`` 换成 no-op，避免连真实 Postgres。
    from contextlib import asynccontextmanager

    final_state = {
        "current_case_id": 116,
        "current_debtor_id": 76,
        "current_debtor_name": "钟山区老鹰山镇晨光煤矿",
        "final_report_ref": "final_report:demo-stream",
        "final_report": "最终报告",
        "trace_items": [
            {
                "citation_id": "1",
                "claim_id": 31,
                "claim_type": "risk_signal",
                "claim_text": "存在关联担保",
                "confidence": 0.91,
                "evidences": [
                    {
                        "chunk_id": "chunk-1",
                        "file_id": 101,
                        "page_no": 2,
                        "quote_text": "证据",
                        "page_image_ref": "minio://derived/page-2.png",
                    }
                ],
            }
        ],
        "citation_coverage": {
            "total_claims": 1,
            "cited_claims": 1,
            "uncited_claims": 0,
            "coverage_ratio": 1.0,
            "missing_items": [],
        },
        "parse_summary": "补充材料已入库。",
        "intent": "full_audit",
        "memory_context": "历史摘要",
    }

    class _FakeChunk:
        """模拟 on_chat_model_stream 的 chunk：正文走 content、思考走 reasoning_content。"""

        def __init__(self, content="", reasoning=""):
            self.content = content
            self.reasoning_content = reasoning
            self.additional_kwargs = {}

    class _Snapshot:
        values = final_state

    class FakeAsyncGraph:
        async def astream_events(self, payload, config=None, version=None):
            yield {
                "event": "on_chain_end",
                "name": "classify_intent",
                "data": {"output": {"intent": "full_audit"}},
            }
            yield {
                "event": "on_chat_model_stream",
                "name": "generate_section_2",
                "metadata": {"langgraph_node": "generate_section_2"},
                "data": {"chunk": _FakeChunk(content="<think>标签思考</think>正文片段", reasoning="思考片段")},
            }

        async def aget_state(self, config=None):
            return _Snapshot()

    async def fake_ensure_async_graph():
        return FakeAsyncGraph()

    @asynccontextmanager
    async def fake_thread_lock(dsn, thread_id):
        yield

    monkeypatch.setattr(
        "ai_hunter.app.api.routes_chat._ensure_async_graph", fake_ensure_async_graph
    )
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_chat.thread_advisory_lock", fake_thread_lock
    )

    client = TestClient(create_app())
    with client.stream(
        "POST",
        "/chat/invoke",
        json={
            "thread_id": "demo-stream",
            "query": "案件116出具完整审计报告",
            "current_case_id": 116,
            "stream": True,
        },
        headers={"accept": "text/event-stream"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: start" in body
    assert "event: node" in body
    assert "event: section_chunk" in body
    assert "event: section_reasoning_chunk" in body
    assert "event: final" in body
    assert "event: done" in body
    assert '"intent": "full_audit"' in body
    assert '"trace_items"' in body
    assert '"citation_coverage"' in body
    assert "正文片段" in body
    assert "思考片段" in body
    assert "标签思考" in body
    assert "<think>" not in body


def test_chat_invoke_rejects_blank_thread_id():
    client = TestClient(create_app())
    for blank in ("", "   "):
        response = client.post("/chat/invoke", json={"thread_id": blank, "query": "hi"})
        assert response.status_code == 422
        assert "thread_id" in response.text


def test_chat_invoke_registers_and_updates_thread_metadata(monkeypatch):
    from contextlib import asynccontextmanager

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    calls = []

    class FakeTenancyService:
        def ensure_thread_for_invoke(self, identity, thread_id, case_id):
            calls.append(("ensure", identity.user_id, thread_id, case_id))

        def update_thread_metadata(self, thread_id, *, last_intent="", title=""):
            calls.append(("update", thread_id, last_intent, title))

    class FakeGraph:
        def invoke(self, payload, config=None):
            return {
                "current_case_id": 116,
                "intent": "full_audit",
                "final_report": "最终报告",
            }

    @asynccontextmanager
    async def fake_thread_lock(dsn, thread_id):
        yield

    monkeypatch.setattr("ai_hunter.app.api.routes_chat.get_tenancy_service", lambda: FakeTenancyService())
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.thread_advisory_lock", fake_thread_lock)
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.graph", FakeGraph())
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="u_owner",
        company_id="co_1",
        roles=["project_manager"],
        authenticated=True,
    )

    response = TestClient(app).post(
        "/chat/invoke",
        json={
            "thread_id": "tenant-thread-1",
            "query": "案件116出具完整审计报告",
            "current_case_id": 116,
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert calls == [
        ("ensure", "u_owner", "tenant-thread-1", 116),
        ("update", "tenant-thread-1", "full_audit", "案件116出具完整审计报告"),
    ]


def test_chat_case_create_uses_unbound_thread_and_binds_created_case(monkeypatch):
    from contextlib import asynccontextmanager

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "router_execution_mode", "business_line")
    calls = []

    class FakeTenancyService:
        def ensure_thread_for_invoke(self, identity, thread_id, case_id, *, allow_unbound=False):
            calls.append(("ensure", thread_id, case_id, allow_unbound))

        def bind_thread_case(self, identity, thread_id, case_id):
            calls.append(("bind", identity.user_id, thread_id, case_id))

        def update_thread_metadata(self, thread_id, *, last_intent="", title=""):
            calls.append(("update", thread_id, last_intent, title))

    class FakeGraph:
        def invoke(self, payload, config=None):
            assert payload["identity_context"]["company_id"] == "co_1"
            assert "company_id" not in payload["write_command"]
            return {
                "current_case_id": 501,
                "current_debtor_id": 601,
                "current_debtor_name": "测试债务人",
                "intent": "drilldown",
                "route_decision": {
                    "route_version": "v2",
                    "business_line": "operator",
                    "capability": "case.create",
                    "intent": "drilldown",
                    "confidence": 0.99,
                    "needs_clarification": False,
                    "source": "rule",
                    "case_id": 501,
                    "action": "create",
                    "target_id": "",
                    "clarification_question": "",
                },
                "business_line_result": {"ok": True, "capability": "case.create"},
                "final_report": "案件已创建",
            }

    @asynccontextmanager
    async def fake_thread_lock(dsn, thread_id):
        yield

    service = FakeTenancyService()
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.get_tenancy_service", lambda: service)
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.thread_advisory_lock", fake_thread_lock)
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.graph", FakeGraph())
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="u_owner",
        company_id="co_1",
        roles=["project_manager"],
        authenticated=True,
    )

    response = TestClient(app).post(
        "/chat/invoke",
        json={
            "thread_id": "create-case-thread",
            "query": "创建案件",
            "write_command": {
                "capability": "case.create",
                "case_name": "测试案件",
                "debtor_name": "测试债务人",
            },
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["current_case_id"] == 501
    assert calls == [
        ("ensure", "create-case-thread", 0, True),
        ("bind", "u_owner", "create-case-thread", 501),
        ("update", "create-case-thread", "drilldown", "创建案件"),
    ]


def test_chat_rejects_query_case_switch_before_graph_execution(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)
    called = {"graph": False}

    class FakeTenancyService:
        def ensure_thread_for_invoke(self, identity, thread_id, case_id):
            assert case_id == 117
            from fastapi import HTTPException

            raise HTTPException(status_code=409, detail="会话已绑定其他案件，不能重新绑定")

    class FakeGraph:
        def invoke(self, payload, config=None):
            called["graph"] = True
            return {}

    monkeypatch.setattr(
        "ai_hunter.app.api.routes_chat.get_tenancy_service",
        lambda: FakeTenancyService(),
    )
    monkeypatch.setattr("ai_hunter.app.api.routes_chat.graph", FakeGraph())
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="u_owner",
        company_id="co_1",
        roles=["project_manager"],
        authenticated=True,
    )

    response = TestClient(app).post(
        "/chat/invoke",
        json={
            "thread_id": "case-116-thread",
            "query": "把案件117的任务28标记完成",
            "current_case_id": 116,
            "stream": False,
        },
    )

    assert response.status_code == 409
    assert called["graph"] is False


def test_thread_messages_returns_graph_context(monkeypatch):
    """issue #8: /chat/threads/{id}/messages 须回放图谱关联字段，刷新历史会话不丢上下文。"""

    class FakeConversationService:
        def get_thread_messages(self, thread_id):
            assert thread_id == "manual-review-1"
            return [
                {"role": "user", "content": "案件116出审计报告", "type": "human", "id": "t1_user"},
                {
                    "role": "assistant",
                    "content": "报告摘要",
                    "type": "ai",
                    "id": "t1_assistant",
                    "intent": "full_audit",
                    "final_report_ref": "final_report:demo-1",
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
                    "unresolved_claims": [{"claim_text": "甲为乙提供担保", "relation_key": "guarantee:A:B"}],
                },
            ]

    monkeypatch.setattr(
        "ai_hunter.app.api.routes_chat.get_conversation_service",
        lambda: FakeConversationService(),
    )

    client = TestClient(create_app())
    response = client.get("/chat/threads/manual-review-1/messages")
    assert response.status_code == 200
    body = response.json()
    assistant = next(m for m in body["messages"] if m["role"] == "assistant")
    assert assistant["intent"] == "full_audit"
    assert assistant["trace_items"][0]["claim_id"] == 31
    assert assistant["citation_coverage"]["cited_claims"] == 2
    assert assistant["unresolved_relations"][0]["relation_key"] == "guarantee:A:B"
    assert assistant["unresolved_claims"][0]["claim_text"] == "甲为乙提供担保"
    # user 消息的图谱字段回落为空，契约稳定
    user = next(m for m in body["messages"] if m["role"] == "user")
    assert user["trace_items"] == []
    assert user["citation_coverage"]["total_claims"] == 0
    assert user["unresolved_relations"] == []


def test_thread_messages_preserves_tenancy_403(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_enabled", True)

    class FakeTenancyService:
        def can_access_thread(self, identity, thread_id):
            assert identity.user_id == "u_member"
            assert thread_id == "other-thread"
            return False

    monkeypatch.setattr(
        "ai_hunter.app.auth.tenancy.get_tenancy_service",
        lambda: FakeTenancyService(),
    )
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="u_member",
        company_id="co_1",
        roles=["project_manager"],
        authenticated=True,
    )

    response = TestClient(app).get("/chat/threads/other-thread/messages")

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问该会话"


def test_sse_event_serializes_decimal_payload():
    frame = _sse_event("node", {"confidence": Decimal("0.91"), "count": Decimal("2")})

    assert "event: node" in frame
    assert '"confidence": 0.91' in frame
    assert '"count": 2' in frame
