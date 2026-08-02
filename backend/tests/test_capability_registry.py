import pytest
from pydantic import ValidationError

from ai_hunter.app.graph.capabilities import (
    BUSINESS_LINE_IDS,
    BUSINESS_LINE_SPECS,
    CAPABILITY_IDS,
    CAPABILITY_SPECS,
    business_line_enabled_capabilities,
    capabilities_for_executor,
    capability_permission_modules,
    get_capability_spec,
    render_route_catalog,
    validate_capability_registry,
)
from ai_hunter.app.graph.schemas import RouteDecisionModel
from ai_hunter.app.settings import Settings


def test_capability_registry_is_complete_and_consistent():
    validate_capability_registry()

    assert BUSINESS_LINE_IDS == ("operator", "audit_analysis", "supervision", "common")
    assert len(CAPABILITY_IDS) == 17
    assert len(set(CAPABILITY_IDS)) == len(CAPABILITY_IDS)
    assert all(spec.business_line in BUSINESS_LINE_IDS for spec in CAPABILITY_SPECS.values())
    assert all(spec.executor and spec.permission_module for spec in CAPABILITY_SPECS.values())
    assert {spec.subgraph_node for spec in BUSINESS_LINE_SPECS.values()} == {
        "operator_subgraph",
        "audit_analysis_subgraph",
        "supervision_subgraph",
        "common_subgraph",
    }


def test_capability_registry_preserves_legacy_execution_contract():
    assert get_capability_spec("audit.full").legacy_intent == "full_audit"
    assert get_capability_spec("audit.reaudit").executor == "extract_correction"
    assert get_capability_spec("recovery.review").legacy_intent == "review"
    assert get_capability_spec("task.write").access_mode == "write"
    assert get_capability_spec("unknown") is None

    drilldown_capabilities = capabilities_for_executor("drilldown_agent_graph")
    assert "audit.drilldown" in drilldown_capabilities
    assert "audit.full" not in drilldown_capabilities
    assert set(business_line_enabled_capabilities()) == {
        "case.create",
        "case.profile",
        "material.upload",
        "material.status",
        "material.validate",
        "audit.full",
        "audit.reaudit",
        "audit.drilldown",
        "evidence.resolve",
        "caselaw.search",
        "graph.query",
        "task.query",
        "task.write",
        "deadline.query",
        "recovery.review",
    }
    assert {
        code
        for code in business_line_enabled_capabilities()
        if CAPABILITY_SPECS[code].access_mode == "write"
    } == {
        "case.create",
        "material.upload",
        "audit.full",
        "audit.reaudit",
        "task.write",
        "recovery.review",
    }
    assert {
        code
        for code, spec in CAPABILITY_SPECS.items()
        if spec.access_mode == "write" and not spec.business_line_executor
    } == set()
    assert CAPABILITY_SPECS["evidence.resolve"].tool_names == ("resolve_case_evidence",)
    assert CAPABILITY_SPECS["caselaw.search"].tool_names == ("query_wenshu_knowledge",)
    assert {code for code, spec in CAPABILITY_SPECS.items() if spec.requires_case} == {
        "audit.full",
        "audit.reaudit",
        "material.upload",
        "recovery.review",
        "task.write",
    }


def test_capability_registry_drives_permissions_and_router_catalog():
    modules = capability_permission_modules()
    catalog = render_route_catalog()

    assert modules["graph.query"] == "graph"
    assert modules["caselaw.search"] == "graph"
    assert modules["task.write"] == "progress"
    assert "audit_analysis: 完整审计" in catalog
    assert "  - graph.query: 查询知识图谱" in catalog
    assert "  - caselaw.search: 检索外部相似裁判案例" in catalog
    assert "  - audit.full: 生成完整审计报告（需案件上下文）" in catalog


def test_capability_registry_is_read_only():
    with pytest.raises(TypeError):
        CAPABILITY_SPECS["unknown"] = CAPABILITY_SPECS["clarify"]


def test_route_schema_uses_registry_and_rejects_unknown_capability():
    decision = RouteDecisionModel(
        business_line="common",
        capability="graph.query",
        confidence=0.9,
    )

    assert decision.business_line == "audit_analysis"
    assert decision.intent == "drilldown"
    with pytest.raises(ValidationError):
        RouteDecisionModel(business_line="common", capability="unknown")


def test_router_execution_mode_defaults_to_legacy_and_rejects_unknown_mode():
    assert Settings(_env_file=None).router_execution_mode == "legacy"
    assert Settings(_env_file=None, router_execution_mode="business_line").router_execution_mode == "business_line"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, router_execution_mode="invalid")
