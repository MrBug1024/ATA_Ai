import pytest

from ai_hunter.app.graph.context_loader import resolve_aggregated_text
from ai_hunter.app.graph.heavy_state import get_heavy_payload
from ai_hunter.app.subgraphs.ingest_graph import build_ingest_graph, infer_debtor_name


class FakeKGService:
    def create_extraction_run(self, **kwargs):
        return 501

    def complete_extraction_run(self, run_id, status="completed"):
        return None

    def fail_extraction_run(self, run_id, error_message):
        return None

    def insert_source_files(self, rows):
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
        return [
            {
                "id": index + 101,
                "file_id": row["file_id"],
                "page_no": row["page_no"],
            }
            for index, row in enumerate(rows)
        ]

    def insert_source_chunks(self, rows):
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

    def upsert_entities(self, *, case_id, rows):
        return [
            {
                "id": index + 2001,
                "case_id": case_id,
                "entity_key": row["entity_key"],
                "canonical_name": row["canonical_name"],
            }
            for index, row in enumerate(rows)
        ]

    def upsert_relations(self, *, case_id, rows):
        return [
            {
                "id": index + 3001,
                "case_id": case_id,
                "relation_key": row["relation_key"],
                "from_entity_id": row["from_entity_id"],
                "to_entity_id": row["to_entity_id"],
            }
            for index, row in enumerate(rows)
        ]

    def insert_claims(self, *, case_id, extraction_run_id, rows, **kwargs):
        return [
            {
                "id": index + 4001,
                "claim_type": row["claim_type"],
                "claim_text": row["claim_text"],
            }
            for index, row in enumerate(rows)
        ]

    def insert_evidence_links(self, rows):
        return [
            {
                "id": index + 5001,
                "claim_id": row["claim_id"],
                "chunk_id": row["chunk_id"],
            }
            for index, row in enumerate(rows)
        ]

    def list_active_claim_summaries(self, case_id):
        return []

    def create_material_event(self, **kwargs):
        return {"id": 7001, **kwargs}

    def insert_reconciliation_items(self, rows):
        return rows

    def mark_reconciliation_items_superseded(self, ids, *, resolved_by_event_id=None):
        return None

    def list_unresolved_graph_items(self, case_id):
        return []

    def create_graph_summary(self, **kwargs):
        return {"id": 8001, **kwargs}

    def fetch_active_entities(self, **kwargs):
        return []

    def fetch_active_relations(self, **kwargs):
        return []

    def fetch_unresolved_graph_items(self, **kwargs):
        return {"unresolved_relations": [], "unresolved_claims": []}

    def fetch_source_chunks_by_ids(self, **kwargs):
        return []

    def fetch_candidate_conflicts_by_chunks(self, **kwargs):
        return {"candidates": []}

    def mark_claims_superseded(self, claim_ids):
        return None

    def mark_relations_superseded(self, relation_ids):
        return None

    def insert_reconciliation_ledger(self, *, case_id, rows):
        return rows

    def fetch_case_graph_snapshot(self, case_id):
        return {}

    def insert_unresolved_graph_items(self, **kwargs):
        return {
            "unresolved_relations": kwargs.get("relation_rows", []),
            "unresolved_claims": kwargs.get("claim_rows", []),
        }

    def mark_unresolved_items_resolved(self, rows):
        return None


class FakeAuditAPIClient:
    def parse_document_sync(self, payload):
        return {
            "case_id": 0,
            "debtor_id": 0,
            "debtor_name": payload.get("debtor_name") or "",
            "categories_found": [],
            "total_segments": 0,
            "unclassified_segments": 0,
            "records_inserted": 0,
            "enterprise": {},
            "details": [],
            "message": "mock parse ok",
        }


class FakeDocCategoryAPIClient:
    def get_doc_categories_sync(self):
        return {"categories": []}

    def get_case_doc_categories_sync(self, case_id):
        return {"case_id": case_id, "missing_categories": [], "uploaded_categories": []}

    def validate_doc_category_sync(self, payload):
        return {"ok": True, "doc_category": payload.get("doc_category", ""), "warnings": []}


class FakeHeavyStateSettings:
    redis_url = ""
    heavy_payload_enable_postgres = False
    heavy_payload_ttl_seconds = 3600


def _patch_load_chunks_dependencies(monkeypatch):
    fake_kg = FakeKGService()
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.load_chunks.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.persist_graph.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.reconcile_graph_delta.get_kg_service",
        lambda: fake_kg,
    )
    monkeypatch.setattr(
        "ai_hunter.app.subgraphs.ingest_graph.get_audit_api_client",
        lambda: FakeAuditAPIClient(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.subgraphs.ingest_graph.get_doc_category_api_client",
        lambda: FakeDocCategoryAPIClient(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.heavy_state.get_settings",
        lambda: FakeHeavyStateSettings(),
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.heavy_state._get_redis_client",
        lambda: None,
    )
    monkeypatch.setattr(
        "ai_hunter.app.graph.nodes.extract_entities_relations.get_settings",
        lambda: type(
            "FakeSettings",
            (),
            {
                "get_llm_config": lambda self, role: {
                    "provider": "openai",
                    "api_key": "",
                    "base_url": "",
                    "model": "offline-test",
                }
            },
        )(),
    )
    return fake_kg


def test_ingest_graph_merges_uploaded_content(monkeypatch):
    _patch_load_chunks_dependencies(monkeypatch)
    graph = build_ingest_graph()
    result = graph.invoke(
        {
            "current_case_id": 116,
            "uploaded_files": [
                {"name": "a.txt", "extension": ".txt", "type": "document", "content": "hello"},
                {"name": "b.csv", "extension": ".csv", "type": "document", "content": "c1,c2\n1,2"},
                {"name": "c.md", "extension": ".md", "type": "document", "content": "world"},
            ]
        }
    )
    aggregated_text = resolve_aggregated_text(result)
    assert "TXT文件提取结果" in aggregated_text
    assert "CSV文件提取结果" in aggregated_text
    assert "Markdown文件提取结果" in aggregated_text
    assert result["aggregated_text"] == ""
    assert result["aggregated_text_ref"].startswith("aggregated_text:")


def test_ingest_graph_runs_ocr_for_document_and_image(monkeypatch):
    class FakeOCRService:
        def parse_pdf_with_layout_sync(self, **kwargs):
            assert kwargs["file_url"] == "https://example.com/a.docx"
            return {
                "text": "document-ocr-result",
                "message": "success",
                "pages": [{"width": 1654, "height": 2339}],
                "blocks": [
                    {
                        "type": "text",
                        "text": "document-ocr-result",
                        "text_level": 1,
                        "bbox": [10, 20, 210, 60],
                        "page_idx": 0,
                    }
                ],
                "page_width": 1654,
                "page_height": 2339,
                "raw_response": {},
            }

        def parse_image_with_layout_sync(self, **kwargs):
            assert kwargs["file_name"] == "b.png"
            return {
                "text": "image-ocr-result",
                "message": "success",
                "pages": [{"width": 1000, "height": 800}],
                "blocks": [
                    {
                        "type": "text",
                        "text": "image-ocr-result",
                        "text_level": 1,
                        "bbox": [5, 5, 105, 55],
                        "page_idx": 0,
                    }
                ],
                "page_width": 1000,
                "page_height": 800,
                "raw_response": {},
            }

    monkeypatch.setattr(
        "ai_hunter.app.subgraphs.ingest_graph.get_ocr_service",
        lambda: FakeOCRService(),
    )
    _patch_load_chunks_dependencies(monkeypatch)

    graph = build_ingest_graph()
    result = graph.invoke(
        {
            "current_case_id": 116,
            "uploaded_files": [
                {
                    "name": "a.docx",
                    "extension": ".docx",
                    "type": "document",
                    "url": "https://example.com/a.docx",
                },
                {
                    "name": "b.png",
                    "extension": ".png",
                    "type": "image",
                    "url": "https://example.com/b.png",
                },
            ]
        }
    )

    aggregated_text = resolve_aggregated_text(result)
    assert "文档OCR提取结果" in aggregated_text
    assert "document-ocr-result" in aggregated_text
    assert "图片OCR提取结果" in aggregated_text
    assert "image-ocr-result" in aggregated_text
    ingest_payload = get_heavy_payload(result["ingest_payload_ref"])
    assert len(ingest_payload["ocr_layout_results"]) == 2


def test_ingest_graph_raises_on_ocr_failure(monkeypatch):
    """OCR 失败应让整批入库失败（commit 7fef63e：OCR failure marks upload as failed），
    而不是把错误文本静默写进 aggregated_text。"""
    import pytest

    class FakeOCRService:
        def parse_pdf_with_layout_sync(self, **kwargs):
            return {"text": "", "message": "OCR超时", "pages": [], "blocks": [], "raw_response": {}}

        def parse_image_with_layout_sync(self, **kwargs):
            return {"text": "", "message": "OCR超时", "pages": [], "blocks": [], "raw_response": {}}

    monkeypatch.setattr(
        "ai_hunter.app.subgraphs.ingest_graph.get_ocr_service",
        lambda: FakeOCRService(),
    )
    _patch_load_chunks_dependencies(monkeypatch)

    graph = build_ingest_graph()
    with pytest.raises(RuntimeError) as exc_info:
        graph.invoke(
            {
                "uploaded_files": [
                    {
                        "name": "a.xlsx",
                        "extension": ".xlsx",
                        "type": "document",
                        "url": "https://example.com/a.xlsx",
                    }
                ]
            }
        )

    message = str(exc_info.value)
    assert "OCR 失败" in message
    assert "a.xlsx" in message
    assert "OCR超时" in message


def test_infer_debtor_name_does_not_treat_asset_purchaser_as_debtor():
    result = infer_debtor_name(
        {
            "current_case_id": 116,
            "aggregated_text": (
                "## 文档OCR提取结果\n"
                "关于受让中国中信金融资产管理股份有限公司整体资产的公告\n"
            )
        }
    )

    assert result == {}


def test_infer_debtor_name_rejects_upload_without_case_master_data():
    with pytest.raises(ValueError, match="必须先建案"):
        infer_debtor_name(
            {
                "aggregated_text": "债务人：钟山区老鹰山镇晨光煤矿",
            }
        )

    with pytest.raises(ValueError, match="必须先建案"):
        infer_debtor_name(
            {
                "current_debtor_name": "钟山区老鹰山镇晨光煤矿",
                "aggregated_text": "已由调用方提供名称，但尚未建立案件。",
            }
        )


def test_ingest_graph_builds_kg_summary_when_case_id_available(monkeypatch):
    _patch_load_chunks_dependencies(monkeypatch)

    graph = build_ingest_graph()
    result = graph.invoke(
        {
            "current_case_id": 116,
            "current_debtor_id": 76,
            "current_debtor_name": "钟山区老鹰山镇晨光煤矿",
            "uploaded_files": [
                {
                    "name": "a.txt",
                    "extension": ".txt",
                    "type": "document",
                    "content_type": "text/plain",
                    "content": "钟山区老鹰山镇晨光煤矿进入破产重整程序。",
                    "storage_ref": "minio://ai-hunter-raw/case-116/debtor-76/raw/a.txt",
                }
            ],
        }
    )

    assert result["kg_extraction_run_id"] == 501
    assert result["kg_summary"] == "已构建案件图谱：实体1个，关系1条，断言1条。"
    assert result["kg_subgraph_ref"].startswith("kg_subgraph:")
