from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from ai_hunter.annual_audit.attachments import repository as attachment_repository
from ai_hunter.annual_audit.storage import migrate
from ai_hunter.document_templates.repository import DocumentTemplateRepository


class _Cursor:
    def __init__(self, *, one=None, many=None, update_rowcount: int = 1) -> None:
        self.one = one
        self.many = list(many or [])
        self.update_rowcount = update_rowcount
        self.rowcount = 0
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split())
        self.executed.append((normalized, tuple(params)))
        self.rowcount = self.update_rowcount if normalized.startswith("UPDATE") else 0

    def fetchone(self):
        return self.one

    def fetchall(self):
        rows, self.many = self.many, []
        return rows


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


def test_storage_ledger_migrations_keep_legacy_objects_out_of_managed_scope() -> None:
    sql_dir = Path(__file__).resolve().parents[1] / "sql"
    postgres_sql = (sql_dir / "document_templates_postgres_v2.sql").read_text(
        encoding="utf-8"
    )
    annual_sql = (sql_dir / "annual_audit_postgres_v3.sql").read_text(encoding="utf-8")

    for migration_sql in (postgres_sql, annual_sql):
        assert "legacy_unknown" in migration_sql
        assert "managed_exclusive" in migration_sql
        assert "reclaim_candidate" in migration_sql
        assert "DELETE FROM" not in migration_sql.upper()
    assert any(
        path.name == "annual_audit_postgres_v3.sql"
        for path in migrate.POSTGRES_MIGRATIONS
    )


def test_template_reinspection_releases_refs_into_retention_without_deleting() -> None:
    file_id = uuid4()
    cursor = _Cursor(
        one={
            "id": file_id,
            "template_version_id": uuid4(),
            "family_id": uuid4(),
            "version_status": "draft",
            "revision": 2,
            "compiled_object_ref": "minio://templates/compiled/old",
            "compiled_sha256": "a" * 64,
            "preview_object_ref": "minio://templates/preview/old",
            "preview_sha256": "b" * 64,
        }
    )
    repository = DocumentTemplateRepository(
        settings=SimpleNamespace(postgres_checkpointer_dsn="postgresql://unused")
    )

    @contextmanager
    def connect():
        yield _Connection(cursor)

    repository._connect = connect
    repository.get_file = lambda value: {"id": value, "status": "mapping"}

    repository.record_inspection(
        file_id,
        revision=2,
        inspection_report={"ok": True},
        actor="superadmin",
    )

    sql = "\n".join(statement for statement, _params in cursor.executed)
    object_inserts = [
        params
        for statement, params in cursor.executed
        if "INSERT INTO public.document_template_storage_object" in statement
    ]
    assert len(object_inserts) == 2
    assert all(params[-1] == "legacy_unknown" for params in object_inserts)
    assert "INTERVAL '30 days'" in sql
    assert "owner_ref.released_at IS NULL" in sql
    assert "DELETE FROM" not in sql.upper()


def test_template_reclamation_planner_requires_managed_scope_and_zero_live_owners() -> None:
    candidate = {
        "storage_ref_hash": "c" * 64,
        "storage_ref": "minio://templates/compiled/candidate",
        "object_kind": "compiled",
        "content_sha256": "d" * 64,
        "retention_state": "reclaim_candidate",
    }
    cursor = _Cursor(many=[candidate])
    repository = DocumentTemplateRepository(
        settings=SimpleNamespace(postgres_checkpointer_dsn="postgresql://unused")
    )

    @contextmanager
    def connect():
        yield _Connection(cursor)

    repository._connect = connect
    planned = repository.plan_storage_reclamation(limit=20)

    sql = "\n".join(statement for statement, _params in cursor.executed)
    assert planned == [candidate]
    assert "management_scope = 'managed_exclusive'" in sql
    assert "owner_ref.released_at IS NULL" in sql
    assert "retention_until <= now()" in sql
    assert "DELETE FROM" not in sql.upper()


def test_attachment_registration_is_managed_but_never_promotes_on_conflict() -> None:
    cursor = _Cursor()
    attachment_repository._register_attachment_storage_reference(
        cursor,
        storage_ref="minio://artifacts/7/context/object",
        object_kind="context",
        content_sha256="e" * 64,
        owner_type="generation_job",
        owner_id=str(uuid4()),
        owner_field="context",
        actor="auditor",
        managed_exclusive=True,
    )

    object_insert, owner_insert = cursor.executed
    assert object_insert[1][-1] == "managed_exclusive"
    assert "management_scope =" not in object_insert[0].split("ON CONFLICT", 1)[1]
    assert "retention_state = CASE WHEN" in object_insert[0]
    assert "annual_attachment_storage_reference" in owner_insert[0]


def test_attachment_reclamation_planner_marks_only_rechecked_candidates(monkeypatch) -> None:
    candidate = {
        "storage_ref_hash": "f" * 64,
        "storage_ref": "minio://artifacts/7/artifacts/candidate",
        "object_kind": "artifact",
        "content_sha256": "0" * 64,
        "unreferenced_at": None,
        "retention_until": None,
    }
    cursor = _Cursor(many=[candidate], update_rowcount=1)
    connection = _Connection(cursor)

    @contextmanager
    def postgres_connection(_settings=None):
        yield connection

    monkeypatch.setattr(attachment_repository, "postgres_connection", postgres_connection)
    planned = attachment_repository.plan_storage_reclamation(
        limit=10, settings=SimpleNamespace()
    )

    sql = "\n".join(statement for statement, _params in cursor.executed)
    assert planned[0]["retention_state"] == "reclaim_candidate"
    assert "management_scope = 'managed_exclusive'" in sql
    assert sql.count("owner_ref.released_at IS NULL") == 2
    assert "DELETE FROM" not in sql.upper()
    assert connection.commits == 1
