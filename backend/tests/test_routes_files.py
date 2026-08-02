import io
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from ai_hunter.app.api._upload_helpers import DebtorResolution
from ai_hunter.app.graph.heavy_state import get_heavy_payload, put_heavy_payload
from ai_hunter.app.main import create_app

EXPECTED_STORAGE_URL = "https://minio.gshbzw.com/ai-hunter-raw/case-116/debtor-unknown/raw/mock.pdf"


@pytest.fixture(autouse=True)
def _resolve_authoritative_debtor(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files.resolve_effective_debtor",
        lambda **kwargs: DebtorResolution(
            debtor_id=int(kwargs.get("debtor_id") or 76),
            debtor_name=kwargs.get("debtor_name") or "钟山区老鹰山镇晨光煤矿",
            source="test",
        ),
    )


def test_upload_and_ingest_route_reads_text_and_binary_files(monkeypatch):
    class FakeMinioUploadResult:
        storage_ref = "minio://ai-hunter-raw/case-116/debtor-unknown/raw/mock.pdf"
        storage_provider = "minio"
        storage_bucket = "ai-hunter-raw"
        storage_key = "case-116/debtor-unknown/raw/mock.pdf"
        storage_etag = "etag-1"
        storage_version = ""

    class FakeMinioService:
        def upload_raw_file(self, **kwargs):
            return FakeMinioUploadResult()

    enqueued = {}
    persisted = {"source_rows": [], "links": []}

    class FakeKGService:
        def upsert_source_upload_batch(self, summary):
            return summary

        def upsert_material_event(self, summary):
            return summary

        def insert_source_files(self, rows):
            persisted["source_rows"] = rows
            return [
                {
                    "id": index,
                    "case_id": row["case_id"],
                    "file_sha256": row["file_sha256"],
                    "file_name": row["file_name"],
                }
                for index, row in enumerate(rows, 1)
            ]

        def link_source_files_to_upload_batch(self, *, upload_batch_id, files, duplicate_by_sha256):
            persisted["links"] = files
            return [{"id": index, "upload_batch_id": upload_batch_id} for index, _ in enumerate(files, 1)]

    fake_kg = FakeKGService()

    def fake_enqueue(job_payload):
        enqueued["payload"] = job_payload

    monkeypatch.setattr(
        "ai_hunter.app.api._upload_helpers.get_minio_service",
        lambda: FakeMinioService(),
    )
    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.services.material_event_progress.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.api.routes_files._enqueue_upload_ingest_job", fake_enqueue)
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._resolve_doc_category_validation",
        lambda **kwargs: {
            "ok": True,
            "suspected_mismatch": False,
            "suspected_duplicate": False,
            "message": "ok",
        },
    )
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._resolve_case_doc_category_status",
        lambda case_id: {"case_id": case_id, "categories": [], "missing_categories": []},
    )

    client = TestClient(create_app())
    response = client.post(
        "/files/upload-and-ingest",
        data={
            "current_case_id": "116",
            "current_debtor_id": "0",
            "current_debtor_name": "",
            "doc_category": "restructuring_plan",
        },
        files=[
            ("files", ("a.csv", io.BytesIO(b"a,b\n1,2"), "text/csv")),
            ("files", ("b.txt", io.BytesIO("hello".encode("utf-8")), "text/plain")),
            ("files", ("c.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")),
            ("files", ("d.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")),
        ],
    )

    body = response.json()
    job_payload = enqueued["payload"]
    uploaded_files = job_payload["uploaded_files"]
    assert uploaded_files[0]["content"] == "a,b\n1,2"
    assert uploaded_files[1]["content"] == "hello"
    assert uploaded_files[2]["content"].startswith("JVBER")
    assert uploaded_files[3]["content"].startswith("iVBOR")
    assert uploaded_files[0]["storage_provider"] == "minio"
    assert uploaded_files[0]["storage_bucket"] == "ai-hunter-raw"
    assert uploaded_files[0]["storage_ref"] == "minio://ai-hunter-raw/case-116/debtor-unknown/raw/mock.pdf"
    assert uploaded_files[0]["url"] == EXPECTED_STORAGE_URL
    assert re.match(r"^local-[0-9a-f]{12}$", uploaded_files[0]["upload_batch_id"])
    assert len(uploaded_files[0]["file_hash"]) == 64
    assert uploaded_files[0]["file_size"] == 7
    assert job_payload["doc_category"] == "restructuring_plan"
    assert job_payload["current_case_id"] == 116
    assert len(job_payload["text_file_content_refs"]) == 2
    assert len(persisted["source_rows"]) == 4
    assert len(persisted["links"]) == 4
    assert persisted["source_rows"][2]["storage_provider"] == "minio"
    assert persisted["source_rows"][2]["file_sha256"] == uploaded_files[2]["file_hash"]

    assert response.status_code == 202
    assert body["accepted"] is True
    assert body["status"] == "processing"
    assert body["stage"] == "stored"
    assert body["uploaded_file_count"] == 4
    assert re.match(r"^local-[0-9a-f]{12}$", body["upload_batch_id"])
    assert body["upload_batch_detail_path"] == f"/files/upload-batches/{body['upload_batch_id']}"
    assert body["material_event_detail_path"] == f"/files/material-events/material-event:{body['upload_batch_id']}"
    assert body["case_upload_batches_path"] == "/files/cases/116/upload-batches"
    assert body["upload_batch_summary"]["material_event_id"] == f"material-event:{body['upload_batch_id']}"
    assert body["upload_batch_summary"]["material_event_type"] == "supplement_upload"
    assert body["upload_batch_summary"]["file_count"] == 4
    assert body["upload_batch_summary"]["status"] == "processing"
    assert body["upload_batch_summary"]["stage"] == "stored"


def test_upload_and_ingest_route_rejects_empty_file_list():
    client = TestClient(create_app())
    response = client.post("/files/upload-and-ingest", data={"current_case_id": "116"})
    assert response.status_code == 422


def test_upload_and_ingest_replays_completed_batch_without_storage_or_enqueue(monkeypatch):
    content = b"existing upload"
    file_sha256 = hashlib.sha256(content).hexdigest()

    class FakeKGService:
        def fetch_source_upload_batch(self, upload_batch_id):
            assert upload_batch_id == "batch-existing"
            return {
                "upload_batch_id": upload_batch_id,
                "case_id": 116,
                "debtor_id": 76,
                "doc_category": "judgment",
                "batch_name": "existing batch",
                "operator_id": "u-owner",
                "operator_name": "Owner",
                "status": "completed",
                "file_count": 1,
                "metadata": {
                    "material_event_id": "material-event:batch-existing",
                    "stage": "completed",
                },
                "files": [
                    {
                        "file_name": "existing.txt",
                        "file_sha256": file_sha256,
                    }
                ],
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._enqueue_upload_ingest_job",
        lambda payload: pytest.fail("idempotent replay must not enqueue ingest"),
    )

    client = TestClient(create_app())
    response = client.post(
        "/files/upload-and-ingest",
        data={
            "current_case_id": "116",
            "current_debtor_id": "76",
            "doc_category": "judgment",
            "upload_batch_id": "batch-existing",
        },
        files=[("files", ("existing.txt", io.BytesIO(content), "text/plain"))],
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"
    assert body["stage"] == "completed"
    assert body["duplicate_files"] == ["existing.txt"]
    assert body["new_files"] == []
    assert body["doc_category_validation"]["suspected_duplicate"] is True


def test_upload_and_ingest_rejects_batch_reuse_with_different_file(monkeypatch):
    class FakeKGService:
        def fetch_source_upload_batch(self, upload_batch_id):
            return {
                "upload_batch_id": upload_batch_id,
                "case_id": 116,
                "debtor_id": 76,
                "doc_category": "judgment",
                "status": "completed",
                "file_count": 1,
                "metadata": {"stage": "completed"},
                "files": [{"file_name": "existing.txt", "file_sha256": "0" * 64}],
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    response = TestClient(create_app()).post(
        "/files/upload-and-ingest",
        data={
            "current_case_id": "116",
            "current_debtor_id": "76",
            "doc_category": "judgment",
            "upload_batch_id": "batch-existing",
        },
        files=[("files", ("different.txt", io.BytesIO(b"different"), "text/plain"))],
    )

    assert response.status_code == 409
    assert "已绑定其他文件集合" in response.json()["detail"]


def test_upload_and_ingest_route_returns_standard_error_when_enqueue_fails(monkeypatch):
    class FakeMinioUploadResult:
        storage_ref = ""
        storage_provider = ""
        storage_bucket = ""
        storage_key = ""
        storage_etag = ""
        storage_version = ""

    class FakeMinioService:
        def upload_raw_file(self, **kwargs):
            return FakeMinioUploadResult()

    failed_batches = []

    class FakeKGService:
        def __init__(self):
            self.material_events = []

        def upsert_source_upload_batch(self, summary):
            failed_batches.append(summary)
            return summary

        def upsert_material_event(self, summary):
            self.material_events.append(summary)
            return summary

        def insert_source_files(self, rows):
            return [
                {
                    "id": index,
                    "case_id": row["case_id"],
                    "file_sha256": row["file_sha256"],
                    "file_name": row["file_name"],
                }
                for index, row in enumerate(rows, 1)
            ]

        def link_source_files_to_upload_batch(self, *, upload_batch_id, files, duplicate_by_sha256):
            return [{"id": index, "upload_batch_id": upload_batch_id} for index, _ in enumerate(files, 1)]

    fake_kg = FakeKGService()
    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.services.material_event_progress.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.api._upload_helpers.get_minio_service", lambda: FakeMinioService())
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._enqueue_upload_ingest_job",
        lambda payload: (_ for _ in ()).throw(RuntimeError("executor unavailable")),
    )
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._resolve_doc_category_validation",
        lambda **kwargs: {
            "ok": True,
            "suspected_mismatch": False,
            "suspected_duplicate": False,
            "message": "ok",
        },
    )

    client = TestClient(create_app())
    response = client.post(
        "/files/upload-and-ingest",
        data={
            "current_case_id": "116",
            "doc_category": "judgment",
            "upload_batch_id": "batch-failed",
        },
        files=[("files", ("a.txt", io.BytesIO(b"hello"), "text/plain"))],
    )

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["error_code"] == "INGEST_JOB_ENQUEUE_FAILED"
    assert detail["stage"] == "queued"
    assert detail["upload_batch_id"] == "batch-failed"
    assert detail["material_event_id"] == "material-event:batch-failed"
    assert failed_batches[-1]["status"] == "failed"
    assert failed_batches[-1]["metadata"]["material_event_id"] == "material-event:batch-failed"
    assert failed_batches[-1]["metadata"]["error"]["error_code"] == "INGEST_JOB_ENQUEUE_FAILED"
    assert fake_kg.material_events[-1]["status"] == "failed"


def test_upload_and_ingest_route_fails_when_file_membership_cannot_persist(monkeypatch):
    class FakeMinioUploadResult:
        storage_ref = "minio://ai-hunter-raw/case-116/debtor-76/raw/a.pdf"
        storage_provider = "minio"
        storage_bucket = "ai-hunter-raw"
        storage_key = "case-116/debtor-76/raw/a.pdf"
        storage_etag = "etag-1"
        storage_version = ""

    class FakeMinioService:
        def upload_raw_file(self, **kwargs):
            return FakeMinioUploadResult()

    batches = []

    class FakeKGService:
        def upsert_source_upload_batch(self, summary):
            batches.append(summary)
            return summary

        def upsert_material_event(self, summary):
            return summary

        def insert_source_files(self, rows):
            raise RuntimeError("source_file unavailable")

    fake_kg = FakeKGService()
    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.services.material_event_progress.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.api._upload_helpers.get_minio_service", lambda: FakeMinioService())
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._resolve_doc_category_validation",
        lambda **kwargs: {"ok": True, "suspected_mismatch": False, "suspected_duplicate": False},
    )

    client = TestClient(create_app())
    response = client.post(
        "/files/upload-and-ingest",
        data={
            "current_case_id": "116",
            "current_debtor_id": "76",
            "doc_category": "restructuring_plan",
            "upload_batch_id": "batch-metadata-failed",
        },
        files=[("files", ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf"))],
    )

    assert response.status_code == 500
    assert response.json()["detail"]["error_code"] == "UPLOAD_METADATA_PERSIST_FAILED"
    assert response.json()["detail"]["stage"] == "stored"
    assert batches[-1]["status"] == "failed"
    assert batches[-1]["metadata"]["error"]["error_code"] == "UPLOAD_METADATA_PERSIST_FAILED"


def test_run_upload_ingest_job_marks_failed_when_graph_raises(monkeypatch):
    class FakeGraph:
        def invoke(self, state):
            raise RuntimeError("ocr service unavailable")

    failed_batches = []

    class FakeKGService:
        def __init__(self):
            self.material_events = []

        def upsert_source_upload_batch(self, summary):
            failed_batches.append(summary)
            return summary

        def upsert_material_event(self, summary):
            self.material_events.append(summary)
            return summary

    fake_kg = FakeKGService()
    monkeypatch.setattr("ai_hunter.app.api.routes_files.upload_parse_graph", FakeGraph())
    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.services.material_event_progress.get_kg_service", lambda: fake_kg)

    from ai_hunter.app.api.routes_files import _run_upload_ingest_job

    _run_upload_ingest_job(
        {
            "current_case_id": 116,
            "current_debtor_id": 0,
            "current_debtor_name": "",
            "doc_category": "judgment",
            "batch_name": "",
            "upload_batch_id": "batch-failed",
            "operator_id": "",
            "operator_name": "",
            "uploaded_files": [{"name": "a.txt", "content": "hello"}],
            "doc_category_validation": {"ok": True},
            "duplicate_files": [],
            "suspected_mismatch_files": [],
            "new_files": ["a.txt"],
            "upload_batch_summary": {"upload_batch_id": "batch-failed"},
        }
    )

    assert failed_batches[-1]["status"] == "failed"
    assert failed_batches[-1]["metadata"]["error"]["error_code"] == "INGEST_PARSE_FAILED"
    assert fake_kg.material_events[-1]["status"] == "failed"
    assert fake_kg.material_events[-1]["event_payload"]["stage"] == "ocr_running"


def test_run_upload_ingest_job_marks_parse_and_graph_progress(monkeypatch):
    class FakeParseGraph:
        def invoke(self, state):
            return {
                **state,
                "current_case_id": 116,
                "current_debtor_id": 0,
                "current_debtor_name": "晨光煤矿",
                "records_inserted": 2,
                "categories_found": ["judgment"],
                "recognized_categories": ["judgment"],
                "parse_summary": "parse ok",
            }

    class FakeKGGraph:
        def invoke(self, state):
            return {
                **state,
                "reconciliation_items": [{"action": "ADD"}],
                "unresolved_relations": [],
                "unresolved_claims": [],
            }

    class FakeKGService:
        def __init__(self):
            self.material_events = []
            self.batches = []

        def upsert_source_upload_batch(self, summary):
            self.batches.append(summary)
            return summary

        def upsert_material_event(self, summary):
            self.material_events.append(summary)
            return summary

    fake_kg = FakeKGService()
    monkeypatch.setattr("ai_hunter.app.api.routes_files.upload_parse_graph", FakeParseGraph())
    monkeypatch.setattr("ai_hunter.app.api.routes_files.knowledge_graph_graph", FakeKGGraph())
    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.services.material_event_progress.get_kg_service", lambda: fake_kg)

    from ai_hunter.app.api.routes_files import _run_upload_ingest_job

    _run_upload_ingest_job(
        {
            "current_case_id": 116,
            "current_debtor_id": 0,
            "current_debtor_name": "",
            "doc_category": "judgment",
            "batch_name": "",
            "upload_batch_id": "batch-progress",
            "operator_id": "",
            "operator_name": "",
            "uploaded_files": [{"name": "a.txt", "content": "hello"}],
            "doc_category_validation": {"ok": True},
            "duplicate_files": [],
            "suspected_mismatch_files": [],
            "new_files": ["a.txt"],
            "upload_batch_summary": {"upload_batch_id": "batch-progress"},
        }
    )

    stages = [event["event_payload"]["stage"] for event in fake_kg.material_events]
    assert stages == ["ocr_running", "parse_completed", "graph_running", "completed"]
    assert fake_kg.material_events[-1]["status"] == "completed"
    assert fake_kg.material_events[-1]["event_payload"]["parse_summary"] == "parse ok"
    assert fake_kg.material_events[-1]["event_payload"]["reconciliation_item_count"] == 1
    assert fake_kg.batches[-1]["metadata"]["stage"] == "completed"


def test_run_upload_parse_job_persists_refs_and_enqueues_graph_job(monkeypatch):
    enqueued = {}

    class FakeParseGraph:
        def invoke(self, state):
            return {
                **state,
                "current_case_id": 116,
                "current_debtor_name": "晨光煤矿",
                "records_inserted": 2,
                "categories_found": ["judgment"],
                "recognized_categories": ["judgment"],
                "parse_summary": "parse ok",
                "ingest_payload_ref": "ingest_payload:abc",
                "aggregated_text_ref": "aggregated_text:def",
                "parse_document_result_ref": "parse_document_result:ghi",
            }

    class FakeKGService:
        def __init__(self):
            self.material_events = []
            self.batches = []

        def upsert_source_upload_batch(self, summary):
            self.batches.append(summary)
            return summary

        def upsert_material_event(self, summary):
            self.material_events.append(summary)
            return summary

    fake_kg = FakeKGService()
    monkeypatch.setattr("ai_hunter.app.api.routes_files.upload_parse_graph", FakeParseGraph())
    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.services.material_event_progress.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._enqueue_graph_enrichment_job",
        lambda payload: enqueued.setdefault("payload", payload),
    )

    from ai_hunter.app.api.routes_files import _run_upload_parse_job

    result = _run_upload_parse_job(
        {
            "current_case_id": 116,
            "current_debtor_id": 0,
            "current_debtor_name": "",
            "doc_category": "judgment",
            "batch_name": "",
            "upload_batch_id": "batch-parse",
            "operator_id": "",
            "operator_name": "",
            "uploaded_files": [{"name": "a.txt", "content": "hello"}],
            "doc_category_validation": {"ok": True},
            "duplicate_files": [],
            "suspected_mismatch_files": [],
            "new_files": ["a.txt"],
            "upload_batch_summary": {"upload_batch_id": "batch-parse"},
        }
    )

    assert result["ingest_payload_ref"] == "ingest_payload:abc"
    assert enqueued["payload"]["parse_result"]["parse_document_result_ref"] == "parse_document_result:ghi"
    assert enqueued["payload"]["parse_result"]["defer_upload_batch_completion"] is True
    assert fake_kg.material_events[-1]["event_payload"]["ingest_payload_ref"] == "ingest_payload:abc"
    assert fake_kg.batches[-1]["metadata"]["aggregated_text_ref"] == "aggregated_text:def"


def test_run_graph_enrichment_job_marks_failed_when_graph_raises(monkeypatch):
    class FakeKGGraph:
        def invoke(self, state):
            raise RuntimeError("kg extractor unavailable")

    class FakeKGService:
        def __init__(self):
            self.material_events = []
            self.batches = []

        def upsert_source_upload_batch(self, summary):
            self.batches.append(summary)
            return summary

        def upsert_material_event(self, summary):
            self.material_events.append(summary)
            return summary

    fake_kg = FakeKGService()
    monkeypatch.setattr("ai_hunter.app.api.routes_files.knowledge_graph_graph", FakeKGGraph())
    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: fake_kg)
    monkeypatch.setattr("ai_hunter.app.services.material_event_progress.get_kg_service", lambda: fake_kg)

    from ai_hunter.app.api.routes_files import _run_graph_enrichment_job

    _run_graph_enrichment_job(
        {
            "parse_result": {
                "current_case_id": 116,
                "current_debtor_id": 0,
                "current_debtor_name": "晨光煤矿",
                "doc_category": "judgment",
                "upload_batch_id": "batch-graph-failed",
                "uploaded_files": [{"name": "a.txt", "content": "hello"}],
                "new_files": ["a.txt"],
                "ingest_payload_ref": "ingest_payload:abc",
                "aggregated_text_ref": "aggregated_text:def",
                "parse_document_result_ref": "parse_document_result:ghi",
            }
        }
    )

    assert fake_kg.material_events[0]["event_payload"]["stage"] == "graph_running"
    assert fake_kg.material_events[-1]["event_payload"]["error"]["error_code"] == "INGEST_GRAPH_FAILED"
    assert fake_kg.material_events[-1]["event_payload"]["ingest_payload_ref"] == "ingest_payload:abc"


def test_get_upload_batch_route_returns_persistence_checks(monkeypatch):
    class FakeKGService:
        def fetch_source_upload_batch(self, upload_batch_id):
            assert upload_batch_id == "batch-001"
            return {
                "upload_batch_id": upload_batch_id,
                "case_id": 116,
                "status": "completed",
                "metadata": {
                    "has_conclusion_changes": True,
                    "reconciliation_item_count": 2,
                    "add_item_count": 1,
                    "override_item_count": 1,
                    "change_summary": "本次补件新增1条结论，并替代1条旧结论。",
                },
                "files": [{"file_id": 1, "chunk_count": 2}],
                "persistence_checks": {"source_file_count_matches": True},
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    client = TestClient(create_app())
    response = client.get("/files/upload-batches/batch-001")

    assert response.status_code == 200
    body = response.json()
    assert body["upload_batch_id"] == "batch-001"
    assert body["persistence_checks"]["source_file_count_matches"] is True
    assert body["has_conclusion_changes"] is True
    assert body["override_item_count"] == 1


def test_list_case_upload_batches_route(monkeypatch):
    class FakeKGService:
        # 路由会对每条批次再 fetch_source_upload_batch(...) or b 富化；返回 None 走 `or b` 兜底。
        def fetch_source_upload_batch(self, upload_batch_id):
            return None

        def list_source_upload_batches_by_case(self, case_id, limit=50):
            assert case_id == 116
            assert limit == 10
            return [
                {
                    "upload_batch_id": "batch-001",
                    "case_id": 116,
                    "status": "completed",
                    "metadata": {
                        "has_conclusion_changes": True,
                        "reconciliation_item_count": 2,
                        "add_item_count": 1,
                        "override_item_count": 1,
                        "change_summary": "本次补件新增1条结论，并替代1条旧结论。",
                    },
                }
            ]

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    client = TestClient(create_app())
    response = client.get("/files/cases/116/upload-batches?limit=10")

    assert response.status_code == 200
    assert response.json()["upload_batches"][0]["upload_batch_id"] == "batch-001"
    assert response.json()["upload_batches"][0]["has_conclusion_changes"] is True


def test_retry_upload_batch_route_enqueues_graph_job(monkeypatch):
    enqueued = {}
    sequence = []

    class FakeKGService:
        def fetch_source_upload_batch(self, upload_batch_id):
            assert upload_batch_id == "batch-graph-retry"
            return {
                "upload_batch_id": upload_batch_id,
                "case_id": 116,
                "debtor_id": 0,
                "batch_name": "补件一",
                "doc_category": "judgment",
                "operator_id": "op-1",
                "operator_name": "A",
                "status": "failed",
                "file_count": 1,
                "records_inserted": 2,
                "metadata": {
                    "material_event_id": "material-event:batch-graph-retry",
                    "stage": "graph_running",
                    "ingest_payload_ref": "ingest_payload:abc",
                    "aggregated_text_ref": "aggregated_text:def",
                    "parse_document_result_ref": "parse_document_result:ghi",
                    "parse_summary": "parse ok",
                    "new_files": ["a.pdf"],
                },
                "files": [
                    {
                        "file_name": "a.pdf",
                        "file_type": "document",
                        "content_type": "application/pdf",
                        "file_sha256": "abc123",
                        "file_size_bytes": 7,
                        "duplicate_of": "",
                        "storage_ref": "minio://bucket/a.pdf",
                        "storage_provider": "minio",
                        "storage_bucket": "bucket",
                        "storage_key": "a.pdf",
                    }
                ],
            }

        def fetch_material_event(self, material_event_id):
            assert material_event_id == "material-event:batch-graph-retry"
            return {
                "material_event_id": material_event_id,
                "status": "failed",
                "event_payload": {
                    "stage": "graph_running",
                    "ingest_payload_ref": "ingest_payload:abc",
                    "aggregated_text_ref": "aggregated_text:def",
                    "parse_document_result_ref": "parse_document_result:ghi",
                },
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._enqueue_graph_enrichment_job",
        lambda payload: (sequence.append("enqueue"), enqueued.setdefault("payload", payload))[1],
    )
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._mark_retry_progress",
        lambda **kwargs: sequence.append(f"mark:{kwargs['status']}:{kwargs['stage']}"),
    )

    client = TestClient(create_app())
    response = client.post("/files/upload-batches/batch-graph-retry/retry?stage=auto")

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["retry_stage"] == "graph"
    assert body["stage"] == "graph_running"
    assert sequence == ["mark:processing:retry_graph_queued", "enqueue"]
    assert enqueued["payload"]["parse_result"]["ingest_payload_ref"] == "ingest_payload:abc"
    assert enqueued["payload"]["parse_result"]["uploaded_files"][0]["file_hash"] == "abc123"
    assert enqueued["payload"]["parse_result"]["defer_upload_batch_completion"] is True


def test_retry_upload_batch_route_returns_409_for_completed_batch(monkeypatch):
    class FakeKGService:
        def fetch_source_upload_batch(self, upload_batch_id):
            return {
                "upload_batch_id": upload_batch_id,
                "case_id": 116,
                "status": "completed",
                "metadata": {"material_event_id": "material-event:batch-completed"},
                "files": [],
            }

        def fetch_material_event(self, material_event_id):
            return {
                "material_event_id": material_event_id,
                "status": "completed",
                "event_payload": {"stage": "completed"},
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    response = TestClient(create_app()).post(
        "/files/upload-batches/batch-completed/retry?stage=graph"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "仅支持对失败批次执行重试。"


def test_retry_upload_batch_route_enqueues_parse_job_for_text_file(monkeypatch):
    enqueued = {}
    sequence = []
    text_ref = put_heavy_payload(
        "text_file_content",
        {
            "file_hash": "abc123",
            "file_name": "a.txt",
            "content": "hello",
        },
    )

    class FakeKGService:
        def fetch_source_upload_batch(self, upload_batch_id):
            return {
                "upload_batch_id": upload_batch_id,
                "case_id": 116,
                "debtor_id": 0,
                "batch_name": "补件一",
                "doc_category": "judgment",
                "operator_id": "op-1",
                "operator_name": "A",
                "status": "failed",
                "file_count": 1,
                "records_inserted": 0,
                "metadata": {
                    "material_event_id": f"material-event:{upload_batch_id}",
                    "stage": "ocr_running",
                    "text_file_content_refs": {"abc123": text_ref},
                },
                "files": [
                    {
                        "file_name": "a.txt",
                        "file_type": "document",
                        "content_type": "text/plain",
                        "file_sha256": "abc123",
                        "file_size_bytes": 5,
                        "duplicate_of": "",
                        "storage_ref": "minio://bucket/a.txt",
                        "storage_provider": "minio",
                        "storage_bucket": "bucket",
                        "storage_key": "a.txt",
                    }
                ],
            }

        def fetch_material_event(self, material_event_id):
            return {
                "material_event_id": material_event_id,
                "status": "failed",
                "event_payload": {"stage": "ocr_running", "text_file_content_refs": {"abc123": text_ref}},
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._enqueue_upload_ingest_job",
        lambda payload: (sequence.append("enqueue"), enqueued.setdefault("payload", payload))[1],
    )
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_files._mark_retry_progress",
        lambda **kwargs: sequence.append(f"mark:{kwargs['status']}:{kwargs['stage']}"),
    )

    client = TestClient(create_app())
    response = client.post("/files/upload-batches/batch-text-retry/retry?stage=parse")

    assert response.status_code == 200
    assert response.json()["retry_stage"] == "parse"
    assert sequence == ["mark:processing:retry_parse_queued", "enqueue"]
    assert enqueued["payload"]["uploaded_files"][0]["content"] == "hello"
    stored_payload = get_heavy_payload(enqueued["payload"]["text_file_content_refs"]["abc123"])
    assert stored_payload["content"] == "hello"


def test_retry_upload_batch_route_rejects_text_parse_retry_without_persisted_content(monkeypatch):
    class FakeKGService:
        def fetch_source_upload_batch(self, upload_batch_id):
            return {
                "upload_batch_id": upload_batch_id,
                "case_id": 116,
                "debtor_id": 0,
                "batch_name": "补件一",
                "doc_category": "judgment",
                "operator_id": "op-1",
                "operator_name": "A",
                "status": "failed",
                "file_count": 1,
                "records_inserted": 0,
                "metadata": {
                    "material_event_id": f"material-event:{upload_batch_id}",
                    "stage": "ocr_running",
                },
                "files": [
                    {
                        "file_name": "a.txt",
                        "file_type": "document",
                        "content_type": "text/plain",
                        "file_sha256": "abc123",
                        "file_size_bytes": 5,
                        "duplicate_of": "",
                        "storage_ref": "minio://bucket/a.txt",
                        "storage_provider": "minio",
                        "storage_bucket": "bucket",
                        "storage_key": "a.txt",
                    }
                ],
            }

        def fetch_material_event(self, material_event_id):
            return {
                "material_event_id": material_event_id,
                "status": "failed",
                "event_payload": {"stage": "ocr_running"},
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    client = TestClient(create_app())
    response = client.post("/files/upload-batches/batch-text-missing/retry?stage=parse")

    assert response.status_code == 409
    assert "parse 重试缺少文本文件持久化内容" in response.json()["detail"]


def test_list_case_unresolved_items_route(monkeypatch):
    class FakeKGService:
        def fetch_unresolved_graph_items(self, *, case_id, upload_batch_id="", status="pending", limit=50):
            assert case_id == 116
            assert upload_batch_id == "batch-001"
            assert status == "resolved"
            assert limit == 20
            return {
                "unresolved_relations": [
                    {
                        "id": 91,
                        "case_id": 116,
                        "upload_batch_id": "batch-001",
                        "material_event_id": "material-event:batch-001",
                        "item_type": "relation",
                        "relation_key": "relation-key-1",
                        "relation_temp_id": "relation_1",
                        "relation_type": "guarantee",
                        "relation_label": "提供担保",
                        "missing_dependencies": ["from_entity"],
                        "reason": "missing_entity_reference",
                        "status": "resolved",
                        "payload": {},
                    }
                ],
                "unresolved_claims": [
                    {
                        "id": 92,
                        "case_id": 116,
                        "upload_batch_id": "batch-001",
                        "material_event_id": "material-event:batch-001",
                        "item_type": "claim",
                        "claim_type": "relation_fact",
                        "claim_text": "晨光煤矿为张三提供担保",
                        "entity_key": "entity-key-1",
                        "relation_key": "relation-key-1",
                        "missing_dependencies": ["relation"],
                        "reason": "missing_graph_reference",
                        "status": "resolved",
                        "payload": {},
                    }
                ],
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    client = TestClient(create_app())
    response = client.get("/files/cases/116/unresolved-items?status=resolved&upload_batch_id=batch-001&limit=20")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == 116
    assert body["upload_batch_id"] == "batch-001"
    assert body["status"] == "resolved"
    assert body["unresolved_relation_count"] == 1
    assert body["unresolved_claim_count"] == 1
    assert body["unresolved_relations"][0]["relation_key"] == "relation-key-1"
    assert body["unresolved_claims"][0]["claim_text"] == "晨光煤矿为张三提供担保"


def test_get_material_event_route(monkeypatch):
    class FakeKGService:
        def fetch_material_event(self, material_event_id):
            assert material_event_id == "material-event:batch-001"
            return {
                "material_event_id": material_event_id,
                "case_id": 116,
                "upload_batch_id": "batch-001",
                "event_type": "supplement_upload",
                "status": "completed",
                "file_count": 3,
                "records_inserted": 2,
                "event_payload": {
                    "stage": "completed",
                    "has_conclusion_changes": True,
                    "reconciliation_item_count": 2,
                    "add_item_count": 1,
                    "override_item_count": 1,
                    "change_summary": "本次补件新增1条结论，并替代1条旧结论。",
                },
            }

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    client = TestClient(create_app())
    response = client.get("/files/material-events/material-event:batch-001")

    assert response.status_code == 200
    body = response.json()
    assert body["material_event_id"] == "material-event:batch-001"
    assert body["status"] == "completed"
    assert body["event_payload"]["stage"] == "completed"
    assert body["stage"] == "completed"
    assert body["has_conclusion_changes"] is True
    assert body["override_item_count"] == 1


def test_list_case_material_events_route(monkeypatch):
    class FakeKGService:
        def list_material_events_by_case(self, case_id, limit=50):
            assert case_id == 116
            assert limit == 5
            return [
                {
                    "material_event_id": "material-event:batch-001",
                    "case_id": 116,
                    "upload_batch_id": "batch-001",
                    "event_type": "supplement_upload",
                    "status": "completed",
                    "file_count": 3,
                    "records_inserted": 2,
                    "event_payload": {
                        "stage": "completed",
                        "has_conclusion_changes": True,
                        "reconciliation_item_count": 2,
                        "add_item_count": 1,
                        "override_item_count": 1,
                        "change_summary": "本次补件新增1条结论，并替代1条旧结论。",
                    },
                }
            ]

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    client = TestClient(create_app())
    response = client.get("/files/cases/116/material-events?limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == 116
    assert body["material_events"][0]["material_event_id"] == "material-event:batch-001"
    assert body["material_events"][0]["has_conclusion_changes"] is True


def test_list_case_evolution_items_route(monkeypatch):
    class FakeKGService:
        def fetch_case_evolution_items(self, *, case_id, action="", limit=20):
            assert case_id == 116
            assert action == "OVERRIDE"
            assert limit == 10
            return [
                {
                    "id": 1,
                    "case_id": 116,
                    "action": "OVERRIDE",
                    "new_claim_id": 101,
                    "new_claim_type": "relation_fact",
                    "new_claim_text": "矿权估值为800万元",
                    "superseded_claim_id": 41,
                    "superseded_claim_type": "relation_fact",
                    "superseded_claim_text": "矿权估值为1200万元",
                    "new_relation_id": 31,
                    "superseded_relation_id": 21,
                    "rationale": "新证据覆盖旧估值",
                    "evidence_chunk_ids": ["chunk-1"],
                    "decision_payload": {"source": "reconcile_graph_delta"},
                    "upload_batch_id": "batch-001",
                    "batch_name": "2025-06 第一次补件",
                    "doc_category": "restructuring_plan",
                    "material_event_id": "material-event:batch-001",
                    "material_event_status": "completed",
                    "material_event_type": "supplement_upload",
                    "evidences": [
                        {
                            "chunk_id": "chunk-1",
                            "file_id": 101,
                            "file_name": "plan.pdf",
                            "page_no": 3,
                            "quote_text": "矿权评估值调整为800万元",
                            "bbox_list": [{"x": 1, "y": 2, "w": 3, "h": 4}],
                            "source_page_id": 9001,
                            "page_image_ref": "https://example.com/page-3.png",
                            "source_file_url": "https://example.com/plan.pdf",
                            "content_type": "application/pdf",
                            "entity_id": 7,
                        }
                    ],
                }
            ]

    monkeypatch.setattr("ai_hunter.app.api.routes_files.get_kg_service", lambda: FakeKGService())

    client = TestClient(create_app())
    response = client.get("/files/cases/116/evolution-items?action=OVERRIDE&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == 116
    assert body["action"] == "OVERRIDE"
    assert body["evolution_items"][0]["new_claim_text"] == "矿权估值为800万元"
    assert body["evolution_items"][0]["material_event_id"] == "material-event:batch-001"
    assert body["evolution_items"][0]["evidences"][0]["page_no"] == 3
    # issue #10: evidences 字段与其它 evidence 接口对齐（content_type / entity_id）
    ev = body["evolution_items"][0]["evidences"][0]
    assert ev["content_type"] == "application/pdf"
    assert ev["entity_id"] == 7
    assert ev["source_file_url"] == "https://example.com/plan.pdf"
