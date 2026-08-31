"""Return a focused clarification question without invoking business tools."""

from ..state import AuditGraphState


def clarify_route(state: AuditGraphState) -> AuditGraphState:
    decision = state.get("route_decision") or {}
    question = decision.get("clarification_question", "") if isinstance(decision, dict) else ""
    if not question:
        question = "请说明您要处理的是案件材料、审计分析还是任务督办。"
    return {"agent_output": question}
