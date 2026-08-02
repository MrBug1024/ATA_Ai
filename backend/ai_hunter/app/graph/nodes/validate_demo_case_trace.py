"""Graph node wrapper for demo-case evidence trace validation."""

from __future__ import annotations

from ..state import AuditGraphState
from ...services.demo_case_trace_service import get_demo_case_trace_service


def validate_demo_case_trace(state: AuditGraphState) -> AuditGraphState:
    """Validate the current report's citation -> evidence -> anchor chain."""
    result = get_demo_case_trace_service().validate_report_trace(
        case_id=int(state.get("current_case_id", 0) or 0),
        report_ref=str(state.get("final_report_ref", "") or ""),
    )
    return {"demo_trace_validation": result.model_dump()}
