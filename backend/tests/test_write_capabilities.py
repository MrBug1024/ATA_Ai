from ai_hunter.app.auth.identity import Identity
from ai_hunter.app.graph.nodes.write_capabilities import (
    create_case_command,
    record_material_upload,
    write_task_command,
)


def _identity_context():
    return {
        "user_id": "u_owner",
        "username": "负责人",
        "company_id": "co_1",
        "roles": ["project_manager"],
        "authenticated": True,
    }


def test_create_case_command_stamps_server_identity(monkeypatch):
    captured = {}

    class _Cases:
        def create_case_sync(self, payload, *, identity=None):
            captured.update({"payload": payload, "identity": identity})
            return {"case_id": 501, "debtor_id": 601, "message": "案件已创建"}

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_case_api_client",
        lambda: _Cases(),
    )
    result = create_case_command(
        {
            "query": "创建案件",
            "write_command": {
                "case_name": "测试案件",
                "debtor_name": "测试债务人",
                "case_type": "单户",
            },
            "identity_context": _identity_context(),
            "route_decision": {"capability": "case.create"},
        }
    )

    assert result["business_line_result"]["ok"] is True
    assert result["current_case_id"] == 501
    assert result["current_debtor_id"] == 601
    assert captured["payload"]["debtor_name"] == "测试债务人"
    assert isinstance(captured["identity"], Identity)
    assert captured["identity"].company_id == "co_1"


def test_create_case_command_never_writes_without_identity(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_case_api_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not build client")),
    )
    result = create_case_command(
        {
            "write_command": {"case_name": "测试案件", "debtor_name": "测试债务人"},
            "route_decision": {"capability": "case.create"},
        }
    )

    assert result["business_line_result"]["ok"] is False
    assert result["business_line_result"]["error"] == "missing_identity_context"


def test_create_case_command_rejects_bound_case_before_upstream(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_case_api_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not build client")),
    )
    result = create_case_command(
        {
            "current_case_id": 116,
            "write_command": {"case_name": "测试案件", "debtor_name": "测试债务人"},
            "identity_context": _identity_context(),
            "route_decision": {"capability": "case.create"},
        }
    )

    assert result["business_line_result"]["ok"] is False
    assert result["business_line_result"]["error"] == "thread_already_bound_to_case"


def test_material_upload_command_only_records_existing_ingest_result():
    result = record_material_upload(
        {
            "current_case_id": 116,
            "uploaded_files": [{"name": "sample.txt", "file_hash": "sha"}],
            "upload_batch_id": "batch-1",
            "parse_summary": "材料已摄入",
            "records_inserted": 3,
            "recognized_categories": ["claim_material"],
            "identity_context": _identity_context(),
        }
    )

    business_result = result["business_line_result"]
    assert business_result["ok"] is True
    assert business_result["response"]["records_inserted"] == 3
    assert business_result["command"]["file_count"] == 1


def test_task_complete_validates_target_then_uses_update(monkeypatch):
    calls = []

    class _Tasks:
        def manage_sync(self, payload):
            calls.append(payload)
            if payload["action"] == "list":
                return {"tasks": [{"task_id": 28, "status": "进行中"}]}
            return {"task_id": 28, "new_status": "已完成", "message": "任务状态已更新"}

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_task_api_client",
        lambda: _Tasks(),
    )
    result = write_task_command(
        {
            "current_case_id": 116,
            "query": "把任务28标记完成",
            "route_decision": {"capability": "task.write", "action": "完成", "target_id": "28"},
            "identity_context": _identity_context(),
        }
    )

    assert result["business_line_result"]["ok"] is True
    assert calls == [
        {"case_id": 116, "action": "list"},
        {
            "case_id": 116,
            "action": "update",
            "task_id": 28,
            "new_status": "已完成",
            "completion_note": "",
        },
    ]


def test_task_write_rejects_target_outside_case_without_write(monkeypatch):
    calls = []

    class _Tasks:
        def manage_sync(self, payload):
            calls.append(payload)
            return {"tasks": [{"task_id": 27}]}

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_task_api_client",
        lambda: _Tasks(),
    )
    result = write_task_command(
        {
            "current_case_id": 116,
            "write_command": {"task_action": "assign", "task_id": 28, "assigned_to": "张律师"},
            "route_decision": {"capability": "task.write", "action": "assign", "target_id": "28"},
            "identity_context": _identity_context(),
        }
    )

    assert result["business_line_result"]["ok"] is False
    assert result["business_line_result"]["error"] == "task_not_found_in_case"
    assert calls == [{"case_id": 116, "action": "list"}]


def test_task_write_upstream_failure_is_not_retried(monkeypatch):
    calls = []

    class _Tasks:
        def create_batch_sync(self, case_id, tasks):
            calls.append((case_id, tasks))
            raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_task_api_client",
        lambda: _Tasks(),
    )
    result = write_task_command(
        {
            "current_case_id": 116,
            "write_command": {"task_action": "create", "task_title": "调取银行流水"},
            "route_decision": {"capability": "task.write", "action": "create"},
            "identity_context": _identity_context(),
        }
    )

    assert result["business_line_result"]["degraded"] is True
    assert result["business_line_result"]["error"] == "upstream_write_failed"
    assert len(calls) == 1


def test_task_write_rejects_permission_before_building_client(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.has_module",
        lambda _identity, _module: False,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_task_api_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not build client")),
    )

    result = write_task_command(
        {
            "current_case_id": 116,
            "write_command": {"task_action": "create", "task_title": "调取银行流水"},
            "route_decision": {"capability": "task.write", "action": "create"},
            "identity_context": _identity_context(),
        }
    )

    assert result["business_line_result"]["ok"] is False
    assert result["business_line_result"]["error"] == "permission_denied"
