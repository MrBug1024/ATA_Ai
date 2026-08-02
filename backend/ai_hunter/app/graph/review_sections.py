"""复盘报告 section 注册表（Tier1-3 Phase 2-A）。

复盘 ≠ 审计资产，故用独立 3 段（对账总览 / 差异归因 / 经验与规则建议），
但复用八段式的段子 agent 机器（并行扇出 + 专家 persona + 有界并发 + 流式 + 容错）。
段 id 用 R1/R2/R3，节点前缀 generate_review_section_，与审计 1~8 段互不冲突；
段文本同样写进 state.report_section_refs（共用 merge reducer），由 reconcile_review 拼接。
"""

from __future__ import annotations

REVIEW_SECTION_NODE_PREFIX = "generate_review_section_"


# provider：核心对账/归因段走 kimi 分摊负载，其余默认（minimax）。None/缺省 = LLM_PROVIDER_REPORT_A。
REVIEW_SECTIONS: list[dict] = [
    {"id": "R1", "title": "预期 vs 实际对账总览", "prompt": "review_s1.txt", "provider": "kimi"},
    {"id": "R2", "title": "差异归因分析", "prompt": "review_s2.txt", "provider": "kimi"},
    {"id": "R3", "title": "经验总结与规则建议", "prompt": "review_s3.txt"},
]

REVIEW_SECTION_IDS = [s["id"] for s in REVIEW_SECTIONS]
REVIEW_SECTION_BY_ID = {s["id"]: s for s in REVIEW_SECTIONS}


def review_section_node_name(section_id: str) -> str:
    return f"{REVIEW_SECTION_NODE_PREFIX}{section_id}"


REVIEW_SECTION_BY_NODE = {review_section_node_name(s["id"]): s for s in REVIEW_SECTIONS}


def review_section_id_from_node(node_name: str) -> str | None:
    section = REVIEW_SECTION_BY_NODE.get(node_name or "")
    return section["id"] if section else None
