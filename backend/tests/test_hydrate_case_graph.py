from ai_hunter.app.graph.nodes import hydrate_case_graph as hydrate


class _KgService:
    def list_source_upload_batches_by_case(self, case_id, limit=20):
        assert case_id == 7
        assert limit == 20
        return [
            {
                "upload_batch_id": "batch-1",
                "batch_name": "历史底稿",
                "status": "completed",
                "doc_category": "audit_workpapers",
                "records_inserted": 0,
            }
        ]

    def fetch_source_upload_batch(self, upload_batch_id):
        assert upload_batch_id == "batch-1"
        return {
            "files": [
                {
                    "file_name": "底稿.xlsx",
                    "file_type": ".xlsx",
                    "page_count": 296,
                    "chunk_count": 386,
                }
            ]
        }


def test_existing_graph_ref_still_hydrates_material_sources(monkeypatch):
    monkeypatch.setattr(hydrate, "get_kg_service", lambda: _KgService())

    result = hydrate.hydrate_case_graph_context(
        {"current_case_id": 7, "kg_subgraph_ref": "kg_subgraph:existing"}
    )

    assert result["case_material_sources"] == [
        {
            "upload_batch_id": "batch-1",
            "batch_name": "历史底稿",
            "status": "completed",
            "doc_category": "audit_workpapers",
            "records_inserted": 0,
            "file_name": "底稿.xlsx",
            "file_type": ".xlsx",
            "page_count": 296,
            "chunk_count": 386,
        }
    ]
