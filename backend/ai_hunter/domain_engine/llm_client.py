# ============================================================================
# AI 猎手 FastAPI — LLM 客户端（Gemini / MiniMax 双引擎）
# 统一使用 OpenAI SDK 兼容接口
# ============================================================================

import json
import logging
import re
import time

from openai import OpenAI, RateLimitError
from .config import get_llm_config, GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL

logger = logging.getLogger("ai_hunter.llm")

# ---------------------------------------------------------------------------
# 敏感词脱敏映射（绕过 MiniMax output_new_sensitive 拦截）
# 原理：发给 LLM 前把敏感数值替换为占位符，LLM 输出占位符后再还原
# ---------------------------------------------------------------------------
_MASK_PATTERNS = [
    # 银行账号（10-22位纯数字）— 最常触发
    re.compile(r'\b(\d{10,22})\b'),
    # 身份证号（17位数字 + 数字或X）
    re.compile(r'\b(\d{17}[\dXx])\b'),
    # 手机号（1开头11位）
    re.compile(r'\b(1[3-9]\d{9})\b'),
    # 统一社会信用代码（18位字母数字）
    re.compile(r'\b([0-9A-HJ-NP-RT-Y]{2}\d{6}[0-9A-HJ-NP-RT-Y]{10})\b'),
]


def mask_sensitive(text: str) -> tuple[str, dict]:
    """
    将文本中的敏感数值替换为占位符 NUM0001/NUM0002...
    返回 (脱敏后文本, {占位符: 原始值} 映射表)
    """
    restore_map: dict[str, str] = {}
    seen: dict[str, str] = {}   # 原始值 → 占位符（去重）
    idx = [0]

    def _replacer(m: re.Match) -> str:
        val = m.group(0)
        if val in seen:
            return seen[val]
        idx[0] += 1
        ph = f"NUM{idx[0]:04d}"
        restore_map[ph] = val
        seen[val] = ph
        return ph

    for pat in _MASK_PATTERNS:
        text = pat.sub(_replacer, text)
    return text, restore_map


def _unmask_obj(obj, restore_map: dict):
    """递归还原 JSON 结构中的占位符"""
    if not restore_map:
        return obj
    if isinstance(obj, str):
        for ph, orig in restore_map.items():
            obj = obj.replace(ph, orig)
        return obj
    if isinstance(obj, dict):
        return {k: _unmask_obj(v, restore_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unmask_obj(item, restore_map) for item in obj]
    return obj


def get_client():
    cfg = get_llm_config()
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])


def _chat_with_cfg(cfg: dict, system_prompt: str, user_prompt: str,
                   temperature: float, max_tokens: int) -> str:
    """用指定 cfg 调一次 LLM，返回文本"""
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    t0 = time.time()
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = resp.choices[0].message.content
    duration_ms = int((time.time() - t0) * 1000)
    logger.info("LLM调用完成 | model=%s | 耗时%dms | 响应长度=%d字符",
                cfg["model"], duration_ms, len(content) if content else 0)
    return content


def chat(system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 4096) -> str:
    cfg = get_llm_config()
    t0 = time.time()
    # 发送前脱敏（分类场景响应只含类别名称，无需还原）
    masked_prompt, _ = mask_sensitive(user_prompt)
    logger.info("LLM调用开始 | model=%s | prompt前100字=%s", cfg["model"], masked_prompt[:100])
    max_retries = 3
    wait_secs = 3
    for attempt in range(max_retries):
        try:
            return _chat_with_cfg(cfg, system_prompt, masked_prompt, temperature, max_tokens)
        except RateLimitError as e:
            duration_ms = int((time.time() - t0) * 1000)
            if attempt < max_retries - 1:
                logger.warning("LLM 429限流，第%d次重试，等待%ds | model=%s | 耗时%dms",
                               attempt + 1, wait_secs, cfg["model"], duration_ms)
                time.sleep(wait_secs)
                wait_secs = min(wait_secs * 2, 15)
            else:
                logger.error("LLM调用失败 | model=%s | 耗时%dms | 错误=%s", cfg["model"], duration_ms, str(e))
                raise
        except Exception as e:
            err_str = str(e)
            duration_ms = int((time.time() - t0) * 1000)
            logger.error("LLM调用失败 | model=%s | 耗时%dms | 错误=%s", cfg["model"], duration_ms, err_str)
            raise


def chat_json(system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
    """调用LLM并解析返回的JSON，自动脱敏输入并还原输出中的占位符"""
    # 脱敏：把银行账号/身份证/手机号等替换为 NUM0001 占位符
    masked_prompt, restore_map = mask_sensitive(user_prompt)
    if restore_map:
        logger.debug("敏感词映射 | 脱敏%d个值", len(restore_map))
    raw = chat(system_prompt, masked_prompt, temperature)
    cleaned = raw.strip()
    # 去除 MiniMax <think>...</think> 标签
    cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        result = json.loads(cleaned)
        # 还原：把 LLM 输出的占位符替换回原始值
        return _unmask_obj(result, restore_map)
    except json.JSONDecodeError:
        logger.warning("LLM返回JSON解析失败 | 原始响应前200字=%s", raw[:200])
        return {"raw_response": raw, "parse_error": True}


def embed(text: str) -> list[float]:
    """
    将文本转为向量（用于 cpwsdata 语义搜索）。
    MiniMax: model=embo-01, dim=1536
    Gemini:  model=text-embedding-004, dim=768
    Phase-0 探查后按实际维度在 config.CPWS_EMBED_DIM 中调整。
    """
    cfg = get_llm_config()
    client = get_client()

    # 选择 embedding 模型
    if cfg.get("model", "").startswith("MiniMax") or "minimax" in cfg.get("base_url", ""):
        embed_model = "embo-01"
    else:
        embed_model = "text-embedding-004"

    t0 = time.time()
    try:
        resp = client.embeddings.create(model=embed_model, input=text[:8000])
        vec = resp.data[0].embedding
        logger.info("embed | model=%s | dim=%d | 耗时%dms", embed_model, len(vec), int((time.time()-t0)*1000))
        return vec
    except Exception as e:
        logger.error("embed 失败 | model=%s | 错误=%s", embed_model, str(e))
        raise
