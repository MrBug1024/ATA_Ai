import pytest

from langgraph.checkpoint.memory import MemorySaver

from ai_hunter.app.graph.context_loader import resolve_final_report
from ai_hunter.app.graph.main import build_audit_orchestrator_graph
from ai_hunter.app.settings import get_settings


def invoke_with_thread(graph, payload: dict):
    return graph.invoke(payload, config={"configurable": {"thread_id": payload["thread_id"]}})


def _force_offline_graph(monkeypatch):
    settings = get_settings()
    original = {
        "langgraph_checkpointer": settings.langgraph_checkpointer,
        "openai_api_key": settings.openai_api_key,
        "minimax_api_key": settings.minimax_api_key,
        "kimi_api_key": settings.kimi_api_key,
        "faker_model_api_key": settings.faker_model_api_key,
        "router_execution_mode": settings.router_execution_mode,
    }

    settings.langgraph_checkpointer = "memory"
    settings.openai_api_key = ""
    settings.minimax_api_key = ""
    settings.kimi_api_key = ""
    settings.faker_model_api_key = ""
    settings.router_execution_mode = "legacy"
    monkeypatch.setattr("ai_hunter.app.graph.main.get_checkpointer", lambda: MemorySaver())
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_report._seed_recovery_forecast",
        lambda *args, **kwargs: None,
    )

    return settings, original


def _restore_settings(settings, original):
    for key, value in original.items():
        setattr(settings, key, value)


def test_main_graph_full_audit_flow(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(graph, {"thread_id": "t1", "query": "案件1出具完整报告"})
        # 八段式：离线时各段产出占位，reconcile 聚合为 final_report
        assert "段占位" in resolve_final_report(result)
    finally:
        _restore_settings(settings, original)


def test_main_graph_drilldown_flow(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(graph, {"thread_id": "t2", "query": "查看任务"})
        assert "追问/任务中枢占位" in result["final_report"]
        assert result["route_shadow"]["active_mode"] == "legacy"
        assert result["route_shadow"]["business_line_target"] == "supervision_subgraph"
        assert result["route_shadow"]["shadow_business_logic_executed"] is False
    finally:
        _restore_settings(settings, original)


def test_main_graph_clarifies_missing_upload(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(graph, {"thread_id": "t-clarify", "query": "给案件116上传卷宗"})

        assert result["route_decision"]["capability"] == "material.upload"
        assert result["route_decision"]["needs_clarification"] is True
        assert result["route_shadow"]["business_line_target"] == "clarify_route"
        assert result["route_shadow"]["write_shadow_blocked"] is False
        assert "请上传" in resolve_final_report(result)
    finally:
        _restore_settings(settings, original)


@pytest.mark.parametrize("execution_mode", ["legacy", "business_line"])
@pytest.mark.parametrize(
    ("query", "capability"),
    [
        ("请出具完整审计报告", "audit.full"),
        ("这个估值不对，按800万重审", "audit.reaudit"),
        ("做一次回款复盘", "recovery.review"),
    ],
)
def test_main_graph_clarifies_missing_case_before_specialized_execution(
    monkeypatch,
    execution_mode,
    query,
    capability,
):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = execution_mode
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {"thread_id": f"t-missing-case-{execution_mode}-{capability}", "query": query},
        )

        assert result["route_decision"]["capability"] == capability
        assert result["route_decision"]["needs_clarification"] is True
        assert result["route_shadow"]["legacy_target"] == "clarify_route"
        assert result["route_shadow"]["business_line_target"] == "clarify_route"
        assert resolve_final_report(result) == "请先提供要处理的案件编号。"
        assert not result.get("final_report_ref")
        assert not result.get("business_line_result")
        assert not result.get("user_corrections")
    finally:
        _restore_settings(settings, original)


def test_main_graph_business_line_mode_executes_migrated_read(monkeypatch):
    import ai_hunter.app.graph.nodes.read_only_capabilities as read_nodes

    settings, original = _force_offline_graph(monkeypatch)

    class FakeCaseProfileTool:
        def invoke(self, payload):
            assert payload == {"case_id": 116}
            return (
                '{"summary":"案件画像查询完成。","key_facts":{"case_id":116,"debtor":"晨光煤矿"},'
                '"truncated":false,"next_hint":""}'
            )

    monkeypatch.setattr(read_nodes, "get_case_profile", FakeCaseProfileTool())
    settings.router_execution_mode = "business_line"
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(graph, {"thread_id": "t-read-business", "query": "案件116"})

        assert result["route_shadow"]["active_mode"] == "business_line"
        assert result["route_shadow"]["business_line_leaf"] == "query_case_profile"
        assert result["business_line_result"]["capability"] == "case.profile"
        assert result["business_line_result"]["ok"] is True
        assert "案件画像查询完成" in result["final_report"]
    finally:
        _restore_settings(settings, original)


def test_main_graph_business_line_mode_executes_full_audit(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = "business_line"
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(graph, {"thread_id": "t-full-business", "query": "案件1出具完整报告"})

        assert result["route_shadow"]["active_mode"] == "business_line"
        assert result["route_shadow"]["business_line_leaf"] == "full_audit_graph"
        assert result["business_line_result"]["capability"] == "audit.full"
        assert result["business_line_result"]["ok"] is True
        assert result["audit_context"]["capability"] == "audit.full"
        assert result["audit_context"]["status"] == "completed"
        assert "段占位" in resolve_final_report(result)
    finally:
        _restore_settings(settings, original)


def test_main_graph_business_line_mode_executes_reaudit(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = "business_line"
    monkeypatch.setattr("ai_hunter.app.graph.nodes.corrections._persist_correction", lambda *args, **kwargs: None)
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {
                "thread_id": "t-reaudit-business",
                "query": "这个房产估值不对，按800万重审",
                "current_case_id": 116,
            },
        )

        assert result["route_shadow"]["active_mode"] == "business_line"
        assert result["route_shadow"]["business_line_leaf"] == "reaudit_graph"
        assert result["business_line_result"]["capability"] == "audit.reaudit"
        assert "800万" in "\n".join(result.get("user_corrections", []))
        assert result["audit_context"]["correction_count"] == 1
        assert "段占位" in resolve_final_report(result)
    finally:
        _restore_settings(settings, original)


def test_main_graph_business_line_mode_executes_review(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = "business_line"
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {"thread_id": "t-review-business", "query": "对案件116做回款复盘"},
        )

        assert result["route_shadow"]["active_mode"] == "business_line"
        assert result["route_shadow"]["business_line_leaf"] == "review_graph"
        assert result["business_line_result"]["capability"] == "recovery.review"
        assert result["supervision_context"]["status"] == "completed"
        assert "回款复盘报告" in resolve_final_report(result)
    finally:
        _restore_settings(settings, original)


def test_main_graph_business_line_mode_uses_graph_domain_agent(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = "business_line"
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {"thread_id": "t-graph-agent-business", "query": "案件116的资金流和企业穿透关系"},
        )

        assert result["route_shadow"]["active_mode"] == "business_line"
        assert result["route_shadow"]["business_line_leaf"] == "graph_query_agent"
        assert result["business_line_result"]["capability"] == "graph.query"
        assert result["business_line_result"]["degraded"] is True
        assert result["audit_context"]["status"] == "degraded"
        assert "图谱查询降级结果" in result["final_report"]
    finally:
        _restore_settings(settings, original)


def test_main_graph_business_line_mode_executes_case_create_command(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = "business_line"

    class _Cases:
        def create_case_sync(self, payload, *, identity=None):
            assert payload["case_name"] == "测试建案"
            assert identity.user_id == "u_owner"
            assert identity.company_id == "co_1"
            return {"case_id": 501, "debtor_id": 601, "message": "案件已创建"}

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_case_api_client",
        lambda: _Cases(),
    )
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {
                "thread_id": "t-create-case-business",
                "query": "创建案件",
                "write_command": {
                    "capability": "case.create",
                    "case_name": "测试建案",
                    "debtor_name": "测试债务人",
                },
                "identity_context": {
                    "user_id": "u_owner",
                    "company_id": "co_1",
                    "roles": ["project_manager"],
                },
            },
        )

        assert result["route_shadow"]["active_mode"] == "business_line"
        assert result["route_shadow"]["business_line_leaf"] == "create_case_command"
        assert result["business_line_result"]["ok"] is True
        assert result["current_case_id"] == 501
        assert result["operator_context"]["status"] == "completed"
    finally:
        _restore_settings(settings, original)


def test_main_graph_business_line_mode_executes_task_write_command(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = "business_line"
    calls = []

    class _Tasks:
        def manage_sync(self, payload):
            calls.append(payload)
            if payload["action"] == "list":
                return {"tasks": [{"task_id": 28}]}
            return {"task_id": 28, "new_status": "已完成", "message": "任务状态已更新"}

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.write_capabilities.get_task_api_client",
        lambda: _Tasks(),
    )
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {
                "thread_id": "t-task-write-business",
                "query": "把案件116的任务28标记完成",
                "current_case_id": 116,
                "identity_context": {
                    "user_id": "u_owner",
                    "company_id": "co_1",
                    "roles": ["project_manager"],
                    "authenticated": True,
                },
            },
        )

        assert result["route_shadow"]["active_mode"] == "business_line"
        assert result["route_shadow"]["business_line_leaf"] == "write_task_command"
        assert result["business_line_result"]["ok"] is True
        assert result["supervision_context"]["status"] == "completed"
        assert calls[-1]["action"] == "update"
        assert calls[-1]["new_status"] == "已完成"
    finally:
        _restore_settings(settings, original)


def test_main_graph_material_upload_records_pre_route_ingest_once(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    settings.router_execution_mode = "business_line"
    calls = []

    def fake_ingest(state):
        calls.append(list(state.get("uploaded_files") or []))
        return {
            "parse_summary": "材料已摄入",
            "records_inserted": 2,
            "recognized_categories": ["claim_material"],
        }

    monkeypatch.setattr("ai_hunter.app.graph.main.build_ingest_graph", lambda: fake_ingest)
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {
                "thread_id": "t-material-upload-business",
                "query": "上传案件116材料",
                "current_case_id": 116,
                "uploaded_files": [{"name": "sample.txt", "content": "sample"}],
                "identity_context": {
                    "user_id": "u_owner",
                    "company_id": "co_1",
                    "roles": ["project_manager"],
                    "authenticated": True,
                },
            },
        )

        assert len(calls) == 1
        assert result["route_decision"]["capability"] == "material.upload"
        assert result["route_shadow"]["business_line_leaf"] == "record_material_upload_command"
        assert result["business_line_result"]["ok"] is True
        assert result["business_line_result"]["response"]["records_inserted"] == 2
    finally:
        _restore_settings(settings, original)


def test_main_graph_legacy_material_upload_does_not_enter_agent(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    ingest_calls = []
    agent_calls = []

    def fake_ingest(state):
        ingest_calls.append(list(state.get("uploaded_files") or []))
        return {"parse_summary": "材料已摄入", "records_inserted": 2}

    def fake_agent(state):
        agent_calls.append(state)
        return {"agent_output": "unexpected agent execution"}

    monkeypatch.setattr("ai_hunter.app.graph.main.build_ingest_graph", lambda: fake_ingest)
    monkeypatch.setattr("ai_hunter.app.graph.main.build_drilldown_agent_node", lambda: fake_agent)
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {
                "thread_id": "t-material-upload-legacy",
                "query": "上传案件116材料",
                "current_case_id": 116,
                "uploaded_files": [{"name": "sample.txt", "content": "sample"}],
            },
        )

        assert len(ingest_calls) == 1
        assert agent_calls == []
        assert result["route_shadow"]["active_mode"] == "legacy"
        assert result["final_report"] == "材料已摄入"
    finally:
        _restore_settings(settings, original)


def test_main_graph_reaudit_flow(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    try:
        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(
            graph,
            {"thread_id": "t3", "query": "这个房产估值不对，按800万重审", "current_case_id": 116},
        )
        # 修正请求经 extract_correction 落到 user_corrections，再驱动 full_audit 重跑
        assert "800万" in "\n".join(result.get("user_corrections", []))
    finally:
        _restore_settings(settings, original)


def test_main_graph_full_audit_hydrates_case_graph_without_upload(monkeypatch):
    settings, original = _force_offline_graph(monkeypatch)
    try:
        class _FakeKgService:
            def fetch_case_graph_snapshot(self, case_id: int) -> dict:
                assert case_id == 116
                return {
                    "entity_count": 2,
                    "relation_count": 1,
                    "claim_count": 1,
                    "evidence_count": 1,
                    "entities": [
                        {"id": 1, "canonical_name": "晨光煤矿", "entity_type": "company"},
                    ],
                    "relations": [
                        {
                            "id": 10,
                            "relation_type": "owns_asset",
                            "relation_label": "持有资产",
                            "confidence": 0.91,
                            "from_entity_id": 1,
                            "to_entity_id": 2,
                            "from_name": "晨光煤矿",
                            "to_name": "采矿权",
                        }
                    ],
                    "claims": [
                        {
                            "id": 100,
                            "claim_type": "asset",
                            "claim_text": "晨光煤矿名下存在采矿权资产。",
                            "confidence": 0.96,
                        }
                    ],
                    "claim_traces": [
                        {
                            "claim_id": 100,
                            "claim_type": "asset",
                            "claim_text": "晨光煤矿名下存在采矿权资产。",
                            "confidence": 0.96,
                            "evidences": [
                                {
                                    "chunk_id": "chunk-1",
                                    "file_id": 9,
                                    "file_name": "4.晨光煤矿二债会资料.pdf",
                                    "page_no": 3,
                                    "quote_text": "采矿许可证记载晨光煤矿拥有采矿权。",
                                    "bbox_list": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4}],
                                    "page_image_ref": "minio://page-3.png",
                                    "source_page_id": 33,
                                }
                            ],
                        }
                    ],
                }

        monkeypatch.setattr(
            "ai_hunter.app.graph.nodes.hydrate_case_graph.get_kg_service",
            lambda: _FakeKgService(),
        )

        graph = build_audit_orchestrator_graph()
        result = invoke_with_thread(graph, {"thread_id": "t4", "query": "案件116全面审计"})

        final_report = resolve_final_report(result)
        assert "### 【知识图谱证据追溯】" in final_report
        assert result.get("kg_subgraph_ref")
        assert "实体2个" in (result.get("kg_summary") or "")
        assert result.get("trace_items")
        assert result["trace_items"][0]["claim_text"] == "晨光煤矿名下存在采矿权资产。"
    finally:
        _restore_settings(settings, original)
