"""Single registry for routed business lines and capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping


BusinessLine = Literal["operator", "audit_analysis", "supervision", "common"]
LegacyIntent = Literal["full_audit", "drilldown", "re_audit", "review"]
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
    legacy_intent: LegacyIntent
    executor: str
    business_line_executor: str | None
    permission_module: str
    access_mode: AccessMode
    requires_case: bool = False
    tool_names: tuple[str, ...] = ()


BUSINESS_LINE_SPECS: Mapping[str, BusinessLineSpec] = MappingProxyType(
    {
        "operator": BusinessLineSpec(
            "operator", "案件创建、材料上传、OCR、类别校验、补件和批次状态", "operator_subgraph"
        ),
        "audit_analysis": BusinessLineSpec(
            "audit_analysis",
            "完整审计、修正重审、局部分析、证据追溯、知识图谱及企业和资金分析",
            "audit_analysis_subgraph",
        ),
        "supervision": BusinessLineSpec(
            "supervision", "任务查询和操作、司法时效、进度及回款复盘", "supervision_subgraph"
        ),
        "common": BusinessLineSpec(
            "common", "闲聊、帮助、导航、澄清和无法稳定判断的请求", "common_subgraph"
        ),
    }
)


def _spec(
    code: str,
    description: str,
    business_line: BusinessLine,
    *,
    intent: LegacyIntent = "drilldown",
    executor: str = "drilldown_agent_graph",
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
        legacy_intent=intent,
        executor=executor,
        business_line_executor=business_executor,
        permission_module=permission,
        access_mode=access,
        requires_case=requires_case,
        tool_names=tools,
    )


_CAPABILITY_SPEC_LIST = (
    _spec(
        "case.create",
        "创建案件",
        "operator",
        business_executor="create_case_command",
        permission="report",
        access="write",
        tools=("create_case",),
    ),
    _spec(
        "case.profile",
        "查询案件画像",
        "operator",
        business_executor="query_case_profile",
        permission="report",
        tools=("get_case_profile",),
    ),
    _spec(
        "material.upload",
        "上传并处理案件材料",
        "operator",
        business_executor="record_material_upload_command",
        permission="report",
        access="write",
        requires_case=True,
        tools=("get_doc_categories", "validate_doc_category", "parse_document", "ingest_structured_fields"),
    ),
    _spec(
        "material.status",
        "查询材料或批次状态",
        "operator",
        business_executor="query_material_status",
        permission="report",
        tools=("get_case_doc_category_status",),
    ),
    _spec(
        "material.validate",
        "校验材料类别和完整性",
        "operator",
        business_executor="query_material_validation",
        permission="report",
        tools=("get_doc_categories", "get_case_doc_category_status", "validate_doc_category"),
    ),
    _spec(
        "audit.full",
        "生成完整审计报告",
        "audit_analysis",
        intent="full_audit",
        executor="full_audit_graph",
        business_executor="full_audit_graph",
        permission="report",
        access="write",
        requires_case=True,
    ),
    _spec(
        "audit.reaudit",
        "记录修正并重新审计",
        "audit_analysis",
        intent="re_audit",
        executor="extract_correction",
        business_executor="reaudit_graph",
        permission="corrections",
        access="write",
        requires_case=True,
    ),
    _spec(
        "audit.drilldown",
        "审计结论下钻分析",
        "audit_analysis",
        business_executor="audit_drilldown_agent",
        tools=(
            "get_case_profile",
            "audit_behavioral_scan",
            "audit_valuation_squeeze",
            "audit_delta_check",
            "audit_deadline_scan",
        ),
    ),
    _spec(
        "evidence.resolve",
        "查询当前案件卷宗证据原文和引用锚点",
        "audit_analysis",
        business_executor="query_evidence",
        permission="graph",
        tools=("resolve_case_evidence",),
    ),
    _spec(
        "caselaw.search",
        "检索外部相似裁判案例，仅供类案参考",
        "audit_analysis",
        business_executor="query_caselaw",
        permission="graph",
        tools=("query_wenshu_knowledge",),
    ),
    _spec(
        "graph.query",
        "查询知识图谱、企业穿透和资金关系",
        "audit_analysis",
        business_executor="graph_query_agent",
        permission="graph",
        tools=("fetch_enterprise", "get_fund_flow", "get_whiteglove_analysis", "query_wenshu_knowledge"),
    ),
    _spec(
        "task.query",
        "查询督办任务",
        "supervision",
        business_executor="query_tasks",
        permission="progress",
        tools=("manage_tasks",),
    ),
    _spec(
        "task.write",
        "创建、完成、指派或更新督办任务",
        "supervision",
        business_executor="write_task_command",
        permission="progress",
        access="write",
        requires_case=True,
        tools=("create_task_batch", "manage_tasks"),
    ),
    _spec(
        "deadline.query",
        "查询司法时效",
        "supervision",
        business_executor="query_deadline",
        permission="deadline",
        tools=("audit_deadline_scan",),
    ),
    _spec(
        "recovery.review",
        "生成回款复盘",
        "supervision",
        intent="review",
        executor="review_graph",
        business_executor="review_graph",
        permission="review",
        access="write",
        requires_case=True,
    ),
    _spec("common.general", "处理闲聊、帮助和导航", "common"),
    _spec(
        "clarify",
        "向用户澄清业务、案件或操作目标",
        "common",
        executor="clarify_route",
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
    if len({line.subgraph_node for line in BUSINESS_LINE_SPECS.values()}) != len(BUSINESS_LINE_SPECS):
        raise ValueError("business line subgraph_node must be unique")
    for code, spec in CAPABILITY_SPECS.items():
        if code != spec.code:
            raise ValueError(f"capability registry key mismatch: {code}")
        if spec.business_line not in BUSINESS_LINE_SPECS:
            raise ValueError(f"unknown business line for capability {code}: {spec.business_line}")
        if spec.legacy_intent not in {"full_audit", "drilldown", "re_audit", "review"}:
            raise ValueError(f"unknown legacy intent for capability {code}: {spec.legacy_intent}")
        if spec.access_mode not in {"read", "write", "system"}:
            raise ValueError(f"unknown access mode for capability {code}: {spec.access_mode}")
        if not spec.executor or not spec.permission_module:
            raise ValueError(f"capability {code} requires executor and permission_module")
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


def capabilities_for_executor(executor: str) -> tuple[str, ...]:
    return tuple(spec.code for spec in CAPABILITY_SPECS.values() if spec.executor == executor)


def capability_permission_modules() -> dict[str, str]:
    return {spec.code: spec.permission_module for spec in CAPABILITY_SPECS.values()}


def render_route_catalog() -> str:
    lines = ["当前注册表允许的业务线与 capability："]
    for line in BUSINESS_LINE_SPECS.values():
        lines.append(f"- {line.code}: {line.description}")
        for spec in CAPABILITY_SPECS.values():
            if spec.business_line == line.code:
                requirement = "（需案件上下文）" if spec.requires_case else ""
                lines.append(f"  - {spec.code}: {spec.description}{requirement}")
    return "\n".join(lines)


validate_capability_registry()
