"""Annual-audit upload route public contract."""

from ai_hunter.app.api import routes_files
from ai_hunter.app.api._upload_helpers import EngagementEntityResolution
from ai_hunter.app.main import create_app


def test_upload_openapi_uses_audited_entity_fields():
    schema = create_app().openapi()
    operation = schema["paths"]["/files/upload-and-ingest"]["post"]
    body_schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    component_name = body_schema["$ref"].rsplit("/", 1)[-1]
    properties = schema["components"]["schemas"][component_name]["properties"]
    assert "current_entity_id" in properties
    assert "current_entity_name" in properties


def _failed_batch() -> dict:
    return {
        "case_id": 2,
        "entity_id": 2,
        "upload_batch_id": "batch-2",
        "doc_category": "audit_workpapers",
        "batch_name": "重试批次",
        "operator_id": "local_super_admin",
        "operator_name": "系统超级管理员",
        "file_count": 1,
        "metadata": {
            "new_files": ["年审底稿.xlsx"],
            "ingest_payload_ref": "ingest_payload:1",
            "aggregated_text_ref": "aggregated_text:1",
        },
        "files": [
            {
                "file_name": "年审底稿.xlsx",
                "file_sha256": "abc123",
                "file_size_bytes": 1024,
                "file_type": "document",
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "storage_ref": "minio://annual-raw/case-2/workpaper.xlsx",
                "storage_provider": "minio",
                "storage_bucket": "annual-raw",
                "storage_key": "case-2/workpaper.xlsx",
            }
        ],
    }


def test_retry_payloads_restore_audited_entity_name(monkeypatch):
    monkeypatch.setattr(
        routes_files,
        "resolve_engagement_entity",
        lambda **_: EngagementEntityResolution(2, "北京有限公司", "engagement"),
    )
    batch = _failed_batch()
    parse_payload = routes_files._build_retry_parse_job_payload(batch=batch, event={})
    graph_payload = routes_files._build_retry_graph_job_payload(
        batch=batch,
        event={"event_payload": batch["metadata"]},
    )

    assert parse_payload["current_entity_id"] == 2
    assert parse_payload["current_entity_name"] == "北京有限公司"
    assert graph_payload["parse_result"]["current_entity_id"] == 2
    assert graph_payload["parse_result"]["current_entity_name"] == "北京有限公司"
