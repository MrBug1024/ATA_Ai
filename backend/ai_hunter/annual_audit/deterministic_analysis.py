"""Pure deterministic calculations for the first annual-audit demo cycles."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def _evidence_ref(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain_row_type": row.get("domain_row_type", ""),
        "domain_row_id": int(row.get("id") or 0),
        "source_locator": row.get("source_locator_json") or {},
    }


def _is_masked_customer(value: str) -> bool:
    normalized = value.strip()
    return (
        not normalized
        or normalized == "未标明客户"
        or ("*" in normalized and normalized.replace("*", "") == "")
        or ("＊" in normalized and normalized.replace("＊", "") == "")
    )


def analyze_receivables(rows: list[dict[str, Any]], *, as_of: date) -> dict[str, Any]:
    buckets = {
        "not_due": Decimal("0"),
        "overdue_1_90": Decimal("0"),
        "overdue_91_180": Decimal("0"),
        "overdue_181_365": Decimal("0"),
        "overdue_over_365": Decimal("0"),
        "credit_balance": Decimal("0"),
        "undated": Decimal("0"),
    }
    by_customer: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_customer_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total = Decimal("0")
    related_party_total = Decimal("0")
    missing_date_count = 0
    long_overdue_rows: list[dict[str, Any]] = []
    masked_positive_rows: list[dict[str, Any]] = []

    for row in rows:
        balance = _decimal(row.get("balance"))
        customer = str(row.get("customer_name") or "未标明客户")
        by_customer[customer] += balance
        by_customer_rows[customer].append(row)
        total += balance
        if bool(row.get("is_related_party")):
            related_party_total += balance
        if balance > 0 and _is_masked_customer(customer):
            masked_positive_rows.append(row)
        if balance < 0:
            buckets["credit_balance"] += balance
            continue
        if balance == 0:
            continue

        base_date = row.get("due_date") or row.get("occurrence_date")
        if not isinstance(base_date, date):
            buckets["undated"] += balance
            missing_date_count += 1
            continue
        overdue_days = (as_of - base_date).days
        if overdue_days <= 0:
            buckets["not_due"] += balance
        elif overdue_days <= 90:
            buckets["overdue_1_90"] += balance
        elif overdue_days <= 180:
            buckets["overdue_91_180"] += balance
        elif overdue_days <= 365:
            buckets["overdue_181_365"] += balance
            long_overdue_rows.append(row)
        else:
            buckets["overdue_over_365"] += balance
            long_overdue_rows.append(row)

    ranked = sorted(
        ((name, amount) for name, amount in by_customer.items() if amount != 0),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    positive_total = sum(
        (amount for name, amount in by_customer.items() if amount > 0 and not _is_masked_customer(name)),
        Decimal("0"),
    )
    top_customers = [
        {
            "customer_name": name,
            "balance": _money(amount),
            "share_of_positive_balance": (
                round(float(amount / positive_total), 4) if positive_total > 0 else 0.0
            ),
        }
        for name, amount in ranked[:5]
    ]
    findings: list[dict[str, Any]] = []
    if masked_positive_rows:
        findings.append(
            {
                "finding_type": "masked_customer_identifiers",
                "risk_level": "medium",
                "title": "应收客户标识已脱敏",
                "description": (
                    f"共有 {len(masked_positive_rows)} 条非零应收记录的客户名称无法区分，"
                    "本轮不执行客户集中度判断；需补充未脱敏客户主数据后重新分析。"
                ),
                "amount": _money(
                    sum((_decimal(row.get("balance")) for row in masked_positive_rows), Decimal("0"))
                ),
                "evidence_refs": [_evidence_ref(row) for row in masked_positive_rows[:20]],
            }
        )
    elif top_customers and top_customers[0]["share_of_positive_balance"] >= 0.30:
        findings.append(
            {
                "finding_type": "customer_concentration",
                "risk_level": "medium",
                "title": "应收账款客户集中度较高",
                "description": (
                    f"最大客户余额占正数应收余额的 "
                    f"{top_customers[0]['share_of_positive_balance']:.2%}，建议结合合同、"
                    "期后回款和函证结果实施针对性程序。"
                ),
                "amount": top_customers[0]["balance"],
                "evidence_refs": [
                    _evidence_ref(row)
                    for row in by_customer_rows[top_customers[0]["customer_name"]][:20]
                ],
            }
        )
    long_overdue_total = buckets["overdue_181_365"] + buckets["overdue_over_365"]
    if long_overdue_total > 0:
        findings.append(
            {
                "finding_type": "long_overdue_receivables",
                "risk_level": "high",
                "title": "存在逾期超过 180 天的应收款项",
                "description": "需检查期后回款、信用减值测算、争议事项及函证差异。",
                "amount": _money(long_overdue_total),
                "evidence_refs": [_evidence_ref(row) for row in long_overdue_rows[:20]],
            }
        )
    if missing_date_count:
        missing_date_rows = [
            row
            for row in rows
            if _decimal(row.get("balance")) != 0
            and row.get("due_date") is None
            and row.get("occurrence_date") is None
        ]
        findings.append(
            {
                "finding_type": "missing_receivable_dates",
                "risk_level": "medium",
                "title": "部分应收明细缺少发生日或到期日",
                "description": f"共有 {missing_date_count} 条记录无法可靠计算账龄。",
                "amount": _money(buckets["undated"]),
                "evidence_refs": [_evidence_ref(row) for row in missing_date_rows[:20]],
            }
        )

    return {
        "as_of": as_of.isoformat(),
        "row_count": len(rows),
        "total_balance": _money(total),
        "aging_buckets": {key: _money(value) for key, value in buckets.items()},
        "related_party_balance": _money(related_party_total),
        "top_customers": top_customers,
        "findings": findings,
        "calculation_note": (
            "优先使用到期日，无到期日时使用发生日；负数余额单列为贷方余额；"
            "零余额行不计入日期缺失风险数量；客户名称脱敏时不执行集中度判断；"
            "金额均由结构化明细确定性汇总。"
        ),
    }


def analyze_revenue_journal(
    rows: list[dict[str, Any]],
    *,
    period_end: date,
) -> dict[str, Any]:
    """Analyze revenue journal lines for monthly trend and cutoff follow-up."""

    monthly: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    net_revenue = Decimal("0")
    debit_rows: list[dict[str, Any]] = []
    cutoff_rows: list[dict[str, Any]] = []
    round_rows: list[dict[str, Any]] = []

    for row in rows:
        debit = _decimal(row.get("debit_amount"))
        credit = _decimal(row.get("credit_amount"))
        net = credit - debit
        net_revenue += net
        voucher_date = row.get("voucher_date")
        if isinstance(voucher_date, date):
            monthly[voucher_date.month] += net
            if abs((period_end - voucher_date).days) <= 7:
                cutoff_rows.append(row)
        if debit > 0:
            debit_rows.append(row)
        gross = max(abs(debit), abs(credit))
        if gross >= Decimal("100000") and gross % Decimal("100000") == 0:
            round_rows.append(row)

    positive_total = sum((max(value, Decimal("0")) for value in monthly.values()), Decimal("0"))
    peak_month = max(monthly, key=lambda month: monthly[month]) if monthly else 0
    peak_share = (
        float(max(monthly.get(peak_month, Decimal("0")), Decimal("0")) / positive_total)
        if positive_total > 0 and peak_month
        else 0.0
    )
    findings: list[dict[str, Any]] = []
    if debit_rows:
        findings.append(
            {
                "finding_type": "revenue_debit_entries",
                "risk_level": "medium",
                "title": "营业收入科目存在借方发生额",
                "description": f"共 {len(debit_rows)} 条收入借方分录，需核查销售退回、折让、冲销依据及审批。",
                "amount": _money(sum((_decimal(row.get("debit_amount")) for row in debit_rows), Decimal("0"))),
                "evidence_refs": [_evidence_ref(row) for row in debit_rows[:20]],
            }
        )
    if cutoff_rows:
        findings.append(
            {
                "finding_type": "revenue_cutoff_window",
                "risk_level": "high",
                "title": "期末前后七日存在营业收入分录",
                "description": f"期末窗口命中 {len(cutoff_rows)} 条，需核对合同、发票、出库/验收资料和期后冲回。",
                "amount": _money(
                    sum(
                        (
                            max(
                                abs(_decimal(row.get("debit_amount"))),
                                abs(_decimal(row.get("credit_amount"))),
                            )
                            for row in cutoff_rows
                        ),
                        Decimal("0"),
                    )
                ),
                "evidence_refs": [_evidence_ref(row) for row in cutoff_rows[:20]],
            }
        )
    if peak_share >= 0.25:
        peak_rows = [
            row
            for row in rows
            if isinstance(row.get("voucher_date"), date)
            and row["voucher_date"].month == peak_month
        ]
        findings.append(
            {
                "finding_type": "revenue_month_concentration",
                "risk_level": "medium",
                "title": "营业收入月度分布较集中",
                "description": f"{peak_month} 月正向收入占全年正向收入 {peak_share:.2%}，建议结合业务季节性复核。",
                "amount": _money(monthly[peak_month]),
                "evidence_refs": [_evidence_ref(row) for row in peak_rows[:20]],
            }
        )
    if round_rows:
        findings.append(
            {
                "finding_type": "round_revenue_entries",
                "risk_level": "medium",
                "title": "营业收入存在十万元以上整额分录",
                "description": f"规则命中 {len(round_rows)} 条，需结合业务合同和原始单据核查。",
                "amount": _money(
                    sum(
                        (
                            max(
                                abs(_decimal(row.get("debit_amount"))),
                                abs(_decimal(row.get("credit_amount"))),
                            )
                            for row in round_rows
                        ),
                        Decimal("0"),
                    )
                ),
                "evidence_refs": [_evidence_ref(row) for row in round_rows[:20]],
            }
        )

    largest_entries = sorted(
        rows,
        key=lambda row: max(
            abs(_decimal(row.get("debit_amount"))),
            abs(_decimal(row.get("credit_amount"))),
        ),
        reverse=True,
    )[:10]
    return {
        "period_end": period_end.isoformat(),
        "row_count": len(rows),
        "net_revenue": _money(net_revenue),
        "monthly_revenue": [
            {"month": month, "net_revenue": _money(monthly.get(month, Decimal("0")))}
            for month in range(1, 13)
        ],
        "peak_month": peak_month,
        "peak_month_share": round(peak_share, 4),
        "largest_entries": [
            {
                "voucher_date": row.get("voucher_date").isoformat()
                if isinstance(row.get("voucher_date"), date)
                else None,
                "voucher_no": row.get("voucher_no"),
                "account_name": row.get("account_name"),
                "debit_amount": _money(_decimal(row.get("debit_amount"))),
                "credit_amount": _money(_decimal(row.get("credit_amount"))),
                "counterparty": row.get("counterparty"),
            }
            for row in largest_entries
        ],
        "findings": findings,
        "calculation_note": (
            "收入净额按贷方减借方确定性汇总；期末窗口为资产负债表日前后七日；"
            "规则命中仅表示需要进一步审计，不直接等同于错报或舞弊。"
        ),
    }


def analyze_cash_transactions(
    rows: list[dict[str, Any]],
    *,
    period_end: date,
    large_amount_threshold: Decimal = Decimal("1000000"),
) -> dict[str, Any]:
    large_rows: list[dict[str, Any]] = []
    period_end_rows: list[dict[str, Any]] = []
    weekend_rows: list[dict[str, Any]] = []
    round_rows: list[dict[str, Any]] = []
    duplicate_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    total_inflow = Decimal("0")
    total_outflow = Decimal("0")

    for row in rows:
        amount = _decimal(row.get("amount"))
        direction = str(row.get("direction") or "").lower()
        signed_amount = amount
        if direction in {"out", "debit", "付款", "支出"} and amount > 0:
            signed_amount = -amount
        if signed_amount >= 0:
            total_inflow += signed_amount
        else:
            total_outflow += abs(signed_amount)
        if abs(signed_amount) >= large_amount_threshold:
            large_rows.append(row)
        transaction_date = row.get("transaction_date")
        if isinstance(transaction_date, date):
            if abs((period_end - transaction_date).days) <= 7:
                period_end_rows.append(row)
            if transaction_date.weekday() >= 5:
                weekend_rows.append(row)
        if abs(signed_amount) >= Decimal("100000") and abs(signed_amount) % Decimal("100000") == 0:
            round_rows.append(row)
        duplicate_groups[
            (
                row.get("bank_account"),
                transaction_date,
                signed_amount,
                str(row.get("counterparty") or ""),
            )
        ].append(row)

    duplicates = [group for group in duplicate_groups.values() if len(group) > 1]
    findings: list[dict[str, Any]] = []
    definitions = (
        ("large_bank_transactions", "high", "存在大额银行流水", large_rows),
        ("period_end_transactions", "medium", "存在期末前后七日银行流水", period_end_rows),
        ("duplicate_bank_transactions", "high", "存在同账户同日同金额同对手方重复流水", [row for group in duplicates for row in group]),
        ("weekend_transactions", "medium", "存在周末银行流水", weekend_rows),
        ("round_amount_transactions", "medium", "存在十万元以上整额流水", round_rows),
    )
    for finding_type, risk_level, title, matched_rows in definitions:
        if not matched_rows:
            continue
        findings.append(
            {
                "finding_type": finding_type,
                "risk_level": risk_level,
                "title": title,
                "description": f"规则命中 {len(matched_rows)} 条，需结合业务背景和支持性文件核查。",
                "amount": _money(sum((abs(_decimal(row.get("amount"))) for row in matched_rows), Decimal("0"))),
                "evidence_refs": [_evidence_ref(row) for row in matched_rows[:20]],
            }
        )

    return {
        "period_end": period_end.isoformat(),
        "row_count": len(rows),
        "total_inflow": _money(total_inflow),
        "total_outflow": _money(total_outflow),
        "large_amount_threshold": _money(large_amount_threshold),
        "rule_hit_counts": {
            "large": len(large_rows),
            "period_end_window": len(period_end_rows),
            "duplicates": sum(len(group) for group in duplicates),
            "weekend": len(weekend_rows),
            "round_amount": len(round_rows),
        },
        "findings": findings,
        "calculation_note": (
            "期末窗口为资产负债表日前后七日；重复流水按账户、日期、金额和对手方组合识别；"
            "规则命中仅表示需要进一步审计，不直接等同于错报或舞弊。"
        ),
    }
