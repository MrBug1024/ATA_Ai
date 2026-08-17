from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from ai_hunter.annual_audit import citation_manifest_service as manifests


REPO_ROOT = Path(__file__).resolve().parents[2]


def _bound_evidence(*, amount: int = 100) -> dict:
    return {
        "source_file_id": 101,
        "source_page_id": 201,
        "source_chunk_id": "a" * 64,
        "file_name": "bank.xlsx",
        "page_no": 2,
        "quote_text": f"amount={amount}",
    }


def _entry(**overrides) -> dict:
    payload = {
        "engagement_id": 7,
        "annual_report_id": 41,
        "report_version": 2,
        "citation_id": "1",
        "section_key": "cash-and-bank",
        "paragraph_key": "cash-and-bank.finding.1",
        "annual_finding_id": 0,
        "analysis_run_id": 0,
        "analysis_type": "cash_and_bank",
        "finding_type": "large_transaction",
        "risk_level": "high",
        "rule_metadata": {
            "rule_code": "C1-LARGE-001",
            "ruleset_version": "2026-08-03-v2",
        },
        "finding_metadata": {
            "title": "期末大额交易",
            "amount": 100,
        },
        "evidence_snapshot": [_bound_evidence()],
    }
    payload.update(overrides)
    return manifests.build_manifest_entry(**payload)


def test_manifest_entry_hash_is_stable_and_excludes_late_report_ref():
    first = _entry()
    reordered = _entry(
        rule_metadata={
            "ruleset_version": "2026-08-03-v2",
            "rule_code": "C1-LARGE-001",
        },
        finding_metadata={
            "amount": 100,
            "title": "期末大额交易",
        },
        evidence_snapshot=[
            {
                "quote_text": "amount=100",
                "page_no": 2,
                "file_name": "bank.xlsx",
                "source_chunk_id": "a" * 64,
                "source_page_id": 201,
                "source_file_id": 101,
            }
        ],
    )

    assert first["anchor_status"] == "bound"
    assert first["annual_finding_key"] == reordered["annual_finding_key"]
    assert first["snapshot_hash"] == reordered["snapshot_hash"]
    assert manifests.build_manifest_snapshot_hash(
        {**first, "final_report_ref": "annual_audit:heavy:response-7"}
    ) == first["snapshot_hash"]


def test_anchor_status_never_fabricates_missing_source_binding():
    assert manifests.derive_anchor_status([]) == "no_evidence"
    assert manifests.derive_anchor_status([{"file_name": "unbound.xlsx"}]) == "unbound"
    assert manifests.derive_anchor_status(
        [_bound_evidence(), {"file_name": "unbound.xlsx"}]
    ) == "partial"


def test_manifest_entry_rejects_non_hash_finding_key_and_invalid_status():
    with pytest.raises(manifests.CitationManifestError):
        _entry(annual_finding_key="not-a-hash")
    with pytest.raises(manifests.CitationManifestError):
        _entry(anchor_status="guessed")


class _Cursor:
    def __init__(self, *, phase: str, row: dict | None = None):
        self.phase = phase
        self.row = row or {}
        self.calls: list[tuple[str, tuple | None]] = []
        self._one: dict | None = None
        self._all: list[dict] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        compact = " ".join(sql.split())
        self.calls.append((compact, tuple(params) if params is not None else None))
        self._one = None
        self._all = []
        if "SELECT id FROM audit_report" in compact:
            self._one = {"id": 41}
        elif "SELECT citation_id, snapshot_hash, final_report_ref" in compact:
            self._all = []
        elif "SELECT DISTINCT final_report_ref" in compact:
            self._all = []
        elif "SELECT COUNT(*) AS manifest_count" in compact:
            self._one = {"manifest_count": 1}
        elif "SELECT m.* FROM annual_report_citation_delivery_ref d" in compact:
            self._all = [self.row]
        elif "SELECT m.* FROM annual_report_citation_manifest" in compact:
            self._all = [self.row]
        elif compact.startswith("INSERT INTO annual_report_citation_manifest"):
            self.rowcount = 1
        elif compact.startswith("INSERT INTO annual_report_citation_delivery_ref"):
            self.rowcount = 1
        elif compact.startswith("UPDATE annual_report_citation_manifest"):
            self.rowcount = 1

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Connection:
    def __init__(self, cursor: _Cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


def _stored_row(entry: dict) -> dict:
    return {
        "id": 1,
        "engagement_id": entry["engagement_id"],
        "annual_report_id": entry["annual_report_id"],
        "report_type": entry["report_type"],
        "report_version": entry["report_version"],
        "citation_id": entry["citation_id"],
        "section_key": entry["section_key"],
        "paragraph_key": entry["paragraph_key"],
        "annual_finding_id": None,
        "annual_finding_key": entry["annual_finding_key"],
        "analysis_run_id": None,
        "analysis_type": entry["analysis_type"],
        "finding_type": entry["finding_type"],
        "risk_level": entry["risk_level"],
        "rule_metadata_json": json.dumps(entry["rule_metadata"], ensure_ascii=False),
        "finding_metadata_json": json.dumps(entry["finding_metadata"], ensure_ascii=False),
        "evidence_snapshot_json": json.dumps(entry["evidence_snapshot"], ensure_ascii=False),
        "anchor_status": entry["anchor_status"],
        "snapshot_hash": entry["snapshot_hash"],
        "final_report_ref": None,
        "created_at": None,
        "updated_at": None,
    }


def test_persist_manifest_locks_exact_report_version_and_fetches_through_same_scope(monkeypatch):
    entry = _entry()
    write_cursor = _Cursor(phase="write")
    read_cursor = _Cursor(phase="read", row=_stored_row(entry))
    write_connection = _Connection(write_cursor)
    read_connection = _Connection(read_cursor)
    connections = iter([write_connection, read_connection])

    @contextmanager
    def fake_connection(*_args, **_kwargs):
        yield next(connections)

    monkeypatch.setattr(manifests, "mysql_connection", fake_connection)

    rows = manifests.persist_report_citation_manifest(
        engagement_id=7,
        annual_report_id=41,
        report_version=2,
        entries=[entry],
        settings=object(),
    )

    assert rows[0]["citation_id"] == "1"
    assert write_connection.commits == 1
    report_lock = next(
        call for call in write_cursor.calls if "SELECT id FROM audit_report" in call[0]
    )
    assert report_lock[1] == (41, 7, "annual_audit_draft", 2)
    insert = next(
        call
        for call in write_cursor.calls
        if call[0].startswith("INSERT INTO annual_report_citation_manifest")
    )
    assert insert[1][0:5] == (7, 41, "annual_audit_draft", 2, "1")
    fetch = next(
        call
        for call in read_cursor.calls
        if "JOIN audit_report r" in call[0]
    )
    assert fetch[1][0:4] == (7, 41, "annual_audit_draft", 2)


def test_persist_rejects_cross_case_entry_before_database_io():
    entry = _entry(engagement_id=9)

    with pytest.raises(manifests.CitationManifestError):
        manifests.persist_report_citation_manifest(
            engagement_id=7,
            annual_report_id=41,
            report_version=2,
            entries=[entry],
            settings=object(),
        )


def test_bind_final_report_ref_keeps_report_version_scope(monkeypatch):
    cursor = _Cursor(phase="bind")
    connection = _Connection(cursor)

    @contextmanager
    def fake_connection(*_args, **_kwargs):
        yield connection

    monkeypatch.setattr(manifests, "mysql_connection", fake_connection)

    result = manifests.bind_final_report_ref(
        engagement_id=7,
        annual_report_id=41,
        report_version=2,
        final_report_ref="annual_audit:heavy:response-7",
        settings=object(),
    )

    assert result["bound_count"] == 1
    assert result["manifest_count"] == 1
    delivery_insert = next(
        call
        for call in cursor.calls
        if call[0].startswith("INSERT INTO annual_report_citation_delivery_ref")
    )
    assert delivery_insert[1][0:5] == (
        7,
        41,
        "annual_audit_draft",
        2,
        "annual_audit:heavy:response-7",
    )


def test_delivery_ref_resolves_frozen_manifest_without_payload(monkeypatch):
    entry = _entry()
    cursor = _Cursor(phase="resolve", row=_stored_row(entry))
    connection = _Connection(cursor)

    @contextmanager
    def fake_connection(*_args, **_kwargs):
        yield connection

    monkeypatch.setattr(manifests, "mysql_connection", fake_connection)

    entries = manifests.resolve_final_report_ref_citation_manifest(
        engagement_id=7,
        final_report_ref="annual_audit:heavy:response-7",
        citation_id="1",
        settings=object(),
    )

    assert entries[0]["citation_id"] == "1"
    assert entries[0]["final_report_ref"] == "annual_audit:heavy:response-7"
    query = next(call for call in cursor.calls if "annual_report_citation_delivery_ref d" in call[0])
    assert query[1][0] == 7
    assert query[1][-1] == "1"


def test_same_report_version_accepts_multiple_message_delivery_refs(monkeypatch):
    first_cursor = _Cursor(phase="first")
    second_cursor = _Cursor(phase="second")
    connections = iter([_Connection(first_cursor), _Connection(second_cursor)])

    @contextmanager
    def fake_connection(*_args, **_kwargs):
        yield next(connections)

    monkeypatch.setattr(manifests, "mysql_connection", fake_connection)

    for suffix in ("one", "two"):
        manifests.bind_final_report_ref(
            engagement_id=7,
            annual_report_id=41,
            report_version=2,
            final_report_ref=f"annual_audit:heavy:{suffix}",
            settings=object(),
        )

    first_insert = next(
        call
        for call in first_cursor.calls
        if call[0].startswith("INSERT INTO annual_report_citation_delivery_ref")
    )
    second_insert = next(
        call
        for call in second_cursor.calls
        if call[0].startswith("INSERT INTO annual_report_citation_delivery_ref")
    )
    assert first_insert[1][4] == "annual_audit:heavy:one"
    assert second_insert[1][4] == "annual_audit:heavy:two"


def test_manifest_schema_and_deployment_wiring_are_versioned():
    schema = (
        REPO_ROOT / "backend" / "sql" / "annual_audit_mysql_v10.sql"
    ).read_text(encoding="utf-8")
    delivery_schema = (
        REPO_ROOT / "backend" / "sql" / "annual_audit_mysql_v11.sql"
    ).read_text(encoding="utf-8")
    migration_runner = (
        REPO_ROOT / "backend" / "ai_hunter" / "annual_audit" / "storage" / "migrate.py"
    ).read_text(encoding="utf-8")
    compose = (
        REPO_ROOT / "deploy" / "annual-audit" / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    migration_record = (
        REPO_ROOT / "deploy" / "annual-audit" / "mysql-init" / "009_record_migrations.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS annual_report_citation_manifest" in schema
    for column in (
        "citation_id",
        "section_key",
        "paragraph_key",
        "annual_finding_id",
        "annual_finding_key",
        "analysis_run_id",
        "rule_metadata_json",
        "finding_metadata_json",
        "evidence_snapshot_json",
        "anchor_status",
        "snapshot_hash",
        "final_report_ref",
    ):
        assert column in schema
    assert "uk_annual_report_citation_version" in schema
    assert "fk_annual_report_citation_report_version" in schema
    assert '"010"' in migration_runner
    assert '"011"' in migration_runner
    assert "annual_audit_mysql_v10.sql:/docker-entrypoint-initdb.d/010_report_citation_manifest.sql:ro" in compose
    assert "CREATE TABLE IF NOT EXISTS annual_report_citation_delivery_ref" in delivery_schema
    assert "final_report_ref_hash" in delivery_schema
    assert "annual_audit_mysql_v11.sql:/docker-entrypoint-initdb.d/011_report_citation_delivery_refs.sql:ro" in compose
    assert "('010', 'immutable annual report citation manifests')" in migration_record
    assert "('011', 'immutable annual report citation delivery references')" in migration_record
