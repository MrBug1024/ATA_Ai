from ai_hunter.app.graph.heavy_state import put_heavy_payload
from ai_hunter.app.graph.nodes.extract_entities_relations import extract_entities_relations
from ai_hunter.app.services.graph_identity import build_entity_key, build_relation_key, normalize_entity_name


class FakeKGService:
    def __init__(self):
        self.created_runs = []
        self.completed_runs = []
        self.failed_runs = []

    def create_extraction_run(self, **kwargs):
        self.created_runs.append(kwargs)
        return 501

    def complete_extraction_run(self, run_id, status="completed"):
        self.completed_runs.append((run_id, status))

    def fail_extraction_run(self, run_id, error_message):
        self.failed_runs.append((run_id, error_message))


def test_extract_entities_relations_falls_back_without_llm(monkeypatch):
    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "钟山区老鹰山镇晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "aggregated_text": "钟山区老鹰山镇晨光煤矿进入破产重整程序。",
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_entities"][0]["name"] == "钟山区老鹰山镇晨光煤矿"
    expected_entity_key = build_entity_key(
        case_id=116,
        entity_type="company",
        normalized_name=normalize_entity_name("钟山区老鹰山镇晨光煤矿"),
    )
    assert result["kg_entities"][0]["entity_key"] == expected_entity_key
    assert result["kg_relations"][0]["relation_type"] == "bankruptcy_participant"
    assert result["kg_relations"][0]["relation_key"] == build_relation_key(
        case_id=116,
        relation_type="bankruptcy_participant",
        from_entity_key=expected_entity_key,
        to_entity_key=expected_entity_key,
        relation_label="案件主体",
    )
    assert fake_kg.created_runs[0]["chunk_count"] == 1
    assert fake_kg.completed_runs == []


def test_extract_entities_relations_uses_structured_llm_when_configured(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            message_text = messages[1].content
            assert "chunk-1" in message_text
            return type(
                "FakeBundle",
                (),
                {
                    "model_dump": lambda self: {
                        "entities": [
                            {
                                "entity_temp_id": "entity_1",
                                "entity_type": "company",
                                "name": "晨光煤矿",
                                "aliases": [],
                                "attributes": {"role": "debtor"},
                                "evidence_chunk_ids": ["chunk-1", "chunk-x"],
                                "confidence": 0.91,
                            }
                        ],
                        "relations": [
                            {
                                "relation_temp_id": "relation_1",
                                "from_entity_temp_id": "entity_1",
                                "to_entity_temp_id": "entity_1",
                                "relation_type": "bankruptcy_participant",
                                "relation_label": "案件主体",
                                "amount": None,
                                "amount_currency": "CNY",
                                "event_date": None,
                                "attributes": {},
                                "evidence_chunk_ids": ["chunk-1", "ghost-chunk"],
                                "confidence": 0.88,
                            }
                        ],
                        "claims": [
                            {
                                "claim_type": "entity_fact",
                                "claim_text": "晨光煤矿为案件主体",
                                "entity_temp_id": "entity_1",
                                "relation_temp_id": "relation_1",
                                "claim_value": {},
                                "evidence_chunk_ids": ["chunk-1", "missing"],
                                "confidence": 0.9,
                            }
                        ],
                    }
                },
            )()

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

    fake_kg = FakeKGService()
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "files": [{"id": 11, "file_name": "sample.pdf"}],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "page_no": 1,
                    "chunk_type": "text",
                    "chunk_text": "晨光煤矿进入破产重整程序。",
                }
            ],
        },
    )

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_entities"][0]["evidence_chunk_ids"] == ["chunk-1"]
    assert result["kg_relations"][0]["evidence_chunk_ids"] == ["chunk-1"]
    assert result["kg_claims"][0]["evidence_chunk_ids"] == ["chunk-1"]
    assert fake_kg.completed_runs == [(501, "completed")]
    assert fake_kg.failed_runs == []


def test_extract_entities_relations_rejects_uncited_model_output_and_uses_fallback(monkeypatch):
    uncited_bundle = type(
        "FakeBundle",
        (),
        {
            "model_dump": lambda self: {
                "entities": [
                    {
                        "entity_temp_id": "entity_1",
                        "entity_type": "company",
                        "name": "正华矿业",
                        "aliases": [],
                        "attributes": {},
                        "evidence_chunk_ids": [],
                        "confidence": 0.9,
                    }
                ],
                "relations": [],
                "claims": [
                    {
                        "claim_type": "entity_fact",
                        "claim_text": "正华矿业进入重整程序",
                        "entity_temp_id": "entity_1",
                        "claim_value": {},
                        "evidence_chunk_ids": [],
                        "confidence": 0.9,
                    }
                ],
            }
        },
    )()

    class FakeLLM:
        def with_structured_output(self, schema):
            return type("FakeStructuredLLM", (), {"invoke": lambda self, messages: uncited_bundle})()

        def invoke(self, messages):
            return type("FakeRawResponse", (), {"content": "entities: []\nrelations: []\nclaims: []"})()

    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 118,
            "current_debtor_name": "贵州正华矿业有限公司",
            "chunk_ids": ["chunk-1"],
            "aggregated_text": "贵州正华矿业有限公司进入破产重整程序。",
        }
    )

    assert fake_kg.completed_runs == []
    assert fake_kg.failed_runs[0][0] == 501
    assert result["kg_claims"][0]["evidence_chunk_ids"] == ["chunk-1"]
    assert result["kg_entities"][0]["evidence_chunk_ids"] == ["chunk-1"]


def test_extract_entities_relations_salvages_sectioned_json_when_structured_output_fails(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            raise ValueError("Invalid JSON: expected value at line 2 column 1")

    class FakeRawResponse:
        content = """
entities
{"entity_temp_id":"entity_1","entity_type":"company","name":"晨光煤矿","aliases":[],"attributes":{"role":"debtor"},"evidence_chunk_ids":["chunk-1"],"confidence":0.91}

relations
{"relation_temp_id":"relation_1","from_entity_temp_id":"entity_1","to_entity_temp_id":"entity_1","relation_type":"bankruptcy_participant","relation_label":"案件主体","amount":null,"amount_currency":"CNY","event_date":null,"attributes":{},"evidence_chunk_ids":["chunk-1"],"confidence":0.88}

claims
{"claim_type":"entity_fact","claim_text":"晨光煤矿为案件主体","entity_temp_id":"entity_1","relation_temp_id":"relation_1","claim_value":{},"evidence_chunk_ids":["chunk-1"],"confidence":0.9}
"""

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

        def invoke(self, messages):
            return FakeRawResponse()

    fake_kg = FakeKGService()
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "files": [{"id": 11, "file_name": "sample.pdf"}],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "page_no": 1,
                    "chunk_type": "text",
                    "chunk_text": "晨光煤矿进入破产重整程序。",
                }
            ],
        },
    )

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_entities"][0]["name"] == "晨光煤矿"
    assert result["kg_relations"][0]["relation_type"] == "bankruptcy_participant"
    assert result["kg_claims"][0]["claim_text"] == "晨光煤矿为案件主体"
    assert fake_kg.completed_runs == [(501, "completed")]
    assert fake_kg.failed_runs == []


def test_extract_entities_relations_salvages_exception_embedded_output(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            raise ValueError(
                "1 validation error for ExtractionBundleModel\n"
                "  Invalid JSON: expected value at line 1 column 1 "
                "[type=json_invalid, input_value='entities:\\n[\\n"
                "  {\\n"
                '    "entity_temp_id": "entity_1",\\n'
                '    "entity_type": "company",\\n'
                '    "name": "晨光煤矿",\\n'
                '    "aliases": [],\\n'
                '    "attributes": {"role": "debtor"},\\n'
                '    "evidence_chunk_ids": ["chunk-1"],\\n'
                '    "confidence": 0.91\\n'
                "  }\\n"
                "]\\n\\n"
                "relations:\\n[\\n"
                "  {\\n"
                '    "relation_temp_id": "relation_1",\\n'
                '    "from_entity_temp_id": "entity_1",\\n'
                '    "to_entity_temp_id": "entity_1",\\n'
                '    "relation_type": "bankruptcy_participant",\\n'
                '    "relation_label": "案件主体",\\n'
                '    "amount": null,\\n'
                '    "amount_currency": "CNY",\\n'
                '    "event_date": null,\\n'
                '    "attributes": {},\\n'
                '    "evidence_chunk_ids": ["chunk-1"],\\n'
                '    "confidence": 0.88\\n'
                "  }\\n"
                "]\\n\\n"
                "claims:\\n[\\n"
                "  {\\n"
                '    "claim_type": "entity_fact",\\n'
                '    "claim_text": "晨光煤矿为案件主体",\\n'
                '    "entity_temp_id": "entity_1",\\n'
                '    "relation_temp_id": "relation_1",\\n'
                '    "claim_value": {},\\n'
                '    "evidence_chunk_ids": ["chunk-1"],\\n'
                '    "confidence": 0.9\\n'
                "  }\\n"
                "]', input_type=str]"
            )

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

        def invoke(self, messages):
            raise AssertionError("raw invoke should not be needed when exception already embeds the content")

    fake_kg = FakeKGService()
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "files": [{"id": 11, "file_name": "sample.pdf"}],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "page_no": 1,
                    "chunk_type": "text",
                    "chunk_text": "晨光煤矿进入破产重整程序。",
                }
            ],
        },
    )

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_entities"][0]["name"] == "晨光煤矿"
    assert result["kg_relations"][0]["relation_type"] == "bankruptcy_participant"
    assert result["kg_claims"][0]["claim_text"] == "晨光煤矿为案件主体"
    assert fake_kg.completed_runs == [(501, "completed")]
    assert fake_kg.failed_runs == []


def test_extract_entities_relations_salvages_yaml_like_raw_output(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            raise ValueError("structured parser rejected yaml-like content")

    class FakeRawResponse:
        content = """
entities:
- entity_id: "ent_1"
  entity_temp_id: "ent_1"
  entity_type: "enterprise"
  name: "晨光煤矿"
  chunk_ids:
    - "chunk-1"
  attributes: "破产状态"

relations:
- relation_id: "rel_1"
  relation_temp_id: "rel_1"
  relation_type: "bankruptcy_participant"
  from_entity_id: "ent_1"
  to_entity_id: "ent_1"
  chunk_ids:
    - "chunk-1"
  attributes: "申请时间2024年4月25日"

claims:
- claim_id: "clm_1"
  claim_text: "晨光煤矿进入破产程序"
  chunk_ids:
    - "chunk-1"
  confidence: 0.95
"""

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

        def invoke(self, messages):
            return FakeRawResponse()

    fake_kg = FakeKGService()
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "files": [{"id": 11, "file_name": "sample.pdf"}],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "page_no": 1,
                    "chunk_type": "text",
                    "chunk_text": "晨光煤矿进入破产重整程序。",
                }
            ],
        },
    )

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_entities"][0]["entity_type"] == "enterprise"
    assert result["kg_entities"][0]["attributes"] == {"summary": "破产状态"}
    assert result["kg_relations"][0]["from_entity_temp_id"] == "ent_1"
    assert result["kg_claims"][0]["claim_text"] == "晨光煤矿进入破产程序"
    assert fake_kg.completed_runs == [(501, "completed")]
    assert fake_kg.failed_runs == []


def test_extract_entities_relations_salvages_inline_keyed_json_sections(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            raise ValueError("structured parser rejected inline keyed content")

    class FakeRawResponse:
        content = """
entities:[{"entity_temp_id":"entity_1","entity_type":"company","name":"晨光煤矿","aliases":[],"attributes":{},"evidence_chunk_ids":["chunk-1"],"confidence":0.91}]
relations:[{"relation_temp_id":"relation_1","from_entity_temp_id":"entity_1","to_entity_temp_id":"entity_1","relation_type":"bankruptcy_participant","relation_label":"案件主体","amount":null,"amount_currency":"CNY","event_date":null,"attributes":{},"evidence_chunk_ids":["chunk-1"],"confidence":0.88}]
claims:[{"claim_type":"entity_fact","claim_text":"晨光煤矿为案件主体","entity_temp_id":"entity_1","relation_temp_id":"relation_1","claim_value":{},"evidence_chunk_ids":["chunk-1"],"confidence":0.9}]
"""

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

        def invoke(self, messages):
            return FakeRawResponse()

    fake_kg = FakeKGService()
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "files": [{"id": 11, "file_name": "sample.pdf"}],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "page_no": 1,
                    "chunk_type": "text",
                    "chunk_text": "晨光煤矿进入破产重整程序。",
                }
            ],
        },
    )

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_entities"][0]["name"] == "晨光煤矿"
    assert result["kg_relations"][0]["relation_type"] == "bankruptcy_participant"
    assert result["kg_claims"][0]["claim_text"] == "晨光煤矿为案件主体"
    assert fake_kg.completed_runs == [(501, "completed")]
    assert fake_kg.failed_runs == []


def test_extract_entities_relations_salvages_minimax_alias_sections(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            raise ValueError("structured parser rejected minimax alias content")

    class FakeRawResponse:
        content = """
entities
[
  {"entity_temp_id": "E1", "entity_type": "企业", "entity_name": "晨光煤矿", "chunk_ids": ["chunk-1"]},
  {"entity_temp_id": "E2", "entity_type": "自然人", "entity_name": "庞启军", "chunk_ids": ["chunk-1"]}
]

relations
[
  {"relation_temp_id": "R1", "relation_type": "bankruptcy_applicant", "from_entity_id": "E2", "to_entity_id": "E1", "chunk_ids": ["chunk-1"]}
]

claims
[
  {"claim_text": "庞启军申请晨光煤矿破产清算", "chunk_ids": ["chunk-1"], "confidence": 1.0}
]
"""

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

        def invoke(self, messages):
            return FakeRawResponse()

    fake_kg = FakeKGService()
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "files": [{"id": 11, "file_name": "sample.pdf"}],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "page_no": 1,
                    "chunk_type": "text",
                    "chunk_text": "晨光煤矿进入破产重整程序。",
                }
            ],
        },
    )

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "minimax",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "MiniMax-M2.7",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_entities"][0]["name"] == "晨光煤矿"
    assert result["kg_entities"][0]["confidence"] == 0.8
    assert result["kg_relations"][0]["from_entity_temp_id"] == "E2"
    assert result["kg_claims"][0]["claim_type"] == "entity_fact"
    assert fake_kg.completed_runs == [(501, "completed")]
    assert fake_kg.failed_runs == []


def test_extract_entities_relations_normalizes_claim_types_by_text_and_relation(monkeypatch):
    class FakeStructuredLLM:
        def invoke(self, messages):
            return type(
                "FakeBundle",
                (),
                {
                    "model_dump": lambda self: {
                        "entities": [
                            {
                                "entity_temp_id": "entity_1",
                                "entity_type": "company",
                                "name": "晨光煤矿",
                                "aliases": [],
                                "attributes": {},
                                "evidence_chunk_ids": ["chunk-1"],
                                "confidence": 0.91,
                            }
                        ],
                        "relations": [
                            {
                                "relation_temp_id": "relation_1",
                                "from_entity_temp_id": "entity_1",
                                "to_entity_temp_id": "entity_1",
                                "relation_type": "bankruptcy_participant",
                                "relation_label": "申请破产清算",
                                "attributes": {},
                                "evidence_chunk_ids": ["chunk-1"],
                                "confidence": 0.88,
                            }
                        ],
                        "claims": [
                            {
                                "claim_type": "entity_fact",
                                "claim_text": "第一次债权人会议上无人提出重整、和解申请，无和解、重整可能性",
                                "entity_temp_id": "entity_1",
                                "claim_value": {},
                                "evidence_chunk_ids": ["chunk-1"],
                                "confidence": 0.9,
                            },
                            {
                                "claim_type": "entity_fact",
                                "claim_text": "庞启军于2024年4月25日申请对晨光煤矿进行破产清算",
                                "entity_temp_id": "entity_1",
                                "relation_temp_id": "relation_1",
                                "claim_value": {},
                                "evidence_chunk_ids": ["chunk-1"],
                                "confidence": 0.9,
                            },
                        ],
                    }
                },
            )()

    class FakeLLM:
        def with_structured_output(self, schema):
            return FakeStructuredLLM()

    fake_kg = FakeKGService()
    chunk_batch_ref = put_heavy_payload(
        "kg_chunk_batch",
        {
            "files": [{"id": 11, "file_name": "sample.pdf"}],
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "page_no": 1,
                    "chunk_type": "text",
                    "chunk_text": "第一次债权人会议上无人提出重整、和解申请。",
                }
            ],
        },
    )

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.build_agent_llm",
        lambda: FakeLLM(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.load_prompt",
        lambda _: "extract prompt",
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "test-key",
                    "base_url": "https://example.com/v1",
                    "model": "gpt-test",
                }
            },
        )(),
    )

    result = extract_entities_relations(
        {
            "current_case_id": 116,
            "current_debtor_name": "晨光煤矿",
            "chunk_ids": ["chunk-1"],
            "chunk_batch_ref": chunk_batch_ref,
        }
    )

    assert result["kg_claims"][0]["claim_type"] == "risk_signal"
    assert result["kg_claims"][1]["claim_type"] == "relation_fact"
