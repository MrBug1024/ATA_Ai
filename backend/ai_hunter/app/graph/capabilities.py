"""Single annual-audit registry for routed business lines and capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping


BusinessLine = Literal["operator", "audit_analysis", "supervision", "common"]
GraphIntent = Literal["full_audit", "drilldown", "re_audit"]
AccessMode = Literal["read", "write", "system"]


@dataclass(frozen=True)
class BusinessLineSpec:
    code: BusinessLine
    description: str
    subgraph_node: str


@dataclass(frozen=True)
class CapabilitySpec:
    code: str
    description: str
    business_line: BusinessLine
    intent: GraphIntent
    business_line_executor: str | None
    permission_module: str
    access_mode: AccessMode
    requires_case: bool = False
    tool_names: tuple[str, ...] = ()


BUSINESS_LINE_SPECS: Mapping[str, BusinessLineSpec] = MappingProxyType(
    {
        "operator": BusinessLineSpec(
            "operator",
            "年审项目创建、资料上传、OCR、分类校验与资料完整性",
            "operator_subgraph",
        ),
        "audit_analysis": BusinessLineSpec(
            "audit_analysis",
            "完整年审、订正重跑、循环分析、证据追溯、关系图谱、底稿与报告",
            "audit_analysis_subgraph",
        ),
        "supervision": BusinessLineSpec(
            "supervision",
            "审计程序、待办任务、分派与复核跟踪",
            "supervision_subgraph",
        ),
        "common": BusinessLineSpec(
            "common",
            "年审帮助、导航、澄清和通用问答",
            "common_subgraph",
        ),
    }
)


def _spec(
    code: str,
    description: str,
    business_line: BusinessLine,
    *,
    intent: GraphIntent = "drilldown",
    business_executor: str | None = None,
    permission: str = "drilldown",
    access: AccessMode = "read",
    requires_case: bool = False,
    tools: tuple[str, ...] = (),
) -> CapabilitySpec:
    return CapabilitySpec(
        code=code,
        description=description,
        business_line=business_line,
        intent=intent,
        business_line_executor=business_executor,
        permission_module=permission,
        access_mode=access,
        requires_case=requires_case,
        tool_names=tools,
    )


_CAPABILITY_SPEC_LIST = (
    _spec(
        "case.create",
        "创建年度审计项目",
        "operator",
        business_executor="create_case_command",
        permission="report",
        access="write",
    ),
    _spec(
        "case.profile",
        "查询年审项目画像与审计期间",
        "operator",
        business_executor="query_case_profile",
        permission="report",
        tools=("get_annual_engagement",),
    ),
    _spec(
        "material.upload",
        "上传并处理财务与审计资料",
        "operator",
        business_executor="record_material_upload_command",
        permission="report",
        access="write",
        requires_case=True,
    ),
    _spec(
        "material.status",
        "查询资料处理状态和缺口",
        "operator",
        business_executor="query_material_status",
        permission="report",
        requires_case=True,
        tools=("get_annual_material_status",),
    ),
    _spec(
        "material.validate",
        "校验资料类别、完整性和结构化数据就绪度",
        "operator",
        business_executor="query_material_validation",
        permission="report",
        requires_case=True,
        tools=(
            "list_annual_material_requirements",
            "get_annual_material_status",
            "analyze_annual_data_readiness",
        ),
    ),
    _spec(
        "audit.full",
        "生成完整年审底稿和报告草稿",
        "audit_analysis",
        intent="full_audit",
        business_executor="full_audit_graph",
        permission="report",
        access="write",
        requires_case=True,
    ),
    _spec(
        "audit.reaudit",
        "记录权威订正并重新生成底稿和报告",
        "audit_analysis",
        intent="re_audit",
        business_executor="reaudit_graph",
        permission="corrections",
        access="write",
        requires_case=True,
    ),
    _spec(
        "audit.drilldown",
        "对收入、应收、货币资金等审计循环下钻分析",
        "audit_analysis",
        business_executor="annual_audit_drilldown_agent",
        requires_case=True,
        tools=(
            "get_annual_engagement",
            "get_annual_audit_context",
            "analyze_annual_data_readiness",
            "analyze_sales_receivables",
            "analyze_cash_and_bank",
        ),
    ),
    _spec(
        "evidence.resolve",
        "查询当前年审项目的原始证据、引用与页锚点",
        "audit_analysis",
        business_executor="query_evidence",
        permission="graph",
        requires_case=True,
    ),
    _spec(
        "graph.query",
        "查询主体、交易、账户和资金流向关系图谱",
        "audit_analysis",
        business_executor="graph_query_agent",
        permission="graph",
        requires_case=True,
        tools=("get_annual_engagement", "get_annual_audit_context", "search_annual_evidence"),
    ),
    _spec(
        "task.query",
        "查询审计程序和待办任务",
        "supervision",
        business_executor="query_tasks",
        permission="tasks",
        requires_case=True,
        tools=("list_annual_tasks",),
    ),
    _spec(
        "task.write",
        "创建、完成、指派或更新审计任务",
        "supervision",
        business_executor="write_task_command",
        permission="tasks",
        access="write",
        requires_case=True,
    ),
    _spec("common.general", "处理年审帮助、导航和通用问答", "common"),
    _spec(
        "clarify",
        "澄清年审项目、资料、循环或操作目标",
        "common",
        access="system",
    ),
)

CAPABILITY_SPECS: Mapping[str, CapabilitySpec] = MappingProxyType(
    {spec.code: spec for spec in _CAPABILITY_SPEC_LIST}
)
BUSINESS_LINE_IDS = tuple(BUSINESS_LINE_SPECS)
CAPABILITY_IDS = tuple(CAPABILITY_SPECS)


def validate_capability_registry() -> None:
    if len(CAPABILITY_SPECS) != len(_CAPABILITY_SPEC_LIST):
        raise ValueError("capability code must be unique")
    for code, spec in CAPABILITY_SPECS.items():
        if code != spec.code or spec.business_line not in BUSINESS_LINE_SPECS:
            raise ValueError(f"invalid capability registration: {code}")
        if spec.access_mode not in {"read", "write", "system"}:
            raise ValueError(f"invalid access mode for capability {code}")
        if len(spec.tool_names) != len(set(spec.tool_names)):
            raise ValueError(f"capability {code} contains duplicate tools")


def get_capability_spec(capability: str) -> CapabilitySpec | None:
    return CAPABILITY_SPECS.get(str(capability or ""))


def get_business_line_spec(business_line: str) -> BusinessLineSpec | None:
    return BUSINESS_LINE_SPECS.get(str(business_line or ""))


def capabilities_for_business_line(business_line: str) -> tuple[str, ...]:
    return tuple(spec.code for spec in CAPABILITY_SPECS.values() if spec.business_line == business_line)


def capability_node_name(capability: str) -> str:
    spec = get_capability_spec(capability)
    if spec is not None and spec.business_line_executor:
        return spec.business_line_executor
    return f"plan_{str(capability or '').replace('.', '_')}"


def business_line_enabled_capabilities() -> tuple[str, ...]:
    return tuple(spec.code for spec in CAPABILITY_SPECS.values() if spec.business_line_executor)


def capability_permission_modules() -> dict[str, str]:
    return {spec.code: spec.permission_module for spec in CAPABILITY_SPECS.values()}


def render_route_catalog() -> str:
    lines = ["年度审计智能体当前允许的业务线与能力："]
    for line in BUSINESS_LINE_SPECS.values():
        lines.append(f"- {line.code}: {line.description}")
        for spec in CAPABILITY_SPECS.values():
            if spec.business_line == line.code:
                requirement = "（需年审项目上下文）" if spec.requires_case else ""
                lines.append(f"  - {spec.code}: {spec.description}{requirement}")
    return "\n".join(lines)


validate_capability_registry()
