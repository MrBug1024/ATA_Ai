from ai_hunter.app.graph.nodes.normalize_entities import normalize_entities
from ai_hunter.app.services.graph_identity import build_entity_key, build_relation_key


def test_normalize_entities_fills_annual_entity_and_relation_keys():
    result = normalize_entities(
        {
            "current_case_id": 7,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_type": "company",
                    "name": "示例制造 有限公司",
                },
                {
                    "entity_temp_id": "entity_2",
                    "entity_type": "customer",
                    "name": " 示例客户有限公司 ",
                    "status": "invalid",
                },
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "relation_1",
                    "from_entity_temp_id": "entity_1",
                    "to_entity_temp_id": "entity_2",
                    "relation_type": "sales_transaction",
                    "relation_label": " 销售商品 ",
                    "amount": "1000000.00",
                    "amount_currency": "cny",
                    "event_date": "2025-12-20",
                }
            ],
            "kg_claims": [
                {
                    "claim_type": "relation_fact",
                    "claim_text": "示例制造有限公司向示例客户有限公司销售商品",
                    "entity_temp_id": "entity_1",
                    "relation_temp_id": "relation_1",
                    "confidence": 0.9,
                }
            ],
        }
    )

    entity = result["kg_entities"][0]
    customer = result["kg_entities"][1]
    relation = result["kg_relations"][0]
    claim = result["kg_claims"][0]
    assert entity["normalized_name"] == "示例制造有限公司"
    assert entity["status"] == "active"
    assert entity["entity_key"] == build_entity_key(
        case_id=7,
        entity_type="company",
        normalized_name="示例制造有限公司",
    )
    assert customer["status"] == "invalid"
    assert relation["status"] == "active"
    assert relation["relation_key"] == build_relation_key(
        case_id=7,
        relation_type="sales_transaction",
        from_entity_key=entity["entity_key"],
        to_entity_key=customer["entity_key"],
        relation_label="销售商品",
        amount="1000000.00",
        amount_currency="cny",
        event_date="2025-12-20",
    )
    assert claim["entity_key"] == entity["entity_key"]
    assert claim["entity_name"] == "示例制造有限公司"
    assert claim["relation_key"] == relation["relation_key"]


def test_normalize_entities_coerces_unknown_status_to_active():
    result = normalize_entities(
        {
            "current_case_id": 7,
            "kg_entities": [
                {
                    "entity_temp_id": "entity_1",
                    "entity_type": "company",
                    "name": "示例制造有限公司",
                    "status": "unexpected",
                }
            ],
            "kg_relations": [],
        }
    )
    assert result["kg_entities"][0]["status"] == "active"
