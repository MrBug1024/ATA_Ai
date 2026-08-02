"""复盘报告段子 agent 节点工厂（Tier1-3 Phase 2-A）。

复用 generate_sections 的并发/流式/容错机器，只换"喂的数据"与"专家 prompt"：
- 数据 = 确定性对账结果 review_context（metrics 三视角 + 原始 forecast/record + 风险）；
- prompt = review_s{N}.txt（对账/归因/经验）。
段文本写进 state.report_section_refs（与审计段共用 merge reducer），由 reconcile_review 拼接。
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from ...settings import get_settings
from ..heavy_state import put_heavy_payload
from ..json_utils import json_dumps_safe
from ..llm import build_report_section_llm
from ..prompting import load_prompt
from ..review_sections import REVIEW_SECTIONS, review_section_node_name
from ..state import AuditGraphState
from .generate_sections import _astream_section_text, _common_prefix, _section_semaphore

LOGGER = logging.getLogger(__name__)


def _build_messages(state: AuditGraphState, section: dict) -> list:
    """复盘段消息：公共前缀 + 本段专家 prompt + 对账数据切片。"""
    review_ctx = state.get("review_context") or {}
    metrics = review_ctx.get("metrics") or {}
    case_id = review_ctx.get("case_id", state.get("current_case_id", 0))
    system = _common_prefix() + "\n\n" + load_prompt(section["prompt"])
    human = (
        f"案件ID: {case_id}\n"
        f"复盘日期: {metrics.get('today', '')}\n\n"
        f"确定性对账结果(JSON，回收率/差异/分档/路径均已算好，禁止自行重算):\n"
        f"{json_dumps_safe(metrics)}\n\n"
        f"实收明细(已确认):\n{json_dumps_safe(review_ctx.get('records') or [])}\n\n"
        f"预期回款分档:\n{json_dumps_safe(review_ctx.get('forecasts') or [])}"
    )
    return [SystemMessage(content=system), HumanMessage(content=human)]


def build_review_section_node(section: dict):
    """构建单段复盘子 agent 节点（同步 invoke / 异步流式 + 有界并发 + 段级容错）。"""
    sid = section["id"]
    settings = get_settings()
    provider = section.get("provider")
    cfg = settings.get_llm_config("report_a", provider_override=provider)
    sem_provider = cfg.get("provider", "default")

    def _fallback(state: AuditGraphState) -> AuditGraphState:
        placeholder = f"### 复盘{sid}段占位：{section['title']}\n（report LLM 不可用，接入后生成）"
        return {"report_section_refs": {sid: put_heavy_payload("report_section", {"text": placeholder})}}

    if not cfg.get("api_key"):
        cfg = settings.get_llm_config("report_a")
        sem_provider = cfg.get("provider", "default")
        provider = None
        if not cfg.get("api_key"):
            return RunnableLambda(_fallback)

    llm = build_report_section_llm(provider_override=provider)
    default_provider = settings.get_llm_config("report_a").get("provider", "default")
    fallback_llm = build_report_section_llm(provider_override=None) if sem_provider != default_provider else None

    def _store(text: str) -> AuditGraphState:
        return {"report_section_refs": {sid: put_heavy_payload("report_section", {"text": (text or "").strip()})}}

    def _sync_node(state: AuditGraphState) -> AuditGraphState:
        messages = _build_messages(state, section)
        try:
            return _store(str(getattr(llm.invoke(messages), "content", "") or ""))
        except Exception as exc:  # noqa: BLE001
            if fallback_llm is None:
                raise
            LOGGER.warning("review_section_%s provider=%s failed (%s); fallback to %s", sid, sem_provider, str(exc)[:120], default_provider)
            return _store(str(getattr(fallback_llm.invoke(messages), "content", "") or ""))

    async def _async_node(state: AuditGraphState) -> AuditGraphState:
        messages = _build_messages(state, section)
        try:
            async with _section_semaphore(sem_provider):
                text = await _astream_section_text(llm, messages, section_id=sid)
        except Exception as exc:  # noqa: BLE001
            if fallback_llm is None:
                raise
            LOGGER.warning("review_section_%s provider=%s failed (%s); fallback to %s", sid, sem_provider, str(exc)[:120], default_provider)
            async with _section_semaphore(default_provider):
                text = await _astream_section_text(fallback_llm, messages, section_id=sid)
        return _store(text)

    return RunnableLambda(_sync_node, afunc=_async_node)


def build_all_review_section_nodes() -> dict:
    """返回 {节点名: Runnable}，供 review_graph 接线。"""
    return {review_section_node_name(s["id"]): build_review_section_node(s) for s in REVIEW_SECTIONS}
