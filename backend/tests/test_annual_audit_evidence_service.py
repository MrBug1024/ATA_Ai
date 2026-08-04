from ai_hunter.annual_audit import evidence_service


def test_resolve_report_evidence_returns_text_mode_anchor(monkeypatch):
    monkeypatch.setattr(
        evidence_service,
        "get_heavy_payload",
        lambda _ref: {
            "case_id": 7,
            "trace_items": [
                {
                    "citation_id": "1",
                    "claim_id": 11,
                    "claim_text": "存在期末大额流水",
                    "evidences": [
                        {
                            "chunk_id": "annual:bank_transaction:9:1",
                            "file_id": 9,
                            "file_name": "银行流水.xlsx · 明细!88",
                            "page_no": 88,
                            "quote_text": "2025-12-31 | 1000000 | 甲公司",
                            "bbox_list": [],
                            "page_image_ref": "",
                            "source_page_id": 0,
                            "source_file_url": "",
                            "content_type": "text/plain",
                            "entity_id": 0,
                        }
                    ],
                }
            ],
        },
    )

    result = evidence_service.resolve_report_evidence(
        engagement_id=7,
        report_ref="payload:annual",
        citation_id="1",
    )

    assert result["resolution_status"] == "ok"
    assert result["claim_id"] == 11
    assert result["primary_page"]["content_type"] == "text/plain"
    assert result["primary_page"]["anchors"][0]["page_no"] == 88


def test_resolve_report_evidence_rejects_cross_engagement_ref(monkeypatch):
    monkeypatch.setattr(
        evidence_service,
        "get_heavy_payload",
        lambda _ref: {"case_id": 99, "trace_items": []},
    )

    result = evidence_service.resolve_report_evidence(
        engagement_id=7,
        report_ref="payload:other-engagement",
        citation_id="1",
    )

    assert result["resolution_status"] == "ref_not_found"
