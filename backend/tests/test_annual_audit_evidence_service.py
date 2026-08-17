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


def _trace(claim_id: int, claim_text: str, *, bound: bool = True) -> dict:
    return {
        "citation_id": "",
        "claim_id": claim_id,
        "claim_type": "exception",
        "claim_text": claim_text,
        "confidence": 1.0,
        "evidences": [
            {
                "chunk_id": "a" * 64 if bound else "",
                "file_id": 101 if bound else 0,
                "file_name": "bank.xlsx" if "cash" in claim_text else "receivable.xlsx",
                "page_no": 2,
                "quote_text": claim_text,
                "bbox_list": [],
                "source_page_id": 201 if bound else 0,
            }
        ],
    }


def test_deterministic_finding_snapshot_has_response_local_non_graph_trace():
    traces = evidence_service.trace_items_from_deterministic_findings(
        [
            {
                "finding_type": "cash_exception",
                "title": "Cash exception",
                "description": "Current full audit run",
                "evidence_refs": [
                    {
                        "source_locator": {
                            "source_file_id": 101,
                            "source_page_id": 201,
                            "source_chunk_id": "a" * 64,
                            "file_name": "bank.xlsx",
                            "page_no": 2,
                        }
                    }
                ],
            }
        ]
    )

    assert len(traces) == 1
    assert traces[0]["claim_id"] == 0
    assert traces[0]["_graph_backed"] is False
    assert traces[0]["evidences"][0]["chunk_id"] == "a" * 64


def test_finalize_annual_answer_does_not_reuse_prior_or_project_wide_traces(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        evidence_service,
        "latest_finding_trace_items",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary chat must not query project-wide findings")
        ),
    )
    monkeypatch.setattr(
        evidence_service,
        "put_heavy_payload",
        lambda _kind, payload: captured.setdefault("payload", payload) and "payload:response-1",
    )

    result = evidence_service.finalize_annual_answer(
        {
            "current_case_id": 7,
            "query": "cash bank",
            # This is a persisted prior response and must not affect this one.
            "trace_items": [_trace(999, "prior response receivable trace")],
        },
        "The cash bank exception needs follow-up.",
    )

    assert result["trace_items"] == []
    assert "证据索引" not in captured["payload"]["text"]
    assert result["citation_coverage"] == {
        "total_claims": 0,
        "cited_claims": 0,
        "uncited_claims": 0,
        "coverage_ratio": 0.0,
        "missing_items": [],
        "unbound_count": 0,
        "evidence_blocked": False,
        "blocking_status": "ready",
    }
    assert captured["payload"]["citation_scope"] == "response"


def test_current_analysis_run_scopes_rejects_mismatched_or_unscoped_runs():
    scopes = evidence_service._current_analysis_run_scopes(
        {
            "response_analysis_runs": [
                {
                    "tool_name": "analyze_sales_receivables",
                    "analysis_type": "sales_receivables",
                    "analysis_run_id": 41,
                },
                {
                    "tool_name": "analyze_sales_receivables",
                    "analysis_type": "cash_and_bank",
                    "analysis_run_id": 42,
                },
                {
                    "tool_name": "analyze_cash_and_bank",
                    "analysis_type": "cash_and_bank",
                    "analysis_run_id": 0,
                },
                {
                    "tool_name": "analyze_cash_and_bank",
                    "analysis_type": "cash_and_bank",
                    "analysis_run_id": 43,
                },
            ]
        }
    )

    assert scopes == [
        {
            "tool_name": "analyze_sales_receivables",
            "analysis_type": "sales_receivables",
            "analysis_run_id": 41,
        },
        {
            "tool_name": "analyze_cash_and_bank",
            "analysis_type": "cash_and_bank",
            "analysis_run_id": 43,
        },
    ]


def test_finalize_current_analysis_scope_uses_explicit_marker_without_fuzzy_match(monkeypatch):
    captured = {}
    trace = {
        **_trace(701, "cash current-run finding"),
        "annual_finding_id": 41,
        "analysis_run_id": 12,
        "analysis_type": "cash_and_bank",
        "_graph_backed": True,
    }
    coverage = {
        "total_claims": 1,
        "cited_claims": 1,
        "uncited_claims": 0,
        "coverage_ratio": 1.0,
        "missing_items": [],
        "unbound_count": 0,
        "evidence_blocked": False,
        "blocking_status": "ready",
    }
    monkeypatch.setattr(
        evidence_service,
        "_traces_and_coverage_from_current_analysis_runs",
        lambda _state: ([trace], coverage),
    )
    monkeypatch.setattr(
        evidence_service,
        "put_heavy_payload",
        lambda _kind, payload: captured.setdefault("payload", payload) and "payload:current-run",
    )
    monkeypatch.setattr(evidence_service, "_persist_response_citation_map", lambda **_kwargs: None)

    result = evidence_service.finalize_annual_answer(
        {
            "current_case_id": 7,
            "response_analysis_runs": [
                {
                    "tool_name": "analyze_cash_and_bank",
                    "analysis_type": "cash_and_bank",
                    "analysis_run_id": 12,
                }
            ],
        },
        "已核验资金规则发现 [[AF:41]]；[2026] 不是角标。",
    )

    text = captured["payload"]["text"]
    assert "[[cite:1]]" in text
    assert "[[AF:41]]" not in text
    assert "[2026]" in text
    assert "### 本轮已核验的规则发现" not in text
    assert result["citation_coverage"] == coverage
    assert captured["payload"]["citation_scope"] == "response_analysis_run"


def test_finalize_current_analysis_scope_adds_exact_fact_when_model_omits_marker(monkeypatch):
    captured = {}
    trace = {
        **_trace(701, "cash current-run finding"),
        "annual_finding_id": 41,
        "analysis_run_id": 12,
        "analysis_type": "cash_and_bank",
        "_graph_backed": True,
    }
    coverage = {
        "total_claims": 1,
        "cited_claims": 1,
        "uncited_claims": 0,
        "coverage_ratio": 1.0,
        "missing_items": [],
        "unbound_count": 0,
        "evidence_blocked": False,
        "blocking_status": "ready",
    }
    monkeypatch.setattr(
        evidence_service,
        "_traces_and_coverage_from_current_analysis_runs",
        lambda _state: ([trace], coverage),
    )
    monkeypatch.setattr(
        evidence_service,
        "put_heavy_payload",
        lambda _kind, payload: captured.setdefault("payload", payload) and "payload:current-run-no-marker",
    )
    monkeypatch.setattr(evidence_service, "_persist_response_citation_map", lambda **_kwargs: None)

    evidence_service.finalize_annual_answer(
        {
            "current_case_id": 7,
            "response_analysis_runs": [
                {
                    "tool_name": "analyze_cash_and_bank",
                    "analysis_type": "cash_and_bank",
                    "analysis_run_id": 12,
                }
            ],
        },
        "模型未使用内部标记。",
    )

    text = captured["payload"]["text"]
    assert "### 本轮已核验的规则发现" in text
    assert "- cash current-run finding [[cite:1]]" in text


def test_finalize_annual_answer_response_coverage_keeps_unbound_current_trace_visible(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        evidence_service,
        "put_heavy_payload",
        lambda _kind, payload: captured.setdefault("payload", payload) and "payload:response-2",
    )

    result = evidence_service.finalize_annual_answer(
        {
            "current_case_id": 7,
            "query": "resolve evidence",
            "business_line_result": {
                "source_scope": "manual",
                "evidence_items": [
                    {
                        **_trace(21, "cash source is not bound", bound=False)["evidences"][0],
                        "claim_id": 21,
                        "claim_type": "exception",
                        "claim_text": "cash source is not bound",
                    }
                ],
            },
        },
        "The selected cash source still needs canonical binding.",
    )

    coverage = result["citation_coverage"]
    assert coverage["total_claims"] == 1
    assert coverage["cited_claims"] == 0
    assert coverage["unbound_count"] == 1
    assert coverage["evidence_blocked"] is True
    assert coverage["missing_items"][0]["citation_id"] == "1"
    assert captured["payload"]["trace_items"][0]["claim_id"] == 21


def test_response_trace_keeps_explicit_graph_provenance_from_evidence_resolve():
    graph_evidence = {
        **_trace(701, "cash graph claim")["evidences"][0],
        "claim_id": 701,
        "claim_type": "exception",
        "claim_text": "cash graph claim",
        "_graph_backed": True,
    }
    annual_evidence = {
        **_trace(702, "cash annual finding")["evidences"][0],
        "claim_id": 702,
        "claim_type": "exception",
        "claim_text": "cash annual finding",
        # A case scope alone must not turn a non-graph annual ID into a
        # report_citation_map foreign key.
        "_graph_backed": False,
    }

    traces = evidence_service.response_trace_items(
        {
            "business_line_result": {
                "capability": "evidence.resolve",
                "source_scope": "case_material",
                "evidence_items": [graph_evidence, annual_evidence],
            }
        },
        "Evidence resolution result.",
    )

    assert [trace["_graph_backed"] for trace in traces] == [True, False]
    assert [trace["citation_id"] for trace in traces] == ["1", "2"]


def test_finalize_annual_answer_persists_only_graph_backed_citation_map(monkeypatch):
    captured = {}

    class FakeGraphService:
        def replace_report_citations(self, **kwargs):
            captured["map"] = kwargs
            return []

    monkeypatch.setattr(evidence_service, "put_heavy_payload", lambda *_args: "payload:response-3")
    monkeypatch.setattr(
        "ai_hunter.app.services.kg_service.get_kg_service",
        lambda: FakeGraphService(),
    )

    result = evidence_service.finalize_annual_answer(
        {
            "current_case_id": 7,
            "response_trace_candidates": [
                {**_trace(701, "cash graph claim"), "_graph_backed": True},
                {**_trace(702, "cash annual finding"), "_graph_backed": False},
            ],
        },
        "Cash evidence was reviewed.",
    )

    assert {item["claim_id"] for item in result["trace_items"]} == {701, 702}
    assert captured["map"]["case_id"] == 7
    assert captured["map"]["report_ref"] == "payload:response-3"
    assert captured["map"]["rows"] == [
        {
            "citation_id": "1",
            "claim_id": 701,
            "report_section": "chat_response",
            "ordinal": 1,
            "paragraph_index": 0,
        }
    ]


def test_finalize_annual_report_keeps_planned_inline_citations_and_appends_only_trace_paths(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        evidence_service,
        "put_heavy_payload",
        lambda _kind, payload: captured.setdefault("payload", payload) and "payload:annual-report",
    )

    result = evidence_service.finalize_annual_answer(
        {
            "current_case_id": 7,
            "response_trace_candidates": [
                {
                    **_trace(701, "现金流量规则命中"),
                    "claim_type": "risk_signal",
                    "entity_id": 81,
                    "_graph_backed": True,
                }
            ],
            "response_citation_coverage": {
                "total_claims": 2,
                "cited_claims": 1,
                "uncited_claims": 1,
                "coverage_ratio": 0.5,
                "missing_items": [
                    {
                        "citation_id": "",
                        "claim_id": 0,
                        "claim_type": "risk_signal",
                        "claim_text": "尚未绑定的规则命中",
                    }
                ],
                "unbound_count": 1,
                "evidence_blocked": True,
                "blocking_status": "evidence_blocked",
            },
            "citation_entries": [{"citation_id": "1", "section_code": "C1-2"}],
        },
        "资金风险规则结果：存在期末异常 [[cite:1]]。",
    )

    text = captured["payload"]["text"]
    assert "### 证据索引" not in text
    assert "### 【知识图谱证据追溯】" in text
    assert text.count("[[cite:1]]") == 2
    assert captured["payload"]["citation_scope"] == "annual_report"
    assert result["citation_coverage"]["coverage_ratio"] == 0.5


def test_finalize_binds_each_message_to_the_frozen_report_version(monkeypatch):
    captured = {}
    monkeypatch.setattr(evidence_service, "put_heavy_payload", lambda *_args: "payload:delivery-2")
    monkeypatch.setattr(
        "ai_hunter.annual_audit.citation_manifest_service.bind_final_report_ref",
        lambda **kwargs: captured.setdefault("binding", kwargs)
        and {"bound_count": 1, "manifest_count": 1},
    )

    result = evidence_service.finalize_annual_answer(
        {
            "current_case_id": 7,
            "annual_report_manifest": {
                "annual_report_id": 41,
                "report_type": "annual_audit_draft",
                "report_version": 2,
                "citation_count": 1,
            },
            "response_trace_candidates": [{**_trace(701, "cash graph claim"), "_graph_backed": True}],
        },
        "Cash evidence was reviewed [[cite:1]].",
    )

    assert captured["binding"] == {
        "engagement_id": 7,
        "annual_report_id": 41,
        "report_version": 2,
        "report_type": "annual_audit_draft",
        "final_report_ref": "payload:delivery-2",
    }
    assert result["citation_manifest_binding"]["status"] == "bound"


def test_resolve_report_evidence_falls_back_to_frozen_manifest(monkeypatch):
    monkeypatch.setattr(evidence_service, "get_heavy_payload", lambda _ref: None)
    monkeypatch.setattr(
        "ai_hunter.annual_audit.citation_manifest_service.resolve_final_report_ref_citation_manifest",
        lambda **_kwargs: [
            {
                "citation_id": "1",
                "annual_finding_id": 11,
                "analysis_run_id": 21,
                "analysis_type": "cash_and_bank",
                "finding_type": "large_transaction",
                "anchor_status": "bound",
                "rule_metadata": {"rule_code": "C1-LARGE-001"},
                "finding_metadata": {
                    "title": "cash exception",
                    "description": "review the transaction",
                    "graph_claim_id": 701,
                    "graph_entity_id": 81,
                },
                "evidence_snapshot": [
                    {
                        "chunk_id": "c" * 64,
                        "file_id": 101,
                        "source_page_id": 201,
                        "page_no": 2,
                        "entity_id": 81,
                    }
                ],
            }
        ],
    )

    result = evidence_service.resolve_report_evidence(
        engagement_id=7,
        report_ref="payload:expired-delivery",
        citation_id="1",
    )

    assert result["resolution_status"] == "ok"
    assert result["citation_source"] == "annual_report_manifest"
    assert result["claim_id"] == 701
    assert result["annual_finding_id"] == 11
    assert result["primary_evidence"]["chunk_id"] == "c" * 64
