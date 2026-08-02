import logging
from datetime import date, datetime, timezone
from types import SimpleNamespace

from psycopg.types.json import Json

from ai_hunter.app.services import kg_service as kg_service_module
from ai_hunter.app.services.kg_service import KnowledgeGraphService


class _FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, payload):
        self.calls.append((query, payload))

    def fetchone(self):
        return {"id": 123}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_kg_service_does_not_log_database_dsn(monkeypatch, caplog):
    dsn = "postgresql://audit_user:secret-password@db.internal:5432/ai_hunter"
    monkeypatch.setattr(
        kg_service_module,
        "get_settings",
        lambda: SimpleNamespace(postgres_checkpointer_dsn=dsn),
    )
    kg_service_module.get_kg_service.cache_clear()
    caplog.set_level(logging.INFO, logger=kg_service_module.__name__)

    service = kg_service_module.get_kg_service()

    assert service.dsn == dsn
    assert "kg_service_initialized" in caplog.text
    assert "secret-password" not in caplog.text
    assert dsn not in caplog.text
    kg_service_module.get_kg_service.cache_clear()


def test_create_extraction_run_serializes_source_file_ids_as_json(monkeypatch):
    cursor = _FakeCursor()
    connection = _FakeConnection(cursor)
    service = KnowledgeGraphService("postgresql://unused")

    monkeypatch.setattr(service, "connect", lambda: connection)

    run_id = service.create_extraction_run(
        case_id=116,
        source_file_ids=[11, 22],
        chunk_count=9,
    )

    assert run_id == 123
    assert connection.committed is True
    _, payload = cursor.calls[0]
    assert isinstance(payload["source_file_ids"], Json)


def test_upsert_entities_normalizes_datetime_attributes_for_json(monkeypatch):
    cursor = _FakeCursor()
    connection = _FakeConnection(cursor)
    service = KnowledgeGraphService("postgresql://unused")

    monkeypatch.setattr(service, "connect", lambda: connection)

    service.upsert_entities(
        case_id=133,
        rows=[
            {
                "entity_key": "entity-key",
                "entity_type": "case",
                "canonical_name": "Phase254 test entity",
                "aliases": [],
                "normalized_name": "phase254 test entity",
                "attributes": {
                    "judgment_date": date(2026, 7, 29),
                    "observed_at": datetime(2026, 7, 29, 3, 0, tzinfo=timezone.utc),
                },
                "first_seen_chunk_id": "chunk-1",
                "confidence": 0.9,
                "source_count": 1,
                "human_verified": False,
                "status": "active",
            }
        ],
    )

    _, payload = cursor.calls[0]
    assert isinstance(payload["attributes"], Json)
    assert payload["attributes"].obj == {
        "judgment_date": "2026-07-29",
        "observed_at": "2026-07-29T03:00:00+00:00",
    }
