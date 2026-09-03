from __future__ import annotations

import asyncio
import logging
from email.header import Header
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from ai_hunter.app.api import _upload_helpers, routes_files
from ai_hunter.app.graph.nodes import load_chunks as load_chunks_node
from ai_hunter.app.services import ingest_file_metadata
from ai_hunter.app.subgraphs import ingest_graph


def _xlsx_bytes() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return output.getvalue()


def _encoded_filename(value: str) -> str:
    return Header(value, "utf-8").encode()


def test_normalize_decodes_rfc2047_filename_before_extension_detection() -> None:
    normalized = ingest_file_metadata.normalize_ingest_file_item(
        {
            "name": _encoded_filename("北京银行询证函.xlsx"),
            "extension": ".bin",
            "content_type": "application/octet-stream",
        }
    )

    assert normalized["name"] == "北京银行询证函.xlsx"
    assert normalized["extension"] == ".xlsx"
    assert normalized["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_normalize_recovers_office_extension_from_zip_signature() -> None:
    normalized = ingest_file_metadata.normalize_ingest_file_item(
        {
            "name": "confirmation.bin",
            "extension": ".bin",
            "content_type": "text/plain",
        },
        file_bytes=_xlsx_bytes(),
    )

    assert normalized["name"] == "confirmation.xlsx"
    assert normalized["extension"] == ".xlsx"
    assert normalized["content_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_filter_files_reads_markdown_when_extension_field_is_stale(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def persist_payload(_kind: str, payload: dict) -> str:
        captured["payload"] = payload
        return "ingest-payload"

    monkeypatch.setattr(ingest_graph, "_resolve_file_bytes", lambda _item: b"# Evidence\ncontent")
    monkeypatch.setattr(ingest_graph, "put_heavy_payload", persist_payload)
    monkeypatch.setattr(
        ingest_graph,
        "_run_ocr_batch",
        lambda _candidates: (_ for _ in ()).throw(AssertionError("markdown must not reach OCR")),
    )

    ingest_graph.filter_files(
        {
            "uploaded_files": [
                {
                    "name": "README.md",
                    "extension": ".bin",
                    "content_type": "application/octet-stream",
                    "storage_ref": "minio://raw/readme",
                }
            ]
        }
    )

    assert captured["payload"] == {
        "txt_contents": [],
        "csv_contents": [],
        "md_contents": ["# Evidence\ncontent"],
        "document_ocr_contents": [],
        "image_ocr_contents": [],
        "ocr_layout_results": [],
    }


def test_structured_import_receives_office_file_recovered_from_bin(monkeypatch) -> None:
    captured: dict[str, object] = {}
    from ai_hunter.annual_audit import import_service

    monkeypatch.setattr(ingest_graph, "_resolve_file_bytes", lambda _item: _xlsx_bytes())
    monkeypatch.setattr(
        import_service,
        "import_uploaded_files",
        lambda **kwargs: captured.update(kwargs) or {"status": "ok"},
    )

    result = ingest_graph.import_annual_structured_files(
        {
            "current_case_id": 8,
            "uploaded_files": [
                {
                    "name": "ledger.bin",
                    "extension": ".bin",
                    "content_type": "application/octet-stream",
                    "storage_ref": "minio://raw/project-8/ledger",
                }
            ],
        }
    )

    imported_file = captured["files"][0]
    assert imported_file["name"] == "ledger.xlsx"
    assert imported_file["extension"] == ".xlsx"
    assert result["uploaded_files"] == [imported_file]


def test_initial_upload_persists_decoded_office_filename(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Upload:
        filename = _encoded_filename("函证模板.xlsx")
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        async def read(self) -> bytes:
            return _xlsx_bytes()

    class Minio:
        def upload_raw_file(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                storage_ref="minio://raw/project-8/file",
                storage_provider="minio",
                storage_bucket="raw",
                storage_key="project-8/file",
                storage_etag="etag",
                storage_version="",
            )

    monkeypatch.setattr(_upload_helpers, "get_minio_service", lambda: Minio())
    monkeypatch.setattr(_upload_helpers, "resolve_minio_reference_url", lambda ref: ref)
    settings = SimpleNamespace(
        max_upload_file_mb=10,
        max_image_file_mb=10,
        annual_minio_enabled=True,
    )

    item = asyncio.run(
        _upload_helpers.to_file_item(
            Upload(),
            settings,
            logging.LoggerAdapter(logging.getLogger(__name__), {}),
            current_case_id=8,
            populate_content=True,
        )
    )

    assert item["name"] == "函证模板.xlsx"
    assert item["extension"] == ".xlsx"
    assert captured["file_name"] == "函证模板.xlsx"


def test_retry_rebuild_recovers_mime_extension_and_uses_minio_for_text() -> None:
    batch = {
        "metadata": {},
        "upload_batch_id": "batch-8",
        "doc_category": "bank_confirmation",
        "files": [
            {
                "file_name": "note.bin",
                "file_type": "document",
                "content_type": "text/plain; charset=utf-8",
                "storage_ref": "minio://raw/project-8/note",
                "storage_provider": "minio",
                "storage_bucket": "raw",
                "storage_key": "project-8/note",
                "file_sha256": "a" * 64,
                "file_size_bytes": 12,
            }
        ],
    }

    files = routes_files._build_retry_uploaded_files(batch)
    routes_files._validate_retry_uploaded_files_have_content(files, retry_stage="parse")

    assert files[0]["name"] == "note.txt"
    assert files[0]["extension"] == ".txt"


def test_load_chunks_direct_reads_recovered_text_file(monkeypatch) -> None:
    class KgService:
        def __init__(self) -> None:
            self.source_rows: list[dict] = []
            self.chunks: list[object] = []

        def insert_source_files(self, rows):
            self.source_rows.extend(rows)
            return [{**row, "id": index + 1} for index, row in enumerate(rows)]

        def insert_source_pages(self, rows):
            return [
                {"id": index + 1, "file_id": row["file_id"], "page_no": row["page_no"]}
                for index, row in enumerate(rows)
            ]

        def insert_source_chunks(self, rows):
            self.chunks.extend(rows)
            return [{"chunk_id": row.chunk_id} for row in rows]

    kg_service = KgService()
    monkeypatch.setattr(load_chunks_node, "get_kg_service", lambda: kg_service)
    monkeypatch.setattr(load_chunks_node, "get_ocr_service", object)
    monkeypatch.setattr(load_chunks_node, "_resolve_file_bytes", lambda _item: b"direct evidence")
    monkeypatch.setattr(load_chunks_node, "_resolve_persisted_ingest_payload", lambda _state: {})
    monkeypatch.setattr(load_chunks_node, "put_heavy_payload", lambda _kind, _payload: "chunk-batch")

    result = load_chunks_node.load_chunks(
        {
            "current_case_id": 8,
            "current_entity_id": 8,
            "uploaded_files": [
                {
                    "name": "evidence.bin",
                    "extension": ".bin",
                    "content_type": "text/plain",
                    "file_hash": "a" * 64,
                    "storage_ref": "minio://raw/project-8/evidence",
                }
            ],
        }
    )

    assert kg_service.source_rows[0]["file_name"] == "evidence.txt"
    assert len(kg_service.chunks) == 1
    assert result["chunk_batch_summary"] == "files=1, pages=1, chunks=1"
