"""八段式报告段落子 agent 节点工厂（Tier1-2，方案 A）。

每段一个专家子 agent：公共前缀 + 本段专家 prompt + 切片数据 + computed_metrics。
节点以 `generate_section_{id}` 注册，便于 astream_events 按 metadata.langgraph_node 打 section_id。
并行节点各写 `report_section_refs[{id}]`（state 用 reducer 合并）。
"""

import asyncio
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from ...settings import get_settings
from ..context_loader import (
    build_inline_citation_catalog,
    build_report_context,
    resolve_computed_metrics,
    resolve_full_context_data,
    resolve_kg_snapshot,
)
from ..heavy_state import put_heavy_payload
from ..json_utils import json_dumps_safe
from ..llm import build_report_section_llm
from ..prompting import load_prompt
from ..report_sections import SECTIONS, section_node_name
from ..state import AuditGraphState

LOGGER = logging.getLogger(__name__)

# 有界并发：八段并行扇出，但单 key 满并发长生成会 529 过载。
# 按 provider 各自一个信号量（段级 env 可覆盖 provider，两端点独立并发，互不拖累），
# 每 provider 限到 N（默认 3），既拿到跨 provider 并行加速又不打爆任一服务。
# 信号量按 (event loop, provider) 维护，避免跨 asyncio.run 的循环绑定错误。
_SECTION_SEMS: dict = {}
_REASONING_TAG_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _clean_section_text(text: str) -> str:
    return _REASONING_TAG_PATTERN.sub("", text or "").strip()


def _section_timeout_seconds() -> float:
    return max(10.0, float(get_settings().report_section_timeout_seconds))


def _section_failure_text(section: dict, reason: str) -> str:
    sid = section.get("id", "")
    title = section.get("title", "")
    return f"### 第{sid}段占位：{title}\n（{reason}，已跳过本段以完成整份报告）"


def _section_provider_override(section: dict) -> str | None:
    sid = str(section.get("id", "") or "").strip()
    return get_settings().report_section_provider_for(sid)


def _section_semaphore(provider: str) -> "asyncio.Semaphore":
    loop = asyncio.get_running_loop()
    key = (id(loop), provider)
    sem = _SECTION_SEMS.get(key)
    if sem is None:
        limit = get_settings().report_section_concurrency_for(provider)
        sem = asyncio.Semaphore(limit)
        _SECTION_SEMS[key] = sem
    return sem


def _is_overloaded(exc: Exception) -> bool:
    """识别可重试的过载/限流/瞬时错误（minimax 529 overloaded、429、超时、连接）。"""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(k in text for k in ("529", "overloaded", "rate limit", "ratelimit", "timeout", "503", "502", "connection"))


async def _astream_section_text(llm, messages, *, section_id: str, retries: int = 3) -> str:
    """异步流式生成并累积文本；过载退避重试。llm.astream 保留 astream_events 的分段 token 事件。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            parts: list[str] = []
            async for chunk in llm.astream(messages):
                content = getattr(chunk, "content", "")
                if isinstance(content, str):
                    parts.append(content)
            return "".join(parts).strip()
        except Exception as exc:  # noqa: BLE001 — 需按内容判定是否可重试
            last_exc = exc
            if attempt < retries - 1 and _is_overloaded(exc):
                backoff = 2.0 * (attempt + 1)
                LOGGER.warning("section_%s overloaded, retry in %.0fs: %s", section_id, backoff, str(exc)[:160])
                await asyncio.sleep(backoff)
                continue
            raise
    raise last_exc  # pragma: no cover


def _common_prefix() -> str:
    return load_prompt("report_common_prefix.txt")


def _slice_context(state: AuditGraphState, section: dict) -> dict:
    """按 section.data_keys 从精选报告上下文切片；case_id + computed_metrics 全段共有。"""
    full = build_report_context(resolve_full_context_data(state), resolve_computed_metrics(state))
    sliced: dict = {
        "case_id": full.get("case_id", 0),
        "computed_metrics": full.get("computed_metrics", {}),
    }
    for key in section.get("data_keys", []):
        if key in full:
            sliced[key] = full[key]
    return sliced


def _build_messages(state: AuditGraphState, section: dict) -> list:
    corrections = state.get("user_corrections", [])
    correction_text = "\n".join(corrections) if corrections else "无修正，按原始数据执行。"
    sliced = _slice_context(state, section)
    kg_snapshot_json = json_dumps_safe(resolve_kg_snapshot(state))
    citation_catalog = build_inline_citation_catalog(state)
    system = _common_prefix() + "\n\n" + load_prompt(section["prompt"])
    human = (
        f"案件ID: {sliced.get('case_id')}\n"
        f"用户修正台账:\n{correction_text}\n\n"
        f"本段数据切片(JSON):\n{json_dumps_safe(sliced)}\n\n"
        f"知识图谱轻量摘要:\n{kg_snapshot_json}\n\n"
        f"可引用断言角标清单:\n{citation_catalog}"
    )
    return [SystemMessage(content=system), HumanMessage(content=human)]


def build_section_node(section: dict):
    """构建单段子 agent 节点。

    - 异步路径（生产 SSE / ainvoke）：有界并发（信号量）+ 流式 + 过载重试，真并行又不打爆服务。
    - 同步路径（sync invoke / 离线测试）：直接 invoke（同步图本就串行）。
    """
    sid = section["id"]
    settings = get_settings()
    # 默认跟随 report_a provider；如需按段分流，使用 REPORT_SECTION_PROVIDER_{段号}。
    provider = _section_provider_override(section) or section.get("provider")
    cfg = settings.get_llm_config("report_a", provider_override=provider)
    sem_provider = cfg.get("provider", "default")

    def _fallback(state: AuditGraphState) -> AuditGraphState:
        placeholder = f"### 第{sid}段占位：{section['title']}\n（report LLM 不可用，接入后生成）"
        return {"report_section_refs": {sid: put_heavy_payload("report_section", {"text": placeholder})}}

    if not cfg.get("api_key"):
        # 该段 provider 无 key → 退回默认 provider；仍无则占位
        cfg = settings.get_llm_config("report_a")
        sem_provider = cfg.get("provider", "default")
        provider = None
        if not cfg.get("api_key"):
            return RunnableLambda(_fallback)

    llm = build_report_section_llm(provider_override=provider)
    # 段级容错：该段 provider（如 kimi）整体失败时，回退默认 provider（minimax）再试一次，
    # 保证单个 provider 故障/不可达不会拖垮整份报告。
    default_provider = settings.get_llm_config("report_a").get("provider", "default")
    fallback_llm = build_report_section_llm(provider_override=None) if sem_provider != default_provider else None

    def _store(text: str) -> AuditGraphState:
        return {"report_section_refs": {sid: put_heavy_payload("report_section", {"text": _clean_section_text(text)})}}

    def _store_failure(reason: str) -> AuditGraphState:
        return _store(_section_failure_text(section, reason))

    def _sync_fallback(messages: list, reason: str) -> AuditGraphState:
        if fallback_llm is None:
            LOGGER.warning("section_%s provider=%s produced no usable text: %s", sid, sem_provider, reason)
            return _store_failure(reason)
        LOGGER.warning("section_%s provider=%s produced no usable text (%s); fallback to %s", sid, sem_provider, reason, default_provider)
        try:
            text = _clean_section_text(str(getattr(fallback_llm.invoke(messages), "content", "") or ""))
        except Exception as fallback_exc:  # noqa: BLE001
            LOGGER.warning("section_%s fallback provider=%s failed: %s", sid, default_provider, str(fallback_exc)[:120])
            return _store_failure("备用 LLM 生成失败")
        if not text:
            LOGGER.warning("section_%s fallback provider=%s returned empty text", sid, default_provider)
            return _store_failure("备用 LLM 返回空内容")
        return _store(text)

    async def _async_fallback(messages: list, timeout_seconds: float, reason: str) -> AuditGraphState:
        if fallback_llm is None:
            LOGGER.warning("section_%s provider=%s produced no usable text: %s", sid, sem_provider, reason)
            return _store_failure(reason)
        LOGGER.warning("section_%s provider=%s produced no usable text (%s); fallback to %s", sid, sem_provider, reason, default_provider)
        try:
            async with _section_semaphore(default_provider):
                text = await asyncio.wait_for(
                    _astream_section_text(fallback_llm, messages, section_id=sid),
                    timeout=timeout_seconds,
                )
        except asyncio.TimeoutError:
            LOGGER.warning("section_%s fallback provider=%s timed out after %.0fs", sid, default_provider, timeout_seconds)
            return _store_failure("备用 LLM 生成超时")
        except Exception as fallback_exc:  # noqa: BLE001
            LOGGER.warning("section_%s fallback provider=%s failed: %s", sid, default_provider, str(fallback_exc)[:120])
            return _store_failure("备用 LLM 生成失败")
        text = _clean_section_text(text)
        if not text:
            LOGGER.warning("section_%s fallback provider=%s returned empty text", sid, default_provider)
            return _store_failure("备用 LLM 返回空内容")
        return _store(text)

    def _sync_node(state: AuditGraphState) -> AuditGraphState:
        messages = _build_messages(state, section)
        try:
            text = _clean_section_text(str(getattr(llm.invoke(messages), "content", "") or ""))
        except Exception as exc:  # noqa: BLE001
            if fallback_llm is None:
                LOGGER.warning("section_%s provider=%s failed without fallback: %s", sid, sem_provider, str(exc)[:120])
                return _store_failure("本段 LLM 生成失败")
            LOGGER.warning("section_%s provider=%s failed (%s); fallback to %s", sid, sem_provider, str(exc)[:120], default_provider)
            return _sync_fallback(messages, "本段 LLM 生成失败")
        if not text:
            return _sync_fallback(messages, "本段 LLM 返回空内容")
        return _store(text)

    async def _async_node(state: AuditGraphState) -> AuditGraphState:
        messages = _build_messages(state, section)
        timeout_seconds = _section_timeout_seconds()
        try:
            async with _section_semaphore(sem_provider):  # 按 provider 有界并发，避免 529 过载
                text = await asyncio.wait_for(
                    _astream_section_text(llm, messages, section_id=sid),
                    timeout=timeout_seconds,
                )
        except asyncio.TimeoutError:
            LOGGER.warning("section_%s provider=%s timed out after %.0fs", sid, sem_provider, timeout_seconds)
            return await _async_fallback(messages, timeout_seconds, "本段 LLM 生成超时")
        except Exception as exc:  # noqa: BLE001 — provider 整体失败 → 回退默认
            LOGGER.warning("section_%s provider=%s failed: %s", sid, sem_provider, str(exc)[:120])
            return await _async_fallback(messages, timeout_seconds, "本段 LLM 生成失败")
        text = _clean_section_text(text)
        if not text:
            return await _async_fallback(messages, timeout_seconds, "本段 LLM 返回空内容")
        return _store(text)

    return RunnableLambda(_sync_node, afunc=_async_node)


def build_all_section_nodes() -> dict:
    """返回 {节点名: Runnable}，供 full_audit_graph 接线。"""
    return {section_node_name(s["id"]): build_section_node(s) for s in SECTIONS}
