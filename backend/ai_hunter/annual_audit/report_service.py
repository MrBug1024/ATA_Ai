"""Annual-audit workpaper and report draft generation.

This module deliberately produces fact-grounded drafts.  It does not issue an
audit opinion: missing evidence and unresolved deterministic findings remain
visible for the auditor to review in the unchanged chat/report UI.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .analysis_service import data_readiness, run_cash_and_bank, run_sales_receivables
from .engagement_repository import get_engagement
from .storage import mysql_connection


WORKPAPER_TEMPLATE_VERSION = "customer-workpaper-2023-v1"
REPORT_TEMPLATE_VERSION = "customer-audit-report-v2"

_FULL_AUDIT_MATERIAL_CATEGORIES = (
    ("financial_statements", "财务报表及附注"),
    ("trial_balance", "科目余额表"),
    ("journal_entries", "序时账及凭证明细"),
    ("receivables", "应收账款及往来明细"),
    ("bank_statements", "银行流水及对账单"),
    ("revenue_support", "收入支持性资料"),
    ("confirmations", "函证及回函"),
    ("tax_materials", "纳税申报及税务资料"),
    ("audit_workpapers", "历史审计底稿"),
    ("other", "其他年审资料"),
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _money(value: Any) -> str:
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except Exception:
        amount = Decimal("0.00")
    return f"{amount:,.2f}"


def _finding_lines(
    findings: list[dict[str, Any]],
    *,
    executed: bool = True,
) -> list[str]:
    if not executed:
        return ["- 未执行：缺少可识别的结构化源数据；0 项规则命中不代表不存在异常。"]
    if not findings:
        return ["- 当前已导入数据未触发已配置的确定性风险规则。"]
    lines: list[str] = []
    risk_names = {"high": "高", "medium": "中", "low": "低"}
    for finding in findings:
        risk = risk_names.get(str(finding.get("risk_level") or "").lower(), "待定")
        amount = finding.get("amount")
        suffix = f"；涉及金额/命中金额 {_money(amount)} 元" if amount not in (None, "") else ""
        lines.append(
            f"- 【{risk}风险】{finding.get('title') or '待核查事项'}："
            f"{finding.get('description') or ''}{suffix}"
        )
    return lines


def _missing_lines(readiness: dict[str, Any], analyses: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for label in [
        *(readiness.get("missing_required_data") or []),
        *(readiness.get("supplemental_required_data") or []),
    ]:
        if label and label not in missing:
            missing.append(str(label))
    for analysis in analyses:
        for label in analysis.get("missing_required_data") or []:
            if label and label not in missing:
                missing.append(str(label))
    return [f"- {label}" for label in missing] or ["- 当前演示范围内未发现结构化必需资料缺口。"]


def _available_lines(readiness: dict[str, Any]) -> list[str]:
    available = readiness.get("available_data") or []
    if not available:
        return ["- 当前尚无可用于确定性年审分析的结构化数据。"]
    lines: list[str] = []
    for item in available:
        source_files = [str(name) for name in item.get("source_files") or [] if str(name)]
        sources = f"；来源：{'、'.join(source_files[:5])}" if source_files else ""
        limitation = str(item.get("limitation") or "").strip()
        limitation_text = f"；限制：{limitation}" if limitation else ""
        lines.append(
            f"- {item.get('name') or item.get('code')}：{int(item.get('row_count') or 0)} 行；"
            f"{item.get('quality_label') or '来源待核实'}{sources}{limitation_text}"
        )
    return lines


def _material_source_lines(material_sources: list[dict[str, Any]]) -> list[str]:
    if not material_sources:
        return ["- 当前项目尚无已落库的证据文件。"]
    lines: list[str] = []
    for source in material_sources[:20]:
        file_name = str(source.get("file_name") or "未命名文件")
        file_type = str(source.get("file_type") or "").lower().lstrip(".")
        file_suffix = str(source.get("file_name") or "").lower().rsplit(".", 1)[-1]
        page_count = int(source.get("page_count") or 0)
        chunk_count = int(source.get("chunk_count") or 0)
        records_inserted = int(source.get("records_inserted") or 0)
        unit = (
            "工作表/证据页"
            if file_type in {"xls", "xlsx", "xlsm", "spreadsheet"}
            or file_suffix in {"xls", "xlsx", "xlsm"}
            else "证据页"
        )
        lines.append(
            f"- {file_name}：{page_count} 个{unit}，{chunk_count} 个证据块，"
            f"结构化事实新增 {records_inserted} 行。"
        )
    if any(int(source.get("page_count") or 0) > 0 and int(source.get("records_inserted") or 0) == 0
           for source in material_sources):
        lines.append(
            "- 上述底稿/模板已完整进入证据检索链路，但未作为原始科目余额表、序时账、"
            "应收明细或银行流水写入分析库，以避免把派生审计底稿误当作源账数据。"
        )
    return lines


def _material_category_coverage_lines(material_sources: list[dict[str, Any]]) -> list[str]:
    uploaded = {
        str(source.get("doc_category") or "").strip()
        for source in material_sources
        if str(source.get("doc_category") or "").strip()
    }
    available = [label for code, label in _FULL_AUDIT_MATERIAL_CATEGORIES if code in uploaded]
    unconfirmed = [label for code, label in _FULL_AUDIT_MATERIAL_CATEGORIES if code not in uploaded]
    return [
        f"- 已单独识别：{'、'.join(available) if available else '无'}。",
        f"- 尚未单独上传或分类确认：{'、'.join(unconfirmed) if unconfirmed else '无'}。",
        "- 历史底稿中的同名或相关工作表仅作为审计证据保留；在原始文件未单独提交并核验前，不视为原始资料已经齐备。",
    ]


def render_annual_report_draft(
    *,
    engagement: dict[str, Any],
    readiness: dict[str, Any],
    sales_receivables: dict[str, Any],
    cash_and_bank: dict[str, Any],
    corrections: list[str] | None = None,
    material_sources: list[dict[str, Any]] | None = None,
) -> str:
    """Render the first demo's auditable chat report without invoking an LLM."""

    receivables = sales_receivables.get("receivables") or {}
    revenue = sales_receivables.get("revenue") or {}
    sales_findings = list(sales_receivables.get("findings") or [])
    cash_findings = list(cash_and_bank.get("findings") or [])
    all_findings = [*sales_findings, *cash_findings]
    counts = readiness.get("counts") or {}
    aging = receivables.get("aging_buckets") or {}
    monthly = revenue.get("monthly_revenue") or []
    nonzero_monthly = [
        f"{item.get('month')}月 {_money(item.get('net_revenue'))} 元"
        for item in monthly
        if Decimal(str(item.get("net_revenue") or 0)) != 0
    ]

    lines = [
        "# 年度财务报表审计工作底稿与报告初稿（对话版）",
        "",
        "> 本稿由已上传资料和确定性规则自动生成，供项目组复核。规则命中不等同于错报或舞弊；在证据未闭环、抽样未完成、管理层声明及期后事项未核实前，不形成正式审计意见。",
        "",
        "## 一、项目范围",
        f"- 被审计单位：{engagement.get('entity_name') or '-'}",
        f"- 审计期间：{engagement.get('period_start')} 至 {engagement.get('period_end')}",
        f"- 项目编号：{engagement.get('engagement_code') or '-'}",
        "- 本次自动化演示范围：营业收入、应收账款、货币资金/银行流水。",
        "",
        "## 二、资料就绪度",
        f"- 科目余额行数：{int(counts.get('account_balance_rows') or 0)}",
        f"- 序时账/凭证明细行数：{int(counts.get('journal_entry_rows') or 0)}",
        f"- 应收账款明细行数：{int(counts.get('receivable_rows') or 0)}",
        f"- 银行流水行数：{int(counts.get('bank_transaction_rows') or 0)}",
        "",
        "### 当前已有的结构化资料",
        *_available_lines(readiness),
        "",
        "### 仍缺或需补充的资料",
        *_missing_lines(readiness, [sales_receivables, cash_and_bank]),
        "",
        "### 已纳入的材料与证据来源",
        *_material_source_lines(list(material_sources or [])),
        "",
        "### 全面年审资料类别覆盖",
        *_material_category_coverage_lines(list(material_sources or [])),
        "",
        "## 三、F1-2 营业收入审定与截止分析草稿",
    ]
    if revenue.get("row_count"):
        lines.extend(
            [
                f"- 已分析收入分录：{int(revenue.get('row_count') or 0)} 行。",
                f"- 收入净额（贷方减借方）：{_money(revenue.get('net_revenue'))} 元。",
                f"- 月度收入：{'；'.join(nonzero_monthly) if nonzero_monthly else '导入数据中各月净额均为 0'}。",
                f"- 峰值月份：{revenue.get('peak_month') or '-'} 月，占正向收入 {float(revenue.get('peak_month_share') or 0):.2%}。",
            ]
        )
    else:
        lines.append("- 尚未导入可识别的营业收入序时账，无法完成月度趋势、凭证抽查和截止分析。")
    lines.extend([
        "",
        "### 收入风险规则结果",
        *_finding_lines(revenue.get("findings") or [], executed=bool(revenue.get("row_count"))),
    ])

    lines.extend(["", "## 四、C5-2 应收账款审定与账龄分析草稿"])
    if receivables.get("row_count"):
        lines.extend(
            [
                f"- 已分析应收明细：{int(receivables.get('row_count') or 0)} 行。",
                f"- 应收账款明细合计：{_money(receivables.get('total_balance'))} 元。",
                f"- 未逾期：{_money(aging.get('not_due'))} 元；逾期 1—90 天：{_money(aging.get('overdue_1_90'))} 元。",
                f"- 逾期 91—180 天：{_money(aging.get('overdue_91_180'))} 元；逾期 181—365 天：{_money(aging.get('overdue_181_365'))} 元。",
                f"- 逾期 365 天以上：{_money(aging.get('overdue_over_365'))} 元；缺少日期：{_money(aging.get('undated'))} 元。",
            ]
        )
    else:
        lines.append("- 尚未导入可识别的应收账款明细，无法完成账龄、客户集中度及函证样本建议。")
    lines.extend([
        "",
        "### 应收风险规则结果",
        *_finding_lines(receivables.get("findings") or [], executed=bool(receivables.get("row_count"))),
    ])

    lines.extend(["", "## 五、C1-2 货币资金与银行流水审定草稿"])
    if cash_and_bank.get("row_count"):
        hits = cash_and_bank.get("rule_hit_counts") or {}
        lines.extend(
            [
                f"- 已分析银行流水：{int(cash_and_bank.get('row_count') or 0)} 行。",
                f"- 流入合计：{_money(cash_and_bank.get('total_inflow'))} 元；流出合计：{_money(cash_and_bank.get('total_outflow'))} 元。",
                f"- 大额 {int(hits.get('large') or 0)} 条；期末窗口 {int(hits.get('period_end_window') or 0)} 条；重复组合 {int(hits.get('duplicates') or 0)} 条；周末 {int(hits.get('weekend') or 0)} 条；整额 {int(hits.get('round_amount') or 0)} 条。",
            ]
        )
    else:
        lines.append("- 尚未导入可识别的银行流水，无法完成大额、期末、重复、周末及整额交易筛查。")
    lines.extend([
        "",
        "### 资金风险规则结果",
        *_finding_lines(cash_findings, executed=bool(cash_and_bank.get("row_count"))),
    ])

    lines.extend(["", "## 六、异常凭证与跨循环筛查"])
    if int(counts.get("journal_entry_rows") or 0) > 0:
        lines.append(
            "- 已有序时账/凭证明细，可执行收入相关异常分录与截止性规则；"
            "其他科目的通用异常凭证仍需结合重要性水平和项目组规则补充复核。"
        )
    else:
        lines.append(
            "- 未执行异常凭证筛查：缺少可识别的序时账/凭证明细；"
            "不得将本轮 0 项命中解释为不存在异常凭证。"
        )

    lines.extend(
        [
            "",
            "## 七、需要项目组执行/复核的程序",
            "- 将收入月度波动、借方分录、期末前后七日分录与合同、发票、出库/验收及期后冲回逐项核对。",
            "- 对大额、长账龄及高集中度应收项目形成函证样本，并检查期后回款与减值测算。",
            "- 将银行流水与银行对账单、银行函证、总账余额交叉核对，对大额、重复、周末和整额交易检查审批及业务实质。",
            "- 对每一项差异保留原文件、工作表、行号/单元格和原文引用，人工复核后再更新底稿结论。",
            "",
            "## 八、当前结论",
            (
                f"- 本轮共形成 {len(all_findings)} 项规则命中事项，其中高风险 "
                f"{sum(1 for item in all_findings if item.get('risk_level') == 'high')} 项、中风险 "
                f"{sum(1 for item in all_findings if item.get('risk_level') == 'medium')} 项。"
                if any((revenue.get("row_count"), receivables.get("row_count"), cash_and_bank.get("row_count")))
                else "- 因核心结构化源数据均为 0 行，本轮相关风险规则未执行，不能据此得出无异常结论。"
            ),
            "- 当前仅可形成审计工作底稿和审计报告初稿，不具备签发正式审计报告或表达审计意见的充分条件。",
        ]
    )
    if corrections:
        lines.extend(["", "## 九、本轮重审采用的订正", *[f"- {item}" for item in corrections]])
    return "\n".join(lines).strip()


def _generation_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _persist_draft_artifacts(
    *,
    engagement_id: int,
    snapshot: dict[str, Any],
    report_text: str,
    created_by: str,
    settings: Settings,
) -> dict[str, Any]:
    generation_key = str(snapshot["generation_key"])
    workpaper_specs = (
        ("F1-2", "营业收入审定与截止分析", snapshot.get("sales_receivables", {}).get("revenue") or {}),
        ("C5-2", "应收账款审定与账龄分析", snapshot.get("sales_receivables", {}).get("receivables") or {}),
        ("C1-2", "货币资金与银行流水审定", snapshot.get("cash_and_bank") or {}),
    )
    persisted: list[dict[str, Any]] = []
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM audit_engagement WHERE id = %s FOR UPDATE", (engagement_id,))
            if not cursor.fetchone():
                raise LookupError(f"年审项目 {engagement_id} 不存在")

            for code, name, facts in workpaper_specs:
                cursor.execute(
                    """
                    SELECT id, workpaper_version, facts_json
                    FROM annual_workpaper
                    WHERE engagement_id = %s AND workpaper_code = %s
                    ORDER BY workpaper_version DESC LIMIT 1
                    """,
                    (engagement_id, code),
                )
                latest = cursor.fetchone()
                latest_facts = latest.get("facts_json") if latest else None
                if isinstance(latest_facts, str):
                    latest_facts = json.loads(latest_facts)
                if latest and (latest_facts or {}).get("generation_key") == generation_key:
                    persisted.append(
                        {"code": code, "id": int(latest["id"]), "version": int(latest["workpaper_version"]), "reused": True}
                    )
                    continue
                version = int(latest["workpaper_version"] if latest else 0) + 1
                facts_payload = {"generation_key": generation_key, "facts": facts}
                cursor.execute(
                    """
                    INSERT INTO annual_workpaper (
                      engagement_id, workpaper_code, workpaper_name, template_version,
                      workpaper_version, status, facts_json, conclusion_text, created_by
                    ) VALUES (%s, %s, %s, %s, %s, 'draft', %s, %s, %s)
                    """,
                    (
                        engagement_id,
                        code,
                        name,
                        WORKPAPER_TEMPLATE_VERSION,
                        version,
                        json.dumps(facts_payload, ensure_ascii=False, default=_json_default),
                        "自动生成的事实草稿，须由项目组结合原始证据复核。",
                        created_by,
                    ),
                )
                persisted.append({"code": code, "id": int(cursor.lastrowid), "version": version, "reused": False})

            cursor.execute(
                """
                SELECT id, report_version, fact_snapshot_json
                FROM audit_report
                WHERE engagement_id = %s AND report_type = 'annual_audit_draft'
                ORDER BY report_version DESC LIMIT 1
                """,
                (engagement_id,),
            )
            latest_report = cursor.fetchone()
            latest_snapshot = latest_report.get("fact_snapshot_json") if latest_report else None
            if isinstance(latest_snapshot, str):
                latest_snapshot = json.loads(latest_snapshot)
            if latest_report and (latest_snapshot or {}).get("generation_key") == generation_key:
                report = {
                    "id": int(latest_report["id"]),
                    "version": int(latest_report["report_version"]),
                    "reused": True,
                }
            else:
                report_version = int(latest_report["report_version"] if latest_report else 0) + 1
                cursor.execute(
                    """
                    INSERT INTO audit_report (
                      engagement_id, report_type, template_version, report_version,
                      status, fact_snapshot_json, artifact_ref, created_by
                    ) VALUES (%s, 'annual_audit_draft', %s, %s, 'draft', %s, NULL, %s)
                    """,
                    (
                        engagement_id,
                        REPORT_TEMPLATE_VERSION,
                        report_version,
                        json.dumps({**snapshot, "report_text": report_text}, ensure_ascii=False, default=_json_default),
                        created_by,
                    ),
                )
                report = {"id": int(cursor.lastrowid), "version": report_version, "reused": False}
        connection.commit()
    return {"workpapers": persisted, "report": report}


def generate_annual_report_draft(
    case_id: int,
    *,
    recompute: bool = False,
    corrections: list[str] | None = None,
    material_sources: list[dict[str, Any]] | None = None,
    created_by: str = "ai_agent",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run deterministic cycles, version drafts, and return chat-ready text."""

    resolved = settings or get_settings()
    engagement = get_engagement(case_id, settings=resolved)
    readiness = data_readiness(case_id, settings=resolved)
    sales = run_sales_receivables(case_id, recompute=recompute, settings=resolved)
    cash = run_cash_and_bank(case_id, recompute=recompute, settings=resolved)
    snapshot = {
        "engagement_id": case_id,
        "report_template_version": REPORT_TEMPLATE_VERSION,
        "workpaper_template_version": WORKPAPER_TEMPLATE_VERSION,
        "sales_analysis_run_id": sales.get("analysis_run_id"),
        "cash_analysis_run_id": cash.get("analysis_run_id"),
        "corrections": list(corrections or []),
        "readiness": readiness,
        "material_sources": list(material_sources or []),
        "sales_receivables": sales,
        "cash_and_bank": cash,
    }
    snapshot["generation_key"] = _generation_key(snapshot)
    report_text = render_annual_report_draft(
        engagement=engagement,
        readiness=readiness,
        sales_receivables=sales,
        cash_and_bank=cash,
        corrections=corrections,
        material_sources=material_sources,
    )
    artifacts = _persist_draft_artifacts(
        engagement_id=case_id,
        snapshot=snapshot,
        report_text=report_text,
        created_by=created_by or "ai_agent",
        settings=resolved,
    )
    return {"report_text": report_text, "artifacts": artifacts, "generation_key": snapshot["generation_key"]}


__all__ = [
    "generate_annual_report_draft",
    "render_annual_report_draft",
]
