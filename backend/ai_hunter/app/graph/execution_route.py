"""Resolve one annual-audit capability to its business-line subgraph."""

from __future__ import annotations

from typing import Any

from .capabilities import capability_node_name, get_business_line_spec, get_capability_spec


def _decision_dict(decision: Any) -> dict[str, Any]:
    if hasattr(decision, "model_dump"):
        return decision.model_dump()
    return decision if isinstance(decision, dict) else {}


def build_execution_route(decision: Any) -> dict[str, Any]:
    payload = _decision_dict(decision)
    capability = str(payload.get("capability") or "")
    spec = get_capability_spec(capability)
    line = get_business_line_spec(spec.business_line) if spec is not None else None
    if spec is None or line is None:
        return {
            "mode": "annual_audit",
            "capability": capability,
            "target": "clarify_route",
            "error": "unregistered annual-audit capability",
        }

    needs_clarification = bool(payload.get("needs_clarification"))
    return {
        "mode": "annual_audit",
        "business_line": spec.business_line,
        "capability": capability,
        "access_mode": spec.access_mode,
        "target": "clarify_route" if needs_clarification else line.subgraph_node,
        "capability_node": (
            "clarify_route" if needs_clarification else capability_node_name(capability)
        ),
    }
