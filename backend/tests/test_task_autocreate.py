import pytest

import ai_hunter.app.graph.nodes.create_tasks as task_nodes
from ai_hunter.app.settings import get_settings
from ai_hunter.app.subgraphs.business_line_graphs import audit_analysis_completion_edge


@pytest.mark.parametrize(
    ("enabled", "tasks", "expected"),
    [
        (True, [{"action": "取得银行函证"}], "create"),
        (False, [{"action": "取得银行函证"}], "skip"),
        (True, [], "skip"),
    ],
)
def test_should_create_tasks_respects_feature_flag(monkeypatch, enabled, tasks, expected):
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", enabled)
    assert task_nodes.should_create_tasks({"extracted_tasks": tasks}) == expected


def test_create_tasks_does_not_write_when_autocreate_is_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", False)
    result = task_nodes.create_tasks(
        {"current_case_id": 7, "extracted_tasks": [{"action": "检查收入截止性"}]}
    )
    assert result["task_create_result"] == {
        "created": 0,
        "skipped": 1,
        "status": "autocreate_disabled",
    }


def test_create_tasks_uses_annual_task_repository(monkeypatch):
    calls = []
    tasks = [{"action": "检查收入截止性"}]
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", True)
    monkeypatch.setattr(
        task_nodes,
        "create_task_batch",
        lambda case_id, rows: calls.append((case_id, rows)) or {"created": 1, "status": "created"},
    )
    result = task_nodes.create_tasks({"current_case_id": 7, "extracted_tasks": tasks})
    assert calls == [(7, tasks)]
    assert result["task_create_result"] == {"created": 1, "status": "created"}


@pytest.mark.parametrize(("enabled", "expected"), [(True, "create"), (False, "finalize")])
@pytest.mark.parametrize("capability", ["audit.full", "audit.reaudit"])
def test_post_audit_edge_respects_feature_flag(monkeypatch, enabled, expected, capability):
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", enabled)
    state = {"route_decision": {"capability": capability}, "extracted_tasks": [{"action": "复核"}]}
    assert audit_analysis_completion_edge(state) == expected
