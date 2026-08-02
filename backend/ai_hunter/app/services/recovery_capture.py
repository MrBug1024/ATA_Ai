"""实收自动捕获（Tier1-3）：从补卷材料 / 操作员上传卷宗 / 对话文本中保守抽取已发生的回款。

安全模型：自动抽取的收款写入为 status='pending'（待确认），**不计入实收总额**，
需人工在看板确认后才计入，避免 LLM 误抽污染核心 KPI。
关键词预过滤 → 命中才调 LLM → 结构化输出 → 写 pending 记录。best-effort，吞异常。
"""

from __future__ import annotations

import datetime
import logging

LOGGER = logging.getLogger(__name__)

# 回款信号词：命中才调 LLM（省成本、降误报）
_RECOVERY_SIGNALS = (
    "回款", "已收", "已回", "收到", "到账", "回收", "清偿", "分红", "拍卖款",
    "执行款", "和解款", "已支付", "已偿还", "已收回", "实收",
)


def has_recovery_signal(text: str) -> bool:
    return bool(text) and any(k in text for k in _RECOVERY_SIGNALS)


def _parse_date(s: str):
    try:
        return datetime.date.fromisoformat((s or "").strip())
    except (ValueError, AttributeError):
        return None


_PROMPT = (
    "从下面文本中提取**已实际发生**的回款/收款记录（忽略预期、计划、目标、估算、"
    "“预计/拟/将/约”等未发生的）。\n"
    "只输出一个 JSON 对象，禁止任何解释、禁止代码块标记，格式严格为：\n"
    '{"records":[{"amount":数字(元),"recovered_at":"YYYY-MM-DD或空串",'
    '"source_desc":"来源/资产说明","disposal_path":"清算拍卖/破产重整/协商和解/执行/分红/其它"}]}\n'
    "没有明确的实际收款则输出 {\"records\":[]}。\n\n文本：\n"
)


def _coerce_records(content: str) -> list[dict]:
    """从模型回复里稳健解析 records（去围栏 + json.loads + 字段校验）。"""
    import json
    import re

    text = (content or "").strip()
    if not text:
        return []
    fenced = re.sub(r"^```(?:json)?|```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
    # 容错：截取首个 { ... } 块
    m = re.search(r"\{.*\}", fenced, re.DOTALL)
    if m:
        fenced = m.group(0)
    try:
        parsed = json.loads(fenced)
    except (ValueError, TypeError):
        return []
    records = parsed.get("records") if isinstance(parsed, dict) else None
    if not isinstance(records, list):
        return []
    out = []
    for r in records:
        if not isinstance(r, dict):
            continue
        try:
            amount = float(r.get("amount"))
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        out.append({
            "amount": amount,
            "recovered_at": str(r.get("recovered_at", "") or ""),
            "source_desc": str(r.get("source_desc", "") or ""),
            "disposal_path": str(r.get("disposal_path", "") or ""),
        })
    return out


def extract_recovery_records(text: str) -> list[dict]:
    """保守抽取已实际发生的回款记录；无信号/无 key/异常 → 空。

    用手动 JSON 解析而非 with_structured_output（minimax 等网关结构化输出不稳）。
    """
    if not has_recovery_signal(text):
        return []
    try:
        from ..graph.llm import build_zero_temp_router_llm, has_api_key

        llm = build_zero_temp_router_llm()
        if not has_api_key(llm):
            return []
        resp = llm.invoke(_PROMPT + text[:6000])
        return _coerce_records(getattr(resp, "content", "") or "")
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("recovery_extract_failed error=%s", str(exc)[:160])
        return []


def capture_recovery_to_db(text: str, case_id: int, *, origin: str) -> int:
    """抽取并写入 pending 收款记录（待人工确认）。返回写入条数。best-effort。"""
    if case_id <= 0:
        return 0
    records = extract_recovery_records(text)
    if not records:
        return 0
    try:
        from .progress_service import get_progress_service

        svc = get_progress_service()
        n = 0
        today = datetime.date.today()
        for r in records:
            amount = r.get("amount")
            if not amount or float(amount) <= 0:
                continue
            svc.add_recovery(
                case_id,
                amount=float(amount),
                recovered_at=_parse_date(r.get("recovered_at")) or today,
                disposal_path=str(r.get("disposal_path", "") or ""),
                source_desc=str(r.get("source_desc", "") or ""),
                operator="系统自动提取",
                note=f"自动抽取自{origin}，待人工确认",
                status="pending",
                origin=origin,
            )
            n += 1
        if n:
            LOGGER.info("recovery_captured case_id=%s origin=%s count=%s", case_id, origin, n)
        return n
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("recovery_capture_failed case_id=%s error=%s", case_id, str(exc)[:160])
        return 0
