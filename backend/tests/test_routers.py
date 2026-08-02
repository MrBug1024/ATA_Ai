import pytest

from ai_hunter.app.graph.routers import extract_case_id, resolve_route_decision, route_intent
from ai_hunter.app.graph.schemas import RouteDecisionModel


def test_extract_case_id_from_numeric_query():
    assert extract_case_id("116") == 116


def test_route_case_number_alone_opens_profile_not_full_audit():
    decision = resolve_route_decision({"query": "案件116"})

    assert decision.business_line == "operator"
    assert decision.capability == "case.profile"
    assert decision.intent == "drilldown"
    assert decision.case_id == 116


def test_route_drilldown_from_task_query():
    assert route_intent({"query": "查看任务"}) == "drilldown"


def test_route_drilldown_by_default_on_greeting():
    decision = resolve_route_decision({"query": "你好"})

    assert decision.capability == "common.general"
    assert decision.intent == "drilldown"


def test_route_reaudit_from_correction_query():
    assert route_intent({"query": "这个房产估值不对，按800万重审", "current_case_id": 116}) == "re_audit"


def test_route_followup_after_report_is_drilldown():
    state = {"query": "债权端：47笔申报债权、10位保证人", "final_report_ref": "final_report:abc"}
    assert route_intent(state) == "drilldown"


def test_route_case_id_followup_after_report_is_drilldown():
    state = {"query": "案件116的债权端情况", "report_section_refs": {"2": "report_section:x"}}
    assert route_intent(state) == "drilldown"


def test_route_explicit_full_report_still_full_audit_with_existing_report():
    state = {"query": "再出一份完整报告", "current_case_id": 116, "final_report_ref": "final_report:abc"}
    assert route_intent(state) == "full_audit"


def test_route_explicit_first_audit_still_full_audit():
    assert route_intent({"query": "案件116全面审计"}) == "full_audit"
    assert route_intent({"query": "案件116重新审计"}) == "full_audit"
    assert route_intent({"query": "案件116走全流程"}) == "full_audit"


def test_route_review_from_keyword():
    assert route_intent({"query": "对案件116做回款复盘"}) == "review"
    assert route_intent({"query": "把预期和实际回款对账一下", "current_case_id": 116}) == "review"


def test_route_review_wins_over_existing_report():
    state = {"query": "做个回款复盘", "current_case_id": 116, "final_report_ref": "final_report:abc"}
    assert route_intent(state) == "review"


@pytest.mark.parametrize(
    ("query", "capability"),
    [
        ("请出具完整审计报告", "audit.full"),
        ("这个估值不对，按800万重审", "audit.reaudit"),
        ("做一次回款复盘", "recovery.review"),
    ],
)
def test_case_bound_capability_without_case_requires_clarification(query, capability):
    decision = resolve_route_decision({"query": query, "current_case_id": 0})

    assert decision.capability == capability
    assert decision.case_id is None
    assert decision.needs_clarification is True
    assert decision.clarification_question == "请先提供要处理的案件编号。"


@pytest.mark.parametrize(
    "query",
    ["请出具完整审计报告", "这个估值不对，按800万重审", "做一次回款复盘"],
)
def test_case_bound_capability_uses_thread_case_context(query):
    decision = resolve_route_decision({"query": query, "current_case_id": 116})

    assert decision.case_id == 116
    assert decision.needs_clarification is False


def test_route_reaudit_wins_over_generic_query_phrase():
    decision = resolve_route_decision({"query": "查一下这个房产估值不对，按800万重审", "current_case_id": 116})

    assert decision.capability == "audit.reaudit"
    assert decision.intent == "re_audit"


def test_route_negation_does_not_trigger_reaudit_or_full_audit():
    drilldown = resolve_route_decision({"query": "案件116不要重审，只查一下估值"})
    graph = resolve_route_decision({"query": "案件116不用完整报告，只看资金流"})
    no_regenerate = resolve_route_decision({"query": "案件116不用重新审计，只查估值"})

    assert drilldown.capability == "audit.drilldown"
    assert graph.capability == "graph.query"
    assert no_regenerate.capability == "audit.drilldown"


def test_route_task_query_and_write_are_distinct():
    query_decision = resolve_route_decision({"query": "查看案件116的任务"})
    write_decision = resolve_route_decision({"query": "把案件116的任务28标记完成"})

    assert query_decision.capability == "task.query"
    assert write_decision.capability == "task.write"
    assert write_decision.target_id == "28"
    assert write_decision.needs_clarification is False


def test_route_task_write_without_target_requires_clarification():
    decision = resolve_route_decision({"query": "把这个任务标记完成", "current_case_id": 116})

    assert decision.capability == "task.write"
    assert decision.needs_clarification is True
    assert "任务编号" in decision.clarification_question


def test_route_material_upload_without_attachment_requires_clarification():
    decision = resolve_route_decision({"query": "给案件116上传卷宗"})

    assert decision.business_line == "operator"
    assert decision.capability == "material.upload"
    assert decision.needs_clarification is True


def test_uploaded_files_route_to_material_upload_command():
    decision = resolve_route_decision(
        {
            "query": "上传完成后处理材料",
            "current_case_id": 116,
            "uploaded_files": [{"name": "sample.txt", "content": "text"}],
        }
    )

    assert decision.capability == "material.upload"
    assert decision.action == "upload"
    assert decision.needs_clarification is False


def test_case_create_requires_slots_and_accepts_structured_command():
    missing = resolve_route_decision({"query": "创建案件"})
    complete = resolve_route_decision(
        {
            "query": "创建案件",
            "write_command": {
                "capability": "case.create",
                "case_name": "晨光煤矿测试案件",
                "debtor_name": "钟山区老鹰山镇晨光煤矿",
            },
        }
    )

    assert missing.capability == "case.create"
    assert missing.needs_clarification is True
    assert "案件名称" in missing.clarification_question
    assert complete.capability == "case.create"
    assert complete.needs_clarification is False


def test_case_create_rejects_existing_case_context():
    decision = resolve_route_decision(
        {
            "query": "创建案件",
            "current_case_id": 116,
            "write_command": {
                "capability": "case.create",
                "case_name": "测试案件",
                "debtor_name": "测试债务人",
            },
        }
    )

    assert decision.capability == "case.create"
    assert decision.needs_clarification is True
    assert decision.case_id == 116
    assert "新的未绑定会话" in decision.clarification_question


def test_structured_task_assign_requires_assignee():
    missing = resolve_route_decision(
        {
            "query": "操作案件116任务28",
            "current_case_id": 116,
            "write_command": {
                "capability": "task.write",
                "task_action": "assign",
                "task_id": 28,
            },
        }
    )
    complete = resolve_route_decision(
        {
            "query": "操作案件116任务28",
            "current_case_id": 116,
            "write_command": {
                "capability": "task.write",
                "task_action": "assign",
                "task_id": 28,
                "assigned_to": "张律师",
            },
        }
    )

    assert missing.needs_clarification is True
    assert "被指派人" in missing.clarification_question
    assert complete.needs_clarification is False
    assert complete.target_id == "28"


def test_route_domain_capabilities():
    cases = {
        "查看案件116的司法时效红黄绿": ("supervision", "deadline.query"),
        "案件116的资金流和企业穿透关系": ("audit_analysis", "graph.query"),
        "查看案件116卷宗中的证据原文": ("audit_analysis", "evidence.resolve"),
        "找几个采矿权抵押无效的相似案件": ("audit_analysis", "caselaw.search"),
        "案件116还缺什么材料": ("operator", "material.validate"),
    }

    for query, expected in cases.items():
        decision = resolve_route_decision({"query": query})
        assert (decision.business_line, decision.capability) == expected


def test_route_generic_legal_writ_requires_clarification(monkeypatch):
    monkeypatch.setattr("ai_hunter.app.graph.routers.build_router_llm", lambda: object())
    monkeypatch.setattr("ai_hunter.app.graph.routers.has_api_key", lambda _llm: False)

    decision = resolve_route_decision({"query": "帮我查一下裁判文书"})

    assert decision.capability == "clarify"
    assert decision.needs_clarification is True


def test_route_model_fallback_is_normalized(monkeypatch):
    class FakeStructured:
        def invoke(self, _messages):
            return RouteDecisionModel(
                business_line="common",
                capability="graph.query",
                confidence=0.91,
                case_id=116,
                action="query",
            )

    class FakeLlm:
        def with_structured_output(self, _schema):
            return FakeStructured()

    monkeypatch.setattr("ai_hunter.app.graph.routers.build_router_llm", lambda: FakeLlm())
    monkeypatch.setattr("ai_hunter.app.graph.routers.has_api_key", lambda _llm: True)

    decision = resolve_route_decision({"query": "帮我看看主体之间是怎么关联的"})

    assert decision.business_line == "audit_analysis"
    assert decision.capability == "graph.query"
    assert decision.source == "model"


def test_route_model_case_bound_capability_without_case_requires_clarification(monkeypatch):
    class FakeStructured:
        def invoke(self, _messages):
            return RouteDecisionModel(
                business_line="audit_analysis",
                capability="audit.full",
                confidence=0.93,
            )

    class FakeLlm:
        def with_structured_output(self, _schema):
            return FakeStructured()

    monkeypatch.setattr("ai_hunter.app.graph.routers.build_router_llm", lambda: FakeLlm())
    monkeypatch.setattr("ai_hunter.app.graph.routers.has_api_key", lambda _llm: True)

    decision = resolve_route_decision({"query": "请生成整体成果"})

    assert decision.capability == "audit.full"
    assert decision.source == "model"
    assert decision.needs_clarification is True
    assert decision.clarification_question == "请先提供要处理的案件编号。"


def test_route_model_unavailable_falls_back_to_clarification(monkeypatch):
    monkeypatch.setattr("ai_hunter.app.graph.routers.build_router_llm", lambda: object())
    monkeypatch.setattr("ai_hunter.app.graph.routers.has_api_key", lambda _llm: False)

    decision = resolve_route_decision({"query": "帮我处理一下"})

    assert decision.capability == "clarify"
    assert decision.needs_clarification is True
    assert decision.source == "fallback"
