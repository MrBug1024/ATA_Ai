import pytest
from pydantic import ValidationError

from ai_hunter.app.graph.schemas import WriteCommandModel
from ai_hunter.app.graph.write_contracts import (
    resolve_case_create_command,
    resolve_task_write_command,
)


def test_case_create_contract_prefers_structured_fields_over_query_labels():
    payload, missing = resolve_case_create_command(
        {
            "query": "创建案件，案件名称：旧名称，债务人：旧债务人",
            "write_command": {
                "case_name": "结构化案件",
                "debtor_name": "结构化债务人",
                "case_type": "单户",
            },
        }
    )

    assert missing == []
    assert payload["case_name"] == "结构化案件"
    assert payload["debtor_name"] == "结构化债务人"
    assert payload["case_type"] == "单户"


def test_task_contract_maps_complete_to_supported_update_status():
    payload, missing = resolve_task_write_command(
        {"query": "把案件116任务28标记完成，备注：材料已提交"},
        {"action": "完成", "target_id": "28"},
    )

    assert missing == []
    assert payload["action"] == "complete"
    assert payload["task_id"] == 28
    assert payload["new_status"] == "已完成"
    assert payload["completion_note"] == "材料已提交"


def test_write_command_schema_rejects_unknown_fields_and_status():
    with pytest.raises(ValidationError):
        WriteCommandModel(capability="task.write", unknown="value")
    with pytest.raises(ValidationError):
        WriteCommandModel(capability="task.write", new_status="随便写")
