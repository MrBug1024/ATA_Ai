from fastapi.testclient import TestClient

from ai_hunter.app.main import create_app

EXPECTED_PAGE_IMAGE_URL = "https://minio.gshbzw.com/derived/page-2.png"
SOURCE_FILE_STORAGE_REF = "minio://raw/sample.pdf"
EXPECTED_SOURCE_FILE_URL = "https://minio.gshbzw.com/raw/sample.pdf"
EXPECTED_ENTITY_ID = 42
EXPECTED_FILE_NAME = "4.晨光煤矿二债会资料.pdf"
EXPECTED_CONTENT_TYPE = "application/pdf"


class FakeKGService:
    def list_report_citations(self, *, case_id, report_ref, citation_ids=None):
        assert case_id == 116
        assert report_ref == "final_report:demo"
        if citation_ids:
            assert citation_ids == ["1"]
        return [{"citation_id": "1", "claim_id": 31, "claim_text": "存在关联担保"}]

    def resolve_claim_by_citation(self, *, case_id, report_ref, citation_id):
        assert case_id == 116
        assert report_ref == "final_report:demo"
        assert citation_id == "1"
        return {"claim_id": 31, "claim_text": "存在关联担保"}

    def fetch_claim_text(self, claim_id, *, case_id=None):
        assert claim_id == 31
        assert case_id == 116
        return "存在关联担保"

    def fetch_claim_evidence(self, claim_id, *, case_id=None):
        assert claim_id == 31
        assert case_id == 116
        return [
            {
                "chunk_id": "chunk-1",
                "file_id": 101,
                "file_name": "卷宗A.pdf",
                "page_no": 2,
                "quote_text": "晨光煤矿进入破产重整程序",
                "bbox_list": [{"x": 1, "y": 2, "w": 3, "h": 4}],
                "page_image_ref": "minio://derived/page-2.png",
                "source_page_id": 9001,
                "source_file_url": EXPECTED_SOURCE_FILE_URL,
                "content_type": EXPECTED_CONTENT_TYPE,
                "entity_id": EXPECTED_ENTITY_ID,
            }
        ]

    def fetch_relation_evidence(self, relation_id, *, case_id=None):
        assert relation_id == 21
        assert case_id == 116
        return [
            {
                "claim_id": 31,
                "claim_type": "risk_signal",
                "claim_text": "存在关联担保",
                "confidence": 0.91,
                "chunk_id": "chunk-1",
                "file_id": 101,
                "file_name": "卷宗A.pdf",
                "page_no": 2,
                "quote_text": "担保事项载于重整方案",
                "bbox_list": [{"x": 1, "y": 2, "w": 3, "h": 4}],
                "page_image_ref": "minio://derived/page-2.png",
                "source_page_id": 9001,
                "storage_ref": SOURCE_FILE_STORAGE_REF,
                "content_type": EXPECTED_CONTENT_TYPE,
                "entity_id": EXPECTED_ENTITY_ID,
                "citation_id": "7",
            }
        ]

    def fetch_subgraph_by_entity(self, *, case_id, center_entity_id, depth, relation_types):
        assert case_id == 116
        assert center_entity_id == 11
        return {
            "nodes": [
                {
                    "id": "entity_11",
                    "entity_id": 11,
                    "label": "晨光煤矿",
                    "entity_type": "company",
                    "risk_level": "unknown",
                }
            ],
            "edges": [],
        }

    def fetch_page_anchors(self, *, file_id, page_no, chunk_id=None):
        assert file_id == 101
        assert page_no == 2
        return [
            {
                "chunk_id": chunk_id or "chunk-1",
                "quote_text": "晨光煤矿进入破产重整程序",
                "bbox_list": [{"x": 1, "y": 2, "w": 3, "h": 4}],
                "source_page_id": 9001,
                "page_image_ref": "minio://derived/page-2.png",
                "page_width": 1200,
                "page_height": 1800,
                "storage_ref": SOURCE_FILE_STORAGE_REF,
                "file_name": EXPECTED_FILE_NAME,
                "content_type": EXPECTED_CONTENT_TYPE,
            }
        ]

    def get_source_file_case_id(self, file_id):
        assert file_id in {31, 101}
        return 116

    def list_entities_by_case(self, case_id, *, limit=100):
        assert case_id == 116
        # 故意乱序返回，验证端点/查询按 degree 降序
        return [
            {"entity_id": 18, "label": "晨光煤矿", "entity_type": "company", "degree": 22},
            {"entity_id": 2, "label": "管理人", "entity_type": "unknown", "degree": 18},
        ]


def test_resolve_evidence_route(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.post("/evidence/resolve", json={"case_id": 116, "claim_id": 31})
    assert response.status_code == 200
    body = response.json()
    assert body["report_ref"] == ""
    assert body["citation_id"] == ""
    assert body["claim_id"] == 31
    assert body["evidences"][0]["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["evidences"][0]["source_page_id"] == 9001
    assert body["primary_evidence"]["chunk_id"] == "chunk-1"
    assert body["primary_page"]["file_id"] == 101
    assert body["primary_page"]["page_no"] == 2
    assert body["primary_page"]["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["primary_page"]["anchors"][0]["chunk_id"] == "chunk-1"
    assert body["resolution_status"] == "ok"
    assert body["evidences"][0]["source_file_url"] == EXPECTED_SOURCE_FILE_URL
    assert body["primary_page"]["source_file_url"] == EXPECTED_SOURCE_FILE_URL
    assert body["primary_page"]["anchors"][0]["source_file_url"] == EXPECTED_SOURCE_FILE_URL
    assert body["evidences"][0]["entity_id"] == EXPECTED_ENTITY_ID
    # issue #7: content_type 透传，前端据此切换 PDF/图片 vs 纯文本渲染
    assert body["evidences"][0]["content_type"] == EXPECTED_CONTENT_TYPE
    assert body["primary_page"]["content_type"] == EXPECTED_CONTENT_TYPE
    assert body["primary_page"]["anchors"][0]["content_type"] == EXPECTED_CONTENT_TYPE


def test_resolve_evidence_route_by_citation_id(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.post(
        "/evidence/resolve",
        json={"case_id": 116, "report_ref": "final_report:demo", "citation_id": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["report_ref"] == "final_report:demo"
    assert body["citation_id"] == "1"
    assert body["claim_id"] == 31
    assert body["claim_text"] == "存在关联担保"
    assert body["evidences"][0]["chunk_id"] == "chunk-1"
    assert body["evidences"][0]["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["primary_page"]["anchors"][0]["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["resolution_status"] == "ok"
    assert body["evidences"][0]["source_file_url"] == EXPECTED_SOURCE_FILE_URL
    assert body["evidences"][0]["entity_id"] == EXPECTED_ENTITY_ID


def test_resolve_evidence_route_by_claim_id_backfills_claim_text(monkeypatch):
    """issue #9: 直接用 claim_id 反查(图谱「最稳」入口)也要回填 claim_text，与 citation_id 路径一致。"""
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.post("/evidence/resolve", json={"case_id": 116, "claim_id": 31})
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == 31
    assert body["claim_text"] == "存在关联担保"  # 不再是空串
    assert body["resolution_status"] == "ok"
    assert body["evidences"][0]["chunk_id"] == "chunk-1"


def test_relation_evidence_route(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.post("/graph/relation-evidence", json={"case_id": 116, "relation_id": 21})
    assert response.status_code == 200
    body = response.json()
    assert body["relation_id"] == 21
    assert body["trace_items"][0]["citation_id"] == "7"
    assert body["trace_items"][0]["claim_text"] == "存在关联担保"
    assert body["trace_items"][0]["evidences"][0]["bbox_list"][0]["w"] == 3
    assert body["trace_items"][0]["evidences"][0]["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["trace_items"][0]["evidences"][0]["source_file_url"] == EXPECTED_SOURCE_FILE_URL
    assert body["trace_items"][0]["entity_id"] == EXPECTED_ENTITY_ID
    assert body["trace_items"][0]["evidences"][0]["entity_id"] == EXPECTED_ENTITY_ID
    assert body["trace_items"][0]["evidences"][0]["content_type"] == EXPECTED_CONTENT_TYPE


def test_validate_demo_case_trace_route(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.services.demo_case_trace_service.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.post(
        "/graph/demo-case-trace/validate",
        json={"case_id": 116, "report_ref": "final_report:demo", "citation_ids": ["1"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["total_citations"] == 1
    assert body["passed_citations"] == 1
    assert body["checks"][0]["citation_id"] == "1"
    assert body["checks"][0]["anchor_count"] == 1


def test_validate_demo_case_trace_route_reports_failures(monkeypatch):
    class BrokenKGService(FakeKGService):
        def fetch_claim_evidence(self, claim_id, *, case_id=None):
            assert case_id == 116
            return [
                {
                    "chunk_id": "chunk-1",
                    "file_id": 101,
                    "file_name": "卷宗A.pdf",
                    "page_no": 2,
                    "quote_text": "晨光煤矿进入破产重整程序",
                    "bbox_list": [],
                    "page_image_ref": "",
                    "source_page_id": 9001,
                }
            ]

        def fetch_page_anchors(self, *, file_id, page_no, chunk_id=None):
            return []

    monkeypatch.setattr(
        "ai_hunter.app.services.demo_case_trace_service.get_kg_service",
        lambda: BrokenKGService(),
    )
    client = TestClient(create_app())
    response = client.post(
        "/graph/demo-case-trace/validate",
        json={"case_id": 116, "report_ref": "final_report:demo"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["failed_citations"] == 1
    assert "missing_source_file_url" in body["checks"][0]["issues"]
    assert "missing_bbox_list" in body["checks"][0]["issues"]
    assert "page_anchor_not_found" in body["checks"][0]["issues"]


def test_graph_subgraph_route(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.post("/graph/subgraph", json={"case_id": 116, "center_entity_id": 11, "depth": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == 116
    assert body["nodes"][0]["label"] == "晨光煤矿"


def test_page_anchors_route(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.get("/files/page-anchors", params={"file_id": 101, "page_no": 2, "chunk_id": "chunk-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["anchors"][0]["chunk_id"] == "chunk-1"
    assert body["anchors"][0]["source_page_id"] == 9001
    assert body["anchors"][0]["page_image_ref"] == EXPECTED_PAGE_IMAGE_URL
    assert body["source_file_url"] == EXPECTED_SOURCE_FILE_URL
    assert body["anchors"][0]["source_file_url"] == EXPECTED_SOURCE_FILE_URL
    # issue #6: 顶层与 anchors[] 都要带原始文件名，供前端「文件名 — 第 N 页」展示
    assert body["file_name"] == EXPECTED_FILE_NAME
    assert body["anchors"][0]["file_name"] == EXPECTED_FILE_NAME
    # issue #7: content_type 透传，前端据此切换渲染模式
    assert body["content_type"] == EXPECTED_CONTENT_TYPE
    assert body["anchors"][0]["content_type"] == EXPECTED_CONTENT_TYPE


class _TextFileKGService:
    """纯文本源文件（.txt）：无页面排版，bbox/page_image 恒空，仅靠 content_type 区分渲染模式。"""

    def fetch_page_anchors(self, *, file_id, page_no, chunk_id=None):
        assert file_id == 31
        return [
            {
                "chunk_id": "txt-chunk-1",
                "quote_text": "债务人：钟山区老鹰山镇晨光煤矿",
                "bbox_list": [],
                "source_page_id": 7001,
                "page_image_ref": "",
                "page_width": 0,
                "page_height": 0,
                "storage_ref": SOURCE_FILE_STORAGE_REF,
                "file_name": "operator_smoke_sample.txt",
                "content_type": "text/plain",
            }
        ]

    def get_source_file_case_id(self, file_id):
        assert file_id == 31
        return 116


def test_page_anchors_route_text_file_marks_content_type(monkeypatch):
    """issue #7: .txt 文件 bbox/page_image 天然为空，但 content_type 必须给出，前端据此降级为纯文本渲染。"""
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: _TextFileKGService(),
    )
    client = TestClient(create_app())
    response = client.get("/files/page-anchors", params={"file_id": 31, "page_no": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["content_type"] == "text/plain"
    assert body["page_width"] == 0
    assert body["page_height"] == 0
    assert body["page_image_ref"] == ""
    assert body["anchors"][0]["content_type"] == "text/plain"
    assert body["anchors"][0]["bbox_list"] == []


class _EmptyResolveKGService:
    """resolve 路径解析不到 claim，用于覆盖 resolution_status 的非 ok 态。"""

    def __init__(self, ref_exists):
        self._ref_exists = ref_exists

    def resolve_claim_by_citation(self, *, case_id, report_ref, citation_id):
        return {}

    def report_ref_exists(self, *, case_id, report_ref):
        return self._ref_exists

    def fetch_claim_evidence(self, claim_id, *, case_id=None):
        return []


class _NoEvidenceKGService(FakeKGService):
    def fetch_claim_evidence(self, claim_id, *, case_id=None):
        assert case_id == 116
        return []


def test_resolve_evidence_ref_not_found(monkeypatch):
    # 前端按 final_report:{thread_id} 自拼出库里不存在的 ref → ref_not_found
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: _EmptyResolveKGService(ref_exists=False),
    )
    client = TestClient(create_app())
    response = client.post(
        "/evidence/resolve",
        json={"case_id": 116, "report_ref": "final_report:bogus", "citation_id": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == 0
    assert body["evidences"] == []
    assert body["resolution_status"] == "ref_not_found"


def test_resolve_evidence_citation_not_found(monkeypatch):
    # report_ref 有效但该 citation 不在报告里 → citation_not_found
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: _EmptyResolveKGService(ref_exists=True),
    )
    client = TestClient(create_app())
    response = client.post(
        "/evidence/resolve",
        json={"case_id": 116, "report_ref": "final_report:demo", "citation_id": "99"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == 0
    assert body["resolution_status"] == "citation_not_found"


def test_resolve_evidence_no_evidence(monkeypatch):
    # claim 有效但暂无证据 → no_evidence（合法的空，区别于 ref 拼错）
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: _NoEvidenceKGService(),
    )
    client = TestClient(create_app())
    response = client.post("/evidence/resolve", json={"case_id": 116, "claim_id": 31})
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == 31
    assert body["evidences"] == []
    assert body["resolution_status"] == "no_evidence"


def test_list_case_entities_route(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.api.routes_graph.get_kg_service",
        lambda: FakeKGService(),
    )
    client = TestClient(create_app())
    response = client.get("/graph/cases/116/entities")
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == 116
    # 按 degree 降序，第一个是连接度最高的实体
    assert body["entities"][0]["entity_id"] == 18
    assert body["entities"][0]["degree"] == 22
    assert body["entities"][0]["label"] == "晨光煤矿"
    assert body["entities"][1]["entity_id"] == 2
