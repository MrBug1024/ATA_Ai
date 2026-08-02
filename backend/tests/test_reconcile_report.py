import pytest
from pydantic import ValidationError

from ai_hunter.app.graph.context_loader import resolve_final_report
from ai_hunter.app.graph.heavy_state import get_heavy_payload, put_heavy_payload
from ai_hunter.app.graph.nodes.reconcile_report import reconcile_report_and_extract_tasks
from ai_hunter.app.graph.schemas import TaskItemModel


def test_task_deadline_normalizes_display_annotation_to_iso_date():
    task = TaskItemModel(
        action="复核资产净值",
        role="审计",
        deadline="2026-06-15（30 日内）",
        deliverable="复核报告",
        priority="高",
    )

    assert task.deadline == "2026-06-15"


def test_task_deadline_rejects_invalid_calendar_date():
    with pytest.raises(ValidationError, match="有效的 YYYY-MM-DD"):
        TaskItemModel(
            action="复核资产净值",
            role="审计",
            deadline="2026-02-30（30 日内）",
            deliverable="复核报告",
            priority="高",
        )


def test_reconcile_report_prefers_json_task_payload():
    result = reconcile_report_and_extract_tasks(
        {
            "report_part_a": "前四段",
            "report_part_b": """
第7段任务

```json
{
  "tasks": [
    {
      "action": "调取银行流水",
      "role": "调查",
      "deadline": "2026-05-01",
      "deliverable": "银行流水回单",
      "priority": "高"
    }
            ]
}
```
""",
        }
    )
    assert "前四段" in resolve_final_report(result)
    assert result["extracted_tasks"][0]["action"] == "调取银行流水"


def test_reconcile_report_appends_kg_trace_summary():
    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "claim_traces": [
                {
                    "claim_id": 31,
                    "claim_type": "risk_signal",
                    "claim_text": "存在关联担保",
                    "confidence": 0.91,
                    "evidences": [
                        {
                            "chunk_id": "chunk-1",
                            "file_id": 101,
                            "page_no": 2,
                            "quote_text": "晨光煤矿进入破产重整程序",
                        }
                    ],
                }
            ]
        },
    )

    result = reconcile_report_and_extract_tasks(
        {
            "report_part_a": "前四段",
            "report_part_b": "后四段",
            "kg_subgraph_ref": kg_subgraph_ref,
        }
    )

    final_report = resolve_final_report(result)
    assert "### 【知识图谱证据追溯】" in final_report
    assert "[1]" in final_report
    assert "存在关联担保" in final_report
    assert "page=2" in final_report
    assert result["trace_items"][0]["citation_id"] == "1"
    assert result["trace_items"][0]["claim_text"] == "存在关联担保"
    assert result["trace_items"][0]["evidences"][0]["page_no"] == 2


def test_reconcile_report_replaces_inline_claim_placeholders():
    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "claim_traces": [
                {
                    "claim_id": 31,
                    "claim_type": "risk_signal",
                    "claim_text": "存在关联担保",
                    "confidence": 0.91,
                    "evidences": [],
                }
            ]
        },
    )

    result = reconcile_report_and_extract_tasks(
        {
            "report_part_a": "该案件存在关联担保[[CLM-31]]，需优先核查。",
            "report_part_b": "后四段",
            "kg_subgraph_ref": kg_subgraph_ref,
        }
    )

    final_report = resolve_final_report(result)
    assert "存在关联担保[1]" in final_report
    assert "[[CLM-31]]" not in final_report


def test_reconcile_report_persists_report_citation_map(monkeypatch):
    class FakeKGService:
        def __init__(self):
            self.rows = []

        def replace_report_citations(self, *, case_id, report_ref, rows):
            assert case_id == 116
            assert report_ref.startswith("final_report:")
            self.rows = rows
            return rows

    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_report.get_kg_service",
        lambda: fake_kg,
    )

    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "claim_traces": [
                {
                    "claim_id": 31,
                    "claim_type": "risk_signal",
                    "claim_text": "存在关联担保",
                    "confidence": 0.91,
                    "evidences": [],
                }
            ]
        },
    )

    result = reconcile_report_and_extract_tasks(
        {
            "current_case_id": 116,
            "report_part_a": "前四段",
            "report_part_b": "后四段",
            "kg_subgraph_ref": kg_subgraph_ref,
        }
    )

    payload = get_heavy_payload(result["final_report_ref"])
    assert fake_kg.rows[0]["citation_id"] == "1"
    assert fake_kg.rows[0]["claim_id"] == 31
    assert payload["trace_items"][0]["citation_id"] == "1"


def test_reconcile_report_autocites_plain_body_sentence():
    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "claim_traces": [
                {
                    "claim_id": 88,
                    "claim_type": "asset",
                    "claim_text": "晨光煤矿名下存在采矿权资产。",
                    "confidence": 0.96,
                    "evidences": [
                        {
                            "chunk_id": "chunk-8",
                            "file_id": 9,
                            "page_no": 3,
                            "quote_text": "采矿许可证记载晨光煤矿拥有采矿权。",
                        }
                    ],
                }
            ]
        },
    )

    result = reconcile_report_and_extract_tasks(
        {
            "report_part_a": "### 2. 【资产清单与去毒重估】\n晨光煤矿名下存在采矿权资产，需单列核查。",
            "report_part_b": "后四段",
            "kg_subgraph_ref": kg_subgraph_ref,
        }
    )

    final_report = resolve_final_report(result)
    assert "晨光煤矿名下存在采矿权资产，需单列核查[1]。" in final_report


def test_reconcile_report_autocites_table_row():
    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "claim_traces": [
                {
                    "claim_id": 99,
                    "claim_type": "asset",
                    "claim_text": "晨光煤矿持有晨光煤矿南区采矿权。",
                    "confidence": 0.95,
                    "evidences": [
                        {
                            "chunk_id": "chunk-9",
                            "file_id": 9,
                            "page_no": 4,
                            "quote_text": "晨光煤矿南区采矿许可证登记在晨光煤矿名下。",
                        }
                    ],
                }
            ]
        },
    )

    result = reconcile_report_and_extract_tasks(
        {
            "report_part_a": "\n".join(
                [
                    "### 2.2 采矿权资产清单",
                    "| 序号 | 矿名 | 矿种 | 许可证到期 |",
                    "| --- | --- | --- | --- |",
                    "| 1 | 晨光煤矿南区采矿权 | 煤 | 2030-01-01 |",
                ]
            ),
            "report_part_b": "后四段",
            "kg_subgraph_ref": kg_subgraph_ref,
        }
    )

    final_report = resolve_final_report(result)
    assert "| 1 | 晨光煤矿南区采矿权 | 煤 | 2030-01-01  [1] |" in final_report


def test_reconcile_report_builds_citation_coverage():
    kg_subgraph_ref = put_heavy_payload(
        "kg_subgraph",
        {
            "claim_traces": [
                {
                    "claim_id": 31,
                    "claim_type": "risk_signal",
                    "claim_text": "存在关联担保",
                    "confidence": 0.91,
                    "evidences": [],
                },
                {
                    "claim_id": 32,
                    "claim_type": "procedure",
                    "claim_text": "案件已进入执行程序",
                    "confidence": 0.88,
                    "evidences": [],
                },
            ]
        },
    )

    result = reconcile_report_and_extract_tasks(
        {
            "report_part_a": "该案件存在关联担保[[CLM-31]]，需优先核查。",
            "report_part_b": "后四段",
            "kg_subgraph_ref": kg_subgraph_ref,
        }
    )

    coverage = result["citation_coverage"]
    assert coverage["total_claims"] == 2
    assert coverage["cited_claims"] == 1
    assert coverage["uncited_claims"] == 1
    assert coverage["coverage_ratio"] == 0.5
    assert coverage["missing_items"][0]["claim_id"] == 32

    payload = get_heavy_payload(result["final_report_ref"])
    assert payload["citation_coverage"]["uncited_claims"] == 1


def test_strip_thousands_separators():
    from ai_hunter.app.graph.nodes.reconcile_report import _strip_thousands_separators as s
    assert s("去毒净值 205,325.0194 万元") == "去毒净值 205325.0194 万元"
    assert s("合计 1,234,567.89") == "合计 1234567.89"
    # 中文顿号/案号不受影响
    assert s("案号(2024)黔02破17号、10位保证人") == "案号(2024)黔02破17号、10位保证人"
