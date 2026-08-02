from fastapi.testclient import TestClient

from ai_hunter.app.main import create_app
from ai_hunter.app.graph.capabilities import CAPABILITY_IDS


def test_docs_endpoints_are_exposed_for_frontend():
    client = TestClient(create_app())

    docs_response = client.get("/docs")
    openapi_response = client.get("/openapi.json")
    index_response = client.get("/docs-index")

    assert docs_response.status_code == 200
    assert openapi_response.status_code == 200
    assert index_response.status_code == 200

    index_body = index_response.json()
    assert index_body["swagger_url"] == "/docs"
    assert index_body["redoc_url"] == "/redoc"
    assert index_body["openapi_url"] == "/openapi.json"
    assert any(section["tag"] == "files" for section in index_body["sections"])
    assert any(section["tag"] == "chat" for section in index_body["sections"])
    assert any(section["tag"] == "graph" for section in index_body["sections"])
    chat_section = next(section for section in index_body["sections"] if section["tag"] == "chat")
    assert "AUDIT_API_TOKEN" in chat_section["description"]
    files_section = next(section for section in index_body["sections"] if section["tag"] == "files")
    file_paths = {item["path"] for item in files_section["endpoints"]}
    assert "/files/upload-and-ingest" in file_paths
    assert "/files/upload-batches/{upload_batch_id}" in file_paths
    assert "/files/cases/{case_id}/upload-batches" in file_paths
    assert "/files/material-events/{material_event_id}" in file_paths
    assert "/files/cases/{case_id}/material-events" in file_paths
    assert "/files/cases/{case_id}/evolution-items" in file_paths
    assert "/files/cases/{case_id}/unresolved-items" in file_paths

    openapi_body = openapi_response.json()
    assert "AUDIT_API_TOKEN" in openapi_body["info"]["description"]
    assert "/files/upload-and-ingest" in openapi_body["paths"]
    upload_description = openapi_body["paths"]["/files/upload-and-ingest"]["post"]["description"]
    assert "上传前必须先建案" in upload_description
    assert "不从材料文本猜测债务人" in upload_description
    health_schema = openapi_body["paths"]["/files/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert health_schema["$ref"].endswith("/HealthResponse")
    assert "/files/material-events/{material_event_id}" in openapi_body["paths"]
    assert "/files/cases/{case_id}/material-events" in openapi_body["paths"]
    assert "/files/cases/{case_id}/evolution-items" in openapi_body["paths"]
    assert "/files/cases/{case_id}/unresolved-items" in openapi_body["paths"]
    assert "/chat/invoke" in openapi_body["paths"]
    chat_upload_description = openapi_body["paths"]["/chat/upload-files"]["post"]["description"]
    assert "案件画像一致" in chat_upload_description
    assert "不会参与债务人解析" in chat_upload_description
    assert "/graph/subgraph" in openapi_body["paths"]
    chat_description = openapi_body["paths"]["/chat/invoke"]["post"]["description"]
    assert "stream=true" in chat_description
    assert "Accept: text/event-stream" in chat_description
    assert "operator / audit_analysis / supervision / common" in chat_description
    assert "Phase 2.5.4" in chat_description
    assert "ROUTER_EXECUTION_MODE=business_line" in chat_description
    assert "七个只读 capability" in chat_description
    assert "audit.full / audit.reaudit / recovery.review" in chat_description
    assert "audit.drilldown / graph.query" in chat_description
    assert "evidence.resolve 只查本案卷宗" in chat_description
    assert "caselaw.search" in chat_description
    assert "case.create / material.upload / task.write 进入确定性写命令节点" in chat_description
    assert "write_command" in chat_description
    assert "不二次摄入" in chat_description
    assert "缺少案件上下文" in chat_description
    chat_response_schema = openapi_body["components"]["schemas"]["ChatInvokeResponse"]["properties"]
    assert "route_decision" in chat_response_schema
    assert "RouteDecisionModel" in str(chat_response_schema["route_decision"])
    route_schema = openapi_body["components"]["schemas"]["RouteDecisionModel"]["properties"]
    assert route_schema["business_line"]["enum"] == ["operator", "audit_analysis", "supervision", "common"]
    assert route_schema["capability"]["enum"] == list(CAPABILITY_IDS)
    chat_request_schema = openapi_body["components"]["schemas"]["ChatRequest"]["properties"]
    assert "write_command" in chat_request_schema
    assert "WriteCommandModel" in str(chat_request_schema["write_command"])
    upload_schema = openapi_body["components"]["schemas"]["UploadAndIngestResponse"]["properties"]
    assert upload_schema["upload_batch_summary"]["$ref"].endswith("/UploadBatchSummaryResponse")
    assert upload_schema["doc_category_validation"]["$ref"].endswith("/ValidateDocCategoryResultModel")
    assert upload_schema["case_doc_category_status"]["$ref"].endswith("/CaseDocCategoryStatusModel")
