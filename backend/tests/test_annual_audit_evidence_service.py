from ai_hunter.annual_audit import evidence_service


def test_resolve_report_evidence_returns_bound_spreadsheet_anchor(monkeypatch):
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
                            "chunk_id": "9" * 64,
                            "file_id": 101,
                            "file_name": "银行流水.xlsx · 明细!88",
                            "page_no": 2,
                            "quote_text": "2025-12-31 | 1000000 | 甲公司",
                            "bbox_list": [],
                            "page_image_ref": "",
                            "source_page_id": 201,
                            "source_file_url": "minio://ata-annual-raw/annual_audit/project-7/raw/bank.xlsx",
                            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "locator_kind": "sheet_row",
                            "sheet_name": "明细",
                            "row_start": 88,
                            "row_end": 88,
                            "cell_range": "A88:XFD88",
                            "preview_available": True,
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
    assert result["primary_page"]["content_type"].startswith("application/vnd.openxmlformats")
    assert result["primary_page"]["locator_kind"] == "sheet_row"
    assert result["primary_page"]["anchors"][0]["page_no"] == 2
    assert result["primary_page"]["anchors"][0]["chunk_id"] == "9" * 64


def test_evidence_item_does_not_fabricate_source_chunk_id():
    item = evidence_service._evidence_item(
        {
            "source_locator": {
                "file_name": "unbound.xlsx",
                "sheet_name": "Sheet1",
                "row_number": 4,
                "quote_text": "amount",
            }
        },
        1,
    )

    assert item is not None
    assert item["chunk_id"] == ""
    assert item["file_id"] == 0
    assert item["preview_available"] is False


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
