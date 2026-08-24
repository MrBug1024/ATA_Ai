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

from .analysis_service import (
    ANALYSIS_RULES_VERSION,
    data_readiness,
    run_cash_and_bank,
    run_sales_receivables,
)
from .artifact_service import publish_annual_artifacts
from .citation_manifest_service import (
    DEFAULT_REPORT_TYPE,
    build_manifest_entry,
    persist_report_citation_manifest,
)
from .evidence_service import (
    render_knowledge_graph_trace_appendix,
    trace_items_from_deterministic_findings,
)
from .engagement_repository import get_engagement
from .knowledge_graph_projection import (
    annual_finding_key,
    project_annual_findings_to_knowledge_graph,
)
from .storage import mysql_connection
from .generic_template_repository import get_active_template_catalog, template_version_ref


WORKPAPER_TEMPLATE_VERSION = "customer-workpaper-2023-v1"
REPORT_TEMPLATE_VERSION = "customer-audit-report-v2"
MAX_REPORT_CITATIONS = 20

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
    citation_id_by_finding_key: dict[str, str] | None = None,
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
        citation_id = (citation_id_by_finding_key or {}).get(annual_finding_key(finding), "")
        citation_marker = f" [[cite:{citation_id}]]" if citation_id else ""
        lines.append(
            f"- 【{risk}风险】{finding.get('title') or '待核查事项'}："
            f"{finding.get('description') or ''}{suffix}{citation_marker}"
        )
    return lines


def build_annual_report_citation_plan(
    *,
    case_id: int,
    entity_name: str,
    sales_receivables: dict[str, Any],
    cash_and_bank: dict[str, Any],
) -> dict[str, Any]:
    """Plan report-local citations before rendering the immutable draft.

    The plan is deterministic: a marker is emitted only when a finding has a
    graph claim backed by a canonical platform anchor.  Similar prose never
    receives a guessed citation.
    """

    groups = [
        (
            "F1-2",
            "revenue_risk",
            list((sales_receivables.get("revenue") or {}).get("findings") or []),
            int(sales_receivables.get("analysis_run_id") or 0),
            "sales_receivables",
        ),
        (
            "C5-2",
            "receivables_risk",
            list((sales_receivables.get("receivables") or {}).get("findings") or []),
            int(sales_receivables.get("analysis_run_id") or 0),
            "sales_receivables",
        ),
        (
            "C1-2",
            "cash_and_bank_risk",
            list(cash_and_bank.get("findings") or []),
            int(cash_and_bank.get("analysis_run_id") or 0),
            "cash_and_bank",
        ),
    ]
    ordered_findings: list[tuple[str, str, int, str, dict[str, Any]]] = []
    for section_code, paragraph_prefix, findings, analysis_run_id, analysis_type in groups:
        for index, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                continue
            enriched = dict(finding)
            enriched.setdefault("analysis_run_id", analysis_run_id)
            ordered_findings.append(
                (section_code, paragraph_prefix, index, analysis_type, enriched)
            )

    projection = project_annual_findings_to_knowledge_graph(
        case_id=case_id,
        entity_name=entity_name,
        findings=[item[4] for item in ordered_findings],
        analysis_rules_version=ANALYSIS_RULES_VERSION,
    )
    projected_traces = dict(projection.get("trace_by_finding_key") or {})
    response_trace_candidates: list[dict[str, Any]] = []
    citation_id_by_finding_key: dict[str, str] = {}
    citation_entries: list[dict[str, Any]] = []
    coverage_items: list[dict[str, Any]] = []

    for section_code, paragraph_prefix, finding_index, analysis_type, finding in ordered_findings:
        finding_key = annual_finding_key(finding)
        fallback_traces = trace_items_from_deterministic_findings([finding], limit=1)
        fallback_trace = fallback_traces[0] if fallback_traces else None
        projected_trace = projected_traces.get(finding_key)
        graph_backed = bool(
            isinstance(projected_trace, dict)
            and projected_trace.get("_graph_backed")
            and int(projected_trace.get("claim_id") or 0) > 0
        )
        selected = graph_backed and len(response_trace_candidates) < MAX_REPORT_CITATIONS
        citation_id = ""
        if selected:
            citation_id = str(len(response_trace_candidates) + 1)
            trace = {**projected_trace, "citation_id": citation_id}
            response_trace_candidates.append(trace)
            citation_id_by_finding_key[finding_key] = citation_id
        trace_for_coverage = projected_trace if graph_backed else fallback_trace
        coverage_items.append(
            {
                "finding_key": finding_key,
                "finding": finding,
                "trace": trace_for_coverage,
                "cited": selected,
                "citation_id": citation_id,
            }
        )
        citation_entries.append(
            {
                "citation_id": citation_id,
                "section_code": section_code,
                "paragraph_key": f"{paragraph_prefix}.{finding_index}",
                "annual_finding_key": finding_key,
                "annual_finding_id": int(finding.get("finding_id") or 0),
                "analysis_run_id": int(finding.get("analysis_run_id") or 0),
                "analysis_type": analysis_type,
                "finding_type": str(finding.get("finding_type") or ""),
                "risk_level": str(finding.get("risk_level") or ""),
                "rule_metadata": {
                    "rule_code": str(finding.get("finding_type") or ""),
                    "ruleset_version": ANALYSIS_RULES_VERSION,
                },
                "finding_metadata": {
                    "title": str(finding.get("title") or ""),
                    "description": str(finding.get("description") or ""),
                    "amount": finding.get("amount"),
                    "finding_type": str(finding.get("finding_type") or ""),
                    "risk_level": str(finding.get("risk_level") or ""),
                    "graph_claim_id": int((projected_trace or {}).get("claim_id") or 0),
                    "graph_entity_id": int((projected_trace or {}).get("entity_id") or 0),
                },
                "claim_id": int((projected_trace or {}).get("claim_id") or 0),
                "entity_id": int((projected_trace or {}).get("entity_id") or 0),
                "claim_text": str(
                    (projected_trace or {}).get("claim_text")
                    or (fallback_trace or {}).get("claim_text")
                    or ""
                ),
                "evidence_snapshot": list((trace_for_coverage or {}).get("evidences") or []),
                "anchor_status": "bound" if graph_backed else "unbound",
            }
        )

    missing_items: list[dict[str, Any]] = []
    cited_claims = 0
    unbound_count = 0
    for item in coverage_items:
        trace = item["trace"] if isinstance(item["trace"], dict) else {}
        if item["cited"]:
            cited_claims += 1
            continue
        evidences = [evidence for evidence in trace.get("evidences") or [] if isinstance(evidence, dict)]
        has_bound_anchor = any(
            str(evidence.get("chunk_id") or "")
            and int(evidence.get("file_id") or 0) > 0
            and int(evidence.get("source_page_id") or 0) > 0
            for evidence in evidences
        )
        if not has_bound_anchor:
            unbound_count += 1
        missing_items.append(
            {
                "citation_id": "",
                "claim_id": int(trace.get("claim_id") or 0),
                "claim_type": str(trace.get("claim_type") or item["finding"].get("finding_type") or ""),
                "claim_text": str(
                    trace.get("claim_text")
                    or "：".join(
                        part
                        for part in (
                            str(item["finding"].get("title") or ""),
                            str(item["finding"].get("description") or ""),
                        )
                        if part
                    )
                ),
            }
        )
    total_claims = len(coverage_items)
    coverage = {
        "total_claims": total_claims,
        "cited_claims": cited_claims,
        "uncited_claims": total_claims - cited_claims,
        "coverage_ratio": cited_claims / total_claims if total_claims else 0.0,
        "missing_items": missing_items,
        "unbound_count": unbound_count,
        "evidence_blocked": bool(missing_items),
        "blocking_status": "evidence_blocked" if missing_items else "ready",
    }
    return {
        "citation_id_by_finding_key": citation_id_by_finding_key,
        "response_trace_candidates": response_trace_candidates,
        "citation_entries": citation_entries,
        "citation_coverage": coverage,
        "projection_summary": {
            "projected_count": int(projection.get("projected_count") or 0),
            "unprojected_count": int(projection.get("unprojected_count") or 0),
        },
    }


def _persist_citation_manifest(
    *,
    engagement_id: int,
    artifacts: dict[str, Any],
    citation_entries: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    """Freeze only the citations actually rendered in this report version.

    Unbound or otherwise uncited findings remain in the coverage gate, but
    cannot enter a citation manifest: doing so would make an unresolved item
    look like a released report assertion.
    """

    report = dict(artifacts.get("report") or {})
    annual_report_id = int(report.get("id") or 0)
    report_version = int(report.get("version") or 0)
    if annual_report_id <= 0 or report_version <= 0:
        raise RuntimeError("annual report draft must be persisted before citations")

    entries = []
    for raw_entry in citation_entries:
        if not isinstance(raw_entry, dict):
            continue
        citation_id = str(raw_entry.get("citation_id") or "").strip()
        if not citation_id:
            continue
        entries.append(
            build_manifest_entry(
                engagement_id=engagement_id,
                annual_report_id=annual_report_id,
                report_version=report_version,
                report_type=DEFAULT_REPORT_TYPE,
                citation_id=citation_id,
                section_key=str(raw_entry.get("section_code") or ""),
                paragraph_key=str(raw_entry.get("paragraph_key") or ""),
                annual_finding_id=int(raw_entry.get("annual_finding_id") or 0),
                annual_finding_key=str(raw_entry.get("annual_finding_key") or ""),
                analysis_run_id=int(raw_entry.get("analysis_run_id") or 0),
                analysis_type=str(raw_entry.get("analysis_type") or ""),
                finding_type=str(raw_entry.get("finding_type") or ""),
                risk_level=str(raw_entry.get("risk_level") or ""),
                rule_metadata=dict(raw_entry.get("rule_metadata") or {}),
                finding_metadata=dict(raw_entry.get("finding_metadata") or {}),
                evidence_snapshot=list(raw_entry.get("evidence_snapshot") or []),
            )
        )

    if not entries:
        return {
            "annual_report_id": annual_report_id,
            "report_type": DEFAULT_REPORT_TYPE,
            "report_version": report_version,
            "citation_count": 0,
            "snapshot_hashes": {},
        }

    persisted = persist_report_citation_manifest(
        engagement_id=engagement_id,
        annual_report_id=annual_report_id,
        report_version=report_version,
        report_type=DEFAULT_REPORT_TYPE,
        entries=entries,
        complete_manifest=True,
        settings=settings,
    )
    if len(persisted) != len(entries):
        raise RuntimeError("annual report citation manifest persistence is incomplete")
    return {
        "annual_report_id": annual_report_id,
        "report_type": DEFAULT_REPORT_TYPE,
        "report_version": report_version,
        "citation_count": len(entries),
        "snapshot_hashes": {
            str(entry.get("citation_id") or ""): str(entry.get("snapshot_hash") or "")
            for entry in persisted
        },
    }


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
    execution_gate: dict[str, Any] | None = None,
    citation_id_by_finding_key: dict[str, str] | None = None,
    report_template: dict[str, Any] | None = None,
) -> str:
    """Render a deterministic review draft without invoking an LLM."""

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

    template_content = (report_template or {}).get("content") or {}
    report_title = str(template_content.get("title") or "年度财务报表审计工作底稿与报告初稿")
    lines = [
        f"# {report_title}（对话版）",
        "",
        "> 本稿由已上传资料和确定性规则自动生成，供项目组复核。规则命中不等同于错报或舞弊；在证据未闭环、抽样未完成、管理层声明及期后事项未核实前，不形成正式审计意见。",
        "",
        "## 一、项目范围",
        f"- 被审计单位：{engagement.get('entity_name') or '-'}",
        f"- 审计期间：{engagement.get('period_start')} 至 {engagement.get('period_end')}",
        f"- 项目编号：{engagement.get('engagement_code') or '-'}",
        "- 当前确定性分析范围：营业收入、应收账款、货币资金/银行流水；完整年审程序以项目工作台的受控程序清单为准。",
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
        *_finding_lines(
            revenue.get("findings") or [],
            executed=bool(revenue.get("row_count")),
            citation_id_by_finding_key=citation_id_by_finding_key,
        ),
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
        *_finding_lines(
            receivables.get("findings") or [],
            executed=bool(receivables.get("row_count")),
            citation_id_by_finding_key=citation_id_by_finding_key,
        ),
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
        *_finding_lines(
            cash_findings,
            executed=bool(cash_and_bank.get("row_count")),
            citation_id_by_finding_key=citation_id_by_finding_key,
        ),
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
    if execution_gate:
        program_summary = execution_gate.get("program_summary") or {}
        blockers = list(execution_gate.get("blockers") or [])
        lines.extend(
            [
                "",
                "## 九、完整年审执行与签发门禁",
                (
                    f"- 受控程序：共 {int(program_summary.get('total') or 0)} 项；"
                    f"已完成 {int(program_summary.get('completed') or 0)} 项；"
                    f"不适用 {int(program_summary.get('not_applicable') or 0)} 项；"
                    f"待处理 {int(program_summary.get('open') or 0)} 项。"
                ),
                (
                    "- 当前签发门禁：已具备待签发条件。"
                    if execution_gate.get("gate_status") == "ready_for_signature"
                    else f"- 当前签发门禁：阻断（{len(blockers)} 项）。"
                ),
                *[
                    f"- 待处理：{str(item.get('message') or item.get('code') or '')}"
                    for item in blockers[:20]
                ],
            ]
        )
    if corrections:
        lines.extend(["", "## 十、本轮重审采用的订正", *[f"- {item}" for item in corrections]])
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
    template_versions = snapshot.get("template_versions") or {}
    report_template_version = str(template_versions.get("annual_report") or "unconfigured")
    workpaper_template_version = str(template_versions.get("audit_workpaper") or "unconfigured")
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
                        {
                            "code": code,
                            "name": name,
                            "id": int(latest["id"]),
                            "version": int(latest["workpaper_version"]),
                            "reused": True,
                        }
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
                        workpaper_template_version,
                        version,
                        json.dumps(facts_payload, ensure_ascii=False, default=_json_default),
                        "自动生成的事实草稿，须由项目组结合原始证据复核。",
                        created_by,
                    ),
                )
                persisted.append(
                    {"code": code, "name": name, "id": int(cursor.lastrowid), "version": version, "reused": False}
                )

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
                        report_template_version,
                        report_version,
                        json.dumps({**snapshot, "report_text": report_text}, ensure_ascii=False, default=_json_default),
                        created_by,
                    ),
                )
                report = {"id": int(cursor.lastrowid), "version": report_version, "reused": False}
        connection.commit()
    return {"workpapers": persisted, "report": report}


def _persist_published_artifact_refs(
    *,
    engagement_id: int,
    artifacts: dict[str, Any],
    settings: Settings,
) -> None:
    """Persist generated object references after the render/upload transaction."""

    published = list(artifacts.get("artifacts") or [])
    report_refs = [
        item
        for item in published
        if str(item.get("artifact_type") or "").startswith("annual_report_")
    ]
    report_id = int((artifacts.get("report") or {}).get("id") or 0)
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            if report_id and report_refs:
                cursor.execute(
                    """
                    UPDATE audit_report
                    SET artifact_ref = %s
                    WHERE id = %s AND engagement_id = %s
                    """,
                    (json.dumps(report_refs, ensure_ascii=False), report_id, engagement_id),
                )
            for workpaper in artifacts.get("workpapers") or []:
                workpaper_id = int(workpaper.get("id") or 0)
                code = str(workpaper.get("code") or "")
                refs = [item for item in published if item.get("artifact_type") == f"workpaper_{code}"]
                if workpaper_id and refs:
                    cursor.execute(
                        """
                        UPDATE annual_workpaper
                        SET artifact_ref = %s
                        WHERE id = %s AND engagement_id = %s
                        """,
                        (json.dumps(refs, ensure_ascii=False), workpaper_id, engagement_id),
                    )
        connection.commit()


def _build_followup_tasks(snapshot: dict[str, Any], *, period_end: Any) -> list[dict[str, Any]]:
    """Turn deterministic findings into deduplicated auditor follow-up tasks."""

    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for analysis_type, result_key in (
        ("sales_receivables", "sales_receivables"),
        ("cash_and_bank", "cash_and_bank"),
    ):
        result = snapshot.get(result_key) or {}
        for finding in result.get("findings") or []:
            title = str(finding.get("title") or "待复核审计发现").strip()
            action = f"复核{title}并补充审计证据"
            if action in seen:
                continue
            seen.add(action)
            tasks.append(
                {
                    "task_no": f"AUTO-{len(tasks) + 1:03d}",
                    "action": action,
                    "detail": str(finding.get("description") or "")[:2000],
                    "assigned_role": "项目主审",
                    "deadline": period_end,
                    "deliverable": "复核记录、支持性证据和处理结论",
                    "priority": {
                        "urgent": "紧急",
                        "high": "高",
                        "medium": "中",
                        "low": "低",
                    }.get(str(finding.get("risk_level") or "").lower(), str(finding.get("risk_level") or "中")),
                    "source_engine": f"annual_{analysis_type}",
                }
            )
    return tasks


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
    from .execution_service import bootstrap_execution

    execution = bootstrap_execution(
        case_id,
        actor_user_id=created_by or "ai_agent",
        settings=resolved,
    )
    execution_gate = dict(execution.get("release_gate") or {})
    template_catalog = get_active_template_catalog(settings=resolved)
    template_versions = {
        template_type: template_version_ref(template)
        for template_type, template in template_catalog.items()
    }
    readiness = data_readiness(case_id, settings=resolved)
    sales = run_sales_receivables(case_id, recompute=recompute, settings=resolved)
    cash = run_cash_and_bank(case_id, recompute=recompute, settings=resolved)
    citation_plan = build_annual_report_citation_plan(
        case_id=case_id,
        entity_name=str(engagement.get("entity_name") or ""),
        sales_receivables=sales,
        cash_and_bank=cash,
    )
    snapshot = {
        "engagement_id": case_id,
        # Keep the identity and period in the frozen fact snapshot.  Artifact
        # rendering happens after the report transaction and must not depend
        # on a second mutable engagement lookup to fill customer templates.
        "engagement": {
            "engagement_code": engagement.get("engagement_code") or "",
            "entity_name": engagement.get("entity_name") or "",
            "entity_uscc": engagement.get("entity_uscc") or "",
            "fiscal_year": engagement.get("fiscal_year") or "",
            "period_start": engagement.get("period_start") or "",
            "period_end": engagement.get("period_end") or "",
        },
        "engagement_code": engagement.get("engagement_code") or "",
        "entity_name": engagement.get("entity_name") or "",
        "fiscal_year": engagement.get("fiscal_year") or "",
        "period_end": engagement.get("period_end") or "",
        "report_template_version": template_versions.get("annual_report") or "unconfigured",
        "workpaper_template_version": template_versions.get("audit_workpaper") or "unconfigured",
        "template_versions": template_versions,
        "sales_analysis_run_id": sales.get("analysis_run_id"),
        "cash_analysis_run_id": cash.get("analysis_run_id"),
        "corrections": list(corrections or []),
        "readiness": readiness,
        "material_sources": list(material_sources or []),
        "sales_receivables": sales,
        "cash_and_bank": cash,
        "execution_program_version": execution.get("program_version"),
        "release_gate": execution_gate,
        "citation_plan_summary": {
            "cited_claims": int((citation_plan.get("citation_coverage") or {}).get("cited_claims") or 0),
            "total_claims": int((citation_plan.get("citation_coverage") or {}).get("total_claims") or 0),
            "projected_count": int((citation_plan.get("projection_summary") or {}).get("projected_count") or 0),
        },
        # The report version must change when the exact claim/anchor plan
        # changes, even where aggregate counts happen to be identical.
        "citation_plan_entries": [
            {
                "citation_id": str(entry.get("citation_id") or ""),
                "annual_finding_key": str(entry.get("annual_finding_key") or ""),
                "claim_id": int(entry.get("claim_id") or 0),
                "evidence_snapshot": list(entry.get("evidence_snapshot") or []),
            }
            for entry in citation_plan.get("citation_entries") or []
            if isinstance(entry, dict) and str(entry.get("citation_id") or "")
        ],
        "workpaper_facts": {
            "F1-2": sales.get("revenue") or {},
            "C5-2": sales.get("receivables") or {},
            "C1-2": cash,
        },
    }
    snapshot["generation_key"] = _generation_key(snapshot)
    report_text = render_annual_report_draft(
        engagement=engagement,
        readiness=readiness,
        sales_receivables=sales,
        cash_and_bank=cash,
        corrections=corrections,
        material_sources=material_sources,
        execution_gate=execution_gate,
        citation_id_by_finding_key=dict(citation_plan.get("citation_id_by_finding_key") or {}),
        report_template=template_catalog.get("annual_report"),
    )
    trace_appendix = render_knowledge_graph_trace_appendix(
        list(citation_plan.get("response_trace_candidates") or [])
    )
    if trace_appendix:
        report_text = f"{report_text}\n\n{trace_appendix}"
    artifacts = _persist_draft_artifacts(
        engagement_id=case_id,
        snapshot=snapshot,
        report_text=report_text,
        created_by=created_by or "ai_agent",
        settings=resolved,
    )
    citation_manifest = _persist_citation_manifest(
        engagement_id=case_id,
        artifacts=artifacts,
        citation_entries=list(citation_plan.get("citation_entries") or []),
        settings=resolved,
    )
    artifacts = {**artifacts, "citation_manifest": citation_manifest}
    published = publish_annual_artifacts(
        engagement_id=case_id,
        report_text=report_text,
        snapshot=snapshot,
        report_version=int((artifacts.get("report") or {}).get("version") or 1),
        workpapers=list(artifacts.get("workpapers") or []),
    )
    _persist_published_artifact_refs(
        engagement_id=case_id,
        artifacts={**artifacts, **published},
        settings=resolved,
    )
    from .task_repository import create_task_batch

    task_result = create_task_batch(
        case_id,
        _build_followup_tasks(snapshot, period_end=engagement["period_end"]),
        settings=resolved,
    )
    artifacts = {**artifacts, **published, "tasks": task_result}
    return {
        "report_text": report_text,
        "artifacts": artifacts,
        "generation_key": snapshot["generation_key"],
        "active_template_versions": template_versions,
        # The report generator plans these citations before rendering.  The
        # response finalizer must use this exact list instead of querying a
        # later project-wide analysis run.
        "response_trace_candidates": list(citation_plan.get("response_trace_candidates") or []),
        "response_citation_coverage": dict(citation_plan.get("citation_coverage") or {}),
        "citation_entries": list(citation_plan.get("citation_entries") or []),
        "annual_report_manifest": citation_manifest,
    }


__all__ = [
    "generate_annual_report_draft",
    "build_annual_report_citation_plan",
    "render_annual_report_draft",
]
