from __future__ import annotations

from decimal import Decimal

import pytest

from ai_hunter.annual_audit.attachments.agent_graph import (
    fact_registry_from_context,
    prepare_attachment,
)
from ai_hunter.annual_audit.attachments.content_schemas import BindingManifest
from ai_hunter.annual_audit.attachments.context_service import build_generation_context_snapshot
from ai_hunter.annual_audit.attachments.fact_registry import (
    ConflictedFactError,
    FactRecord,
    FactRegistry,
    MissingFactError,
)


def _fact(
    value,
    *,
    source: str,
    status: str = "confirmed",
    revision: int = 1,
    fact_key: str = "entity.registered_capital",
) -> FactRecord:
    return FactRecord(
        fact_key=fact_key,
        value=value,
        display_value=str(value),
        status=status,
        source_kind=source,
        revision=revision,
        evidence_refs=[{"source_file_id": 1, "source_page_id": 2}],
    )


def _context(entity_facts) -> object:
    return build_generation_context_snapshot(
        engagement={"engagement_id": 1},
        entity_facts=entity_facts,
        report={"id": 2, "version": 1, "fact_snapshot": {}},
        generation_policy_version="annual-attachment-v1",
    )


def test_fact_priority_project_master_then_correction_then_manual_review() -> None:
    registry = FactRegistry(
        [
            _fact(100, source="material_extraction"),
            _fact(200, source="report_snapshot"),
            _fact(300, source="approved_correction"),
            _fact(400, source="manual_review"),
            _fact(500, source="project_master"),
        ]
    )
    assert registry.resolve("entity.registered_capital").value == 500

    without_master = FactRegistry(
        [
            _fact(100, source="material_extraction"),
            _fact(300, source="approved_correction"),
            _fact(400, source="manual_review"),
        ]
    )
    assert without_master.resolve("entity.registered_capital").value == 300

    without_correction = FactRegistry(
        [
            _fact(100, source="material_extraction", revision=5),
            _fact(400, source="manual_review", revision=1),
        ]
    )
    assert without_correction.resolve("entity.registered_capital").value == 400


def test_candidate_correction_is_not_usable_and_cannot_override_confirmed_value() -> None:
    registry = FactRegistry(
        [
            _fact(100, source="report_snapshot"),
            _fact(999, source="correction", status="candidate", revision=2),
        ]
    )
    resolution = registry.resolve("entity.registered_capital")
    assert resolution.value == 100
    assert resolution.source_kind == "report_snapshot"


def test_same_priority_distinct_values_are_conflicted_but_equal_values_are_not() -> None:
    conflicted = FactRegistry(
        [
            _fact(100, source="material_extraction", revision=1),
            _fact(101, source="material_extraction", revision=2),
        ]
    )
    with pytest.raises(ConflictedFactError):
        conflicted.resolve("entity.registered_capital")

    equivalent = FactRegistry(
        [
            _fact(Decimal("100.00"), source="material_extraction", revision=1),
            _fact(Decimal("100.00"), source="material_extraction", revision=2),
        ]
    )
    assert equivalent.resolve("entity.registered_capital").revision == 2


def test_explicit_conflict_below_project_master_does_not_override_master() -> None:
    registry = FactRegistry(
        [
            _fact(500, source="project_master"),
            _fact(0, source="material_extraction", status="conflicted"),
        ]
    )
    assert registry.resolve("entity.registered_capital").value == 500


def test_frozen_snapshot_preserves_conflicted_and_unconfirmed_current_candidates() -> None:
    registry = FactRegistry(
        [
            _fact(100, source="material_extraction", status="conflicted"),
            _fact(
                "candidate address",
                source="material_extraction",
                status="candidate",
                fact_key="entity.registered_address",
            ),
        ]
    )
    frozen = registry.frozen_snapshot()
    assert frozen["entity.registered_capital"]["resolution_status"] == "conflicted"
    assert frozen["entity.registered_address"]["resolution_status"] == "unconfirmed"
    assert frozen["entity.registered_capital"]["candidates"][0]["status"] == "conflicted"

    direct_context = build_generation_context_snapshot(
        engagement={"engagement_id": 1},
        fact_registry=registry,
        report={"id": 2, "version": 1, "fact_snapshot": {}},
        generation_policy_version="annual-attachment-v1",
    )
    assert direct_context.entity_facts == frozen

    restored = fact_registry_from_context(_context(frozen))
    with pytest.raises(ConflictedFactError):
        restored.resolve("entity.registered_capital")
    with pytest.raises(MissingFactError):
        restored.resolve("entity.registered_address")


def test_required_missing_fact_and_conflicted_fact_produce_distinct_errors() -> None:
    manifest = BindingManifest(
        document_code="audit_report",
        slots=[
            {
                "slot_id": "address",
                "target": "md:variable:address",
                "source": "document.entity.registered_address",
                "value_type": "scalar",
                "required": True,
                "missing_policy": "block",
            }
        ],
    )
    empty_context = _context({})
    with pytest.raises(MissingFactError):
        prepare_attachment(manifest, empty_context, FactRegistry())

    conflicted_registry = FactRegistry(
        [
            _fact(
                "A",
                source="manual_review",
                status="conflicted",
                fact_key="entity.registered_address",
            )
        ]
    )
    conflicted_context = _context(conflicted_registry.frozen_snapshot())
    with pytest.raises(ConflictedFactError):
        prepare_attachment(manifest, conflicted_context, conflicted_registry)


def test_structured_table_fact_is_resolved_without_stringifying_numbers() -> None:
    registry = FactRegistry(
        [
            _fact(
                [{"shareholder": "Owner", "amount": Decimal("88.25")}],
                source="manual_review",
                fact_key="entity.shareholders[]",
            )
        ]
    )
    context = _context(registry.frozen_snapshot())
    manifest = BindingManifest(
        document_code="shareholders",
        slots=[
            {
                "slot_id": "rows",
                "target": "xlsx:range:'Data'!A1:B3",
                "source": "document.entity.shareholders[]",
                "value_type": "table_rows",
                "required": True,
                "missing_policy": "block",
                "overflow_policy": "error",
            }
        ],
    )
    prepared = prepare_attachment(manifest, context, registry)
    assert prepared.resolved_payload.slots[0].value[0]["amount"] == Decimal("88.25")
    assert prepared.resolved_payload.slots[0].fact_refs == ["entity.shareholders[]"]
