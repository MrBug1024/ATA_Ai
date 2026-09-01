from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_hunter.annual_audit.attachments.agent_graph import (
    compose_document_payload,
    prepare_attachment,
)
from ai_hunter.annual_audit.attachments.content_schemas import (
    BindingManifest,
    DocumentPayload,
    FactRefSegment,
    LiteralSegment,
    ScalarSlotPayload,
)
from ai_hunter.annual_audit.attachments.context_service import (
    build_generation_context_snapshot,
)
from ai_hunter.annual_audit.attachments.fact_registry import FactRecord, FactRegistry


def _context(*, registry: FactRegistry | None = None, financial_statements=None):
    return build_generation_context_snapshot(
        engagement={"engagement_id": 7, "project_name": "Example Audit"},
        fact_registry=registry,
        report={"id": 8, "version": 3, "fact_snapshot": {"balance": 10}},
        financial_statements=financial_statements or {},
        generation_policy_version="annual-attachment-v1",
    )


def test_fact_refs_and_literals_are_strict_and_preserve_native_scalars() -> None:
    segment = LiteralSegment(value=Decimal("12.34"))
    assert segment.value == Decimal("12.34")
    assert FactRefSegment(fact_ref="entity.registered_capital").fact_ref == "entity.registered_capital"
    with pytest.raises(ValidationError):
        FactRefSegment(fact_ref="entity[0].name")
    with pytest.raises(ValidationError):
        LiteralSegment(value={"not": "a scalar"})


def test_runtime_binding_accepts_optional_binding_sha_but_rejects_legacy_policies() -> None:
    manifest = BindingManifest.model_validate(
        {
            "contract_version": "1.0",
            "document_code": "audit_report",
            "source_template_sha256": "a" * 64,
            "binding_sha256": "b" * 64,
            "slots": [
                {
                    "slot_id": "company_name",
                    "target": "docx:content-control:company_name",
                    "source": "document.entity.legal_name",
                    "value_type": "scalar",
                    "required": True,
                    "missing_policy": "block",
                    "overflow_policy": "error",
                }
            ],
        }
    )
    assert manifest.binding_sha256 == "b" * 64
    with pytest.raises(ValidationError):
        BindingManifest.model_validate(
            {
                **manifest.model_dump(),
                "slots": [
                    {
                        **manifest.slots[0].model_dump(),
                        "missing_policy": "display_unavailable",
                    }
                ],
            }
        )


def test_document_prefix_resolves_flat_entity_fact_and_prepares_fact_ref() -> None:
    registry = FactRegistry(
        [
            FactRecord(
                fact_key="entity.legal_name",
                value="Example Co",
                display_value="Example Co",
                status="confirmed",
                source_kind="manual_review",
                evidence_refs=[{"source_file_id": 9, "source_page_id": 2}],
            )
        ]
    )
    context = _context(registry=registry)
    manifest = BindingManifest(
        document_code="audit_report",
        slots=[
            {
                "slot_id": "company_name",
                "target": "md:variable:company_name",
                "source": "document.entity.legal_name",
                "value_type": "scalar",
                "required": True,
                "missing_policy": "block",
            }
        ],
    )
    payload = compose_document_payload(manifest, context)
    assert isinstance(payload.slots[0].segments[0], FactRefSegment)
    prepared = prepare_attachment(manifest, context, registry, payload=payload)
    assert prepared.resolved_payload.slots[0].value == "Example Co"
    assert prepared.resolved_payload.slots[0].fact_refs == ["entity.legal_name"]
    assert prepared.context_snapshot_sha256 == context.snapshot_sha256


def test_deterministic_table_composition_keeps_native_numbers() -> None:
    context = _context(
        financial_statements={
            "balance_sheet": [
                {"line_item": "cash", "amount": Decimal("123.45")},
                {"line_item": "receivables", "amount": 80},
            ]
        }
    )
    manifest = BindingManifest(
        document_code="financial_statements",
        slots=[
            {
                "slot_id": "statement_rows",
                "target": "xlsx:table:BalanceSheet",
                "source": "document.financial_statements.balance_sheet",
                "value_type": "table_rows",
                "required": True,
                "missing_policy": "block",
                "overflow_policy": "extend_rows",
            }
        ],
    )
    payload = compose_document_payload(manifest, context)
    first_amount = payload.slots[0].rows[0].cells["amount"].segments[0]
    assert isinstance(first_amount, LiteralSegment)
    assert first_amount.value == Decimal("123.45")
    context_token = payload.slots[0].rows[0].evidence_refs[0]
    assert context_token.startswith("context:document.financial_statements.balance_sheet@")
    assert context.snapshot_sha256 in context_token
    assert context.report.fact_snapshot_sha256 in context_token
    prepared = prepare_attachment(manifest, context, FactRegistry(), payload=payload)
    assert prepared.resolved_payload.slots[0].value[0]["amount"] == Decimal("123.45")
    assert prepared.resolved_payload.slots[0].evidence_refs == [context_token]


def test_context_snapshot_is_stable_and_detached_from_mutable_inputs() -> None:
    engagement = {"engagement_id": 7, "labels": ["original"]}
    context = build_generation_context_snapshot(
        engagement=engagement,
        report={"id": 8, "version": 3, "fact_snapshot": {"z": 1, "a": 2}},
        generation_policy_version="annual-attachment-v1",
    )
    first_sha = context.snapshot_sha256
    engagement["labels"].append("mutated")
    assert context.engagement["labels"] == ["original"]
    assert context.snapshot_sha256 == first_sha
    equivalent = build_generation_context_snapshot(
        engagement={"labels": ["original"], "engagement_id": 7},
        report={"version": 3, "id": 8, "fact_snapshot": {"a": 2, "z": 1}},
        generation_policy_version="annual-attachment-v1",
    )
    assert equivalent.snapshot_sha256 == first_sha


def test_document_payload_rejects_duplicate_slots() -> None:
    with pytest.raises(ValidationError):
        DocumentPayload(
            document_code="audit_report",
            slots=[
                ScalarSlotPayload(slot_id="same", segments=[LiteralSegment(value="one")]),
                ScalarSlotPayload(slot_id="same", segments=[LiteralSegment(value="two")]),
            ],
        )
