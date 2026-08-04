import logging

from ..routers import resolve_route_decision
from ..execution_route import build_execution_route
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
        "execution_route": build_execution_route(decision),
    }


def execution_route_edge(state: AuditGraphState) -> str:
    """Route every request through the annual-audit business-line graph."""
    decision = state.get("route_decision") or {}
    if isinstance(decision, dict) and decision.get("needs_clarification"):
        return "clarify"
    route = state.get("execution_route") or {}
    if isinstance(route, dict):
        return str(route.get("target") or "clarify_route")
    return "clarify_route"
