from ai_hunter.app.graph.context_loader import (
    resolve_citation_coverage,
    resolve_final_report,
    resolve_report_part_a,
    resolve_report_part_b,
    resolve_trace_items,
)
from ai_hunter.app.graph.nodes.reconcile_report import reconcile_report_and_extract_tasks


def test_reconcile_report_stores_final_report_out_of_band():
    result = reconcile_report_and_extract_tasks(
        {
            "report_part_a": "前四段内容",
            "report_part_b": "后四段内容",
        }
    )

    assert result["final_report"] == ""
    assert result["final_report_ref"].startswith("final_report:")
    assert "前四段内容" in resolve_final_report(result)
    assert "后四段内容" in resolve_final_report(result)
    assert resolve_trace_items(result) == []
    assert resolve_citation_coverage(result)["total_claims"] == 0


def test_report_loaders_prefer_ref_payloads():
    state = {
        "report_part_a_ref": "",
        "report_part_b_ref": "",
        "final_report_ref": "",
        "report_part_a": "A段",
        "report_part_b": "B段",
        "final_report": "最终报告",
    }

    assert resolve_report_part_a(state) == "A段"
    assert resolve_report_part_b(state) == "B段"
    assert resolve_final_report(state) == "最终报告"
    assert resolve_citation_coverage(state)["total_claims"] == 0
