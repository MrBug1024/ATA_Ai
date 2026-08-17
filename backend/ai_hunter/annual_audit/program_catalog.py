"""Versioned baseline audit-program catalogue.

The catalogue is intentionally a delivery skeleton rather than a substitute
for professional judgement.  It maps the customer's working-paper index into
atomic procedures whose applicable evidence, conclusion and review can be
recorded per engagement.  Firm methodology and applicable standards are
bound separately and frozen by :mod:`execution_service`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PROGRAM_VERSION = "cn-annual-fs-audit-baseline-2026.1"


def _item(
    code: str,
    phase: str,
    cycle: str,
    name: str,
    *,
    assertions: tuple[str, ...] = (),
    risk_area: str = "",
    materials: tuple[str, ...] = (),
    requires_evidence: bool = True,
) -> dict[str, Any]:
    return {
        "procedure_code": code,
        "phase": phase,
        "cycle": cycle,
        "procedure_name": name,
        "assertions": list(assertions),
        "risk_area": risk_area,
        "required_material_categories": list(materials),
        "requires_evidence": requires_evidence,
    }


# Codes preserve the high-level index convention used in the customer supplied
# 296-sheet working-paper package, but are not a claim that its content is
# authoritative evidence for a new engagement.
_CATALOG: tuple[dict[str, Any], ...] = (
    _item(
        "A1",
        "承接与独立性",
        "项目综合",
        "承接/续约、职业道德与独立性评价",
        risk_area="承接风险、独立性威胁",
        materials=("engagement_acceptance",),
    ),
    _item(
        "A2",
        "承接与独立性",
        "项目综合",
        "业务约定书及管理层责任确认",
        risk_area="业务范围与责任边界",
        materials=("engagement_acceptance",),
    ),
    _item(
        "A3",
        "计划",
        "项目综合",
        "总体审计策略、重要性与执行重要性",
        assertions=("所有认定",),
        risk_area="审计范围、重大错报风险",
        materials=("financial_statements", "trial_balance"),
    ),
    _item(
        "A4",
        "计划",
        "项目综合",
        "风险评估、舞弊风险与分析性程序",
        assertions=("发生", "完整性", "截止"),
        risk_area="舞弊及重大错报风险",
        materials=("financial_statements", "trial_balance", "general_ledger", "governance_minutes"),
    ),
    _item(
        "A5",
        "计划",
        "项目综合",
        "了解内部控制并确定进一步审计程序",
        assertions=("发生", "完整性", "准确性"),
        risk_area="控制设计与执行",
        materials=("governance_minutes", "general_ledger"),
    ),
    _item(
        "F1",
        "循环执行",
        "销售与收款",
        "收入发生、截止与舞弊风险应对",
        assertions=("发生", "截止", "准确性"),
        risk_area="收入确认",
        materials=("revenue_support", "general_ledger", "journal_entries"),
    ),
    _item(
        "F2",
        "循环执行",
        "销售与收款",
        "应收账款存在性、可收回性与函证",
        assertions=("存在", "计价和分摊", "权利和义务"),
        risk_area="应收账款及坏账准备",
        materials=("receivables", "confirmations", "revenue_support"),
    ),
    _item(
        "F3",
        "循环执行",
        "销售与收款",
        "销售回款、退货与期后收款测试",
        assertions=("发生", "截止", "计价和分摊"),
        risk_area="虚构收入、期后冲回",
        materials=("bank_statements", "revenue_support", "general_ledger"),
    ),
    _item(
        "C5",
        "循环执行",
        "采购与付款",
        "应付账款完整性、采购截止与供应商函证",
        assertions=("完整性", "截止", "存在"),
        risk_area="未记录负债",
        materials=("accounts_payable", "purchase_support", "confirmations", "general_ledger"),
    ),
    _item(
        "C6",
        "循环执行",
        "采购与付款",
        "采购付款、暂估及期后付款测试",
        assertions=("完整性", "准确性", "截止"),
        risk_area="采购成本及负债错报",
        materials=("purchase_support", "bank_statements", "general_ledger"),
    ),
    _item(
        "C9",
        "循环执行",
        "存货",
        "存货监盘、第三方保管与数量核查",
        assertions=("存在", "完整性", "权利和义务"),
        risk_area="存货数量及权属",
        materials=("inventory_records", "inventory_count"),
    ),
    _item(
        "C10",
        "循环执行",
        "存货",
        "存货计价、跌价准备与截止测试",
        assertions=("计价和分摊", "截止"),
        risk_area="存货减值、成本结转",
        materials=("inventory_records", "purchase_support", "revenue_support", "general_ledger"),
    ),
    _item(
        "D8",
        "循环执行",
        "薪酬与人事",
        "薪酬发生、人员真实性及社保个税核查",
        assertions=("发生", "完整性", "准确性"),
        risk_area="虚列人员、薪酬负债",
        materials=("payroll_hr", "tax_materials", "bank_statements"),
    ),
    _item(
        "D9",
        "循环执行",
        "薪酬与人事",
        "薪酬计提、奖金及期后支付测试",
        assertions=("完整性", "计价和分摊", "截止"),
        risk_area="薪酬计提",
        materials=("payroll_hr", "general_ledger", "bank_statements"),
    ),
    _item(
        "C1",
        "循环执行",
        "资金",
        "银行账户完整性、函证及受限资金核查",
        assertions=("存在", "权利和义务", "完整性"),
        risk_area="资金安全、受限资金",
        materials=("bank_statements", "confirmations", "general_ledger"),
    ),
    _item(
        "C2",
        "循环执行",
        "资金",
        "银行余额调节、流水与大额异常测试",
        assertions=("存在", "完整性", "截止"),
        risk_area="资金流水及余额调节",
        materials=("bank_statements", "general_ledger"),
    ),
    _item(
        "C21",
        "循环执行",
        "固定资产与长期资产",
        "固定资产存在性、权属及实物盘点",
        assertions=("存在", "权利和义务"),
        risk_area="资产权属、闲置及处置",
        materials=("fixed_assets", "asset_rights", "inventory_count"),
    ),
    _item(
        "C22",
        "循环执行",
        "固定资产与长期资产",
        "折旧、减值、资本化与处置测试",
        assertions=("计价和分摊", "完整性", "截止"),
        risk_area="折旧减值与资本化",
        materials=("fixed_assets", "general_ledger", "purchase_support"),
    ),
    _item(
        "G1",
        "完成",
        "跨循环事项",
        "关联方识别、披露和关联交易测试",
        assertions=("完整性", "发生", "披露"),
        risk_area="关联方及关联交易",
        materials=("related_parties", "governance_minutes", "general_ledger"),
    ),
    _item(
        "G2",
        "完成",
        "跨循环事项",
        "税务事项、递延税项及税务风险评价",
        assertions=("完整性", "计价和分摊", "披露"),
        risk_area="税务合规及税项计量",
        materials=("tax_materials", "financial_statements", "general_ledger"),
    ),
    _item(
        "G3",
        "完成",
        "跨循环事项",
        "会计估计、减值和公允价值评价",
        assertions=("计价和分摊", "披露"),
        risk_area="管理层判断和估计不确定性",
        materials=("financial_statements", "general_ledger", "going_concern"),
    ),
    _item(
        "G4",
        "完成",
        "跨循环事项",
        "诉讼、担保、或有事项及法律意见",
        assertions=("完整性", "披露"),
        risk_area="或有负债与承诺",
        materials=("legal_contingencies", "governance_minutes"),
    ),
    _item(
        "G5",
        "完成",
        "跨循环事项",
        "期后事项测试",
        assertions=("完整性", "披露"),
        risk_area="资产负债表日后事项",
        materials=("subsequent_events", "bank_statements", "governance_minutes"),
    ),
    _item(
        "G6",
        "完成",
        "跨循环事项",
        "持续经营评价",
        assertions=("计价和分摊", "披露"),
        risk_area="持续经营重大不确定性",
        materials=("going_concern", "financial_statements", "bank_statements"),
    ),
    _item(
        "G7",
        "完成",
        "跨循环事项",
        "财务报表、附注及其他信息披露复核",
        assertions=("列报和披露",),
        risk_area="财务报表列报与披露",
        materials=("financial_statements",),
    ),
    _item(
        "G8",
        "完成",
        "跨循环事项",
        "审计调整、未更正错报及意见影响汇总",
        assertions=("所有认定",),
        risk_area="错报汇总及审计意见",
        materials=("adjustments", "financial_statements", "trial_balance"),
    ),
    _item(
        "A12",
        "完成",
        "项目综合",
        "管理层声明书与治理层沟通",
        assertions=("所有认定",),
        risk_area="管理层责任与沟通",
        materials=("management_representation", "governance_minutes"),
    ),
    _item(
        "A13",
        "完成",
        "项目综合",
        "完成阶段检查表与审计证据充分性评价",
        assertions=("所有认定",),
        risk_area="完成阶段质量控制",
        materials=("audit_workpapers",),
    ),
)


def baseline_program() -> list[dict[str, Any]]:
    """Return a defensive copy so callers cannot mutate the global catalogue."""

    return deepcopy(list(_CATALOG))


def procedure_codes() -> set[str]:
    return {str(item["procedure_code"]) for item in _CATALOG}


__all__ = ["PROGRAM_VERSION", "baseline_program", "procedure_codes"]
