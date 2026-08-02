import json

from ai_hunter.app.graph.context_loader import resolve_full_context_data, resolve_full_context_json
from ai_hunter.app.graph.heavy_state import get_heavy_payload
from ai_hunter.app.graph.nodes.fetch_full_context import _build_full_context_summary, fetch_full_context


class _FakeAuditClient:
    def get_full_context_sync(self, case_id: int) -> dict:
        return {
            "case_id": case_id,
            "debtors": [{"name": "晨光煤矿"}],
            "claims": [{"id": 1}, {"id": 2}],
            "guarantors": [{"id": 3}],
            "real_estate_evaluations": [{"id": 4}],
            "mining_evaluations": [{"id": 5}],
            "whiteglove": {"score": 0.7},
            "fund_flow": [{"path": "A->B"}],
        }


def test_build_full_context_summary_is_lightweight():
    summary = _build_full_context_summary(
        {
            "case_id": 116,
            "debtors": [{"name": "晨光煤矿"}],
            "claims": [{"id": 1}, {"id": 2}],
            "guarantors": [{"id": 3}],
        }
    )

    assert '"case_id": 116' in summary
    assert '"claims_count": 2' in summary
    assert '"guarantors_count": 1' in summary


def test_fetch_full_context_stores_heavy_payload_out_of_band(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.fetch_full_context.get_audit_api_client",
        lambda: _FakeAuditClient(),
    )

    result = fetch_full_context({"current_case_id": 116})

    assert result["full_context_ref"].startswith("full_context:")
    assert result["full_context_summary"]
    assert result["full_context_json"] == ""
    assert result["full_context_data"] == {}
    assert get_heavy_payload(result["full_context_ref"]) is not None


def test_context_loader_resolves_payload_from_ref(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.fetch_full_context.get_audit_api_client",
        lambda: _FakeAuditClient(),
    )
    result = fetch_full_context({"current_case_id": 116})

    state = {
        "full_context_ref": result["full_context_ref"],
        "full_context_summary": result["full_context_summary"],
        "full_context_json": "",
        "full_context_data": {},
    }
    resolved_data = resolve_full_context_data(state)
    resolved_json = resolve_full_context_json(state)
    parsed_json = json.loads(resolved_json)

    assert resolved_data["case_id"] == 116
    assert parsed_json["case_id"] == 116
