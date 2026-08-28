"""Single-domain annual-audit platform contracts."""

import pytest
from pydantic import ValidationError

from ai_hunter.app.graph.routers import resolve_route_decision
from ai_hunter.app.main import create_app
from ai_hunter.app.settings import Settings
from ai_hunter.app.subgraphs.business_line_executors import build_domain_full_audit_graph
from ai_hunter.app.subgraphs.ingest_graph import finalize_annual_ingest
from ai_hunter.app.tools.registry import tools_for_capability


def annual_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "annual_mysql_database": "ata_ai",
        "annual_mysql_password": "mysql-secret",
        "annual_postgres_password": "postgres-secret",
        "annual_redis_password": "redis-secret",
        "annual_minio_secret_key": "minio-secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_force_single_annual_domain_and_port():
    settings = annual_settings(business_domain="anything", app_port=9999)
    assert settings.business_domain == "annual_audit"
    assert settings.app_port == 8080


def test_settings_reject_missing_or_legacy_mysql_database():
    with pytest.raises(ValidationError, match="MYSQL_DATABASE/ANNUAL_MYSQL_DATABASE"):
        annual_settings(annual_mysql_database="")
    with pytest.raises(ValidationError, match="legacy MySQL database"):
        annual_settings(annual_mysql_database="ata_agent")


def test_settings_rejects_legacy_postgres_database():
    with pytest.raises(ValidationError, match="legacy PostgreSQL database"):
        annual_settings(annual_postgres_database="ai_hunter")


def test_postgres_dsn_is_derived_only_from_annual_settings():
    settings = annual_settings(annual_postgres_dsn="", annual_postgres_port=55432)
    assert settings.postgres_checkpointer_dsn.startswith("postgresql://")
    assert "127.0.0.1:55432/ata_agent_platform" in settings.postgres_checkpointer_dsn


def test_app_mounts_only_platform_and_annual_routes():
    paths = set(create_app().openapi()["paths"])
    assert "/api/cases" in paths
    assert "/api/audit/get_full_context" in paths
    assert "/chat/invoke" in paths
    assert "/evidence/resolve" in paths
    assert "/cases/{case_id}/review" not in paths
    assert "/cases/{case_id}/progress" not in paths


@pytest.mark.parametrize(
    ("query", "capability"),
    [
        ("执行完整年审并生成报告", "audit.full"),
        ("执行年度审计，生成底稿", "audit.full"),
        ("全面检查并生成审计报告草稿", "audit.full"),
        ("请生成本项目的全面年度审计报告初稿，并列出无法执行的审计程序", "audit.full"),
        ("分析收入截止性和应收账龄", "audit.drilldown"),
        ("查看报告结论的证据原文", "evidence.resolve"),
        ("查看银行账户与对手方关系图谱", "graph.query"),
        ("还缺什么资料", "material.validate"),
        ("我想知道年审最终应该有哪些产出结果", "audit.workflow"),
        ("请处理年审项目、资料、审计循环、证据、底稿、报告、任务全部业务流程", "audit.workflow"),
    ],
)
def test_annual_language_routes_to_annual_capabilities(query, capability):
    decision = resolve_route_decision({"query": query, "current_case_id": 7})
    assert decision.capability == capability


def test_registered_tools_are_annual_only():
    names = {tool.name for tool in tools_for_capability("audit.drilldown")}
    assert names == {
        "get_annual_engagement",
        "get_annual_audit_context",
        "analyze_annual_data_readiness",
        "analyze_sales_receivables",
        "analyze_cash_and_bank",
    }
    graph_names = {tool.name for tool in tools_for_capability("graph.query")}
    assert "search_annual_evidence" in graph_names
    assert tools_for_capability("unknown") == []


def test_full_report_factory_builds_annual_graph():
    assert build_domain_full_audit_graph() is not None


def test_finalize_ingest_maps_structured_datasets_to_material_categories():
    result = finalize_annual_ingest(
        {
            "annual_import_summary": {
                "recognized_datasets": ["account_balance", "journal_entry", "receivable_item"],
                "new_row_count": 12,
                "errors": [],
            }
        }
    )
    assert result["categories_found"] == ["trial_balance", "journal_entries", "receivables"]
    assert result["records_inserted"] == 12


def test_redis_keys_are_namespaced_for_annual_project():
    from ai_hunter.annual_audit.storage.redis_keys import annual_redis_key

    settings = annual_settings(annual_redis_namespace="ata:test:")
    assert annual_redis_key("engagement", 7, settings=settings) == "ata:test:annual_audit:engagement:7"
