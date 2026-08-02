"""Classification tests for the auth v2-B metadata backfill."""

from datetime import datetime, timezone

from ai_hunter.app.scripts.tenancy_backfill import ThreadCandidate, classify_candidate


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _candidate(**kwargs) -> ThreadCandidate:
    defaults = {
        "thread_id": "t1",
        "message_created_at": NOW,
        "message_updated_at": NOW,
        "message_all_deleted": False,
    }
    defaults.update(kwargs)
    return ThreadCandidate(**defaults)


def test_backfill_resolves_single_existing_case():
    row = classify_candidate(_candidate(message_case_ids=(116,)), {116: "co_1"})
    assert row.case_id == 116
    assert row.company_id == "co_1"
    assert row.classification == "case_resolved"
    assert row.status == "active"


def test_backfill_keeps_no_case_and_missing_case_admin_only():
    no_case = classify_candidate(_candidate(), {116: "co_1"})
    missing = classify_candidate(_candidate(message_case_ids=(1,)), {116: "co_1"})
    assert no_case.case_id is None and no_case.created_by == ""
    assert no_case.classification == "no_case"
    assert missing.case_id is None
    assert missing.classification == "missing_case_to_null"


def test_backfill_conflict_policy_is_explicit():
    candidate = _candidate(message_case_ids=(116, 124))
    blocked = classify_candidate(candidate, {116: "co_1", 124: "co_1"})
    downgraded = classify_candidate(
        candidate,
        {116: "co_1", 124: "co_1"},
        conflict_policy="null",
    )
    assert blocked.classification == "conflict"
    assert downgraded.classification == "conflict_to_null"
    assert downgraded.case_id is None


def test_backfill_preserves_deleted_state():
    row = classify_candidate(
        _candidate(message_all_deleted=True, checkpoint_all_deleted=True),
        {},
    )
    assert row.status == "deleted"
    assert row.deleted_at == NOW
