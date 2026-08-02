import httpx

from ai_hunter.app.services.doc_category_api import DocCategoryAPIClient


def test_validate_doc_category_sync_normalizes_fastserver_400(monkeypatch):
    client = DocCategoryAPIClient(base_url="http://fastserver.test")
    request = httpx.Request("POST", "http://fastserver.test/api/ingest/validate-doc-category")
    response = httpx.Response(
        400,
        json={"detail": "不支持的文档类型: invalid"},
        request=request,
    )

    def raise_bad_request(path, payload):
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr(client, "post_json_sync", raise_bad_request)

    result = client.validate_doc_category_sync(
        {"case_id": 116, "doc_category": "invalid", "file_names": ["判决书.pdf"]}
    )

    assert result == {
        "ok": False,
        "suspected_mismatch": True,
        "suspected_duplicate": False,
        "message": "不支持的文档类型: invalid",
    }
