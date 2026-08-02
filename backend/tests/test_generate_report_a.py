from ai_hunter.app.graph.context_loader import resolve_report_part_a
from ai_hunter.app.graph.heavy_state import put_heavy_payload
from ai_hunter.app.graph.nodes.generate_report_a import generate_report_part_a


def test_generate_report_part_a_placeholder_includes_kg_summary(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.generate_report_a.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {"get_llm_config": lambda self, role: {"api_key": ""}},
        )(),
    )
    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [{"id": 11, "canonical_name": "晨光煤矿", "entity_type": "company"}],
            "relations": [{"id": 21, "relation_type": "guarantee", "relation_label": "保证"}],
            "claims": [{"id": 31, "claim_type": "risk_signal", "claim_text": "存在关联担保"}],
            "evidence_count": 2,
        },
    )

    result = generate_report_part_a(
        {
            "current_case_id": 116,
            "user_corrections": ["矿权估值按最新口径重算"],
            "full_context_json": '{"claims":[{"amount":1000}]}',
            "kg_subgraph_ref": kg_subgraph_ref,
        }
    )

    report_text = resolve_report_part_a(result)
    assert "报告前4段占位" in report_text
    assert "知识图谱摘要: 已构建案件图谱：实体1个，关系1条，断言1条。" in report_text
