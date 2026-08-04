from ai_hunter.app.api.routes_chat import ChatRequest, _build_graph_input
from ai_hunter.app.main import create_app


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
