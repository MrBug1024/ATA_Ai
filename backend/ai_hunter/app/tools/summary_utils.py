"""Shared dehydration helpers for tool outputs returned to the drilldown agent."""

import json
from collections.abc import Mapping, Sequence
from typing import Any


MAX_STRING_CHARS = 240
MAX_LIST_ITEMS = 5
MAX_DICT_ITEMS = 12
MAX_DEPTH = 3


def _truncate_text(value: str, max_chars: int = MAX_STRING_CHARS) -> tuple[str, bool]:
    """Clip long strings so tool messages stay compact."""
    if len(value) <= max_chars:
        return value, False
    return f"{value[:max_chars]}...(truncated)", True


def _dehydrate_value(value: Any, depth: int = 0) -> tuple[Any, bool]:
    """Recursively dehydrate nested payloads into a compact JSON-safe structure."""
    if value is None or isinstance(value, (bool, int, float)):
        return value, False

    if isinstance(value, str):
        return _truncate_text(value)

    if depth >= MAX_DEPTH:
        text, truncated = _truncate_text(str(value), max_chars=160)
        return text, True or truncated

    if isinstance(value, Mapping):
        truncated = False
        items = list(value.items())
        dehydrated: dict[str, Any] = {}
        for key, nested in items[:MAX_DICT_ITEMS]:
            compact, nested_truncated = _dehydrate_value(nested, depth + 1)
            dehydrated[str(key)] = compact
            truncated = truncated or nested_truncated
        if len(items) > MAX_DICT_ITEMS:
            truncated = True
            dehydrated["_omitted_keys"] = len(items) - MAX_DICT_ITEMS
        return dehydrated, truncated

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        truncated = False
        items = list(value)
        dehydrated_list: list[Any] = []
        for nested in items[:MAX_LIST_ITEMS]:
            compact, nested_truncated = _dehydrate_value(nested, depth + 1)
            dehydrated_list.append(compact)
            truncated = truncated or nested_truncated
        if len(items) > MAX_LIST_ITEMS:
            truncated = True
        return {
            "items": dehydrated_list,
            "returned_count": len(dehydrated_list),
            "total_count": len(items),
        }, truncated

    text, truncated = _truncate_text(str(value), max_chars=160)
    return text, truncated


def _infer_summary(tool_name: str, payload: Any, truncated: bool) -> str:
    """Build a compact natural-language summary for the agent."""
    if isinstance(payload, Mapping):
        keys = [str(key) for key in list(payload.keys())[:6]]
        suffix = "，结果已脱水截断。" if truncated else "。"
        return f"{tool_name} 返回字典结果，关键字段包括: {', '.join(keys) or '无'}{suffix}"
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        size = len(payload)
        suffix = "，仅保留前几项摘要。" if truncated else "。"
        return f"{tool_name} 命中 {size} 条记录{suffix}"
    suffix = "，内容已截断。" if truncated else "。"
    return f"{tool_name} 返回标量结果{suffix}"


def build_tool_result(tool_name: str, payload: Any, next_hint: str | None = None) -> str:
    """Wrap raw tool payloads in a compact, agent-friendly envelope."""
    key_facts, truncated = _dehydrate_value(payload)
    result = {
        "summary": _infer_summary(tool_name, payload, truncated),
        "key_facts": key_facts,
        "truncated": truncated,
        "next_hint": next_hint
        or (
            "如需更多细节，请缩小查询范围或指定更明确的对象。"
            if truncated
            else ""
        ),
    }
    return json.dumps(result, ensure_ascii=False)


def build_tool_error(tool_name: str, exc: Exception) -> str:
    """Normalize tool errors into the same compact envelope."""
    message, _ = _truncate_text(str(exc), max_chars=180)
    return json.dumps(
        {
            "summary": f"{tool_name} 调用失败。",
            "key_facts": {"error": message},
            "truncated": False,
            "next_hint": "请检查参数、目标对象或稍后重试。",
        },
        ensure_ascii=False,
    )
