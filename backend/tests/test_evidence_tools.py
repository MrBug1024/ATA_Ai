import json

import ai_hunter.app.tools.evidence_tools as evidence_tools


def test_resolve_case_evidence_tool_uses_case_bound_query(monkeypatch):
    class FakeKgService:
        def __init__(self):
            self.calls = []

        def fetch_case_evidence_traces(self, case_id, *, query_text, limit):
            self.calls.append((case_id, query_text, limit))
            return [
                {
                    "claim_id": 31,
                    "claim_text": "晨光煤矿采矿权未办理抵押登记",
                    "evidences": [
                        {
                            "chunk_id": "chunk-31",
                            "file_id": 5,
                            "file_name": "二债会资料.pdf",
                            "page_no": 4,
                            "quote_text": "采矿权未办理抵押登记",
                        }
                    ],
                }
            ]

    service = FakeKgService()
    monkeypatch.setattr(evidence_tools, "get_kg_service", lambda: service)

    raw = evidence_tools.resolve_case_evidence.invoke(
        {"case_id": 116, "query": "查看采矿权证据原文", "limit": 5}
    )
    payload = json.loads(raw)

    assert service.calls == [(116, "查看采矿权证据原文", 5)]
    assert payload["key_facts"]["source_scope"] == "case_material"
    assert payload["key_facts"]["case_binding"] is True
    assert payload["key_facts"]["reference_only"] is False
