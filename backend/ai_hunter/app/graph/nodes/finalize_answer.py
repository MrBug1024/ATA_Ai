from ..context_loader import resolve_final_report
from ..state import AuditGraphState


def finalize_answer(state: AuditGraphState) -> AuditGraphState:
    final_report = resolve_final_report(state).strip()
    agent_output = state.get("agent_output", "").strip()
    intent = state.get("intent", "")
    # full_audit and re_audit both produce a heavy report that is already persisted
    # to the heavy-payload store. Clear it from state to keep checkpoints lean.
    # drilldown (and any other intent) promotes agent_output to final_report so the
    # frontend can resolve the answer uniformly via resolve_final_report().
    if final_report and intent in ("full_audit", "re_audit", "review"):
        return {"final_report": "", "agent_output": ""}
    return {"final_report": agent_output}
