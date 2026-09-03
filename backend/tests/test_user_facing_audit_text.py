from email.header import Header

from ai_hunter.annual_audit import execution_service, report_service
from ai_hunter.annual_audit.evidence_service import render_knowledge_graph_trace_appendix
from ai_hunter.app.graph import context_loader
from ai_hunter.app.response_safety import sanitize_user_response
from ai_hunter.app.user_facing import display_file_name


def test_display_file_name_decodes_legacy_encoded_name_and_humanizes_system_key() -> None:
    encoded = Header("科目余额表.xlsx", "utf-8").encode()

    assert display_file_name(encoded) == "科目余额表.xlsx"
    assert display_file_name("trial_balance_source.xlsx") == "科目余额表源数据.xlsx"
    assert display_file_name("journal_entries_salary_v2.xlsx") == "工资薪酬序时账（版本 2）.xlsx"
    assert display_file_name("case_materials_readme_ocr.docx") == "项目资料说明（识别稿）.docx"
    assert display_file_name("bank_confirmation_ocr.docx") == "银行函证（识别稿）.docx"
    assert display_file_name("tax_gap_ocr.docx") == "税务资料缺口说明（识别稿）.docx"


def test_chat_response_hides_internal_fields_file_keys_and_error_codes() -> None:
    encoded = Header("财务报表.xlsx", "utf-8").encode()
    response = sanitize_user_response(
        (
            f"来源：trial_balance_source.xlsx\n"
            f"已纳入材料：{encoded}\n"
            "项目画像缺少entity_type\n"
            "附件生成失败（错误码：FINANCIAL_STATEMENTS_BLOCKED）"
        ),
        fallback="不应使用兜底回复",
    )

    assert "科目余额表源数据.xlsx" in response
    assert "财务报表.xlsx" in response
    assert "被审计单位类型" in response
    assert "=?utf-8?" not in response.lower()
    assert "trial_balance_source.xlsx" not in response
    assert "entity_type" not in response
    assert "FINANCIAL_STATEMENTS_BLOCKED" not in response
    assert "错误码" not in response


def test_chat_response_hides_evidence_locator_but_keeps_evidence_quote() -> None:
    response = sanitize_user_response(
        "证据锚点: 文件编号=183 page=1 chunk=4d9e47cc0e8f9427565be2ebaf1b9d87 | 银行函证回函金额与账面余额一致。",
        fallback="不应使用兜底回复",
    )

    assert response == "证据摘录：银行函证回函金额与账面余额一致。"
    assert "183" not in response
    assert "page=" not in response
    assert "chunk=" not in response
    assert "4d9e47cc" not in response


def test_report_trace_appendix_keeps_citation_and_quote_without_locator_ids() -> None:
    appendix = render_knowledge_graph_trace_appendix(
        [
            {
                "citation_id": "7",
                "claim_type": "异常事项",
                "confidence": 0.96,
                "claim_text": "银行函证回函金额与账面余额一致。",
                "evidences": [
                    {
                        "file_id": 183,
                        "source_page_id": 12,
                        "page_no": 1,
                        "chunk_id": "4d9e47cc0e8f9427565be2ebaf1b9d87",
                        "quote_text": "银行函证回函金额与账面余额一致。",
                    }
                ],
            }
        ]
    )

    assert "[[cite:7]]" in appendix
    assert "证据摘录：银行函证回函金额与账面余额一致。" in appendix
    assert "file_id" not in appendix
    assert "page=" not in appendix
    assert "chunk=" not in appendix
    assert "4d9e47cc" not in appendix


def test_agent_evidence_context_hides_locator_ids_before_the_model_sees_it(monkeypatch) -> None:
    monkeypatch.setattr(
        context_loader,
        "get_heavy_payload",
        lambda _ref: {
            "claim_traces": [
                {
                    "claim_id": 9,
                    "claim_type": "异常事项",
                    "claim_text": "银行函证回函金额与账面余额一致。",
                    "confidence": 0.96,
                    "evidences": [
                        {
                            "file_id": 183,
                            "page_no": 1,
                            "chunk_id": "4d9e47cc0e8f9427565be2ebaf1b9d87",
                            "quote_text": "银行函证回函金额与账面余额一致。",
                        }
                    ],
                }
            ]
        },
    )

    summary = context_loader.resolve_kg_trace_summary({"kg_subgraph_ref": "case-ref"})

    assert "证据摘录: 银行函证回函金额与账面余额一致。" in summary
    assert "file_id" not in summary
    assert "page=" not in summary
    assert "chunk=" not in summary
    assert "4d9e47cc" not in summary


def test_report_available_and_material_lines_use_display_names() -> None:
    encoded = Header("审计调整明细.xlsx", "utf-8").encode()
    available = report_service._available_lines(
        {
            "available_data": [
                {
                    "code": "trial_balance",
                    "row_count": 12,
                    "quality_label": "原始/标准化源数据",
                    "source_files": ["trial_balance_source.xlsx"],
                }
            ]
        }
    )
    materials = report_service._material_source_lines(
        [
            {
                "file_name": encoded,
                "file_type": "xlsx",
                "page_count": 1,
                "chunk_count": 2,
                "records_inserted": 3,
            }
        ]
    )

    assert "科目余额表" in available[0]
    assert "科目余额表源数据.xlsx" in available[0]
    assert "trial_balance_source.xlsx" not in available[0]
    assert "审计调整明细.xlsx" in materials[0]
    assert "=?utf-8?" not in materials[0].lower()


def test_profile_blockers_use_chinese_field_labels() -> None:
    blockers = execution_service.profile_blockers(
        {
            "acceptance_status": "accepted",
            "independence_status": "cleared",
        }
    )
    messages = {item["message"] for item in blockers}

    assert "项目画像缺少被审计单位类型" in messages
    assert "项目画像缺少审计目的" in messages
    assert "项目画像缺少适用会计准则" in messages
    assert all("_" not in message for message in messages)
