from ..context_loader import resolve_final_report
from ..state import AuditGraphState
from ...settings import get_settings


def finalize_answer(state: AuditGraphState) -> AuditGraphState:
    final_report = resolve_final_report(state).strip()
    agent_output = state.get("agent_output", "").strip()
    response_text = agent_output or final_report
    if response_text:
        from ai_hunter.annual_audit.evidence_service import finalize_annual_answer

        # Every visible assistant response receives a fresh immutable payload
        # ref. This keeps one message's citation ids from resolving against a
        # later report in the same thread.
        return finalize_annual_answer(state, response_text)
    return {}
