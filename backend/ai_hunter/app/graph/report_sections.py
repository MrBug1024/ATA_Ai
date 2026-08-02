"""八段式报告 section 注册表（Tier1-2，方案 A）。

单一来源：段落 id / 标题 / prompt 文件 / 数据切片键 / audience（权限前向兼容）。
generate_sections / full_audit_graph / reconcile_report / routes_chat 均从此读，
避免段落定义散写。
"""

from __future__ import annotations

SECTION_NODE_PREFIX = "generate_section_"


# data_keys：从 build_report_context() 输出里切给该段的顶层键（case_id/computed_metrics 全段共有，自动带）。
# audience：可见人群层级（field ⊂ expert ⊂ management），本次仅打标，供后续权限网关筛段。
# provider：不在注册表硬编码。默认用 LLM_PROVIDER_REPORT_A；如需按段分流，
#           设置 REPORT_SECTION_PROVIDER_{段号}。各 provider 独立并发信号量，互不拖累。
SECTIONS: list[dict] = [
    {"id": "1", "title": "数据洗脱与缺失核查", "prompt": "report_s1.txt",
     "audience": "field", "data_keys": ["debtors", "financial_snapshots", "delta"]},
    {"id": "2", "title": "资产清单与去毒重估", "prompt": "report_s2.txt",
     "audience": "field", "data_keys": ["real_estate", "mining", "valuation_detail", "claims"]},
    {"id": "3", "title": "黑盒穿透：资金流向拓扑图（含白手套线索识别）", "prompt": "report_s3.txt",
     "audience": "expert", "data_keys": ["fund_flow", "behavioral", "whiteglove"]},
    {"id": "4", "title": "司法时效预警看板", "prompt": "report_s4.txt",
     "audience": "field", "data_keys": ["deadline_board"]},
    {"id": "5", "title": "重整盘活可行性评估", "prompt": "report_s5.txt",
     "audience": "expert", "data_keys": ["claims", "whiteglove"]},
    {"id": "6", "title": "猎人行动令：多维博弈与社会工程学策略", "prompt": "report_s6.txt",
     "audience": "management", "data_keys": ["behavioral", "whiteglove"]},
    {"id": "7", "title": "督办看板：标准化执行任务", "prompt": "report_s7.txt",
     "audience": "management", "data_keys": ["deadline_board"], "tasks": True},
    {"id": "8", "title": "审计对账：增量回款贡献 + 下钻行动索引", "prompt": "report_s8.txt",
     "audience": "management", "data_keys": ["behavioral", "whiteglove"]},
]

SECTION_IDS = [s["id"] for s in SECTIONS]
SECTION_BY_ID = {s["id"]: s for s in SECTIONS}


def section_node_name(section_id: str) -> str:
    """段落 id → LangGraph 节点名。"""
    return f"{SECTION_NODE_PREFIX}{section_id}"


# 节点名 → section 定义（routes_chat 流式 handler 用 metadata.langgraph_node 反查打 section_id）
SECTION_BY_NODE = {section_node_name(s["id"]): s for s in SECTIONS}


def section_id_from_node(node_name: str) -> str | None:
    """节点名 → section_id；非段节点返回 None。"""
    section = SECTION_BY_NODE.get(node_name or "")
    return section["id"] if section else None
