from __future__ import annotations

from datetime import date

from ai_hunter.annual_audit import report_graph
from ai_hunter.annual_audit.analysis_service import _source_quality
from ai_hunter.annual_audit.report_service import render_annual_report_draft


def test_report_draft_is_grounded_and_never_claims_a_formal_opinion():
    text = render_annual_report_draft(
        engagement={
            "entity_name": "北京示例有限公司",
            "engagement_code": "AUD-2023-DEMO",
            "period_start": date(2023, 1, 1),
            "period_end": date(2023, 12, 31),
        },
        readiness={
            "counts": {
                "account_balance_rows": 20,
                "journal_entry_rows": 12,
                "receivable_rows": 3,
                "bank_transaction_rows": 8,
            },
            "available_data": [
                {
                    "code": "receivables",
                    "name": "应收账款明细",
                    "row_count": 3,
                    "quality_label": "派生审计底稿数据",
                    "source_files": ["C5-2应收帐款审定表.xlsx"],
                    "limitation": "适合案例分析，不替代原始账务资料。",
                }
            ],
            "supplemental_required_data": ["原始应收账款明细、账龄及客户主数据"],
            "missing_required_data": [],
        },
        sales_receivables={
            "receivables": {
                "row_count": 3,
                "total_balance": 300000,
                "aging_buckets": {"not_due": 100000, "overdue_over_365": 200000},
                "findings": [
                    {
                        "risk_level": "high",
                        "title": "存在长账龄应收",
                        "description": "需检查期后回款",
                        "amount": 200000,
                    }
                ],
            },
            "revenue": {
                "row_count": 12,
                "net_revenue": 1200000,
                "monthly_revenue": [{"month": 12, "net_revenue": 1200000}],
                "peak_month": 12,
                "peak_month_share": 1,
                "findings": [],
            },
            "findings": [{"risk_level": "high"}],
            "missing_required_data": [],
        },
        cash_and_bank={
            "row_count": 8,
            "total_inflow": 500000,
            "total_outflow": 400000,
            "rule_hit_counts": {"large": 1, "period_end_window": 2},
            "findings": [],
        },
        corrections=["标的：收入截止 -> 强制指令：扩大期末测试窗口"],
        material_sources=[
            {
                "file_name": "北京有限公司2023年年审底稿.xlsx",
                "file_type": "xlsx",
                "doc_category": "audit_workpapers",
                "page_count": 296,
                "chunk_count": 386,
                "records_inserted": 0,
            }
        ],
    )

    assert "F1-2 营业收入" in text
    assert "C5-2 应收账款" in text
    assert "C1-2 货币资金" in text
    assert "北京示例有限公司" in text
    assert "1,200,000.00" in text
    assert "扩大期末测试窗口" in text
    assert "296 个工作表/证据页" in text
    assert "派生审计底稿误当作源账数据" in text
    assert "当前已有的结构化资料" in text
    assert "C5-2应收帐款审定表.xlsx" in text
    assert "仍缺或需补充的资料" in text
    assert "原始应收账款明细、账龄及客户主数据" in text
    assert "全面年审资料类别覆盖" in text
    assert "已单独识别：历史审计底稿" in text
    assert "财务报表及附注、科目余额表、序时账及凭证明细" in text
    assert "不视为原始资料已经齐备" in text
    assert "不具备签发正式审计报告" in text


def test_source_quality_distinguishes_split_workpapers_and_partial_ledgers():
    assert _source_quality(["C5-2应收帐款审定表.xlsx"]) == "derived"
    assert _source_quality(["工资.xlsx"]) == "partial"
    assert _source_quality(["完整序时账.xlsx"]) == "source"
    assert _source_quality(["工资.xlsx", "完整序时账.xlsx"]) == "mixed"


def test_report_draft_exposes_missing_data_instead_of_inventing_results():
    text = render_annual_report_draft(
        engagement={
            "entity_name": "缺资料企业",
            "engagement_code": "AUD-2023-MISSING",
            "period_start": date(2023, 1, 1),
            "period_end": date(2023, 12, 31),
        },
        readiness={
            "counts": {},
            "missing_required_data": ["序时账/凭证明细", "银行流水"],
        },
        sales_receivables={"status": "needs_data", "missing_required_data": ["应收账款明细"]},
        cash_and_bank={"status": "needs_data", "missing_required_data": ["银行流水"]},
    )

    assert "序时账/凭证明细" in text
    assert "应收账款明细" in text
    assert text.count("银行流水") >= 1
    assert "尚未导入可识别的营业收入序时账" in text
    assert "0 项规则命中不代表不存在异常" in text
    assert "不得将本轮 0 项命中解释为不存在异常凭证" in text
    assert "不能据此得出无异常结论" in text
    assert "当前仅可形成审计工作底稿和审计报告初稿" in text


def test_annual_report_graph_node_returns_original_agent_output_contract(monkeypatch):
    monkeypatch.setattr(
        report_graph,
        "generate_annual_report_draft",
        lambda *_args, **_kwargs: {
            "report_text": "年审报告初稿正文",
            "artifacts": {
                "report": {"version": 2},
                "workpapers": [{"code": "F1-2", "version": 3}],
            },
        },
    )

    result = report_graph.generate_annual_report_node(
        {"current_case_id": 7, "operator_id": "auditor-1"}
    )

    assert result["agent_output"].startswith("年审报告初稿正文")
    assert "报告草稿 v2" in result["agent_output"]
    assert "F1-2 v3" in result["agent_output"]
    assert result["extracted_tasks"] == []
