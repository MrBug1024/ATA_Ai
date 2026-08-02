from ai_hunter.app.graph.nodes.load_chunks import _persist_upload_batch_context, load_chunks
from ai_hunter.app.graph.heavy_state import get_heavy_payload, put_heavy_payload


class FakeKGService:
    def __init__(self):
        self.source_files = []
        self.source_pages = []
        self.source_chunks = []
        self.upload_batch = {}
        self.upload_batch_links = []
        self.doc_category_links = []

    def insert_source_files(self, rows):
        self.source_files = rows
        return [
            {
                "id": index + 1,
                "case_id": row["case_id"],
                "file_sha256": row["file_sha256"],
                "file_name": row["file_name"],
            }
            for index, row in enumerate(rows)
        ]

    def insert_source_pages(self, rows):
        self.source_pages = rows
        return [
            {
                "id": index + 101,
                "file_id": row["file_id"],
                "page_no": row["page_no"],
            }
            for index, row in enumerate(rows)
        ]

    def insert_source_chunks(self, rows):
        self.source_chunks = rows
        return [
            {
                "id": index + 1001,
                "chunk_id": row.chunk_id,
                "case_id": row.case_id,
                "file_id": row.file_id,
                "page_id": row.page_id,
                "page_no": row.page_no,
            }
            for index, row in enumerate(rows)
        ]

    def upsert_source_upload_batch(self, summary):
        self.upload_batch = summary
        return {
            "upload_batch_id": summary["upload_batch_id"],
            "case_id": summary["case_id"],
            "doc_category": summary["doc_category"],
            "status": summary["status"],
            "file_count": summary["file_count"],
        }

    def link_source_files_to_upload_batch(self, *, upload_batch_id, files, duplicate_by_sha256=None):
        self.upload_batch_links = [
            {
                "upload_batch_id": upload_batch_id,
                "file_id": row["id"],
                "file_sha256": row["file_sha256"],
                "duplicate_of": (duplicate_by_sha256 or {}).get(row["file_sha256"], ""),
            }
            for row in files
        ]
        return self.upload_batch_links

    def upsert_source_file_doc_categories(self, *, case_id, category_code, files, match_source, confidence, notes):
        self.doc_category_links = [
            {
                "file_id": row["id"],
                "case_id": case_id,
                "category_code": category_code,
                "match_source": match_source,
                "confidence": confidence,
                "notes": notes,
            }
            for row in files
        ]
        return self.doc_category_links

    def fetch_source_upload_batch(self, upload_batch_id):
        return {}


class FakeOCRService:
    def parse_pdf_with_layout_sync(self, **kwargs):
        assert kwargs["file_name"] == "sample.pdf"
        return {
            "text": "第一页标题\n第一页正文\n第二页正文",
            "message": "success",
            "pages": [{"width": 1654, "height": 2339}, {"width": 1654, "height": 2339}],
            "blocks": [
                {
                    "type": "text",
                    "text": "第一页标题",
                    "text_level": 1,
                    "bbox": [10, 20, 210, 60],
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": "第一页正文",
                    "text_level": 2,
                    "bbox": [10, 80, 320, 140],
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": "第二页正文",
                    "text_level": 2,
                    "bbox": [15, 90, 330, 150],
                    "page_idx": 1,
                },
            ],
            "page_width": 1654,
            "page_height": 2339,
            "raw_response": {"content_list": []},
        }

    def parse_image_with_layout_sync(self, **kwargs):
        raise AssertionError("image OCR should not be used in this test")


def test_load_chunks_persists_source_file_page_and_chunk_rows(monkeypatch):
    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.load_chunks.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.load_chunks.get_ocr_service",
        lambda: FakeOCRService(),
    )

    result = load_chunks(
        {
            "current_case_id": 116,
            "current_debtor_id": 76,
            "doc_category": "restructuring_plan",
            "batch_name": "第一次上传",
            "upload_batch_id": "batch-001",
            "operator_id": "op-1",
            "operator_name": "操作员A",
            "new_files": ["sample.pdf"],
            "duplicate_files": [],
            "suspected_mismatch_files": [],
            "upload_batch_summary": {
                "material_event_id": "material-event:batch-001",
                "material_event_type": "supplement_upload",
                "material_event_status": "received",
                "upload_batch_id": "batch-001",
                "batch_name": "第一次上传",
                "doc_category": "restructuring_plan",
                "file_count": 1,
                "new_file_count": 1,
                "duplicate_file_count": 0,
                "suspected_mismatch_file_count": 0,
                "status": "received",
            },
            "ingest_payload_ref": "ingest_payload:test",
            "uploaded_files": [
                {
                    "name": "sample.pdf",
                    "extension": ".pdf",
                    "type": "document",
                    "content_type": "application/pdf",
                    "content": "JVBERi0xLjQ=",
                    "url": "",
                    "doc_category": "restructuring_plan",
                    "upload_batch_id": "batch-001",
                }
            ],
        }
    )

    assert result["chunk_batch_ref"].startswith("kg_chunk_batch:")
    assert result["chunk_batch_summary"] == "files=1, pages=2, chunks=3"
    assert len(result["chunk_ids"]) == 3
    assert len(fake_kg.source_files) == 1
    assert len(fake_kg.source_pages) == 2
    assert len(fake_kg.source_chunks) == 3
    assert fake_kg.upload_batch["upload_batch_id"] == "batch-001"
    assert fake_kg.upload_batch["status"] == "completed"
    assert fake_kg.upload_batch["metadata"]["material_event_id"] == "material-event:batch-001"
    assert fake_kg.upload_batch["metadata"]["stage"] == "completed"
    assert fake_kg.upload_batch_links[0]["upload_batch_id"] == "batch-001"
    assert fake_kg.doc_category_links[0]["category_code"] == "restructuring_plan"
    assert fake_kg.source_files[0]["storage_provider"] == ""

    first_chunk = fake_kg.source_chunks[0]
    assert first_chunk.page_no == 1
    assert first_chunk.bbox_list[0].x == 10
    assert first_chunk.bbox_list[0].w == 200
    payload = get_heavy_payload(result["chunk_batch_ref"])
    assert payload["files"][0]["file_name"] == "sample.pdf"
    assert payload["upload_batch"]["upload_batch_id"] == "batch-001"
    assert payload["doc_category_links"][0]["category_code"] == "restructuring_plan"
    assert len(payload["chunks"]) == 3


def test_load_chunks_returns_empty_without_case_or_files():
    assert load_chunks({"current_case_id": 0, "uploaded_files": []}) == {}


def test_async_graph_job_does_not_mark_upload_batch_completed_during_load_chunks():
    fake_kg = FakeKGService()

    _persist_upload_batch_context(
        kg_service=fake_kg,
        state={
            "upload_batch_id": "batch-async",
            "doc_category": "judgment",
            "upload_batch_summary": {
                "material_event_id": "material-event:batch-async",
                "material_event_type": "supplement_upload",
            },
            "defer_upload_batch_completion": True,
        },
        case_id=133,
        debtor_id=94,
        inserted_files=[{"id": 77, "file_sha256": "abc123"}],
        uploaded_files=[{"name": "a.txt", "file_hash": "abc123"}],
    )

    assert fake_kg.upload_batch["status"] == "processing"
    assert fake_kg.upload_batch["metadata"]["material_event_status"] == "processing"
    assert fake_kg.upload_batch["metadata"]["stage"] == "graph_running"


def test_load_chunks_reuses_cached_layout_from_ingest_payload(monkeypatch):
    fake_kg = FakeKGService()
    persisted_ref = put_heavy_payload(
        "ingest_payload",
        {
            "ocr_layout_results": [
                {
                    "cache_key": "e16fa5d9b51928755db85b917f0297babaf22c7a47e97d9212adab56e61ba04e",
                    "layout_result": {
                        "text": "缓存命中的正文",
                        "message": "success",
                        "pages": [{"width": 1654, "height": 2339}],
                        "blocks": [
                            {
                                "type": "text",
                                "text": "缓存命中的正文",
                                "text_level": 1,
                                "bbox": [10, 20, 210, 60],
                                "page_idx": 0,
                            }
                        ],
                        "page_width": 1654,
                        "page_height": 2339,
                        "raw_response": {},
                    },
                }
            ]
        },
    )
    fake_kg.fetch_source_upload_batch = lambda upload_batch_id: {
        "upload_batch_id": upload_batch_id,
        "metadata": {
            "ingest_payload_ref": persisted_ref,
        },
    }
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.load_chunks.get_kg_service",
        lambda: fake_kg,
    )

    class ForbiddenOCRService:
        def parse_pdf_with_layout_sync(self, **kwargs):
            raise AssertionError("layout OCR should not run when cached payload exists")

        def parse_image_with_layout_sync(self, **kwargs):
            raise AssertionError("image OCR should not run when cached payload exists")

    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.load_chunks.get_ocr_service",
        lambda: ForbiddenOCRService(),
    )

    result = load_chunks(
        {
            "current_case_id": 116,
            "current_debtor_id": 76,
            "doc_category": "restructuring_plan",
            "upload_batch_id": "batch-cache",
            "uploaded_files": [
                {
                    "name": "sample.pdf",
                    "extension": ".pdf",
                    "type": "document",
                    "content_type": "application/pdf",
                    "content": "JVBERi0xLjQ=",
                }
            ],
        }
    )

    assert result["chunk_batch_summary"] == "files=1, pages=1, chunks=1"
    assert fake_kg.source_pages[0]["page_width"] == 1654
    assert fake_kg.source_chunks[0].chunk_text == "缓存命中的正文"
