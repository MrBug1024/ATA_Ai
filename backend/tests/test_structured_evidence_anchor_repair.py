from __future__ import annotations

import hashlib
from contextlib import contextmanager

from ai_hunter.annual_audit import evidence_service, import_service


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        assert "annual_receivable_item" in query
        assert params == (7, [41])

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)


def test_hydrates_legacy_finding_from_current_domain_row_anchor(monkeypatch) -> None:
    rows = [
        {
            "id": 41,
            "source_locator_json": {
                "source_file_ref": "minio://annual/raw.xlsx",
                "source_file_id": 12,
                "source_page_id": 23,
                "source_chunk_id": "chunk-41",
                "page_no": 3,
                "sheet_name": "Receivables",
                "row_start": 41,
                "row_end": 41,
            },
            "source_file_id": 12,
            "source_page_id": 23,
            "source_chunk_id": "chunk-41",
            "locator_kind": "sheet_row",
        }
    ]

    @contextmanager
    def fake_connection(_settings):
        yield _Connection(rows)

    monkeypatch.setattr(evidence_service, "postgres_connection", fake_connection)
    original = {
        "finding_id": 9,
        "evidence_refs": [
            {
                "domain_row_type": "receivable_item",
                "domain_row_id": 41,
                "source_locator": {
                    "file_name": "raw.xlsx",
                    "quote_text": "row 41",
                },
            }
        ],
    }

    hydrated = evidence_service.hydrate_deterministic_finding_evidence_refs(
        7,
        [original],
        settings=object(),
    )

    locator = hydrated[0]["evidence_refs"][0]["source_locator"]
    assert locator["source_file_id"] == 12
    assert locator["source_page_id"] == 23
    assert locator["source_chunk_id"] == "chunk-41"
    assert locator["source_file_ref"] == "minio://annual/raw.xlsx"
    assert locator["quote_text"] == "row 41"
    assert original["evidence_refs"][0]["source_locator"] == {
        "file_name": "raw.xlsx",
        "quote_text": "row 41",
    }


class _KgService:
    def __init__(self):
        self.pages = []
        self.chunks = []

    def insert_source_pages(self, rows):
        self.pages.extend(rows)
        return [
            {"id": 99 + index, "file_id": row["file_id"], "page_no": row["page_no"]}
            for index, row in enumerate(rows)
        ]

    def insert_source_chunks(self, rows):
        self.chunks.extend(rows)
        return [row.model_dump() for row in rows]


def test_backfill_parses_only_referenced_files_and_binds_rows(monkeypatch) -> None:
    statuses = iter(
        [
            {"status": "evidence_blocked", "total_count": 2, "bound_count": 0, "unbound_count": 2},
            {"status": "ready", "total_count": 2, "bound_count": 2, "unbound_count": 0},
        ]
    )
    source_file = {
        "id": 12,
        "case_id": 7,
        "entity_id": 7,
        "file_name": "receivables.xlsx",
        "file_type": "document",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "file_sha256": "a" * 64,
        "file_size_bytes": 100,
        "storage_ref": "minio://annual/receivables.xlsx",
        "storage_provider": "minio",
        "storage_bucket": "annual",
        "storage_key": "receivables.xlsx",
        "storage_etag": "etag",
        "storage_version": "",
    }
    batch_calls = 0

    def fake_batch(_file_ids, *, settings):
        nonlocal batch_calls
        batch_calls += 1
        if batch_calls == 1:
            return {"pages": [], "chunks": []}
        return {
            "pages": [{"id": 99, "file_id": 12, "page_no": 1, "page_text": "## 工作表：Receivables"}],
            "chunks": [{"chunk_id": "chunk-1", "file_id": 12, "page_id": 99, "page_no": 1}],
        }

    monkeypatch.setattr(
        import_service,
        "structured_source_anchor_status",
        lambda *_args, **_kwargs: next(statuses),
    )
    monkeypatch.setattr(
        import_service,
        "_unbound_structured_locators",
        lambda *_args, **_kwargs: [{"source_sha256": "a" * 64}],
    )
    monkeypatch.setattr(
        import_service,
        "_source_files_for_locators",
        lambda *_args, **_kwargs: ([source_file], {}),
    )
    monkeypatch.setattr(import_service, "_load_anchor_batch", fake_batch)
    monkeypatch.setattr(
        import_service,
        "_scope_safe_chunks",
        lambda chunks, **_kwargs: ([chunk.model_dump() for chunk in chunks], 0),
    )
    monkeypatch.setattr(
        import_service,
        "bind_structured_source_refs",
        lambda **_kwargs: {"bound_count": 2, "unbound_count": 0, "unbound_reasons": {}},
    )
    seen_items = []

    def layout_loader(file_item):
        seen_items.append(file_item)
        return {
            "pages": [{"width": 0, "height": 0}],
            "blocks": [
                {
                    "type": "spreadsheet",
                    "text": "## 工作表：Receivables\n[第41行] row 41",
                    "page_idx": 0,
                    "bbox": [],
                    "text_level": 1,
                }
            ],
        }

    kg_service = _KgService()
    result = import_service.backfill_structured_source_anchors(
        7,
        settings=object(),
        kg_service=kg_service,
        layout_loader=layout_loader,
    )

    assert result["repair_status"] == "completed"
    assert result["newly_bound_count"] == 2
    assert result["parsed_source_file_count"] == 1
    assert seen_items[0]["file_hash"] == "a" * 64
    assert seen_items[0]["storage_ref"] == "minio://annual/receivables.xlsx"
    assert len(kg_service.pages) == 1
    assert len(kg_service.chunks) == 1


def test_backfill_is_noop_when_all_structured_rows_are_bound(monkeypatch) -> None:
    monkeypatch.setattr(
        import_service,
        "structured_source_anchor_status",
        lambda *_args, **_kwargs: {
            "status": "ready",
            "total_count": 8,
            "bound_count": 8,
            "unbound_count": 0,
        },
    )

    result = import_service.backfill_structured_source_anchors(
        7,
        settings=object(),
        layout_loader=lambda _item: (_ for _ in ()).throw(AssertionError("must not parse")),
    )

    assert result == {
        "status": "ready",
        "total_count": 8,
        "bound_count": 8,
        "unbound_count": 0,
        "repair_status": "not_needed",
        "parsed_source_file_count": 0,
    }


def test_scope_safe_chunks_remints_cross_case_collision(monkeypatch) -> None:
    collided_id = "legacy-chunk-id"

    class ChunkOwnerCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params):
            assert "FROM public.source_chunk" in query
            assert params == ([collided_id],)

        def fetchall(self):
            return [
                {
                    "chunk_id": collided_id,
                    "case_id": 4,
                    "file_id": 136,
                    "page_id": 991,
                }
            ]

    class ChunkOwnerConnection:
        def cursor(self):
            return ChunkOwnerCursor()

    @contextmanager
    def fake_connection(_settings):
        yield ChunkOwnerConnection()

    monkeypatch.setattr(import_service, "postgres_connection", fake_connection)
    chunk = {
        "chunk_id": collided_id,
        "case_id": 1,
        "file_id": 12,
        "page_id": 99,
        "page_no": 1,
        "chunk_index": 3,
        "chunk_text_sha256": "b" * 64,
        "metadata": {"sheet_name": "Receivables"},
    }

    safe_chunks, reminted_count = import_service._scope_safe_chunks(
        [chunk],
        settings=object(),
    )

    expected_seed = "|".join(
        ["legacy-scope-collision-v1", "1", "12", "99", "1", "3", "b" * 64]
    )
    assert safe_chunks[0]["chunk_id"] == hashlib.sha256(
        expected_seed.encode("utf-8")
    ).hexdigest()
    assert safe_chunks[0]["metadata"] == {
        "sheet_name": "Receivables",
        "chunk_id_compatibility": "legacy_scope_collision_v1",
        "collided_chunk_id": collided_id,
    }
    assert reminted_count == 1
    assert chunk["chunk_id"] == collided_id
