from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from ai_hunter.annual_audit.attachments import repository
from ai_hunter.annual_audit.attachments.fact_registry import FactRegistry


class ScriptedCursor:
    def __init__(
        self,
        *,
        fetchone_rows: list[dict] | None = None,
        fetchall_rows: list[list[dict]] | None = None,
    ) -> None:
        self.fetchone_rows = list(fetchone_rows or [])
        self.fetchall_rows = list(fetchall_rows or [])
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql: str, params=()):
        self.executed.append((" ".join(sql.split()), tuple(params)))
        return self

    def fetchone(self):
        return self.fetchone_rows.pop(0) if self.fetchone_rows else None

    def fetchall(self):
        return self.fetchall_rows.pop(0) if self.fetchall_rows else []


class ScriptedConnection:
    def __init__(self, cursor: ScriptedCursor) -> None:
        self.scripted_cursor = cursor
        self.commits = 0

    def cursor(self):
        return self.scripted_cursor

    def commit(self):
        self.commits += 1


def _install_connection(monkeypatch, cursor: ScriptedCursor) -> ScriptedConnection:
    connection = ScriptedConnection(cursor)

    @contextmanager
    def connect(_settings):
        yield connection

    monkeypatch.setattr(repository, "postgres_connection", connect)
    return connection


def _fact_row(*, value: int, source_kind: str, revision: int) -> dict:
    return {
        "id": revision,
        "engagement_id": 7,
        "fact_key": "entity.registered_capital",
        "value_json": str(value),
        "display_value": str(value),
        "data_type": "number",
        "status": "confirmed",
        "source_kind": source_kind,
        "source_ref_json": "{}",
        "evidence_refs_json": "[]",
        "revision": revision,
        "is_current": 1,
        "reviewed_by": "reviewer",
        "reviewed_at": None,
        "created_by": "reviewer",
        "created_at": "2026-08-31 10:00:00",
    }


def test_fact_candidate_key_is_canonical_and_source_scoped() -> None:
    first = repository._fact_candidate_key(
        source_kind="material_extraction",
        source_ref=None,
        evidence_refs=[{"page": 2, "file": 1}, {"file": 3, "page": 1}],
        actor_user_id="worker",
    )
    reordered = repository._fact_candidate_key(
        source_kind="material_extraction",
        source_ref=None,
        evidence_refs=[{"page": 1, "file": 3}, {"file": 1, "page": 2}],
        actor_user_id="worker",
    )
    manual = repository._fact_candidate_key(
        source_kind="manual_review",
        source_ref=None,
        evidence_refs=[],
        actor_user_id="worker",
    )
    manual_with_new_evidence = repository._fact_candidate_key(
        source_kind="manual_review",
        source_ref={"changed": True},
        evidence_refs=[{"file": 99}],
        actor_user_id="worker",
    )

    assert first == reordered
    assert first != manual
    assert manual == manual_with_new_evidence
    assert len(first) == 64


def test_upsert_retires_only_matching_candidate_and_allocates_global_revision(
    monkeypatch,
) -> None:
    cursor = ScriptedCursor(
        fetchone_rows=[{"id": 7}, {"max_revision": 8}, {"id": 101}],
        fetchall_rows=[[{"id": 4}, {"id": 6}]],
    )
    connection = _install_connection(monkeypatch, cursor)

    created = repository.upsert_fact_version(
        engagement_id=7,
        fact_key="entity.registered_capital",
        value=900,
        display_value="900",
        data_type="number",
        status="confirmed",
        source_kind="manual_review",
        source_ref={"review_channel": "capital"},
        evidence_refs=[],
        actor_user_id="reviewer-1",
        reviewed=True,
        settings=object(),
    )

    statements = [statement for statement, _params in cursor.executed]
    assert "FROM audit_engagement WHERE id = %s FOR UPDATE" in statements[0]
    assert "MAX(revision)" in statements[1]
    assert "candidate_key = %s" in statements[2]
    assert "candidate_key LIKE 'legacy:%%'" in statements[2]
    update_index = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("UPDATE annual_engagement_fact")
    )
    insert_index = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("INSERT INTO annual_engagement_fact")
    )
    update_params = cursor.executed[update_index][1]
    insert_params = cursor.executed[insert_index][1]
    assert update_params[:2] == (7, "entity.registered_capital")
    assert update_params[2:] == (insert_params[2], "manual_review", "reviewer-1")
    assert created["revision"] == 9
    assert created["source_kind"] == "manual_review"
    assert connection.commits == 1


def test_multiple_current_rows_reach_registry_and_low_priority_later_write_loses(
    monkeypatch,
) -> None:
    cursor = ScriptedCursor(
        fetchall_rows=[
            [
                _fact_row(value=500, source_kind="manual_review", revision=1),
                _fact_row(
                    value=999,
                    source_kind="material_extraction",
                    revision=12,
                ),
            ]
        ]
    )
    _install_connection(monkeypatch, cursor)

    current = repository.list_current_facts(7, settings=object())
    resolved = FactRegistry(current).resolve("entity.registered_capital")

    assert len(current) == 2
    assert resolved.value == 500
    assert resolved.source_kind == "manual_review"
    assert "ORDER BY fact_key, source_kind, revision" in cursor.executed[0][0]


def test_postgres_baseline_supports_multiple_current_fact_candidates() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "annual_audit_postgres_v3.sql"
    sql = sql_path.read_text(encoding="utf-8")

    assert "candidate_key varchar(191) NOT NULL" in sql
    assert "current_marker smallint GENERATED ALWAYS AS" in sql
    assert "engagement_id, fact_key, candidate_key, current_marker" in sql
    assert "UNIQUE (engagement_id, fact_key, candidate_key, current_marker)" in sql
