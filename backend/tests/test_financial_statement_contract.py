from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ai_hunter.annual_audit import api
from ai_hunter.annual_audit import execution_service
from ai_hunter.annual_audit.attachments import job_service
from ai_hunter.annual_audit.attachments.agent_graph import (
    compose_document_payload,
    prepare_attachment,
)
from ai_hunter.annual_audit.attachments.content_schemas import BindingManifest
from ai_hunter.annual_audit.attachments.context_service import (
    GenerationContextSnapshot,
    build_generation_context_snapshot,
)
from ai_hunter.annual_audit.attachments.fact_registry import FactRegistry
from ai_hunter.annual_audit.attachments.financial_statements import (
    FinancialStatementPackage,
    FinancialStatementsContext,
    adapt_financial_statement_snapshot,
)
from ai_hunter.annual_audit.report_service import freeze_financial_statement_input


def _evidence(row: int) -> list[dict]:
    return [
        {
            "source_file_id": 91,
            "source_sha256": "a" * 64,
            "source_locator": {
                "sheet_name": "审定报表",
                "cell_range": f"A{row}:D{row}",
            },
        }
    ]


def _line(
    line_id: str,
    line_name: str,
    current: str,
    comparative: str,
    order: int,
    *,
    note_ref: str | None = None,
    total: bool = False,
    semantic_role: str | None = None,
) -> dict:
    return {
        "line_id": line_id,
        "line_name": line_name,
        "current_amount": current,
        "comparative_amount": comparative,
        "section": "测试分部",
        "display_order": order,
        "note_ref": note_ref,
        "is_total": total,
        "semantic_role": semantic_role,
        "evidence_refs": _evidence(order + 1),
    }


def _package_value() -> dict:
    return {
        "schema_version": "1.0",
        "approval_status": "approved",
        "approved_by": "reviewer-1",
        "approved_at": "2026-01-15T09:30:00+08:00",
        "source_revision": "ledger-close-v7",
        "currency": "CNY",
        "unit": "1",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "comparative_period_start": "2024-01-01",
        "comparative_period_end": "2024-12-31",
        "balance_sheet": {
            "statement_type": "balance_sheet",
            "title": "资产负债表",
            "rows": [
                _line(
                    "assets.total",
                    "资产总计",
                    "100",
                    "90",
                    1,
                    total=True,
                    semantic_role="balance.total_assets",
                ),
                _line(
                    "liabilities.total",
                    "负债合计",
                    "60",
                    "50",
                    2,
                    total=True,
                    semantic_role="balance.total_liabilities",
                ),
                _line(
                    "equity.total",
                    "所有者权益合计",
                    "40",
                    "40",
                    3,
                    total=True,
                    semantic_role="balance.total_equity",
                ),
                _line(
                    "cash.cash_equivalents",
                    "货币资金",
                    "20",
                    "18",
                    4,
                    note_ref="note.cash",
                    semantic_role="balance.cash_and_cash_equivalents",
                ),
            ],
        },
        "income_statement": {
            "statement_type": "income_statement",
            "title": "利润表",
            "rows": [
                _line(
                    "profit.net",
                    "净利润",
                    "12",
                    "10",
                    10,
                    total=True,
                    semantic_role="income.net_profit",
                ),
                _line(
                    "revenue.operating",
                    "营业收入",
                    "100",
                    "90",
                    11,
                    semantic_role="income.operating_revenue",
                ),
                _line(
                    "profit.operating",
                    "营业利润",
                    "18",
                    "15",
                    12,
                    total=True,
                    semantic_role="income.operating_profit",
                ),
                _line(
                    "profit.before_tax",
                    "利润总额",
                    "16",
                    "13",
                    13,
                    total=True,
                    semantic_role="income.profit_before_tax",
                ),
            ],
        },
        "cash_flow_statement": {
            "statement_type": "cash_flow_statement",
            "title": "现金流量表",
            "rows": [
                _line(
                    "cash.ending",
                    "期末现金及现金等价物余额",
                    "20",
                    "18",
                    20,
                    total=True,
                    semantic_role="cash_flow.cash_ending",
                ),
                _line(
                    "cash.beginning",
                    "期初现金及现金等价物余额",
                    "18",
                    "15",
                    21,
                    semantic_role="cash_flow.cash_beginning",
                ),
                _line(
                    "cash.net_change",
                    "现金及现金等价物净增加额",
                    "2",
                    "3",
                    22,
                    semantic_role="cash_flow.net_cash_change",
                ),
            ],
        },
        "notes": [
            {
                "note_id": "note.cash",
                "title": "货币资金",
                "paragraphs": ["余额已经项目组复核。"],
                "line_refs": [
                    {
                        "statement_type": "balance_sheet",
                        "line_id": "cash.cash_equivalents",
                    }
                ],
                "evidence_refs": _evidence(30),
            }
        ],
        "note_tie_outs": [
            {
                "note_id": "note.cash",
                "statement_type": "balance_sheet",
                "line_id": "cash.cash_equivalents",
                "current_note_amount": "20",
                "comparative_note_amount": "18",
                "tolerance": "0",
                "evidence_refs": _evidence(31),
            }
        ],
        "reconciliations": [
            {
                "check_id": "balance.current",
                "kind": "balance_equation",
                "description": "资产总计等于负债与所有者权益合计",
                "left_terms": [
                    {"statement_type": "balance_sheet", "line_id": "assets.total"}
                ],
                "right_terms": [
                    {"statement_type": "balance_sheet", "line_id": "liabilities.total"},
                    {"statement_type": "balance_sheet", "line_id": "equity.total"},
                ],
                "tolerance": "0",
            },
            {
                "check_id": "cash.ending",
                "kind": "cash_to_balance_sheet",
                "description": "现金流量表期末现金与资产负债表货币资金一致",
                "left_terms": [
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.ending",
                    }
                ],
                "right_terms": [
                    {
                        "statement_type": "balance_sheet",
                        "line_id": "cash.cash_equivalents",
                    }
                ],
                "tolerance": "0",
            },
            {
                "check_id": "cash.movement",
                "kind": "cash_movement",
                "description": "期末现金等于期初现金加本期净增加额",
                "left_terms": [
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.ending",
                    }
                ],
                "right_terms": [
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.beginning",
                    },
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.net_change",
                    },
                ],
                "tolerance": "0",
            },
            {
                "check_id": "balance.comparative",
                "kind": "balance_equation",
                "description": "比较期资产总计等于负债与所有者权益合计",
                "left_terms": [
                    {
                        "statement_type": "balance_sheet",
                        "line_id": "assets.total",
                        "amount_field": "comparative_amount",
                    }
                ],
                "right_terms": [
                    {
                        "statement_type": "balance_sheet",
                        "line_id": "liabilities.total",
                        "amount_field": "comparative_amount",
                    },
                    {
                        "statement_type": "balance_sheet",
                        "line_id": "equity.total",
                        "amount_field": "comparative_amount",
                    },
                ],
                "tolerance": "0",
            },
            {
                "check_id": "cash.ending.comparative",
                "kind": "cash_to_balance_sheet",
                "description": "比较期期末现金与资产负债表货币资金一致",
                "left_terms": [
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.ending",
                        "amount_field": "comparative_amount",
                    }
                ],
                "right_terms": [
                    {
                        "statement_type": "balance_sheet",
                        "line_id": "cash.cash_equivalents",
                        "amount_field": "comparative_amount",
                    }
                ],
                "tolerance": "0",
            },
            {
                "check_id": "cash.movement.comparative",
                "kind": "cash_movement",
                "description": "比较期期末现金等于期初现金加净增加额",
                "left_terms": [
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.ending",
                        "amount_field": "comparative_amount",
                    }
                ],
                "right_terms": [
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.beginning",
                        "amount_field": "comparative_amount",
                    },
                    {
                        "statement_type": "cash_flow_statement",
                        "line_id": "cash.net_change",
                        "amount_field": "comparative_amount",
                    },
                ],
                "tolerance": "0",
            },
        ],
    }


def test_complete_package_round_trips_to_typed_renderer_context() -> None:
    package = FinancialStatementPackage.model_validate(_package_value())
    adaptation = adapt_financial_statement_snapshot(package.frozen_report_value())

    assert adaptation.status == "ready"
    assert adaptation.blockers == ()
    assert adaptation.context is not None
    context = build_generation_context_snapshot(
        engagement={"engagement_id": 7},
        report={"id": 8, "version": 1, "fact_snapshot": {}},
        financial_statements=adaptation.context,
        financial_statement_validation=adaptation.validation_snapshot(),
        generation_policy_version="annual-attachment-v1",
    )
    restored = GenerationContextSnapshot.model_validate(json.loads(context.canonical_bytes()))

    assert isinstance(restored.financial_statements, FinancialStatementsContext)
    assert restored.financial_statements.balance_sheet[0].current_amount == Decimal("100")
    assert restored.financial_statement_validation["status"] == "ready"


def test_statement_table_composition_keeps_amounts_and_source_evidence() -> None:
    adaptation = adapt_financial_statement_snapshot(_package_value())
    context = build_generation_context_snapshot(
        engagement={"engagement_id": 7},
        report={"id": 8, "version": 1, "fact_snapshot": {}},
        financial_statements=adaptation.context,
        financial_statement_validation=adaptation.validation_snapshot(),
        generation_policy_version="annual-attachment-v1",
    )
    manifest = BindingManifest.model_validate(
        {
            "document_code": "financial_statements",
            "slots": [
                {
                    "slot_id": "balance_sheet",
                    "target": "xlsx:table:BalanceSheet",
                    "source": "document.financial_statements.balance_sheet",
                    "value_type": "table_rows",
                    "required": True,
                    "missing_policy": "block",
                    "style_policy": "clone_prototype_row",
                    "overflow_policy": "extend_rows",
                    "options": {
                        "columns": ["line_name", "current_amount", "comparative_amount"]
                    },
                }
            ],
        }
    )

    payload = compose_document_payload(manifest, context)
    assert "__evidence_refs__" not in payload.slots[0].rows[0].cells
    assert payload.slots[0].rows[0].evidence_refs[0].startswith("financial-source:file:91:")
    prepared = prepare_attachment(manifest, context, FactRegistry(), payload=payload)
    first_row = prepared.resolved_payload.slots[0].value[0]
    assert first_row["current_amount"] == Decimal("100")
    assert any(
        token.startswith("financial-source:file:91:")
        for token in prepared.resolved_payload.slots[0].evidence_refs
    )


def test_adapter_blocks_incomplete_or_unanchored_statement_inputs() -> None:
    incomplete = deepcopy(_package_value())
    incomplete.pop("cash_flow_statement")
    missing_statement = adapt_financial_statement_snapshot(incomplete)
    assert missing_statement.status == "invalid"
    assert any("cash_flow_statement" in item.field for item in missing_statement.blockers)

    unanchored = deepcopy(_package_value())
    unanchored["balance_sheet"]["rows"][0]["evidence_refs"] = []
    missing_evidence = adapt_financial_statement_snapshot(unanchored)
    assert missing_evidence.status == "invalid"
    assert any("evidence_refs" in item.field for item in missing_evidence.blockers)

    unhashed = deepcopy(_package_value())
    unhashed["balance_sheet"]["rows"][0]["evidence_refs"][0].pop("source_sha256")
    missing_hash = adapt_financial_statement_snapshot(unhashed)
    assert missing_hash.status == "invalid"
    assert any("source_sha256" in item.field for item in missing_hash.blockers)


def test_evidence_ownership_rejects_source_sha_mismatch(monkeypatch) -> None:
    class _Rows:
        def fetchall(self):
            return [{"id": 91, "file_sha256": "b" * 64}]

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, _params):
            assert "SELECT id, file_sha256" in sql
            return _Rows()

    monkeypatch.setattr(
        execution_service,
        "postgres_connection",
        lambda _settings: _Connection(),
    )

    errors = execution_service.validate_evidence_ownership(
        7,
        _evidence(1),
        settings=object(),
    )

    assert errors == ["证据文件 91 的 SHA-256 与当前有效文件不一致"]


def test_adapter_recomputes_and_blocks_failed_reconciliation() -> None:
    value = deepcopy(_package_value())
    value["balance_sheet"]["rows"][0]["current_amount"] = "101"

    adaptation = adapt_financial_statement_snapshot(value)

    assert adaptation.status == "invalid"
    assert any(
        "absolute difference exceeds tolerance" in item.message
        for item in adaptation.blockers
    )


def test_adapter_requires_all_formal_reconciliation_kinds() -> None:
    value = deepcopy(_package_value())
    value["reconciliations"] = [value["reconciliations"][0]]

    adaptation = adapt_financial_statement_snapshot(value)

    assert adaptation.status == "invalid"
    assert any("missing required formal reconciliations" in item.message for item in adaptation.blockers)


def test_contract_rejects_one_line_statements_and_empty_notes() -> None:
    value = deepcopy(_package_value())
    for statement_name in ("balance_sheet", "income_statement", "cash_flow_statement"):
        value[statement_name]["rows"] = value[statement_name]["rows"][:1]
    value["balance_sheet"]["rows"][0]["note_ref"] = None
    value["notes"] = []
    value["note_tie_outs"] = []

    adaptation = adapt_financial_statement_snapshot(value)

    assert adaptation.status == "invalid"
    assert any(
        "missing required semantic roles" in item.message or "at least 1 item" in item.message
        for item in adaptation.blockers
    )


def test_contract_rejects_vacuous_or_scaled_formal_reconciliations() -> None:
    self_equal = deepcopy(_package_value())
    self_equal["reconciliations"][0]["right_terms"] = deepcopy(
        self_equal["reconciliations"][0]["left_terms"]
    )
    self_equal_result = adapt_financial_statement_snapshot(self_equal)
    assert self_equal_result.status == "invalid"
    assert any("canonical semantic roles" in item.message for item in self_equal_result.blockers)

    scaled = deepcopy(_package_value())
    scaled["reconciliations"][1]["left_terms"][0]["coefficient"] = "2"
    scaled["reconciliations"][1]["right_terms"][0]["coefficient"] = "2"
    scaled_result = adapt_financial_statement_snapshot(scaled)
    assert scaled_result.status == "invalid"
    assert any("requires coefficient 1" in item.message for item in scaled_result.blockers)


def test_contract_requires_comparative_period_formal_reconciliations() -> None:
    value = deepcopy(_package_value())
    value["reconciliations"] = value["reconciliations"][:3]

    adaptation = adapt_financial_statement_snapshot(value)

    assert adaptation.status == "invalid"
    assert any("comparative_amount" in item.message for item in adaptation.blockers)


def test_contract_recomputes_comparative_period_and_disallows_tolerance_bypass() -> None:
    comparative_mismatch = deepcopy(_package_value())
    comparative_mismatch["balance_sheet"]["rows"][0]["comparative_amount"] = "999999"
    comparative_result = adapt_financial_statement_snapshot(comparative_mismatch)
    assert comparative_result.status == "invalid"
    assert any("balance.comparative" in item.message for item in comparative_result.blockers)

    note_bypass = deepcopy(_package_value())
    note_bypass["note_tie_outs"][0]["current_note_amount"] = "0"
    note_bypass["note_tie_outs"][0]["tolerance"] = "1000000"
    note_result = adapt_financial_statement_snapshot(note_bypass)
    assert note_result.status == "invalid"
    assert any("zero tolerance" in item.message for item in note_result.blockers)


def test_contract_does_not_treat_confirmed_as_approved() -> None:
    value = deepcopy(_package_value())
    value["approval_status"] = "confirmed"

    adaptation = adapt_financial_statement_snapshot(value)

    assert adaptation.status == "invalid"
    assert any("approval_status" in item.field for item in adaptation.blockers)


def test_adapter_blocks_failed_cash_movement_reconciliation() -> None:
    value = deepcopy(_package_value())
    value["cash_flow_statement"]["rows"][2]["current_amount"] = "3"

    adaptation = adapt_financial_statement_snapshot(value)

    assert adaptation.status == "invalid"
    assert any("cash.movement" in item.message for item in adaptation.blockers)


def test_adapter_requires_and_recomputes_formal_note_tie_out() -> None:
    missing = deepcopy(_package_value())
    missing["note_tie_outs"] = []
    missing_adaptation = adapt_financial_statement_snapshot(missing)
    assert missing_adaptation.status == "invalid"
    assert any("requires exactly one note tie-out" in item.message for item in missing_adaptation.blockers)

    mismatched = deepcopy(_package_value())
    mismatched["note_tie_outs"][0]["current_note_amount"] = "19"
    mismatch_adaptation = adapt_financial_statement_snapshot(mismatched)
    assert mismatch_adaptation.status == "invalid"
    assert any("failed for current_amount" in item.message for item in mismatch_adaptation.blockers)


def test_freeze_binds_approver_timestamp_and_engagement_period() -> None:
    value = _package_value()
    observed_at = datetime(2026, 1, 15, 2, 0, tzinfo=timezone.utc)

    frozen = freeze_financial_statement_input(
        value,
        actor_user_id="reviewer-1",
        observed_at=observed_at,
        engagement_period_start=date(2025, 1, 1),
        engagement_period_end=date(2025, 12, 31),
    )
    assert frozen is not None

    from ai_hunter.annual_audit.attachments.financial_statements import (
        FinancialStatementApprovalError,
    )

    with pytest.raises(FinancialStatementApprovalError) as approver:
        freeze_financial_statement_input(value, actor_user_id="another-user", observed_at=observed_at)
    assert approver.value.code == "FINANCIAL_STATEMENT_APPROVER_MISMATCH"

    future = deepcopy(value)
    future["approved_at"] = (observed_at + timedelta(minutes=6)).isoformat()
    with pytest.raises(FinancialStatementApprovalError) as future_error:
        freeze_financial_statement_input(future, actor_user_id="reviewer-1", observed_at=observed_at)
    assert future_error.value.code == "FINANCIAL_STATEMENT_APPROVED_AT_FUTURE"
    assert future_error.value.status_code == 422

    with pytest.raises(FinancialStatementApprovalError) as period:
        freeze_financial_statement_input(
            value,
            actor_user_id="reviewer-1",
            observed_at=observed_at,
            engagement_period_start="2025-02-01",
            engagement_period_end="2025-12-31",
        )
    assert period.value.code == "FINANCIAL_STATEMENT_PERIOD_MISMATCH"

    with pytest.raises(FinancialStatementApprovalError) as missing_period:
        freeze_financial_statement_input(
            value,
            actor_user_id="reviewer-1",
            observed_at=observed_at,
            require_engagement_period=True,
        )
    assert missing_period.value.code == "ENGAGEMENT_PERIOD_MISSING"
    assert missing_period.value.status_code == 422


def test_report_api_passes_only_validated_explicit_statement_package(monkeypatch) -> None:
    request = api.AnnualReportRequest.model_validate(
        {
            "case_id": 7,
            "financial_statements": _package_value(),
        }
    )
    captured = {}

    monkeypatch.setattr(api, "require_case_access", lambda *_args, **_kwargs: None)

    def fake_generate(case_id: int, **kwargs):
        captured["case_id"] = case_id
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(api, "generate_annual_report_draft", fake_generate)

    result = api.generate_report(
        request,
        SimpleNamespace(
            user_id="reviewer-1",
            is_admin=False,
            roles=("reviewer",),
        ),
    )

    assert result == {"ok": True}
    assert isinstance(captured["financial_statements"], FinancialStatementPackage)
    frozen = freeze_financial_statement_input(captured["financial_statements"])
    assert frozen is not None
    assert set(frozen) >= {
        "balance_sheet",
        "income_statement",
        "cash_flow_statement",
        "reconciliations",
    }


def test_report_api_rejects_self_approved_statements_from_non_control_role(monkeypatch) -> None:
    request = api.AnnualReportRequest.model_validate(
        {"case_id": 7, "financial_statements": _package_value()}
    )
    monkeypatch.setattr(api, "require_case_access", lambda *_args, **_kwargs: None)

    with pytest.raises(api.HTTPException) as caught:
        api.generate_report(
            request,
            SimpleNamespace(
                user_id="reviewer-1",
                is_admin=False,
                roles=("audit_assistant",),
            ),
        )

    assert caught.value.status_code == 403


def test_frozen_report_snapshot_is_adapted_by_job_context_loader(monkeypatch) -> None:
    monkeypatch.setattr(
        job_service,
        "get_engagement",
        lambda *_args, **_kwargs: {
            "id": 7,
            "engagement_code": "ENG-7",
            "case_name": "Annual audit",
            "entity_name": "Example Co",
            "fiscal_year": 2025,
        },
    )
    monkeypatch.setattr(
        job_service.repository,
        "list_current_facts",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        job_service,
        "get_execution_snapshot",
        lambda *_args, **_kwargs: {
            "program": [],
            "reviews": [],
            "release_gate": {},
            "policy_binding": {},
        },
    )
    monkeypatch.setattr(
        job_service,
        "validate_evidence_ownership",
        lambda *_args, **_kwargs: [],
    )
    frozen = freeze_financial_statement_input(_package_value())

    context, _registry = job_service._load_generation_context(
        engagement_id=7,
        report={
            "id": 8,
            "report_version": 2,
            "status": "draft",
            "fact_snapshot": {"financial_statements": frozen},
        },
        settings=object(),
    )

    assert isinstance(context.financial_statements, FinancialStatementsContext)
    assert context.financial_statements.income_statement[0].current_amount == Decimal("12")
    assert context.financial_statement_validation["status"] == "ready"


def test_context_loader_blocks_only_financial_inputs_with_foreign_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        job_service,
        "get_engagement",
        lambda *_args, **_kwargs: {"id": 7, "entity_name": "Example Co"},
    )
    monkeypatch.setattr(
        job_service.repository,
        "list_current_facts",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        job_service,
        "get_execution_snapshot",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        job_service,
        "validate_evidence_ownership",
        lambda *_args, **_kwargs: ["source_file_id is outside the case"],
    )

    context, _registry = job_service._load_generation_context(
        engagement_id=7,
        report={
            "id": 8,
            "report_version": 2,
            "status": "draft",
            "fact_snapshot": {
                "financial_statements": freeze_financial_statement_input(_package_value())
            },
        },
        settings=object(),
    )

    assert context.financial_statements == {}
    assert context.financial_statement_validation == {
        "status": "invalid",
        "blockers": [
            {
                "code": "FINANCIAL_STATEMENT_EVIDENCE_INVALID",
                "field": "financial_statements.evidence",
                "message": "财务报表证据不属于当前项目或缺少有效定位",
            }
        ],
    }


def test_report_api_surfaces_evidence_ownership_blocker(monkeypatch) -> None:
    request = api.AnnualReportRequest(
        case_id=7,
        financial_statements=FinancialStatementPackage.model_validate(_package_value()),
    )
    monkeypatch.setattr(api, "require_case_access", lambda *_args, **_kwargs: None)

    def blocked(*_args, **_kwargs):
        from ai_hunter.annual_audit.attachments.financial_statements import (
            FinancialStatementEvidenceOwnershipError,
        )

        raise FinancialStatementEvidenceOwnershipError(["foreign source"])

    monkeypatch.setattr(api, "generate_annual_report_draft", blocked)

    with pytest.raises(api.HTTPException) as caught:
        api.generate_report(
            request,
            SimpleNamespace(user_id="auditor-1", is_admin=False, roles=("reviewer",)),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "FINANCIAL_STATEMENT_EVIDENCE_INVALID"
    assert set(caught.value.detail) == {"code", "message"}


def test_report_api_surfaces_approver_mismatch_without_internal_details(monkeypatch) -> None:
    request = api.AnnualReportRequest(
        case_id=7,
        financial_statements=FinancialStatementPackage.model_validate(_package_value()),
    )
    monkeypatch.setattr(api, "require_case_access", lambda *_args, **_kwargs: None)

    def blocked(*_args, **_kwargs):
        from ai_hunter.annual_audit.attachments.financial_statements import (
            FinancialStatementApprovalError,
        )

        raise FinancialStatementApprovalError(
            "FINANCIAL_STATEMENT_APPROVER_MISMATCH",
            "财务报表 approved_by 必须与当前调用身份一致",
        )

    monkeypatch.setattr(api, "generate_annual_report_draft", blocked)

    with pytest.raises(api.HTTPException) as caught:
        api.generate_report(
            request,
            SimpleNamespace(user_id="another-user", is_admin=False, roles=("reviewer",)),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "FINANCIAL_STATEMENT_APPROVER_MISMATCH",
        "message": "财务报表 approved_by 必须与当前调用身份一致",
    }
