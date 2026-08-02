from ai_hunter.app.graph.nodes.normalize_entities import normalize_entities
from ai_hunter.app.services.graph_identity import build_entity_key, build_relation_key


def test_normalize_entities_fills_entity_and_relation_keys():
    result = normalize_entities(
        {
            "current_case_id": 116,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_type": "company",
                    "name": "晨光 煤矿",
                },
                {
                    "entity_temp_id": "entity_2",
                    "entity_type": "person",
                    "name": " 张三 ",
                    "status": "invalid",
                },
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "relation_1",
                    "from_entity_temp_id": "entity_1",
                    "to_entity_temp_id": "entity_2",
                    "relation_type": "guarantee",
                    "relation_label": " 提供担保 ",
                    "amount": "1000000.00",
                    "amount_currency": "cny",
                    "event_date": "2024-01-01",
                }
            ],
            "kg_claims": [
                {
                    "claim_type": "relation_fact",
                    "claim_text": "晨光煤矿为张三提供担保",
                    "entity_temp_id": "entity_1",
                    "relation_temp_id": "relation_1",
                    "confidence": 0.9,
                }
            ],
        }
    )

    entity_1 = result["kg_entities"][0]
    entity_2 = result["kg_entities"][1]
    relation = result["kg_relations"][0]
    claim = result["kg_claims"][0]

    assert entity_1["normalized_name"] == "晨光煤矿"
    assert entity_1["status"] == "active"
    assert entity_1["entity_key"] == build_entity_key(
        case_id=116,
        entity_type="company",
        normalized_name="晨光煤矿",
    )
    assert entity_2["status"] == "invalid"
    assert relation["status"] == "active"
    assert relation["relation_key"] == build_relation_key(
        case_id=116,
        relation_type="guarantee",
        from_entity_key=entity_1["entity_key"],
        to_entity_key=entity_2["entity_key"],
        relation_label="提供担保",
        amount="1000000.00",
        amount_currency="cny",
        event_date="2024-01-01",
    )
    assert relation["from_entity_key"] == entity_1["entity_key"]
    assert relation["to_entity_key"] == entity_2["entity_key"]
    assert claim["entity_key"] == entity_1["entity_key"]
    assert claim["entity_name"] == "晨光煤矿"
    assert claim["relation_key"] == relation["relation_key"]


def test_normalize_entities_coerces_unknown_status_to_active():
    result = normalize_entities(
        {
            "current_case_id": 116,
            "kg_entities": [{"entity_temp_id": "entity_1", "entity_type": "company", "name": "晨光煤矿", "status": "weird"}],
            "kg_relations": [],
        }
    )

    assert result["kg_entities"][0]["status"] == "active"
