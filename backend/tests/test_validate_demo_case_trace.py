from ai_hunter.app.graph.nodes.validate_demo_case_trace import validate_demo_case_trace


class _FakeValidationResult:
    def model_dump(self):
        return {
            "case_id": 116,
            "report_ref": "final_report:demo",
            "ready": True,
            "total_citations": 1,
            "passed_citations": 1,
            "failed_citations": 0,
            "checks": [],
            "issues": [],
        }


def test_validate_demo_case_trace_node(monkeypatch):
    class FakeService:
        def validate_report_trace(self, *, case_id, report_ref, citation_ids=None):
            assert case_id == 116
            assert report_ref == "final_report:demo"
            assert citation_ids is None
            return _FakeValidationResult()

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.validate_demo_case_trace.get_demo_case_trace_service",
        lambda: FakeService(),
    )

    result = validate_demo_case_trace(
        {
            "current_case_id": 116,
            "final_report_ref": "final_report:demo",
        }
    )

    assert result["demo_trace_validation"]["ready"] is True
    assert result["demo_trace_validation"]["report_ref"] == "final_report:demo"
