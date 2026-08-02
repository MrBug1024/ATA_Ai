import logging

from ..routers import resolve_route_decision
from ..route_shadow import build_route_shadow
from ..state import AuditGraphState


LOGGER = logging.getLogger(__name__)


def classify_intent(state: AuditGraphState) -> AuditGraphState:
    decision = resolve_route_decision(state)
    LOGGER.info(
        "route_decision version=%s business_line=%s capability=%s intent=%s confidence=%.2f source=%s clarify=%s",
        decision.route_version,
        decision.business_line,
        decision.capability,
        decision.intent,
        decision.confidence,
        decision.source,
        decision.needs_clarification,
    )
    return {
        "intent": decision.intent,
        "route_decision": decision.model_dump(),
        "route_shadow": build_route_shadow(decision),
    }


def intent_edge(state: AuditGraphState) -> str:
    decision = state.get("route_decision") or {}
    if isinstance(decision, dict) and decision.get("needs_clarification"):
        return "clarify"
    return state.get("intent", "drilldown")


def execution_route_edge(state: AuditGraphState) -> str:
    """Route migrated capabilities while keeping legacy ingestion single-pass."""
    decision = state.get("route_decision") or {}
    if isinstance(decision, dict) and decision.get("needs_clarification"):
        return "clarify"
    shadow = state.get("route_shadow") or {}
    if isinstance(shadow, dict) and shadow.get("active_mode") == "business_line":
        return str(shadow.get("business_line_target") or "drilldown")
    if (
        isinstance(decision, dict)
        and decision.get("capability") == "material.upload"
        and state.get("uploaded_files")
    ):
        return "finalize"
    return state.get("intent", "drilldown")
