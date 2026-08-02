from typing import get_type_hints

from langgraph.managed.is_last_step import RemainingSteps

import ai_hunter.app.graph.nodes.run_drilldown_agent as drilldown_nodes
from ai_hunter.app.graph.nodes.run_drilldown_agent import (
    DrilldownAgentState,
    _build_case_snapshot,
    _build_correction_block,
    _build_system_prompt,
)
from ai_hunter.app.graph.prompting import load_prompt


def test_build_case_snapshot_uses_lightweight_summary_not_full_json():
    snapshot = _build_case_snapshot(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "full_context_data": {
                "debtors": [{"name": "A"}, {"name": "B"}],
                "claims": [{"id": 1}],
                "guarantors": [{"id": 2}],
                "real_estate_evaluations": [{"id": 3}],
                "mining_evaluations": [{"id": 4}, {"id": 5}],
                "whiteglove": {"score": 0.7},
                "fund_flow": [{"path": "x"}],
                "engine_results": {"delta": {}, "deadline": {}},
            },
        }
    )

    assert '"case_id": 116' in snapshot
    assert '"debtors_count": 2' in snapshot
    assert '"claims_count": 1' in snapshot
    assert "晨光煤矿" in snapshot


def test_build_correction_block_prioritizes_structured_records():
    block = _build_correction_block(
        {
            "correction_records": [
                {
                    "target": "水西南路房产",
                    "instruction": "估值按800万重算",
                    "source_query": "房产估值不对，按800万重审",
                }
            ]
        }
    )

    assert "水西南路房产" in block
    assert "估值按800万重算" in block
    assert "来源" in block


def test_build_system_prompt_puts_corrections_after_case_context():
    prompt = _build_system_prompt(
        {
            "current_case_id": 116,
            "current_debtor_id": 7,
            "current_debtor_name": "晨光煤矿",
            "memory_context": "用户最近在追问白手套风险",
            "parse_summary": "已补录抵押合同",
            "report_part_b": "下钻索引：优先核查采矿权证照与白手套路径",
            "full_context_data": {"debtors": [{"name": "晨光煤矿"}]},
            "kg_summary": "已构建案件图谱：实体2个，关系1条，断言1条。",
            "correction_records": [
                {
                    "target": "矿权状态",
                    "instruction": "以最新行政审批状态为准",
                    "source_query": "矿权状态有误",
                }
            ],
        }
    )

    # _build_system_prompt 现在返回 [HumanMessage(...)]，供 create_react_agent 直接当 prompt 用
    content = prompt[0].content
    assert "当前案件轻量摘要" in content
    assert "当前案件知识图谱摘要" in content
    assert "前序审计后半段/下钻索引" in content
    assert "以下修正台账优先级最高" in content
    assert content.index("当前案件轻量摘要") < content.index("以下修正台账优先级最高")


def test_agent_state_uses_managed_remaining_steps():
    hints = get_type_hints(DrilldownAgentState, include_extras=True)

    assert hints["remaining_steps"] == RemainingSteps


def test_agent_recursion_limit_uses_settings_with_safe_floor(monkeypatch):
    monkeypatch.setattr(
        drilldown_nodes,
        "get_settings",
        lambda: type("Settings", (), {"agent_recursion_limit": 10})(),
    )
    assert drilldown_nodes._agent_recursion_limit() == 10

    monkeypatch.setattr(
        drilldown_nodes,
        "get_settings",
        lambda: type("Settings", (), {"agent_recursion_limit": 1})(),
    )
    assert drilldown_nodes._agent_recursion_limit() == 4


def test_all_agent_prompts_forbid_duplicate_tool_calls():
    for prompt_name in (
        "drilldown_agent.txt",
        "audit_drilldown_agent.txt",
        "graph_query_agent.txt",
    ):
        prompt = load_prompt(prompt_name)
        assert "同一工具和完全相同的参数最多调用一次" in prompt
        assert "不得" in prompt and "重试" in prompt
