import logging

from ai_hunter.app.graph.heavy_state import get_heavy_payload, put_heavy_payload
from ai_hunter.app.graph.nodes.persist_graph import persist_graph


class FakeKGService:
    def __init__(self):
        self.evidence_rows = []
        self.last_relation_rows = []
        self.last_claim_rows = []
        self.unresolved_payload = None
        self.pending_unresolved_relations = []
        self.pending_unresolved_claims = []
        self.active_entities = []
        self.active_relations = []
        self.resolved_updates = []
        self.chunk_lookup = {}
        self.ledger_rows = []

    def upsert_entities(self, *, case_id, rows):
        return [{"id": 11, "case_id": case_id, "entity_key": rows[0]["entity_key"], "canonical_name": "晨光煤矿"}]

    def upsert_relations(self, *, case_id, rows):
        self.last_relation_rows = rows
        returned = []
        for index, row in enumerate(rows):
            returned.append(
                {
                    "id": 21 + index,
                    "case_id": case_id,
                    "relation_key": row["relation_key"],
                    "from_entity_id": row["from_entity_id"],
                    "to_entity_id": row["to_entity_id"],
                }
            )
        return returned

    def insert_claims(self, *, case_id, extraction_run_id, rows, **kwargs):
        self.last_claim_rows = rows
        return [
            {"id": 31 + index, "claim_type": row["claim_type"], "claim_text": row["claim_text"]}
            for index, row in enumerate(rows)
        ]

    def insert_evidence_links(self, rows):
        self.evidence_rows = rows
        return [{"id": index + 1, "claim_id": row["claim_id"], "chunk_id": row["chunk_id"]} for index, row in enumerate(rows)]

    def insert_unresolved_graph_items(
        self,
        *,
        case_id,
        extraction_run_id,
        upload_batch_id="",
        material_event_id="",
        relation_rows=None,
        claim_rows=None,
    ):
        self.unresolved_payload = {
            "case_id": case_id,
            "extraction_run_id": extraction_run_id,
            "upload_batch_id": upload_batch_id,
            "material_event_id": material_event_id,
            "relation_rows": relation_rows or [],
            "claim_rows": claim_rows or [],
        }
        return {
            "unresolved_relations": [
                {"id": 91, "item_type": "relation", **row} for row in (relation_rows or [])
            ],
            "unresolved_claims": [
                {"id": 92, "item_type": "claim", **row} for row in (claim_rows or [])
            ],
        }

    def fetch_unresolved_graph_items(self, *, case_id, upload_batch_id="", status="pending", limit=50):
        return {
            "unresolved_relations": self.pending_unresolved_relations[:limit],
            "unresolved_claims": self.pending_unresolved_claims[:limit],
        }

    def fetch_active_entities(self, *, case_id, entity_keys=None, entity_names=None):
        return list(self.active_entities)

    def fetch_active_relations(self, *, case_id, relation_keys=None):
        return list(self.active_relations)

    def mark_unresolved_items_resolved(self, rows):
        self.resolved_updates = rows
        return len(rows)

    def fetch_source_chunks_by_ids(self, *, case_id, chunk_ids):
        return [self.chunk_lookup[chunk_id] for chunk_id in chunk_ids if chunk_id in self.chunk_lookup]

    def insert_reconciliation_ledger(self, *, case_id, rows):
        self.ledger_rows.append((case_id, rows))
        return [{"id": index + 1, **row} for index, row in enumerate(rows)]


def test_persist_graph_reads_evidence_from_chunk_batch_ref(monkeypatch):
    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.persist_graph.get_kg_service",
        lambda: fake_kg,
    )
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "file_id": 101,
                    "page_id": 9001,
                    "page_no": 2,
                    "anchor_text": "晨光煤矿进入破产重整程序",
                    "bbox_list": [{"x": 1, "y": 2, "w": 3, "h": 4}],
                    "page_image_ref": "minio://derived/page-2.png",
                }
            ]
        },
    )

    result = persist_graph(
        {
            "current_case_id": 116,
            "kg_extraction_run_id": 501,
            "chunk_batch_ref": chunk_batch_ref,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "entity_type": "company",
                    "canonical_name": "晨光煤矿",
                    "aliases": [],
                    "normalized_name": "晨光煤矿",
                    "attributes": {},
                    "first_seen_chunk_id": "chunk-1",
                    "confidence": 0.9,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "relation_1",
                    "relation_key": "relation-key-1",
                    "from_entity_temp_id": "entity_1",
                    "to_entity_temp_id": "entity_1",
                    "relation_type": "bankruptcy_participant",
                    "relation_label": "案件主体",
                    "direction": "directed",
                    "amount": None,
                    "amount_currency": "CNY",
                    "event_date": None,
                    "attributes": {},
                    "confidence": 0.8,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_claims": [
                {
                    "claim_type": "entity_fact",
                    "claim_text": "晨光煤矿为案件主体",
                    "entity_temp_id": "entity_1",
                    "relation_temp_id": "relation_1",
                    "claim_value": {},
                    "evidence_chunk_ids": ["chunk-1"],
                    "confidence": 0.88,
                }
            ],
        }
    )

    assert fake_kg.evidence_rows[0]["file_id"] == 101
    assert fake_kg.evidence_rows[0]["page_no"] == 2
    assert fake_kg.evidence_rows[0]["quote_text"] == "晨光煤矿进入破产重整程序"
    assert result["kg_subgraph_ref"].startswith("kg_subgraph:")
    payload = get_heavy_payload(result["kg_subgraph_ref"])
    assert payload["evidence_count"] == 1
    assert payload["claim_traces"][0]["claim_text"] == "晨光煤矿为案件主体"
    assert payload["claim_traces"][0]["evidences"][0]["page_no"] == 2
    assert payload["claim_traces"][0]["evidences"][0]["source_page_id"] == 9001
    assert payload["claim_traces"][0]["evidences"][0]["page_image_ref"] == "minio://derived/page-2.png"


def test_persist_graph_skips_orphan_relations_and_claims(monkeypatch):
    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.persist_graph.get_kg_service",
        lambda: fake_kg,
    )

    result = persist_graph(
        {
            "current_case_id": 116,
            "kg_extraction_run_id": 501,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "entity_type": "company",
                    "canonical_name": "晨光煤矿",
                    "aliases": [],
                    "normalized_name": "晨光煤矿",
                    "attributes": {},
                    "first_seen_chunk_id": "chunk-1",
                    "confidence": 0.9,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "relation_ok",
                    "relation_key": "relation-key-ok",
                    "from_entity_temp_id": "entity_1",
                    "to_entity_temp_id": "entity_1",
                    "relation_type": "bankruptcy_participant",
                    "relation_label": "案件主体",
                    "direction": "directed",
                    "amount": None,
                    "amount_currency": "CNY",
                    "event_date": None,
                    "attributes": {},
                    "confidence": 0.8,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                },
                {
                    "relation_temp_id": "relation_bad",
                    "relation_key": "relation-key-bad",
                    "from_entity_temp_id": "missing_entity",
                    "to_entity_temp_id": "entity_1",
                    "relation_type": "judge",
                    "relation_label": "无效关系",
                    "direction": "directed",
                    "amount": None,
                    "amount_currency": "CNY",
                    "event_date": None,
                    "attributes": {},
                    "confidence": 0.8,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                },
            ],
            "kg_claims": [
                {
                    "claim_type": "entity_fact",
                    "claim_text": "有效 claim",
                    "entity_temp_id": "entity_1",
                    "relation_temp_id": "relation_ok",
                    "claim_value": {},
                    "evidence_chunk_ids": [],
                    "confidence": 0.88,
                },
                {
                    "claim_type": "entity_fact",
                    "claim_text": "无效 claim",
                    "entity_temp_id": "missing_entity",
                    "relation_temp_id": "relation_bad",
                    "claim_value": {},
                    "evidence_chunk_ids": [],
                    "confidence": 0.5,
                },
            ],
            "upload_batch_id": "batch-001",
            "upload_batch_summary": {"material_event_id": "material-event:batch-001"},
        }
    )

    assert len(fake_kg.last_relation_rows) == 1
    assert fake_kg.last_relation_rows[0]["relation_key"] == "relation-key-ok"
    assert len(fake_kg.last_claim_rows) == 1
    assert fake_kg.last_claim_rows[0]["claim_text"] == "有效 claim"
    assert result["kg_subgraph_ref"].startswith("kg_subgraph:")
    assert result["unresolved_relations"][0]["relation_temp_id"] == "relation_bad"
    assert result["unresolved_relations"][0]["missing_dependencies"] == ["from_entity"]
    assert result["unresolved_claims"][0]["claim_text"] == "无效 claim"
    assert result["unresolved_claims"][0]["missing_dependencies"] == ["entity", "relation"]
    assert result["unresolved_relations"][0]["id"] == 91
    assert fake_kg.unresolved_payload["upload_batch_id"] == "batch-001"
    assert fake_kg.unresolved_payload["material_event_id"] == "material-event:batch-001"
    assert "未决关系1条，未决断言1条" in result["kg_summary"]
    payload = get_heavy_payload(result["kg_subgraph_ref"])
    assert payload["unresolved_relations"][0]["reason"] == "missing_entity_reference"
    assert payload["unresolved_claims"][0]["reason"] == "missing_graph_reference"


def test_persist_graph_skips_orphan_evidence_rows(monkeypatch, caplog):
    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.persist_graph.get_kg_service",
        lambda: fake_kg,
    )
    caplog.set_level(logging.WARNING, logger="ai_hunter.app.graph.nodes.persist_graph")

    result = persist_graph(
        {
            "current_case_id": 116,
            "kg_extraction_run_id": 501,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "entity_type": "company",
                    "canonical_name": "晨光煤矿",
                    "aliases": [],
                    "normalized_name": "晨光煤矿",
                    "attributes": {},
                    "first_seen_chunk_id": "chunk-missing",
                    "confidence": 0.9,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "relation_1",
                    "relation_key": "relation-key-1",
                    "from_entity_temp_id": "entity_1",
                    "to_entity_temp_id": "entity_1",
                    "relation_type": "bankruptcy_participant",
                    "relation_label": "案件主体",
                    "direction": "directed",
                    "amount": None,
                    "amount_currency": "CNY",
                    "event_date": None,
                    "attributes": {},
                    "confidence": 0.8,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_claims": [
                {
                    "claim_type": "entity_fact",
                    "claim_text": "引用了不存在 chunk 的 claim",
                    "entity_temp_id": "entity_1",
                    "relation_temp_id": "relation_1",
                    "claim_value": {},
                    "evidence_chunk_ids": ["chunk-missing"],
                    "confidence": 0.88,
                }
            ],
        }
    )

    assert fake_kg.evidence_rows == []
    payload = get_heavy_payload(result["kg_subgraph_ref"])
    assert payload["evidence_count"] == 0
    assert payload["claim_traces"][0]["evidences"] == []
    assert payload["skipped_evidences"][0]["chunk_id"] == "chunk-missing"
    assert payload["skipped_evidences"][0]["reason"] == "missing_source_chunk"
    assert payload["skipped_evidences"][0]["path"] == "claim"
    assert "Skipping evidence row because chunk_id was not found" in caplog.text


def test_persist_graph_replays_pending_unresolved_claims_when_later_batch_supplies_relation(monkeypatch):
    fake_kg = FakeKGService()
    fake_kg.pending_unresolved_claims = [
        {
            "id": 501,
            "item_type": "claim",
            "payload": {
                "claim_type": "relation_fact",
                "claim_text": "晨光煤矿为张三提供担保",
                "entity_name": "晨光煤矿",
                "entity_key": "entity-key-1",
                "relation_key": "relation-key-new",
                "relation_temp_id": "relation_missing",
                "claim_value": {},
                "confidence": 0.77,
                "status": "active",
                "review_status": "pending",
                "evidence_chunk_ids": ["chunk-old-1"],
            },
        }
    ]
    fake_kg.chunk_lookup = {
        "chunk-old-1": {
            "chunk_id": "chunk-old-1",
            "file_id": 401,
            "page_id": 9401,
            "page_no": 7,
            "anchor_text": "保证合同记载晨光煤矿为张三提供担保",
            "chunk_text": "保证合同记载晨光煤矿为张三提供担保",
            "bbox_list": [{"x": 9, "y": 8, "w": 7, "h": 6}],
            "page_image_ref": "minio://derived/page-7.png",
        }
    }
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.persist_graph.get_kg_service",
        lambda: fake_kg,
    )

    result = persist_graph(
        {
            "current_case_id": 116,
            "kg_extraction_run_id": 501,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "entity_type": "company",
                    "canonical_name": "晨光煤矿",
                    "aliases": [],
                    "normalized_name": "晨光煤矿",
                    "attributes": {},
                    "first_seen_chunk_id": "chunk-1",
                    "confidence": 0.9,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "relation_new",
                    "relation_key": "relation-key-new",
                    "from_entity_temp_id": "entity_1",
                    "to_entity_temp_id": "entity_1",
                    "relation_type": "guarantee",
                    "relation_label": "提供担保",
                    "direction": "directed",
                    "amount": None,
                    "amount_currency": "CNY",
                    "event_date": None,
                    "attributes": {},
                    "confidence": 0.85,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_claims": [],
        }
    )

    assert len(fake_kg.last_claim_rows) == 1
    assert fake_kg.last_claim_rows[0]["claim_text"] == "晨光煤矿为张三提供担保"
    assert any(row["chunk_id"] == "chunk-old-1" for row in fake_kg.evidence_rows)
    assert fake_kg.resolved_updates[0]["id"] == 501
    assert fake_kg.resolved_updates[0]["resolved_claim_id"] == 31
    assert fake_kg.ledger_rows[0][0] == 116


def test_persist_graph_replay_skips_invalid_chunk_backed_evidence(monkeypatch, caplog):
    fake_kg = FakeKGService()
    fake_kg.pending_unresolved_claims = [
        {
            "id": 501,
            "item_type": "claim",
            "payload": {
                "claim_type": "relation_fact",
                "claim_text": "晨光煤矿为张三提供担保",
                "entity_name": "晨光煤矿",
                "entity_key": "entity-key-1",
                "relation_key": "relation-key-new",
                "relation_temp_id": "relation_missing",
                "claim_value": {},
                "confidence": 0.77,
                "status": "active",
                "review_status": "pending",
                "evidence_chunk_ids": ["chunk-old-1"],
            },
        }
    ]
    fake_kg.chunk_lookup = {
        "chunk-old-1": {
            "chunk_id": "chunk-old-1",
            "file_id": 0,
            "page_id": 9401,
            "page_no": 7,
            "anchor_text": "保证合同记载晨光煤矿为张三提供担保",
            "chunk_text": "保证合同记载晨光煤矿为张三提供担保",
            "bbox_list": [{"x": 9, "y": 8, "w": 7, "h": 6}],
            "page_image_ref": "minio://derived/page-7.png",
        }
    }
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.persist_graph.get_kg_service",
        lambda: fake_kg,
    )
    caplog.set_level(logging.WARNING, logger="ai_hunter.app.graph.nodes.persist_graph")

    result = persist_graph(
        {
            "current_case_id": 116,
            "kg_extraction_run_id": 501,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_key": "entity-key-1",
                    "entity_type": "company",
                    "canonical_name": "晨光煤矿",
                    "aliases": [],
                    "normalized_name": "晨光煤矿",
                    "attributes": {},
                    "first_seen_chunk_id": "chunk-1",
                    "confidence": 0.9,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "relation_new",
                    "relation_key": "relation-key-new",
                    "from_entity_temp_id": "entity_1",
                    "to_entity_temp_id": "entity_1",
                    "relation_type": "guarantee",
                    "relation_label": "提供担保",
                    "direction": "directed",
                    "amount": None,
                    "amount_currency": "CNY",
                    "event_date": None,
                    "attributes": {},
                    "confidence": 0.85,
                    "source_count": 1,
                    "human_verified": False,
                    "status": "active",
                }
            ],
            "kg_claims": [],
        }
    )

    assert fake_kg.evidence_rows == []
    assert fake_kg.resolved_updates[0]["resolved_claim_id"] == 31
    payload = get_heavy_payload(result["kg_subgraph_ref"])
    replay_trace = next(item for item in payload["claim_traces"] if item["claim_id"] == 31)
    assert replay_trace["evidences"] == []
    assert payload["skipped_evidences"][0]["chunk_id"] == "chunk-old-1"
    assert payload["skipped_evidences"][0]["reason"] == "invalid_file_id"
    assert payload["skipped_evidences"][0]["path"] == "replay"
    assert "Skipping evidence row because chunk payload cannot satisfy DB foreign keys" in caplog.text
    assert fake_kg.ledger_rows[0][1][0]["action"] == "ADD"
    assert fake_kg.ledger_rows[0][1][0]["decision_payload"]["source"] == "unresolved_replay"
    payload = get_heavy_payload(result["kg_subgraph_ref"])
    assert any(item["claim_text"] == "晨光煤矿为张三提供担保" for item in payload["claim_traces"])
    assert payload["reconciliation_items"][0]["new_claim_id"] == 31
