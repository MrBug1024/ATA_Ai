"""Compute Phase 2.5.1 route shadow metadata without executing business logic."""

from __future__ import annotations

import logging
from typing import Any

from .capabilities import capability_node_name, get_business_line_spec, get_capability_spec
from ..settings import get_settings


LOGGER = logging.getLogger(__name__)


def _decision_dict(decision: Any) -> dict[str, Any]:
    if hasattr(decision, "model_dump"):
        return decision.model_dump()
    return decision if isinstance(decision, dict) else {}


def build_route_shadow(decision: Any) -> dict[str, Any]:
    payload = _decision_dict(decision)
    capability = str(payload.get("capability") or "")
    spec = get_capability_spec(capability)
    line = get_business_line_spec(spec.business_line) if spec is not None else None
    configured_mode = get_settings().router_execution_mode

    if spec is None or line is None:
        shadow = {
            "phase": "2.5.4",
            "configured_mode": configured_mode,
            "active_mode": "legacy",
            "capability": capability,
            "shadow_business_logic_executed": False,
            "error": "unregistered route decision",
        }
        LOGGER.warning("route_shadow_invalid capability=%s", capability)
        return shadow

    needs_clarification = bool(payload.get("needs_clarification"))
    business_line_execution_enabled = bool(spec.business_line_executor)
    active_mode = (
        "business_line"
        if configured_mode == "business_line" and business_line_execution_enabled and not needs_clarification
        else "legacy"
    )
    legacy_target = "clarify_route" if needs_clarification else spec.executor
    business_line_target = "clarify_route" if needs_clarification else line.subgraph_node
    business_line_leaf = "clarify_route" if needs_clarification else capability_node_name(capability)
    target_differs = legacy_target != business_line_target
    shadow = {
        "phase": "2.5.4",
        "configured_mode": configured_mode,
        "active_mode": active_mode,
        "business_line": spec.business_line,
        "capability": capability,
        "access_mode": spec.access_mode,
        "legacy_target": legacy_target,
        "business_line_target": business_line_target,
        "business_line_leaf": business_line_leaf,
        "target_differs": target_differs,
        "business_line_execution_enabled": business_line_execution_enabled,
        "write_shadow_blocked": spec.access_mode == "write" and not business_line_execution_enabled,
        "shadow_business_logic_executed": False,
    }
    LOGGER.info(
        "route_shadow configured_mode=%s active_mode=%s business_line=%s capability=%s "
        "legacy_target=%s business_line_target=%s differs=%s write_blocked=%s",
        configured_mode,
        active_mode,
        spec.business_line,
        capability,
        legacy_target,
        business_line_target,
        target_differs,
        shadow["write_shadow_blocked"],
    )
    return shadow
