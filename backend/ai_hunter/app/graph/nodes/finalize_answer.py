from ..context_loader import resolve_final_report
from ..state import AuditGraphState
from ...response_safety import friendly_no_result_response, sanitize_user_response
from ...settings import get_settings


def finalize_answer(state: AuditGraphState) -> AuditGraphState:
    final_report = resolve_final_report(state).strip()
    agent_output = state.get("agent_output", "").strip()
    response_text = agent_output or final_report or state.get("final_report_summary", "")
    response_text = sanitize_user_response(
        response_text,
        fallback=friendly_no_result_response(state),
    )

    from ai_hunter.annual_audit.evidence_service import finalize_annual_answer

    # Every visible assistant response receives a fresh immutable payload
    # ref. This keeps one message's citation ids from resolving against a
    # later report in the same thread. Even a failed/empty node gets a
    # human-readable response rather than exposing orchestration metadata.
    return finalize_annual_answer(state, response_text)
