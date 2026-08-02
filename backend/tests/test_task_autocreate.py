import pytest

import ai_hunter.app.graph.nodes.create_tasks as task_nodes
from ai_hunter.app.settings import get_settings
from ai_hunter.app.subgraphs.business_line_graphs import audit_analysis_completion_edge


@pytest.mark.parametrize(
    ("enabled", "tasks", "expected"),
    [
        (True, [{"action": "调取流水"}], "create"),
        (False, [{"action": "调取流水"}], "skip"),
        (True, [], "skip"),
    ],
)
def test_should_create_tasks_respects_feature_flag(monkeypatch, enabled, tasks, expected):
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", enabled)

    assert task_nodes.should_create_tasks({"extracted_tasks": tasks}) == expected


def test_create_tasks_does_not_call_api_when_autocreate_is_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", False)
    monkeypatch.setattr(
        task_nodes,
        "get_task_api_client",
        lambda: pytest.fail("task API must not be resolved when autocreate is disabled"),
    )

    result = task_nodes.create_tasks(
        {
            "current_case_id": 116,
            "extracted_tasks": [{"action": "调取流水"}, {"action": "核验抵押"}],
        }
    )

    assert result["task_create_result"] == {
        "created": 0,
        "skipped": 2,
        "status": "autocreate_disabled",
    }


def test_create_tasks_calls_api_when_autocreate_is_enabled(monkeypatch):
    calls = []

    class FakeTaskClient:
        def create_batch_sync(self, case_id, tasks):
            calls.append((case_id, tasks))
            return {"created": len(tasks), "status": "created"}

    tasks = [{"action": "调取流水"}]
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", True)
    monkeypatch.setattr(task_nodes, "get_task_api_client", lambda: FakeTaskClient())

    result = task_nodes.create_tasks({"current_case_id": 116, "extracted_tasks": tasks})

    assert calls == [(116, tasks)]
    assert result["task_create_result"] == {"created": 1, "status": "created"}


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [
        (True, "create"),
        (False, "finalize"),
    ],
)
@pytest.mark.parametrize("capability", ["audit.full", "audit.reaudit"])
def test_business_line_post_audit_edge_respects_feature_flag(monkeypatch, enabled, expected, capability):
    monkeypatch.setattr(get_settings(), "enable_task_autocreate", enabled)
    state = {
        "route_decision": {"capability": capability},
        "extracted_tasks": [{"action": "调取流水"}],
    }

    assert audit_analysis_completion_edge(state) == expected
