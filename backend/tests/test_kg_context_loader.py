from ai_hunter.app.graph.context_loader import resolve_kg_snapshot
from ai_hunter.app.graph.heavy_state import put_heavy_payload


def test_resolve_kg_snapshot_reads_lightweight_subgraph_payload():
    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [
                {"id": 11, "canonical_name": "晨光煤矿", "entity_type": "company"},
                {"id": 12, "canonical_name": "某保证人", "entity_type": "person"},
            ],
            "relations": [
                {
                    "id": 21,
                    "relation_type": "guarantee",
                    "relation_label": "保证",
                    "from_entity_id": 11,
                    "to_entity_id": 12,
                }
            ],
            "claims": [{"id": 31, "claim_type": "risk_signal", "claim_text": "存在关联担保"}],
            "evidence_count": 4,
        },
    )

    snapshot = resolve_kg_snapshot({"kg_subgraph_ref": kg_subgraph_ref})

    assert snapshot["summary"] == "已构建案件图谱：实体2个，关系1条，断言1条。"
    assert snapshot["entity_samples"][0]["name"] == "晨光煤矿"
    assert snapshot["relation_samples"][0]["type"] == "guarantee"
    assert snapshot["claim_samples"][0]["text"] == "存在关联担保"
    assert snapshot["evidence_count"] == 4
