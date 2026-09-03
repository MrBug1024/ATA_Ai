from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from ai_hunter.app.api import routes_files
from ai_hunter.app.graph.nodes import load_chunks as load_chunks_node


_FILE_HASH = "a" * 64


def _xlsx_bytes() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return output.getvalue()


def test_nonempty_spreadsheet_without_chunks_or_structured_rows_is_rejected(monkeypatch) -> None:
    class KgService:
        def __init__(self) -> None:
            self.source_rows: list[dict] = []
            self.chunk_batches: list[list[object]] = []

        def insert_source_files(self, rows):
            self.source_rows.extend(rows)
            return [{**row, "id": index + 1} for index, row in enumerate(rows)]

        def insert_source_pages(self, rows):
            return [
                {"id": index + 1, "file_id": row["file_id"], "page_no": row["page_no"]}
                for index, row in enumerate(rows)
            ]

        def insert_source_chunks(self, rows):
            self.chunk_batches.append(list(rows))
            return []

    kg_service = KgService()
    empty_layout = {"pages": [{"width": 0, "height": 0}], "blocks": []}
    monkeypatch.setattr(load_chunks_node, "get_kg_service", lambda: kg_service)
    monkeypatch.setattr(load_chunks_node, "get_ocr_service", object)
    monkeypatch.setattr(load_chunks_node, "_resolve_file_bytes", lambda _item: _xlsx_bytes())
    monkeypatch.setattr(
        load_chunks_node,
        "_resolve_persisted_ingest_payload",
        lambda _state: {
            "ocr_layout_results": [
                {"cache_key": _FILE_HASH, "layout_result": empty_layout}
            ]
        },
    )

    with pytest.raises(
        load_chunks_node.EvidenceChunkCompletenessError,
        match="未生成可追溯证据分块或结构化记录",
    ):
        load_chunks_node.load_chunks(
            {
                "current_case_id": 8,
                "current_entity_id": 8,
                "records_inserted": 0,
                "uploaded_files": [
                    {
                        "name": "trial-balance.xlsx",
                        "extension": ".xlsx",
                        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "file_hash": _FILE_HASH,
                        "storage_ref": "minio://annual/raw/trial-balance",
                    }
                ],
            }
        )

    assert kg_service.source_rows[0]["file_name"] == "trial-balance.xlsx"
    assert kg_service.chunk_batches == [[]]


def test_graph_job_marks_evidence_gap_failed_not_completed(monkeypatch) -> None:
    progress_calls: list[dict] = []

    class Graph:
        @staticmethod
        def invoke(_state):
            raise load_chunks_node.EvidenceChunkCompletenessError("缺少证据分块")

    monkeypatch.setattr(routes_files, "knowledge_graph_graph", Graph())
    monkeypatch.setattr(
        routes_files,
        "mark_upload_ingest_progress",
        lambda **kwargs: progress_calls.append(kwargs),
    )

    routes_files._run_graph_enrichment_job(
        {
            "parse_result": {
                "current_case_id": 8,
                "current_entity_id": 8,
                "doc_category": "trial_balance",
                "upload_batch_id": "batch-zero-chunks",
                "uploaded_files": [{"name": "trial-balance.xlsx"}],
            }
        }
    )

    assert progress_calls[-1]["status"] == "failed"
    assert progress_calls[-1]["stage"] == "evidence_chunks_missing"
    assert progress_calls[-1]["error_payload"]["error_code"] == "INGEST_EVIDENCE_CHUNKS_MISSING"


@pytest.mark.parametrize(
    "layout_payloads",
    [
        [{"file_name": "empty.xlsx", "file_size_bytes": 0, "extension": ".xlsx"}],
        [{"file_name": "archive.bin", "file_size_bytes": 512, "extension": ".bin"}],
    ],
)
def test_evidence_gate_leaves_empty_or_unknown_materials_outside_failure_contract(layout_payloads) -> None:
    load_chunks_node._require_evidence_output_for_nonempty_parseable_materials(
        layout_payloads=layout_payloads,
        inserted_chunks=[],
        structured_record_count=0,
    )


def test_completed_batch_with_no_durable_evidence_can_retry_parse() -> None:
    batch = {
        "status": "completed",
        "file_count": 1,
        "records_inserted": 0,
        "files": [
            {
                "file_name": "trial-balance.xlsx",
                "file_size_bytes": 512,
                "chunk_count": 0,
            }
        ],
        "metadata": {"stage": "completed"},
    }

    assert routes_files._is_completed_batch_missing_all_evidence(batch) is True
    assert routes_files._resolve_retry_stage(
        batch=batch,
        event={"status": "completed"},
        requested_stage="auto",
    ) == "parse"
    assert routes_files._decorate_upload_batch_response(batch)["persistence_checks"][
        "retryable_missing_evidence"
    ] is True


def test_completed_batch_with_durable_output_stays_non_retryable() -> None:
    batch = {
        "status": "completed",
        "file_count": 1,
        "records_inserted": 0,
        "files": [{"file_size_bytes": 512, "chunk_count": 1}],
    }

    assert routes_files._is_completed_batch_missing_all_evidence(batch) is False
    with pytest.raises(ValueError, match="仅支持对失败批次"):
        routes_files._resolve_retry_stage(
            batch=batch,
            event={"status": "completed"},
            requested_stage="auto",
        )
