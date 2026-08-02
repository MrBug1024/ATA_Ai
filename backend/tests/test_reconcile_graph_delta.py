from ai_hunter.app.graph.heavy_state import get_heavy_payload, put_heavy_payload
from ai_hunter.app.graph.nodes.reconcile_graph_delta import reconcile_graph_delta


class FakeKGService:
    def __init__(self, candidates=None, snapshot=None):
        self.candidates = candidates or {"candidates": []}
        self.snapshot = snapshot or {}
        self.fetch_candidate_calls = []
        self.superseded_claim_calls = []
        self.superseded_relation_calls = []
        self.ledger_rows = []

    def fetch_candidate_conflicts_by_chunks(self, **kwargs):
        self.fetch_candidate_calls.append(kwargs)
        return self.candidates

    def mark_claims_superseded(self, claim_ids):
        self.superseded_claim_calls.append(claim_ids)
        return len(claim_ids)

    def mark_relations_superseded(self, relation_ids):
        self.superseded_relation_calls.append(relation_ids)
        return len(relation_ids)

    def fetch_case_graph_snapshot(self, case_id):
        return self.snapshot

    def insert_reconciliation_ledger(self, *, case_id, rows):
        self.ledger_rows.append((case_id, rows))
        persisted = []
        for index, row in enumerate(rows, start=1):
            persisted.append({"id": index, **row})
        return persisted


def test_reconcile_graph_delta_supersedes_old_claims_and_relations(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 41,
                    "claim_text": "矿权估值为1200万元",
                    "entity_key": "entity-key-1",
                    "relation_key": "relation-key-1",
                    "relation_id": 21,
                    "matched_by": ["relation_key", "claim_text"],
                    "match_score": 0.91,
                },
                {
                    "claim_id": 101,
                    "claim_text": "矿权估值为800万元",
                    "entity_key": "entity-key-1",
                    "relation_key": "relation-key-1",
                    "relation_id": 31,
                    "matched_by": ["relation_key", "claim_text"],
                    "match_score": 0.98,
                },
            ]
        },
        snapshot={
            "entities": [{"id": 11, "canonical_name": "晨光煤矿", "entity_type": "company"}],
            "relations": [{"id": 31, "relation_type": "valuation", "relation_label": "矿权估值"}],
            "claims": [{"id": 101, "relation_id": 31, "claim_type": "relation_fact", "claim_text": "矿权估值为800万元", "confidence": 0.95}],
            "claim_traces": [{"claim_id": 101, "evidences": []}],
            "reconciliation_items": [
                {
                    "id": 1,
                    "action": "OVERRIDE",
                    "new_claim_id": 101,
                    "new_claim_text": "矿权估值为800万元",
                    "superseded_claim_id": 41,
                    "superseded_claim_text": "矿权估值为1200万元",
                    "new_relation_id": 31,
                    "superseded_relation_id": 21,
                    "rationale": "新证据覆盖旧估值",
                    "evidence_chunk_ids": ["chunk-1"],
                    "decision_payload": {},
                }
            ],
            "evidence_count": 1,
            "entity_count": 1,
            "relation_count": 1,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [{"id": 11}],
            "relations": [{"id": 31}],
            "claims": [{"id": 101, "relation_id": 31, "claim_text": "矿权估值为800万元"}],
            "claim_traces": [],
            "evidence_count": 1,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "这个矿权估值不对，按800万重审",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [{"entity_temp_id": "entity_1", "entity_key": "entity-key-1"}],
            "kg_relations": [{"relation_temp_id": "relation_1", "relation_key": "relation-key-1"}],
            "kg_claims": [
                {
                    "claim_text": "矿权估值为800万元",
                    "entity_temp_id": "entity_1",
                    "relation_temp_id": "relation_1",
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [41]
    assert result["superseded_relation_ids"] == [21]
    assert fake_kg.superseded_claim_calls == [[41]]
    assert fake_kg.superseded_relation_calls == [[21]]
    assert fake_kg.ledger_rows[0][0] == 116
    payload = get_heavy_payload(result["kg_subgraph_ref"])
    assert payload["claims"][0]["id"] == 101
    assert payload["reconciliation_items"][0]["superseded_claim_id"] == 41
    assert "实体1个，关系1条，断言1条" in result["kg_summary"]


def test_reconcile_graph_delta_skips_without_override_signal(monkeypatch):
    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {"claims": [{"id": 101}], "entities": [], "relations": [], "claim_traces": [], "evidence_count": 0},
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充一份材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [],
            "kg_relations": [],
            "kg_claims": [],
        }
    )

    assert result["superseded_claim_ids"] == []
    assert result["superseded_relation_ids"] == []
    assert fake_kg.fetch_candidate_calls == []


def test_reconcile_graph_delta_uses_structured_llm_decision(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            assert "candidate_old_claims" in messages[1].content
            return type(
                "FakeDecisionBundle",
                (),
                {
                    "decisions": [
                        type(
                            "FakeDecision",
                            (),
                            {
                                "model_dump": lambda self: {
                                    "new_claim_text": "矿权估值为800万元",
                                    "action": "OVERRIDE",
                                    "supersede_claim_ids": [41],
                                    "rationale": "新旧估值结论冲突",
                                }
                            },
                        )()
                    ]
                },
            )()

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 41,
                    "claim_text": "矿权估值为1200万元",
                    "entity_key": "entity-key-1",
                    "relation_key": "relation-key-1",
                    "relation_id": 21,
                    "matched_by": ["relation_key", "claim_text"],
                    "match_score": 0.91,
                }
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [{"id": 101, "relation_id": 31, "claim_type": "relation_fact", "claim_text": "矿权估值为800万元", "confidence": 0.95}],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.build_zero_temp_router_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.load_prompt",
        lambda _: "reconcile prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {"get_llm_config": lambda self, role: {"api_key": "test-key"}},
        )(),
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [{"id": 31}],
            "claims": [{"id": 101, "relation_id": 31, "claim_text": "矿权估值为800万元"}],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "chunks": [{"chunk_id": "chunk-1", "page_no": 1, "chunk_text": "矿权估值调整为800万元。"}],
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充材料显示矿权估值应调整为800万元",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [{"entity_temp_id": "entity_1", "entity_key": "entity-key-1"}],
            "kg_relations": [{"relation_temp_id": "relation_1", "relation_key": "relation-key-1"}],
            "kg_claims": [
                {
                    "claim_text": "矿权估值为800万元",
                    "entity_temp_id": "entity_1",
                    "relation_temp_id": "relation_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [41]
    assert fake_kg.superseded_claim_calls == [[41]]
    assert fake_kg.ledger_rows[0][1][0]["new_claim_id"] == 101


def test_reconcile_graph_delta_merges_llm_add_with_fallback_override(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            return type(
                "FakeDecisionBundle",
                (),
                {
                    "decisions": [
                        type(
                            "FakeDecision",
                            (),
                            {
                                "model_dump": lambda self: {
                                    "new_claim_text": "第一次债权人会议上，无人提出重整或和解申请。",
                                    "action": "ADD",
                                    "supersede_claim_ids": [],
                                    "rationale": "模型认为是补充事实",
                                }
                            },
                        )()
                    ]
                },
            )()

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 41,
                    "claim_type": "risk_signal",
                    "claim_text": "第一次债权人会议上无人提出重整、和解申请，无和解、重整可能性",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key", "claim_text"],
                    "match_score": 0.80,
                }
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [{"id": 101, "claim_text": "第一次债权人会议上，无人提出重整或和解申请。", "confidence": 0.95}],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.build_zero_temp_router_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.load_prompt",
        lambda _: "reconcile prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {"get_llm_config": lambda self, role: {"api_key": "test-key"}},
        )(),
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [{"id": 101, "claim_text": "第一次债权人会议上，无人提出重整或和解申请。"}],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充一债会材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                }
            ],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "第一次债权人会议上，无人提出重整或和解申请。",
                    "claim_type": "entity_fact",
                    "entity_temp_id": "entity_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [41]
    assert fake_kg.superseded_claim_calls == [[41]]


def test_reconcile_graph_delta_uses_null_relation_ids_when_claims_have_no_relation(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 41,
                    "claim_text": "企业已停产",
                    "entity_key": "entity-key-1",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key", "claim_text"],
                    "match_score": 0.93,
                }
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [{"id": 101, "claim_text": "企业已恢复生产", "confidence": 0.95}],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [{"id": 101, "claim_text": "企业已恢复生产"}],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "新证据显示企业已恢复生产",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [{"entity_temp_id": "entity_1", "entity_key": "entity-key-1"}],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "企业已恢复生产",
                    "entity_temp_id": "entity_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [41]
    ledger_row = fake_kg.ledger_rows[0][1][0]
    assert ledger_row["new_relation_id"] is None
    assert ledger_row["superseded_relation_id"] is None


def test_reconcile_graph_delta_does_not_supersede_cross_topic_entity_claims(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 24,
                    "claim_type": "entity_fact",
                    "claim_text": "钟山区老鹰山镇晨光煤矿已被贵州省六盘水市中级人民法院裁定宣告破产",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key", "claim_text"],
                    "match_score": 0.80,
                },
                {
                    "claim_id": 25,
                    "claim_type": "entity_fact",
                    "claim_text": "钟山区老鹰山镇晨光煤矿清算净值为负债188,283,103.12元，资产评估总价值为121,219,380元，明显资不抵债",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key", "claim_text"],
                    "match_score": 0.74,
                },
            ]
        }
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "第二次债权人会议于2025年3月23日下午2:30在六盘水市钟山大道时代假日酒店举行",
                }
            ],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充二债会材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                }
            ],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "第二次债权人会议于2025年3月23日下午2:30在六盘水市钟山大道时代假日酒店举行",
                    "claim_type": "entity_fact",
                    "entity_temp_id": "entity_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == []
    assert result["superseded_relation_ids"] == []
    assert fake_kg.superseded_claim_calls == []
    assert fake_kg.ledger_rows == []


def test_reconcile_graph_delta_still_supersedes_same_topic_entity_claims(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 29,
                    "claim_type": "entity_fact",
                    "claim_text": "第二次债权人会议于2025年3月23日下午2:30在六盘水市钟山大道时代假日酒店召开",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key", "claim_text"],
                    "match_score": 0.77,
                }
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "第二次债权人会议于2025年3月23日下午2:30在六盘水市钟山大道时代假日酒店举行",
                }
            ],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "第二次债权人会议于2025年3月23日下午2:30在六盘水市钟山大道时代假日酒店举行",
                }
            ],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充二债会材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                }
            ],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "第二次债权人会议于2025年3月23日下午2:30在六盘水市钟山大道时代假日酒店举行",
                    "claim_type": "entity_fact",
                    "entity_temp_id": "entity_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [29]
    assert fake_kg.superseded_claim_calls == [[29]]
    assert fake_kg.fetch_candidate_calls[0]["exclude_claim_ids"] == [101]


def test_reconcile_graph_delta_allows_same_family_cross_type_supersede(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 28,
                    "claim_type": "risk_signal",
                    "claim_text": "第一次债权人会议上无人提出重整、和解申请，无和解重整可能性",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key", "claim_text"],
                    "match_score": 0.80,
                }
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "在第一次债权人会议上，无人提出重整或和解申请",
                }
            ],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {"get_llm_config": lambda self, role: {"api_key": ""}},
        )(),
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "在第一次债权人会议上，无人提出重整或和解申请",
                }
            ],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充一债会材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                }
            ],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "在第一次债权人会议上，无人提出重整或和解申请",
                    "claim_type": "entity_fact",
                    "entity_temp_id": "entity_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [28]
    assert fake_kg.superseded_claim_calls == [[28]]


def test_reconcile_graph_delta_supersedes_exact_text_duplicate(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 39,
                    "claim_type": "entity_fact",
                    "claim_text": "贵州省六盘水市中级人民法院于2024年5月23日裁定受理钟山区老鹰山镇晨光煤矿破产清算案",
                    "entity_key": "",
                    "canonical_name": "",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["claim_text"],
                    "match_score": 0.73,
                }
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "贵州省六盘水市中级人民法院于2024年5月23日裁定受理钟山区老鹰山镇晨光煤矿破产清算案",
                }
            ],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {"get_llm_config": lambda self, role: {"api_key": ""}},
        )(),
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "贵州省六盘水市中级人民法院于2024年5月23日裁定受理钟山区老鹰山镇晨光煤矿破产清算案",
                }
            ],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充受理裁定材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "贵州省六盘水市中级人民法院于2024年5月23日裁定受理钟山区老鹰山镇晨光煤矿破产清算案",
                    "claim_type": "entity_fact",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [39]
    assert fake_kg.superseded_claim_calls == [[39]]


def test_reconcile_graph_delta_fallback_supersedes_multiple_split_claims(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 82,
                    "claim_type": "risk_signal",
                    "claim_text": "钟山区老鹰山镇晨光煤矿资不抵债，清算净值为负债188,283,103.12元",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key"],
                    "match_score": 0.45,
                },
                {
                    "claim_id": 83,
                    "claim_type": "risk_signal",
                    "claim_text": "钟山区老鹰山镇晨光煤矿资产评估总价值为121,219,380元",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key"],
                    "match_score": 0.45,
                },
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "risk_signal",
                    "claim_text": "钟山区老鹰山镇晨光煤矿清算净值为负债188,283,103.12元，资产评估总价值为121,219,380元，明显资不抵债",
                }
            ],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {"get_llm_config": lambda self, role: {"api_key": ""}},
        )(),
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "risk_signal",
                    "claim_text": "钟山区老鹰山镇晨光煤矿清算净值为负债188,283,103.12元，资产评估总价值为121,219,380元，明显资不抵债",
                }
            ],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充资不抵债材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                }
            ],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "钟山区老鹰山镇晨光煤矿清算净值为负债188,283,103.12元，资产评估总价值为121,219,380元，明显资不抵债",
                    "claim_type": "risk_signal",
                    "entity_temp_id": "entity_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == [82, 83]
    assert fake_kg.superseded_claim_calls == [[82, 83]]


def test_reconcile_graph_delta_fallback_keeps_more_specific_bankruptcy_claim(monkeypatch):
    fake_kg = FakeKGService(
        candidates={
            "candidates": [
                {
                    "claim_id": 30,
                    "claim_type": "entity_fact",
                    "claim_text": "钟山区老鹰山镇晨光煤矿已被贵州省六盘水市中级人民法院裁定宣告破产",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                    "relation_key": "",
                    "relation_id": 0,
                    "matched_by": ["entity_key", "claim_text"],
                    "match_score": 0.80,
                }
            ]
        },
        snapshot={
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "钟山区老鹰山镇晨光煤矿已被宣告破产",
                }
            ],
            "claim_traces": [],
            "reconciliation_items": [],
            "evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "claim_count": 1,
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {"get_llm_config": lambda self, role: {"api_key": ""}},
        )(),
    )

    initial_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "entities": [],
            "relations": [],
            "claims": [
                {
                    "id": 101,
                    "claim_type": "entity_fact",
                    "claim_text": "钟山区老鹰山镇晨光煤矿已被宣告破产",
                }
            ],
            "claim_traces": [],
            "evidence_count": 0,
        },
    )

    result = reconcile_graph_delta(
        {
            "current_case_id": 116,
            "query": "补充破产材料",
            "chunk_ids": ["chunk-1"],
            "kg_subgraph_ref": initial_ref,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "canonical_name": "钟山区老鹰山镇晨光煤矿",
                }
            ],
            "kg_relations": [],
            "kg_claims": [
                {
                    "claim_text": "钟山区老鹰山镇晨光煤矿已被宣告破产",
                    "claim_type": "entity_fact",
                    "entity_temp_id": "entity_1",
                    "evidence_chunk_ids": ["chunk-1"],
                }
            ],
        }
    )

    assert result["superseded_claim_ids"] == []
    assert fake_kg.superseded_claim_calls == []
