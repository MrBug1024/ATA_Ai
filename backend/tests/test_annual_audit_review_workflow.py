from ai_hunter.app.graph.nodes.clarify_route import clarify_route
from ai_hunter.app.graph.routers import _review_confirmation_route


def test_no_issue_confirmation_moves_to_attachment_confirmation():
    decision = _review_confirmation_route(
        {
            "current_case_id": 7,
            "audit_review_stage": "awaiting_result_review",
            "query": "我确认没有问题",
        }
    )

    assert decision is not None
    assert decision.action == "confirm_audit_result"
    assert decision.needs_clarification is True
    next_state = clarify_route({"route_decision": decision.model_dump()})
    assert next_state["audit_review_stage"] == "awaiting_artifact_confirmation"
    assert "已激活的模板版本" in next_state["agent_output"]


def test_issue_confirmation_routes_to_reaudit():
    decision = _review_confirmation_route(
        {
            "current_case_id": 7,
            "audit_review_stage": "awaiting_result_review",
            "query": "收入截止性有问题，请继续审计",
        }
    )

    assert decision is not None
    assert decision.capability == "audit.reaudit"
    assert decision.action == "reaudit"


def test_attachment_confirmation_routes_to_the_existing_report_capability():
    decision = _review_confirmation_route(
        {
            "current_case_id": 7,
            "audit_review_stage": "awaiting_artifact_confirmation",
            "query": "确认生成附件",
        }
    )

    assert decision is not None
    assert decision.capability == "audit.full"
    assert decision.action == "generate_attachments"
