"""Regression tests for the governed full annual-audit execution skeleton."""

from pathlib import Path

from ai_hunter.annual_audit.execution_service import (
    _program_completion_blockers,
    canonical_evidence_errors,
    profile_blockers,
    scope_matches_profile,
)
from ai_hunter.annual_audit.knowledge_service import split_knowledge_chunks
from ai_hunter.annual_audit.program_catalog import PROGRAM_VERSION, baseline_program


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_baseline_program_covers_all_six_cycles_and_completion_work():
    program = baseline_program()
    cycles = {item["cycle"] for item in program}

    assert PROGRAM_VERSION.startswith("cn-annual-fs-audit-baseline-")
    assert {
        "销售与收款",
        "采购与付款",
        "存货",
        "薪酬与人事",
        "资金",
        "固定资产与长期资产",
    } <= cycles
    assert {"承接与独立性", "计划", "循环执行", "完成"} == {
        item["phase"] for item in program
    }
    assert {"A1", "F1", "C5", "C9", "D8", "C1", "C21", "G8", "A13"} <= {
        item["procedure_code"] for item in program
    }


def test_completed_program_requires_categories_evidence_and_conclusion():
    item = next(entry for entry in baseline_program() if entry["procedure_code"] == "F1")
    completed = {
        **item,
        "status": "completed",
        "evidence_refs": [{"source_file_id": 7, "source_locator": {"page_no": 2}}],
        "conclusion_text": "已完成收入截止测试，例外事项已转入发现处理。",
    }
    categories = {
        category: {"uploaded": True}
        for category in item["required_material_categories"]
    }

    assert _program_completion_blockers(completed, categories) == []

    without_anchor = {**completed, "evidence_refs": []}
    blocker_codes = {
        item["code"] for item in _program_completion_blockers(without_anchor, categories)
    }
    assert "program.F1.evidence" in blocker_codes

    missing_material = _program_completion_blockers(completed, {})
    assert missing_material[0]["code"] == "program.F1.materials"


def test_evidence_anchor_needs_both_source_file_and_locator():
    assert canonical_evidence_errors(
        [{"source_file_id": 9, "source_locator": {"sheet_name": "序时账", "row_number": 12}}]
    ) == []
    assert "source_file_id" in "；".join(
        canonical_evidence_errors([{"source_locator": {"page_no": 1}}])
    )
    assert "定位" in "；".join(canonical_evidence_errors([{"source_file_id": 9}]))


def test_profile_cannot_pass_without_accepted_and_independent_engagement():
    profile = {
        "entity_type": "有限责任公司",
        "audit_purpose": "年度财务报表审计",
        "accounting_framework": "企业会计准则",
        "firm_name": "示例会计师事务所",
        "engagement_partner": "项目合伙人",
        "signing_cpa_primary": "签字注册会计师",
        "data_classification": "重要数据",
        "data_residency": "中国境内",
        "model_data_policy": "已批准",
        "acceptance_status": "pending",
        "independence_status": "pending",
    }

    blocker_codes = {item["code"] for item in profile_blockers(profile)}
    assert {"profile.acceptance", "profile.independence"} <= blocker_codes

    profile.update({"acceptance_status": "accepted", "independence_status": "cleared"})
    assert profile_blockers(profile) == []


def test_ruleset_scope_cannot_be_frozen_for_an_unmatched_engagement():
    profile = {
        "entity_type": "有限责任公司",
        "accounting_framework": "企业会计准则",
        "industry_code": "制造业",
        "audit_purpose": "年度财务报表审计",
    }

    assert scope_matches_profile({"industries": ["制造业"]}, profile)
    assert not scope_matches_profile({"industries": ["金融业"]}, profile)


def test_knowledge_chunking_keeps_auditable_paragraph_locators():
    first = f"第一条 总则 {'甲' * 150}"
    second = f"第二条 适用范围 {'乙' * 150}"
    chunks = split_knowledge_chunks(f"{first}\n{second}", max_chars=200)

    assert len(chunks) >= 2
    assert all(chunk["locator"].startswith("段落 ") for chunk in chunks)
    assert "第一条 总则" in "".join(chunk["content_text"] for chunk in chunks)


def test_execution_and_knowledge_schema_are_wired_to_deployment():
    migration = (
        REPO_ROOT / "backend" / "sql" / "annual_audit_mysql_v9.sql"
    ).read_text(encoding="utf-8")
    migration_runner = (
        REPO_ROOT / "backend" / "ai_hunter" / "annual_audit" / "storage" / "migrate.py"
    ).read_text(encoding="utf-8")
    compose = (
        REPO_ROOT / "deploy" / "annual-audit" / "docker-compose.yml"
    ).read_text(encoding="utf-8")

    for table in (
        "annual_engagement_profile",
        "annual_audit_program_item",
        "annual_review_decision",
        "annual_knowledge_version",
        "annual_audit_ruleset",
        "annual_engagement_policy_binding",
        "annual_release_gate",
        "annual_audit_issuance",
        "annual_audit_archive",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
    assert '"009"' in migration_runner
    assert "annual_audit_mysql_v9.sql" in compose
    assert "annual_audit_postgres_v2.sql" in compose
