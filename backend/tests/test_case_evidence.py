from ai_hunter.app.services.case_evidence import rank_case_evidence


def _trace(claim_id: int, citation_id: str, text: str, quote: str) -> dict:
    return {
        "claim_id": claim_id,
        "citation_id": citation_id,
        "claim_text": text,
        "evidences": [
            {
                "chunk_id": f"chunk-{claim_id}",
                "file_id": claim_id,
                "file_name": "案件卷宗.pdf",
                "page_no": claim_id,
                "quote_text": quote,
            }
        ],
    }


def test_rank_case_evidence_prefers_query_terms_and_limits_to_five():
    traces = [_trace(index, str(index), f"普通断言 {index}", "普通原文") for index in range(1, 7)]
    traces[-1] = _trace(6, "6", "晨光煤矿采矿权存在瑕疵", "采矿权未办理抵押登记")

    results = rank_case_evidence(traces, "查看采矿权证据原文")

    assert len(results) == 5
    assert results[0]["claim_id"] == 6
    assert results[0]["quote_text"] == "采矿权未办理抵押登记"


def test_rank_case_evidence_prefers_explicit_citation():
    traces = [
        _trace(11, "1", "第一条断言", "第一条原文"),
        _trace(12, "2", "第二条断言", "第二条原文"),
    ]

    results = rank_case_evidence(traces, "查看角标2的原文")

    assert results[0]["citation_id"] == "2"
    assert results[0]["claim_id"] == 12
