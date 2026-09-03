from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from ai_hunter.annual_audit import report_graph
from ai_hunter.annual_audit.attachments import job_service
from ai_hunter.app.api import routes_artifacts
from ai_hunter.app.auth.identity import Identity, get_current_identity
from ai_hunter.app.graph.nodes import memory
from ai_hunter.app.graph.nodes.normalize_input import normalize_input
from ai_hunter.app.repositories.conversation_message_repo import (
    ConversationMessageRepository,
)


class _ConversationRepo:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append_messages(self, thread_id: str, entries: list[dict]) -> int:
        for entry in entries:
            self.rows.append(
                {
                    "thread_id": thread_id,
                    "turn_id": entry["id"],
                    "role": entry["role"],
                    "content": entry["content"],
                    "intent": entry.get("intent"),
                    "case_id": entry.get("case_id"),
                    "final_report_ref": entry.get("final_report_ref", ""),
                    "uploaded_files": entry.get("uploaded_files", []),
                    "graph_context": entry.get("graph_context", {}),
                    "version": entry.get("version", 1),
                    "created_at": len(self.rows) + 1,
                }
            )
        return len(entries)

    def get_messages(self, thread_id: str, *, conn=None) -> list[dict]:
        return [row for row in self.rows if row["thread_id"] == thread_id]

    def get_max_assistant_version(self, _thread_id: str, _turn_id: str) -> int:
        return 0


def _turn_state(*, query: str, client_turn_id: str, attachment_job: dict) -> dict:
    return {
        "thread_id": "thread-annual-1",
        "query": query,
        "client_turn_id": client_turn_id,
        "current_case_id": 7,
        "current_entity_id": 70,
        "current_entity_name": "示例公司",
        "messages": [],
        "intent": "drilldown",
        "agent_output": f"{query} 的回复",
        "attachment_job": attachment_job,
    }


def test_normalize_input_resets_attachment_job_on_every_turn_and_case_switch() -> None:
    stale_job = {"job_id": "job-from-prior-turn", "case_id": 7}

    same_case = normalize_input(
        _turn_state(query="继续分析", client_turn_id="turn-2", attachment_job=stale_job)
    )
    switched_case = normalize_input(
        {
            **_turn_state(
                query="切换到年审项目 8",
                client_turn_id="turn-3",
                attachment_job=stale_job,
            ),
            "current_case_id": 7,
        }
    )

    assert same_case["attachment_job"] == {}
    assert switched_case["case_switched"] is True
    assert switched_case["current_case_id"] == 8
    assert switched_case["attachment_job"] == {}


def test_consecutive_turn_refresh_keeps_attachment_job_bound_to_exact_reply(
    monkeypatch,
) -> None:
    repo = _ConversationRepo()
    monkeypatch.setattr(memory, "get_conversation_message_repo", lambda: repo)
    monkeypatch.setattr(
        memory,
        "get_settings",
        lambda: SimpleNamespace(langgraph_memory_max_tokens=20_000),
    )

    first_state = _turn_state(
        query="生成年审报告",
        client_turn_id="turn-1",
        attachment_job={"job_id": "job-1", "case_id": 7},
    )
    memory.persist_conversation_memory(first_state)

    second_state = normalize_input(
        {
            **first_state,
            "query": "解释上一条结论",
            "client_turn_id": "turn-2",
            "messages": [
                HumanMessage(content=first_state["query"]),
                AIMessage(content=first_state["agent_output"]),
            ],
        }
    )
    second_state.update(
        {
            "current_case_id": 7,
            "intent": "drilldown",
            "agent_output": "这是第二轮解释，没有创建附件任务。",
        }
    )
    memory.persist_conversation_memory(second_state)

    refreshed_turns = ConversationMessageRepository.get_turns(
        repo,
        "thread-annual-1",
    )
    first_context = refreshed_turns[0]["assistants"][0]["graph_context"]
    second_context = refreshed_turns[1]["assistants"][0]["graph_context"]

    assert first_context["attachment_job"]["job_id"] == "job-1"
    assert second_context["attachment_job"] == {}


def _artifact_client(monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(routes_artifacts.router)
    app.dependency_overrides[get_current_identity] = Identity.admin
    monkeypatch.setattr(routes_artifacts, "require_case_access", lambda *_args: None)
    return TestClient(app)


@pytest.mark.parametrize("server_owned_field", ["thread_id", "assistant_turn_id"])
def test_public_attachment_create_rejects_conversation_binding_fields(
    monkeypatch,
    server_owned_field: str,
) -> None:
    client = _artifact_client(monkeypatch)

    response = client.post(
        "/api/annual-audit/7/attachment-jobs",
        json={"report_id": 12, server_owned_field: "caller-controlled"},
    )

    assert response.status_code == 422
    assert any(
        error["type"] == "extra_forbidden"
        and error["loc"][-1] == server_owned_field
        for error in response.json()["detail"]
    )


def test_public_attachment_create_does_not_patch_a_conversation(
    monkeypatch,
) -> None:
    captured: dict = {}

    def fake_create_job(**kwargs):
        captured.update(kwargs)
        return {"attachment_job": {"job_id": "job-public", "case_id": 7}}

    monkeypatch.setattr(job_service, "create_attachment_job", fake_create_job)
    monkeypatch.setattr(job_service, "dispatch_pending_outbox", lambda **_kwargs: 1)
    client = _artifact_client(monkeypatch)

    response = client.post(
        "/api/annual-audit/7/attachment-jobs",
        json={"report_id": 12, "idempotency_key": "public-request-1"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["attachment_job"]["job_id"] == "job-public"
    assert "thread_id" not in captured
    assert "assistant_turn_id" not in captured


def _report_result(*, report_id: int = 12) -> dict:
    return {
        "report_text": "# 年度审计报告草稿",
        "artifacts": {
            "report": {"id": report_id, "version": 3},
            "workpapers": [],
            "tasks": {"created_count": 0},
        },
        "response_trace_candidates": [],
        "response_citation_coverage": {},
        "citation_entries": [],
        "annual_report_manifest": {},
    }


def test_report_graph_keeps_internal_derived_conversation_binding(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(report_graph, "generate_annual_report_draft", lambda *_args, **_kwargs: _report_result())

    def fake_create_job(**kwargs):
        captured.update(kwargs)
        return {
            "attachment_job": {
                "job_id": "job-internal",
                "case_id": 7,
                "assistant_turn_id": kwargs["assistant_turn_id"],
            }
        }

    monkeypatch.setattr(job_service, "create_attachment_job", fake_create_job)
    monkeypatch.setattr(job_service, "dispatch_pending_outbox", lambda **_kwargs: 1)

    result = report_graph.generate_annual_report_node(
        {
            "thread_id": "thread-internal",
            "client_turn_id": "client-turn-1",
            "query": "生成年审报告",
            "current_case_id": 7,
            "intent": "full_audit",
            "operator_id": "auditor-1",
            "messages": [],
        }
    )

    assert captured["thread_id"] == "thread-internal"
    assert captured["assistant_turn_id"].endswith("_assistant")
    assert result["attachment_job"]["job_id"] == "job-internal"


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    [
        (
            job_service.AttachmentJobError(
                "NO_ACTIVE_TEMPLATE",
                "年度审计当前没有已激活模板",
                status_code=409,
            ),
            "当前没有可用于生成附件的已激活模板",
        ),
        (
            job_service.AttachmentJobError(
                "FINANCIAL_STATEMENTS_BLOCKED",
                "internal message must not be displayed",
                status_code=409,
            ),
            "用于生成附件的财务报表及附注尚未满足条件",
        ),
        (RuntimeError("database password must not leak"), "附件任务服务当前不可用"),
    ],
)
def test_report_graph_explains_automatic_attachment_acceptance_failure(
    monkeypatch,
    failure: Exception,
    expected_reason: str,
) -> None:
    monkeypatch.setattr(report_graph, "generate_annual_report_draft", lambda *_args, **_kwargs: _report_result())

    def fail_create_job(**_kwargs):
        raise failure

    monkeypatch.setattr(job_service, "create_attachment_job", fail_create_job)

    result = report_graph.generate_annual_report_node(
        {
            "thread_id": "thread-failure",
            "client_turn_id": "client-turn-failure",
            "query": "生成年审报告",
            "current_case_id": 7,
            "intent": "full_audit",
            "messages": [],
        }
    )

    assert result["attachment_job"] == {}
    assert "附件暂未生成" in result["agent_output"]
    assert expected_reason in result["agent_output"]
    assert "重新生成附件" in result["agent_output"]
    if isinstance(failure, job_service.AttachmentJobError):
        assert failure.code not in result["agent_output"]
        assert str(failure) not in result["agent_output"]
    assert "database password must not leak" not in result["agent_output"]


def test_report_graph_never_presents_a_missing_job_reference_as_accepted(
    monkeypatch,
) -> None:
    monkeypatch.setattr(report_graph, "generate_annual_report_draft", lambda *_args, **_kwargs: _report_result())
    monkeypatch.setattr(job_service, "create_attachment_job", lambda **_kwargs: {})

    result = report_graph.generate_annual_report_node(
        {
            "thread_id": "thread-missing-ref",
            "client_turn_id": "client-turn-missing-ref",
            "query": "生成年审报告",
            "current_case_id": 7,
            "intent": "full_audit",
            "messages": [],
        }
    )

    assert result["attachment_job"] == {}
    assert "附件生成未受理" not in result["agent_output"]
    assert "附件任务服务当前不可用" in result["agent_output"]
