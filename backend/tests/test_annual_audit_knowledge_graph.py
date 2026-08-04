from ai_hunter.app.graph.nodes.extract_entities_relations import (
    _build_fallback_bundle,
    _claim_semantic_family,
)
from ai_hunter.app.graph.nodes.reconcile_graph_delta import _claim_semantic_family as reconcile_family
from ai_hunter.app.services.case_evidence import rank_case_evidence


def test_fallback_graph_anchors_to_audited_entity_and_source_chunk():
    bundle = _build_fallback_bundle(
        {"current_case_id": 7, "current_entity_name": "示例制造有限公司"},
        ["chunk-annual-1"],
    )
    assert bundle["entities"][0]["canonical_name"] == "示例制造有限公司"
    assert bundle["relations"][0]["relation_type"] == "audited_entity"
    assert bundle["claims"][0]["evidence_chunk_ids"] == ["chunk-annual-1"]


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
