"""User-facing response safeguards for the annual-audit chat.

The graph carries routing and execution metadata alongside the answer.  That
metadata is useful for logs and evidence drawers, but it must never become the
assistant's visible reply when a node forgets to produce prose.
"""

from __future__ import annotations

import re
from typing import Any

from .user_facing import humanize_audit_text


_MACHINE_SUMMARY_RE = re.compile(
    r"^\s*intent\s*=\s*[^|\n]+"
    r"\s*\|\s*case_id\s*=\s*\d+"
    r"(?:\s*\|\s*(?:entity_name|ingest|report_generated\s+chars|agent)\s*=\s*[^|\n]*)*\s*$",
    re.IGNORECASE,
)
_MACHINE_LINE_RE = re.compile(
    r"^\s*(?:intent|case_id|report_generated\s+chars|memory_context|"
    r"case_snapshot|kg_summary|report_part_b|agent)\s*=",
    re.IGNORECASE,
)
_STREAM_DEBUG_PREFIXES = (
    "intent=",
    "case_id=",
    "report_generated chars=",
    "memory_context=",
    "case_snapshot=",
    "kg_summary=",
    "report_part_b=",
    "agent=",
)


def is_internal_debug_response(value: Any) -> bool:
    """Return whether *value* is an orchestration/debug summary, not prose."""

    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if _MACHINE_SUMMARY_RE.fullmatch(text):
        return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    # Also catch a legacy summary followed by an otherwise harmless line.
    if _MACHINE_SUMMARY_RE.fullmatch(lines[0]):
        return True
    if len(lines) > 4:
        return False
    machine_lines = sum(bool(_MACHINE_LINE_RE.match(line)) for line in lines)
    return machine_lines >= 2 or (len(lines) == 1 and machine_lines == 1)


def sanitize_user_response(value: Any, *, fallback: str) -> str:
    """Keep visible assistant content human-readable and never machine-only."""

    text = value.strip() if isinstance(value, str) else ""
    if not text or is_internal_debug_response(text):
        return fallback
    return humanize_audit_text(text) or fallback


def filter_stream_debug_text(value: Any, state: dict[str, Any]) -> str:
    """Drop a known machine-summary stream before it reaches the chat bubble.

    Model tokens can split ``intent=...`` across several chunks. Keep only a
    very small prefix buffer until the response can be identified; ordinary
    prose is then emitted unchanged. The authoritative final response is
    still sanitized separately at the graph boundary.
    """

    if not isinstance(value, str) or not value:
        return ""
    if state.get("suppressed"):
        return ""
    if state.get("decided"):
        return value

    buffered = f"{state.get('buffer', '')}{value}"
    normalized = buffered.lstrip().lower()
    if any(normalized.startswith(prefix) for prefix in _STREAM_DEBUG_PREFIXES):
        state["suppressed"] = True
        state["buffer"] = ""
        return ""

    # Decide quickly for normal prose. This only delays the first handful of
    # characters and prevents a split ``intent=`` prefix from flashing.
    if "\n" in buffered or len(buffered) >= 16:
        state["decided"] = True
        state["buffer"] = ""
        return buffered

    state["buffer"] = buffered
    return ""


def friendly_no_result_response(state: dict[str, Any] | None = None) -> str:
    """Explain a missing result without exposing graph fields or exceptions."""

    state = state or {}
    decision = state.get("route_decision") or {}
    capability = decision.get("capability") if isinstance(decision, dict) else ""
    case_id = state.get("current_case_id") or 0
    try:
        has_case = int(case_id) > 0
    except (TypeError, ValueError):
        has_case = False

    if capability == "audit.full":
        if not has_case:
            return "请先选择或创建一个年审项目，我才能执行年度审计并生成底稿。"
        return (
            "这次暂时没有生成可展示的年度审计结果。为了避免把未经核验的信息当作底稿，"
            "本轮未输出审计结论；请确认项目资料已导入并重试。"
        )
    if capability == "audit.drilldown":
        return (
            "这次暂时没有取得可核验的项目资料，因此我不能直接给出审计判断。"
            "请确认当前年审项目和相关资料已导入后再试。"
        )
    if not has_case and capability not in {"common.general", "clarify"}:
        return "请先选择或创建一个年审项目，再继续处理这项请求。"
    return (
        "这次请求暂时没有形成可展示的结果。为避免输出未经核验的信息，"
        "本轮未生成审计结论；请稍后重试。"
    )


def friendly_execution_failure_response() -> str:
    """Explain an unexpected processing failure without returning exception text."""

    return (
        "这次请求未能完成，因为审计处理服务暂时发生异常。为避免输出未经核验的信息，"
        "本轮没有生成审计结论；请稍后重试。如果问题持续，请联系管理员。"
    )


LEGACY_UNAVAILABLE_RESPONSE = (
    "这条历史回复没有保存可展示的正文。为避免显示内部系统信息，请重新发起该请求，"
    "系统会在完成后返回可读结果。"
)


__all__ = [
    "LEGACY_UNAVAILABLE_RESPONSE",
    "friendly_execution_failure_response",
    "friendly_no_result_response",
    "filter_stream_debug_text",
    "is_internal_debug_response",
    "sanitize_user_response",
]
