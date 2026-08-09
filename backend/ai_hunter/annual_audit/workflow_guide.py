"""Business-facing annual-audit workflow and delivery contract.

This is deliberately deterministic.  It gives the chat a stable answer for
questions such as "what should a complete annual audit produce?" instead of
leaking orchestration or tool payloads into the user conversation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ANNUAL_AUDIT_PHASES: tuple[dict[str, Any], ...] = (
    {
        "name": "业务承接与前期准备",
        "purpose": "确认项目可承接、审计对象、期间、范围、团队和沟通机制。",
        "procedures": "业务约定与独立性检查；了解被审计单位及其环境；确认期初余额、前任沟通和资料清单。",
        "deliverables": "项目基本信息、业务承接/保持评价、独立性记录、业务约定书、资料清单和审计沟通计划。",
        "gate": "项目范围、责任边界和资料入口已确认。",
    },
    {
        "name": "风险评估、重要性与审计计划",
        "purpose": "把企业风险转化为可执行、可复核的审计策略和程序。",
        "procedures": "识别重大错报和舞弊风险；确定重要性水平；制定总体策略、具体计划、抽样和函证方案；设计控制测试和实质性程序。",
        "deliverables": "风险评估底稿、重要性水平底稿、总体审计策略、具体审计计划、舞弊风险评估、控制测试方案和抽样/函证计划。",
        "gate": "每项重大风险都有对应的审计应对程序、责任人和证据要求。",
    },
    {
        "name": "资料摄入、完整性与证据链",
        "purpose": "确保分析使用的是可识别、可定位、可追溯的原始资料。",
        "procedures": "接收财务报表及附注、科目余额表、序时账/凭证、明细账、银行资料、合同发票和税务资料；分类、解析、校验缺口并建立证据索引。",
        "deliverables": "资料完整性清单、缺口清单、解析结果、数据质量说明、证据索引、原始文件/页码/工作表/行列锚点和版本记录。",
        "gate": "缺失资料、派生底稿和原始账务资料已明确区分；关键结论均可回源。",
    },
    {
        "name": "控制测试与实质性程序",
        "purpose": "围绕风险执行控制测试、分析程序和细节测试，形成各循环底稿。",
        "procedures": "覆盖销售与收款、采购与付款、存货、薪资与人事、货币资金、固定资产等循环；执行抽凭、重新计算、截止测试、账龄、函证、银行流水和异常交易分析。",
        "deliverables": "控制测试底稿、实质性分析底稿、各科目底稿、特殊事项底稿、抽样记录、函证台账及回函/替代程序记录。",
        "gate": "程序已执行或有明确未执行原因；异常、例外和替代程序均有证据与结论。",
    },
    {
        "name": "差异汇总、事项判断与审计完成",
        "purpose": "把发现、调整、未更正错报和重大事项汇总为可发表意见的依据。",
        "procedures": "汇总审计差异和调整分录；评价未更正错报；核查期后事项、持续经营、关联方、税务/法律事项和管理层声明；形成各科目与整体结论。",
        "deliverables": "审计发现清单、审计调整台账、未更正错报汇总、重大事项清单、管理层声明、期后事项检查、持续经营评价和审计完成检查表。",
        "gate": "所有重大事项都有处理结论，并已反映到报告意见或沟通文件。",
    },
    {
        "name": "三级复核与签发",
        "purpose": "通过项目、部门、主任/合伙人三级复核控制专业质量和报告风险。",
        "procedures": "项目经理复核底稿索引、抽样和证据；部门经理复核风险应对、判断和异常解释；主任会计师/合伙人复核意见类型、报告措辞、独立性和签字条件。",
        "deliverables": "三级复核清单、复核意见与整改记录、重大事项沟通记录、复核通过/退回轨迹、签字审批记录。",
        "gate": "复核意见已闭环，未解决事项已升级或阻断正式签发。",
    },
    {
        "name": "正式交付与归档回访",
        "purpose": "形成可交付、可下载、可追溯、可长期保存的最终成果包。",
        "procedures": "锁定最终版本；出具审计报告和附送财务报表/附注；发送管理建议书及重大事项沟通文件；完成归档和客户回访。",
        "deliverables": "正式审计报告、审计报告附送的财务报表及附注、管理建议书、重大事项沟通文件、完整工作底稿包、证据索引、审批日志、归档清单和回访记录。",
        "gate": "只有通过三级复核并完成签发的版本才标记为正式报告；其余均为草稿或待复核成果。",
    },
)


FINAL_DELIVERABLE_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "name": "项目与计划包",
        "items": "业务约定/保持评价、独立性记录、项目画像、风险评估、重要性水平、总体策略、具体审计计划。",
    },
    {
        "name": "资料与证据包",
        "items": "财务报表及附注、科目余额表、序时账/凭证、各类明细账、合同/发票、银行资料、函证及回函、证据索引和资料缺口清单。",
    },
    {
        "name": "工作底稿包",
        "items": "控制测试、实质性分析、六大循环、各科目底稿、特殊事项底稿、抽样记录、函证台账和替代程序记录。",
    },
    {
        "name": "审计结论包",
        "items": "审计发现、审计调整、未更正错报、重大事项、期后事项、持续经营、关联方、税务/法律事项、管理层声明和完成检查。",
    },
    {
        "name": "复核与正式交付包",
        "items": "三级复核与整改记录、正式审计报告、附送财务报表及附注、管理建议书、重大事项沟通文件、签字审批和归档回访记录。",
    },
)


def _status_value(value: Any) -> str:
    if value in (None, ""):
        return "未提供"
    return str(value)


def render_annual_workflow_guide(
    *,
    case_id: int = 0,
    engagement: Mapping[str, Any] | None = None,
    task_summary: Mapping[str, Any] | None = None,
) -> str:
    """Render a concise but complete business answer for annual-audit outputs."""

    lines = [
        "# 年审完整业务流程与最终交付清单",
        "",
        "> 先说结论：完整年审不是一张待办列表，也不是一次自动分析结果。它必须从业务承接开始，经过风险评估、计划、资料与证据、各审计循环、差异与重大事项、三级复核，最终形成正式报告和可追溯归档包。",
        "",
        "## 一、端到端流程",
    ]
    for index, phase in enumerate(ANNUAL_AUDIT_PHASES, start=1):
        lines.extend(
            [
                f"### {index}. {phase['name']}",
                f"- 目的：{phase['purpose']}",
                f"- 主要程序：{phase['procedures']}",
                f"- 应形成：{phase['deliverables']}",
                f"- 放行条件：{phase['gate']}",
            ]
        )

    lines.extend(["", "## 二、最终应该拿到的成果包"])
    for index, group in enumerate(FINAL_DELIVERABLE_GROUPS, start=1):
        lines.append(f"{index}. **{group['name']}**：{group['items']}")

    lines.extend(
        [
            "",
            "## 三、正式报告与草稿的边界",
            "- 审计报告只能在证据充分、重大事项处理完毕、三级复核通过并完成签发后标记为正式报告。",
            "- AI 可以生成资料完整性结果、确定性分析、工作底稿草稿、审计报告初稿、管理建议书草稿和复核任务；这些成果必须保留证据引用、版本和人工复核轨迹。",
            "- 缺少原始账务资料、函证/替代程序、管理层声明、期后事项或复核签字时，只能输出“待补证据/待复核/草稿”，不能输出“无异常”或正式审计意见。",
        ]
    )

    if case_id > 0:
        lines.extend(["", f"## 四、当前项目 {case_id} 的状态提示"])
        if engagement:
            annual_audit = engagement.get("annual_audit") or engagement
            entity_name = _status_value(annual_audit.get("entity_name"))
            period_start = _status_value(annual_audit.get("period_start"))
            period_end = _status_value(annual_audit.get("period_end"))
            lines.append(f"- 被审计单位：{entity_name}；审计期间：{period_start} 至 {period_end}。")
        if task_summary:
            lines.append(
                f"- 当前待办：共 {int(task_summary.get('total') or 0)} 项；"
                f"待执行 {int(task_summary.get('pending') or 0)} 项、"
                f"进行中 {int(task_summary.get('in_progress') or 0)} 项、"
                f"已完成 {int(task_summary.get('completed') or 0)} 项、"
                f"逾期 {int(task_summary.get('overdue') or 0)} 项。"
            )
        lines.extend(
            [
                "- 当前系统的自动化演示范围主要是 F1-2 营业收入、C5-2 应收账款、C1-2 货币资金/银行流水；它们是完整年审的一部分，不代表全部审计程序已经完成。",
                "- 若要进入正式签发，仍需补齐完整资料、控制测试和其他循环底稿、函证或替代程序、差异与重大事项结论、三级复核和管理建议书等成果。",
            ]
        )
    else:
        lines.extend(["", "## 四、使用原则", "- 选择具体年审项目后，系统应把上述交付物映射到资料、底稿、发现、任务、复核和报告状态；没有项目上下文时只展示通用流程。"])

    return "\n".join(lines).strip()


__all__ = [
    "ANNUAL_AUDIT_PHASES",
    "FINAL_DELIVERABLE_GROUPS",
    "render_annual_workflow_guide",
]
