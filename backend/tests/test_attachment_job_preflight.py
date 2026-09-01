from __future__ import annotations

import pytest

from ai_hunter.annual_audit.attachments.context_service import (
    build_generation_context_snapshot,
)
from ai_hunter.annual_audit.attachments.fact_registry import FactRecord, FactRegistry
from ai_hunter.annual_audit.attachments.job_service import (
    AttachmentJobError,
    _preflight_template_context,
)


def _context(*, financial_statements=None, statement_validation=None):
    return build_generation_context_snapshot(
        engagement={"engagement_id": 7},
        entity_facts={},
        report={"id": 8, "version": 1, "fact_snapshot": {}},
        financial_statements=financial_statements or {},
        financial_statement_validation=statement_validation or {},
        generation_policy_version="annual-attachment-v1",
    )


def _file(source: str) -> dict:
    return {
        "document_code": "financial_statements",
        "binding_manifest": {
            "document_code": "financial_statements",
            "slots": [
                {
                    "slot_id": "statement_rows",
                    "target": "xlsx:table:ATA_STATEMENT",
                    "source": source,
                    "value_type": "table_rows",
                    "required": True,
                    "missing_policy": "block",
                    "style_policy": "clone_prototype_row",
                    "overflow_policy": "extend_rows",
                    "options": {"columns": ["name", "amount"]},
                }
            ],
        },
    }


def test_preflight_blocks_missing_complete_financial_statement_snapshot() -> None:
    with pytest.raises(AttachmentJobError) as caught:
        _preflight_template_context(
            [_file("document.financial_statements.balance_sheet")],
            context=_context(
                statement_validation={
                    "status": "missing",
                    "blockers": [
                        {
                            "code": "FINANCIAL_STATEMENTS_MISSING",
                            "field": "financial_statements",
                            "message": "missing complete statements",
                        }
                    ],
                }
            ),
            registry=FactRegistry([]),
        )

    assert caught.value.code == "FINANCIAL_STATEMENTS_BLOCKED"
    assert caught.value.status_code == 409
    assert caught.value.details[0]["code"] == "FINANCIAL_STATEMENTS_MISSING"


def test_preflight_accepts_explicit_frozen_statement_rows() -> None:
    rows = [{"name": "货币资金", "amount": 100}]
    _preflight_template_context(
        [_file("document.financial_statements.balance_sheet")],
        context=_context(
            financial_statements={"balance_sheet": rows},
            statement_validation={"status": "ready", "blockers": []},
        ),
        registry=FactRegistry([]),
    )


def test_preflight_blocks_whole_active_version_when_one_file_needs_statements() -> None:
    financial_file = _file("document.financial_statements.balance_sheet")
    financial_file.update(
        {
            "id": "financial-file",
            "display_name": "Financial statements",
        }
    )
    report_file = _file("document.engagement.engagement_id")
    report_file.update(
        {
            "id": "report-file",
            "document_code": "audit_report",
            "display_name": "Audit report",
        }
    )
    report_file["binding_manifest"]["document_code"] = "audit_report"
    report_file["binding_manifest"]["slots"][0].update(
        {
            "target": "md:variable:engagement_id",
            "value_type": "scalar",
            "options": {},
            "style_policy": "inherit_template",
            "overflow_policy": "error",
        }
    )

    with pytest.raises(AttachmentJobError) as caught:
        _preflight_template_context(
            [report_file, financial_file],
            context=_context(
                statement_validation={
                    "status": "missing",
                    "blockers": [
                        {
                            "code": "FINANCIAL_STATEMENTS_MISSING",
                            "field": "financial_statements",
                            "message": "missing complete statements",
                        }
                    ],
                }
            ),
            registry=FactRegistry([]),
        )

    assert caught.value.code == "FINANCIAL_STATEMENTS_BLOCKED"
    assert caught.value.details[0]["document_code"] == "financial_statements"


def test_preflight_distinguishes_missing_authoritative_entity_fact() -> None:
    file_record = _file("document.entity.registered_capital")
    file_record["binding_manifest"]["slots"][0].update(
        {
            "target": "xlsx:cell:Sheet1!A1",
            "value_type": "scalar",
            "options": {},
            "style_policy": "inherit_template",
            "overflow_policy": "error",
        }
    )

    with pytest.raises(AttachmentJobError) as caught:
        _preflight_template_context(
            [file_record],
            context=_context(),
            registry=FactRegistry(
                [
                    FactRecord(
                        fact_key="entity.legal_name",
                        value="示例公司",
                        status="approved",
                        source_kind="project_master",
                    )
                ]
            ),
        )

    assert caught.value.code == "REQUIRED_FACT_MISSING"
