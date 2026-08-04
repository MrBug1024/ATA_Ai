from datetime import date
from decimal import Decimal

from ai_hunter.annual_audit.deterministic_analysis import (
    analyze_cash_transactions,
    analyze_receivables,
    analyze_revenue_journal,
)


def test_receivable_analysis_is_deterministic_and_evidence_linked():
    rows = [
        {
            "id": 1,
            "customer_name": "甲客户",
            "due_date": date(2024, 1, 1),
            "balance": Decimal("600.00"),
            "is_related_party": False,
            "source_locator_json": {"sheet": "应收", "row": 2},
            "domain_row_type": "receivable_item",
        },
        {
            "id": 2,
            "customer_name": "乙客户",
            "due_date": date(2025, 12, 31),
            "balance": Decimal("400.00"),
            "is_related_party": True,
            "source_locator_json": {"sheet": "应收", "row": 3},
            "domain_row_type": "receivable_item",
        },
    ]

    result = analyze_receivables(rows, as_of=date(2025, 12, 31))

    assert result["total_balance"] == 1000.0
    assert result["aging_buckets"]["overdue_over_365"] == 600.0
    assert result["related_party_balance"] == 400.0
    assert result["top_customers"][0]["share_of_positive_balance"] == 0.6
    overdue = next(item for item in result["findings"] if item["finding_type"] == "long_overdue_receivables")
    assert overdue["evidence_refs"][0]["source_locator"] == {"sheet": "应收", "row": 2}


def test_receivable_analysis_does_not_treat_masked_or_zero_rows_as_customer_risk():
    rows = [
        {
            "id": 1,
            "customer_name": "****",
            "balance": Decimal("24000.00"),
            "source_locator_json": {"sheet": "C5-2", "row": 43},
            "domain_row_type": "receivable_item",
        },
        *[
            {
                "id": index,
                "customer_name": "****",
                "balance": Decimal("0"),
                "source_locator_json": {"sheet": "C5-2", "row": index + 42},
                "domain_row_type": "receivable_item",
            }
            for index in range(2, 101)
        ],
    ]

    result = analyze_receivables(rows, as_of=date(2023, 12, 31))
    findings = {item["finding_type"]: item for item in result["findings"]}

    assert "customer_concentration" not in findings
    assert findings["masked_customer_identifiers"]["amount"] == 24000.0
    assert "1 条非零应收记录" in findings["masked_customer_identifiers"]["description"]
    assert "1 条记录无法可靠计算账龄" in findings["missing_receivable_dates"]["description"]


def test_cash_analysis_flags_rules_without_calling_them_misstatements():
    rows = [
        {
            "id": 1,
            "bank_account": "A001",
            "transaction_date": date(2025, 12, 31),
            "amount": Decimal("1000000.00"),
            "direction": "in",
            "counterparty": "甲公司",
            "source_locator_json": {"sheet": "流水", "row": 2},
            "domain_row_type": "bank_transaction",
        },
        {
            "id": 2,
            "bank_account": "A001",
            "transaction_date": date(2025, 12, 31),
            "amount": Decimal("1000000.00"),
            "direction": "in",
            "counterparty": "甲公司",
            "source_locator_json": {"sheet": "流水", "row": 3},
            "domain_row_type": "bank_transaction",
        },
    ]

    result = analyze_cash_transactions(rows, period_end=date(2025, 12, 31))

    assert result["total_inflow"] == 2_000_000.0
    assert result["rule_hit_counts"]["large"] == 2
    assert result["rule_hit_counts"]["duplicates"] == 2
    assert "不直接等同于错报或舞弊" in result["calculation_note"]


def test_revenue_analysis_covers_monthly_cutoff_and_debit_entries():
    rows = [
        {
            "id": 1,
            "voucher_date": date(2025, 1, 15),
            "voucher_no": "记-1",
            "account_name": "主营业务收入",
            "debit_amount": Decimal("0"),
            "credit_amount": Decimal("200000"),
            "counterparty": "甲公司",
            "domain_row_type": "journal_entry_line",
            "source_locator_json": {"file_name": "序时账.xlsx", "sheet_name": "明细", "row_number": 2},
        },
        {
            "id": 2,
            "voucher_date": date(2025, 12, 31),
            "voucher_no": "记-999",
            "account_name": "主营业务收入",
            "debit_amount": Decimal("100000"),
            "credit_amount": Decimal("0"),
            "counterparty": "乙公司",
            "domain_row_type": "journal_entry_line",
            "source_locator_json": {"file_name": "序时账.xlsx", "sheet_name": "明细", "row_number": 999},
        },
    ]

    result = analyze_revenue_journal(rows, period_end=date(2025, 12, 31))

    assert result["net_revenue"] == 100000.0
    assert result["monthly_revenue"][0]["net_revenue"] == 200000.0
    assert result["monthly_revenue"][11]["net_revenue"] == -100000.0
    findings = {item["finding_type"]: item for item in result["findings"]}
    assert "revenue_debit_entries" in findings
    assert "revenue_cutoff_window" in findings
    assert findings["revenue_cutoff_window"]["evidence_refs"][0]["domain_row_id"] == 2
