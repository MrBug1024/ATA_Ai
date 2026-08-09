from ai_hunter.app.graph.nodes.extract_entities_relations import (
    _build_fallback_bundle,
    _claim_semantic_family,
)
from ai_hunter.app.graph.nodes.normalize_entities import normalize_entities
from ai_hunter.app.graph.nodes.reconcile_graph_delta import _claim_semantic_family as reconcile_family
from ai_hunter.app.services.case_evidence import rank_case_evidence


def test_fallback_graph_anchors_to_audited_entity_and_source_chunk():
    bundle = _build_fallback_bundle(
        {"current_case_id": 7, "current_entity_name": "示例制造有限公司"},
        ["chunk-annual-1"],
    )
    assert bundle["entities"][0]["canonical_name"] == "示例制造有限公司"
    assert bundle["relations"] == []
    assert bundle["claims"][0]["evidence_chunk_ids"] == ["chunk-annual-1"]


def test_normalize_entities_maps_business_roles_and_keeps_missing_relation_endpoints_unresolved():
    normalized = normalize_entities(
        {
            "current_case_id": 7,
            "kg_entities": [
                {"entity_temp_id": "e1", "entity_type": "bank_account", "name": "银行账户"},
            ],
            "kg_relations": [
                {
                    "relation_temp_id": "r1",
                    "from_entity_temp_id": "e1",
                    "to_entity_temp_id": "missing",
                    "relation_type": "关联",
                }
            ],
            "kg_claims": [],
        }
    )

    assert normalized["kg_entities"][0]["entity_type"] == "account"
    assert normalized["kg_relations"][0]["relation_type"] == "related_to"
    assert normalized["kg_relations"][0]["relation_key"] == ""
    assert normalized["kg_relations"][0]["missing_dependencies"] == ["to_entity"]


def test_claim_families_cover_annual_audit_facts():
    assert _claim_semantic_family("营业收入截止性测试发现跨期确认") == "revenue_recognition"
    assert reconcile_family("应收账款期末余额与总账不一致") == "receivable_aging"
    assert reconcile_family("银行对账单存在未达账项") == "bank_transaction"


def test_evidence_ranking_prefers_matching_annual_audit_quote():
    traces = [
        {
            "citation_id": "1",
            "claim_id": 11,
            "claim_text": "收入截止性存在异常",
            "evidences": [{"chunk_id": "c1", "quote_text": "12月收入对应1月出库单"}],
        },
        {
            "citation_id": "2",
            "claim_id": 12,
            "claim_text": "银行账户已函证",
            "evidences": [{"chunk_id": "c2", "quote_text": "银行函证已回函"}],
        },
    ]
    ranked = rank_case_evidence(traces, "收入截止性出库单", limit=2)
    assert ranked[0]["chunk_id"] == "c1"
