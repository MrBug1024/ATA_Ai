from ai_hunter.app.services.knowledge_api import KnowledgeAPIClient


def test_knowledge_client_builds_result_shape_without_db_roundtrip():
    client = KnowledgeAPIClient(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="secret",
        dbname="cpwsdata",
        default_limit=5,
    )
    assert client.default_limit == 5


def test_semantic_query_uses_qdrant_order_and_postgres_metadata(monkeypatch):
    client = KnowledgeAPIClient(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="secret",
        dbname="cpwsdata",
        qdrant_base_url="http://qdrant:6333",
    )
    monkeypatch.setattr(client, "_embed_query", lambda _question: [0.1, 0.2])
    monkeypatch.setattr(
        client,
        "_query_qdrant",
        lambda _embedding, _limit: [
            {"section_id": 20, "score": 0.95},
            {"section_id": 10, "score": 0.90},
        ],
    )
    monkeypatch.setattr(
        client,
        "_fetch_sections_by_ids",
        lambda _section_ids: {
            10: {"case_id": 1, "title": "first"},
            20: {"case_id": 2, "title": "second"},
        },
    )

    result = client._semantic_query("裁判文书", 2)

    assert result is not None
    assert result["query_mode"] == "hybrid_semantic"
    assert [item["title"] for item in result["results"]] == ["second", "first"]
    assert [item["score"] for item in result["results"]] == [0.95, 0.90]


def test_semantic_query_safely_falls_back_when_qdrant_has_no_match(monkeypatch):
    client = KnowledgeAPIClient(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="secret",
        dbname="cpwsdata",
        qdrant_base_url="http://qdrant:6333",
    )
    monkeypatch.setattr(client, "_embed_query", lambda _question: [0.1, 0.2])
    monkeypatch.setattr(client, "_query_qdrant", lambda _embedding, _limit: [])

    assert client._semantic_query("裁判文书", 2) is None


def test_qdrant_query_parses_section_payload_and_skips_invalid_points(monkeypatch):
    client = KnowledgeAPIClient(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="secret",
        dbname="cpwsdata",
        qdrant_base_url="http://qdrant:6333",
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "result": {
                    "points": [
                        {"score": 0.8, "payload": {"section_id": "12"}},
                        {"score": 0.7, "payload": {"case_id": 99}},
                    ]
                }
            }

    monkeypatch.setattr("ai_hunter.app.services.knowledge_api.httpx.post", lambda *args, **kwargs: Response())

    assert client._query_qdrant([0.1, 0.2], 2) == [{"section_id": 12, "score": 0.8}]
