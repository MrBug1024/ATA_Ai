from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document

from ai_hunter.annual_audit.file_attachment_service import (
    _context,
    _content_type_for_file_name,
    _infer_workpaper_code,
    _output_name,
    render_template_file,
)


def _docx_bytes() -> bytes:
    document = Document()
    document.add_paragraph("一般企业模板")
    document.add_paragraph("二〇二五年度财务报表审计报告")
    document.add_paragraph("我们认为，后附的财务报表在所有重大方面按照企业会计准则的规定编制。")
    table = document.add_table(rows=1, cols=4)
    table.cell(0, 0).text = "应收账款"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_reference_docx_is_filled_and_formal_opinion_is_downgraded():
    context = _context(
        {
            "engagement": {
                "entity_name": "北京示例有限公司",
                "fiscal_year": 2023,
                "period_end": "2023-12-31",
            },
            "sales_receivables": {"receivables": {"total_balance": 1234.5}},
        },
        "当前为事实性审计草稿。",
        1,
        {"version_label": "年度审计模板 v1"},
        template_type="annual_report",
    )

    rendered, status = render_template_file(_docx_bytes(), "审计报告正文.docx", context)
    document = Document(BytesIO(rendered))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert status == "filled"
    assert "北京示例有限公司" in text
    assert "二〇二三年度" in text
    assert "未形成正式审计意见" in text
    # The generated file must remain the uploaded template's structure.  Do
    # not append a second AI-written report section after the template.
    assert "系统生成的审计结果摘要" not in text


def test_workpaper_code_is_inferred_from_case_template_names():
    assert _infer_workpaper_code("3100-2 销售与收款循环(控制测试).xls") == "3100-2"
    assert _infer_workpaper_code("C5-2应收帐款审定表.xlsx") == "C5-2"
    assert _infer_workpaper_code("管理建议书模板.docx") == ""


def test_output_names_are_readable_and_keep_the_source_extension():
    context = _context(
        {"engagement": {"entity_name": "北京有限公司", "fiscal_year": 2023}},
        "审计结果摘要。",
        1,
        {"version_label": "年度审计模板 v1"},
        template_type="annual_report",
    )

    assert _output_name(
        "annual_report",
        7,
        1,
        "审计报告正文.docx",
        context=context,
    ) == "北京有限公司2023年度财务报表审计报告.docx"
    assert _output_name(
        "financial_statements",
        7,
        1,
        "2、经审计的财务报表.xls",
        context=context,
    ) == "北京有限公司2023年度财务报表.xls"
    assert _output_name(
        "audit_workpaper",
        7,
        1,
        "4101 货币资金.xls",
        "4101",
        context=context,
        duplicate_count=2,
    ) == "北京有限公司2023年度审计工作底稿-4101 货币资金.xls"


def test_output_content_type_follows_the_actual_extension():
    assert _content_type_for_file_name("财务报表.xls") == "application/vnd.ms-excel"
    assert _content_type_for_file_name("财务报表.xlsx") == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert _content_type_for_file_name("审计报告.docx") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_case_legacy_xls_templates_keep_the_original_xls_format():
    template_root = next(
        Path(__file__).parents[2].glob(
            "new_docs/**/10、函证模版/2有价证券询证函.xls"
        )
    )
    context = _context(
        {"engagement": {"entity_name": "北京示例有限公司", "fiscal_year": 2023}},
        "审计结果摘要。",
        1,
        {"version_label": "函证模板 v1"},
        template_type="confirmations",
    )

    rendered, status = render_template_file(
        template_root.read_bytes(), template_root.name, context
    )

    # BIFF8 must never be silently rebuilt as OOXML.  Excel automation may
    # fill and save the workbook, or a service account without Excel may keep
    # the original bytes; both paths preserve the source format.
    assert rendered[:2] != b"PK"
    assert status in {"filled", "copied_no_matching_placeholders", "copied_legacy_unmodified"}
    if status == "copied_legacy_unmodified":
        assert rendered == template_root.read_bytes()
