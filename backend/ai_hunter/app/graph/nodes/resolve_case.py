import json

from ..routers import extract_case_id
from ..state import AuditGraphState


def _recover_case_id_from_context(state: AuditGraphState) -> int:
    """When current_case_id has been overwritten to 0 by a Pydantic default,
    try to recover it from previous-turn state fields."""
    full_context_summary = state.get("full_context_summary", "")
    if full_context_summary:
        try:
            summary = json.loads(full_context_summary)
            if isinstance(summary, dict):
                case_id = summary.get("case_id")
                if isinstance(case_id, int) and case_id > 0:
                    return case_id
        except (json.JSONDecodeError, ValueError):
            pass
    return 0


def resolve_case_context(state: AuditGraphState) -> AuditGraphState:
    query = state.get("query", "")
    current_case_id = state.get("current_case_id", 0)
    resolved_case_id = extract_case_id(query) or current_case_id

    # If the payload carried a Pydantic-default 0 and overwrote the checkpointer
    # value, recover from full_context_summary (written by full_audit turns).
    if not resolved_case_id:
        recovered = _recover_case_id_from_context(state)
        if recovered:
            resolved_case_id = recovered

    return {
        **state,
        "current_case_id": resolved_case_id,
    }
