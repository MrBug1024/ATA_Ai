from ai_hunter.annual_audit.knowledge_graph_projection import (
    annual_finding_key,
    project_annual_findings_to_knowledge_graph,
)


def _finding(*, bound: bool = True) -> dict:
    return {
        "analysis_run_id": 41,
        "finding_type": "period_end_transactions",
        "risk_level": "high",
        "title": "期末存在大额资金流水",
        "description": "规则命中 1 条，需核查交易背景。",
        "amount": "1000000",
        "evidence_refs": [
            {
                "source_locator": {
                    "source_file_id": 101 if bound else 0,
                    "source_page_id": 201 if bound else 0,
                    "source_chunk_id": "a" * 64 if bound else "",
                    "file_name": "银行流水.xlsx",
                    "sheet_name": "流水明细",
                    "page_no": 2,
                    "row_number": 88,
                    "row_start": 88,
                    "row_end": 88,
                    "cell_range": "A88:H88",
                    "quote_text": "2025-12-31 | 1000000 | 甲公司",
                }
            }
        ],
    }


class _ProjectionGraphService:
    def __init__(self):
        self.calls: dict[str, list] = {
            "entities": [],
            "relations": [],
            "claims": [],
            "evidences": [],
            "runs": [],
        }

    def find_active_annual_projection_claims(self, **_kwargs):
        return []

    def upsert_entities(self, *, rows, **_kwargs):
        self.calls["entities"].append(rows)
        return [
            {"id": index, "entity_key": row["entity_key"]}
            for index, row in enumerate(rows, start=1)
        ]

    def upsert_relations(self, *, rows, **_kwargs):
        self.calls["relations"].append(rows)
        return [
            {"id": index + 100, "relation_key": row["relation_key"]}
            for index, row in enumerate(rows, start=1)
        ]

    def create_extraction_run(self, **kwargs):
        self.calls["runs"].append(kwargs)
        return 401

    def insert_claims(self, *, rows, **_kwargs):
        self.calls["claims"].append(rows)
        return [
            {
                "id": index + 500,
                "entity_id": row["entity_id"],
                "relation_id": row["relation_id"],
            }
            for index, row in enumerate(rows, start=1)
        ]

    def insert_evidence_links(self, rows):
        self.calls["evidences"].append(rows)
        return []

    def complete_extraction_run(self, _run_id):
        return None

    def fail_extraction_run(self, _run_id, _message):
        raise AssertionError("a valid projection must not fail")


def test_bound_deterministic_finding_projects_to_graph_claim_relation_and_chunk():
    service = _ProjectionGraphService()

    result = project_annual_findings_to_knowledge_graph(
        case_id=7,
        entity_name="示例制造有限公司",
        findings=[_finding()],
        analysis_rules_version="rules-v1",
        kg_service=service,
    )

    finding_key = annual_finding_key(_finding())
    trace = result["trace_by_finding_key"][finding_key]
    assert trace["claim_id"] == 501
    assert trace["entity_id"] == 2
    assert trace["_graph_backed"] is True
    assert trace["evidences"][0]["chunk_id"] == "a" * 64
    assert service.calls["claims"][0][0]["claim_value"]["source_kind"] == "annual_rule"
    assert service.calls["claims"][0][0]["claim_value"]["annual_finding_key"] == finding_key
    assert service.calls["relations"][0][0]["relation_type"] == "audit_finding"
    assert service.calls["evidences"][0] == [
        {
            "claim_id": 501,
            "chunk_id": "a" * 64,
            "file_id": 101,
            "page_no": 2,
            "quote_text": "2025-12-31 | 1000000 | 甲公司",
            "bbox_list": [],
            "score": 1.0,
        }
    ]


def test_unbound_finding_is_not_projected_or_mislabeled_as_graph_evidence():
    service = _ProjectionGraphService()

    result = project_annual_findings_to_knowledge_graph(
        case_id=7,
        entity_name="示例制造有限公司",
        findings=[_finding(bound=False)],
        kg_service=service,
    )

    assert result["trace_by_finding_key"] == {}
    assert result["projected_count"] == 0
    assert service.calls["entities"] == []
    assert service.calls["claims"] == []
