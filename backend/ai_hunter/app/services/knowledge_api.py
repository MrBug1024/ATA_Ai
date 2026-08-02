"""Knowledge retrieval helpers backed by the cpwsdata PostgreSQL database."""

from __future__ import annotations

import re

import httpx
import psycopg

from ..settings import get_settings


class KnowledgeAPIClient:
    """Query the Wenshu corpus directly from PostgreSQL when no HTTP API exists."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
        default_limit: int = 5,
        qdrant_base_url: str | None = None,
        qdrant_collection: str = "case_chunks_000",
        qdrant_api_key: str = "",
        qdrant_timeout_seconds: int = 30,
        embedding_base_url: str | None = None,
        embedding_api_key: str = "",
        embedding_model: str = "embo-01",
        embedding_timeout_seconds: int = 30,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.dbname = dbname
        self.default_limit = default_limit
        self.qdrant_base_url = qdrant_base_url.rstrip("/") if qdrant_base_url else None
        self.qdrant_collection = qdrant_collection
        self.qdrant_api_key = qdrant_api_key
        self.qdrant_timeout_seconds = qdrant_timeout_seconds
        self.embedding_base_url = embedding_base_url.rstrip("/") if embedding_base_url else None
        self.embedding_api_key = embedding_api_key
        self.embedding_model = embedding_model
        self.embedding_timeout_seconds = embedding_timeout_seconds

    def _connect(self):
        return psycopg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.dbname,
        )

    def _extract_keywords(self, question: str) -> list[str]:
        """Pull a few stable Chinese/alnum tokens for candidate filtering."""
        candidates = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", question)
        seen: set[str] = set()
        keywords: list[str] = []
        for token in candidates:
            if token not in seen:
                seen.add(token)
                keywords.append(token)
            if len(keywords) >= 5:
                break
        return keywords or [question.strip()]

    def _embed_query(self, question: str) -> list[float] | None:
        """Generate a query embedding when an embedding provider is configured."""
        if not self.embedding_base_url or not self.embedding_api_key:
            return None

        try:
            endpoint = self.embedding_base_url
            if not endpoint.endswith("/embeddings"):
                endpoint = f"{endpoint}/embeddings"
            response = httpx.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.embedding_api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.embedding_model, "input": question},
                timeout=self.embedding_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            return payload["data"][0]["embedding"]
        except Exception:
            return None

    def _keyword_query(self, question: str, final_limit: int) -> dict:
        """Run a keyword-first retrieval across metadata, sections, and entities."""
        like_term = f"%{question.strip()}%"
        sql = """
        select
            cm.id,
            cm.case_no,
            cm.title,
            cm.doc_type,
            cm.court,
            cm.judge_date,
            cs.section_title,
            left(cs.content, 280) as snippet
        from case_metadata cm
        left join case_sections cs on cs.case_id = cm.id
        where
            cm.title ilike %(like_term)s
            or cs.content ilike %(like_term)s
            or exists (
                select 1
                from case_entities ce
                where ce.case_id = cm.id and ce.name ilike %(like_term)s
            )
        order by cm.judge_date desc nulls last, cm.id desc
        limit %(limit)s
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"like_term": like_term, "limit": final_limit})
                rows = cur.fetchall()

        return {
            "question": question,
            "match_count": len(rows),
            "results": [
                {
                    "case_id": row[0],
                    "case_no": row[1],
                    "title": row[2],
                    "doc_type": row[3],
                    "court": row[4],
                    "judge_date": str(row[5]) if row[5] else None,
                    "section_title": row[6],
                    "snippet": row[7],
                }
                for row in rows
            ],
            "query_mode": "keyword",
            "note": "HTTP knowledge endpoint not found; served directly from cpwsdata.",
        }

    def _query_qdrant(self, embedding: list[float], limit: int) -> list[dict]:
        if not self.qdrant_base_url:
            return []
        headers = {"Content-Type": "application/json"}
        if self.qdrant_api_key:
            headers["api-key"] = self.qdrant_api_key
        try:
            response = httpx.post(
                f"{self.qdrant_base_url}/collections/{self.qdrant_collection}/points/query",
                headers=headers,
                json={
                    "query": embedding,
                    "limit": limit,
                    "with_payload": True,
                    "with_vector": False,
                },
                timeout=self.qdrant_timeout_seconds,
            )
            response.raise_for_status()
            points = response.json().get("result", {}).get("points", [])
        except Exception:
            return []

        matches: list[dict] = []
        for point in points:
            payload = point.get("payload") or {}
            try:
                section_id = int(payload["section_id"])
            except (KeyError, TypeError, ValueError):
                continue
            matches.append({"section_id": section_id, "score": point.get("score")})
        return matches

    def _fetch_sections_by_ids(self, section_ids: list[int]) -> dict[int, dict]:
        if not section_ids:
            return {}
        sql = """
        select
            cs.id,
            cm.id,
            cm.case_no,
            cm.title,
            cm.doc_type,
            cm.court,
            cm.judge_date,
            cs.section_title,
            left(cs.content, 280) as snippet
        from case_sections cs
        join case_metadata cm on cm.id = cs.case_id
        where cs.id = any(%(section_ids)s)
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"section_ids": section_ids})
                rows = cur.fetchall()
        return {
            row[0]: {
                "case_id": row[1],
                "case_no": row[2],
                "title": row[3],
                "doc_type": row[4],
                "court": row[5],
                "judge_date": str(row[6]) if row[6] else None,
                "section_title": row[7],
                "snippet": row[8],
            }
            for row in rows
        }

    def _semantic_query(self, question: str, final_limit: int) -> dict | None:
        """Rank Qdrant sections and hydrate their legal-writ metadata from PostgreSQL."""
        embedding = self._embed_query(question)
        if not embedding:
            return None
        matches = self._query_qdrant(embedding, final_limit)
        if not matches:
            return None
        sections = self._fetch_sections_by_ids([item["section_id"] for item in matches])
        results = []
        for match in matches:
            section = sections.get(match["section_id"])
            if section is not None:
                results.append({**section, "score": match.get("score")})
        if not results:
            return None

        return {
            "question": question,
            "match_count": len(results),
            "results": results,
            "query_mode": "hybrid_semantic",
            "keywords": self._extract_keywords(question),
            "note": "Qdrant cosine ranking with legal-writ metadata hydrated from cpwsdata.",
        }

    def query_wenshu_sync(self, question: str, limit: int | None = None) -> dict:
        """Run dual-mode retrieval: semantic when embeddings work, keyword fallback otherwise."""
        final_limit = limit or self.default_limit
        semantic_result = self._semantic_query(question, final_limit)
        if semantic_result is not None:
            return semantic_result

        keyword_result = self._keyword_query(question, final_limit)
        keyword_result["note"] += " Semantic mode unavailable, fell back to keyword retrieval."
        return keyword_result

    def query_case_legal_writ_sync(
        self,
        *,
        debtor_name: str | None = None,
        q: str | None = None,
        doc_type: str | None = None,
        date_from: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """Best-effort local fallback for case legal-writ retrieval."""
        final_limit = limit or self.default_limit
        if q:
            base_result = self.query_wenshu_sync(q, limit=final_limit)
            results = base_result.get("results", [])
        else:
            patterns = [f"%{debtor_name}%"] if debtor_name else ["%%"]
            sql = """
            select
                cm.id,
                cm.case_no,
                cm.title,
                cm.doc_type,
                cm.court,
                cm.judge_date,
                cs.section_title,
                left(cs.content, 280) as snippet
            from case_metadata cm
            left join case_sections cs on cs.case_id = cm.id
            where exists (
                select 1
                from case_entities ce
                where ce.case_id = cm.id and ce.name ilike any(%(patterns)s)
            )
            and (%(doc_type)s is null or cm.doc_type = %(doc_type)s)
            and (%(date_from)s is null or cm.judge_date >= %(date_from)s::date)
            order by cm.judge_date desc nulls last, cm.id desc
            limit %(limit)s
            """
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql,
                        {
                            "patterns": patterns,
                            "doc_type": doc_type,
                            "date_from": date_from,
                            "limit": final_limit,
                        },
                    )
                    rows = cur.fetchall()
            results = [
                {
                    "case_id": row[0],
                    "case_no": row[1],
                    "title": row[2],
                    "doc_type": row[3],
                    "court": row[4],
                    "judge_date": str(row[5]) if row[5] else None,
                    "section_title": row[6],
                    "snippet": row[7],
                }
                for row in rows
            ]
            base_result = {
                "query_mode": "entity_filter",
                "question": q or debtor_name or "",
                "keywords": [debtor_name] if debtor_name else [],
            }

        if doc_type:
            results = [item for item in results if item.get("doc_type") == doc_type]
        if date_from:
            results = [
                item
                for item in results
                if item.get("judge_date") and item["judge_date"] >= date_from
            ]
        results = results[:final_limit]
        return {
            "case_scope": debtor_name or "unknown",
            "question": base_result.get("question", q or ""),
            "match_count": len(results),
            "results": results,
            "query_mode": f"case_local_{base_result.get('query_mode', 'keyword')}",
            "note": "Local cpwsdata fallback used for legal-writ retrieval.",
        }


def get_knowledge_api_client() -> KnowledgeAPIClient:
    """Build the knowledge client from environment settings."""
    settings = get_settings()
    return KnowledgeAPIClient(
        host=settings.cpws_db_host,
        port=settings.cpws_db_port,
        user=settings.cpws_db_user,
        password=settings.cpws_db_password,
        dbname=settings.cpws_db_name,
        default_limit=settings.cpws_query_limit,
        qdrant_base_url=settings.cpws_qdrant_base_url,
        qdrant_collection=settings.cpws_qdrant_collection,
        qdrant_api_key=settings.cpws_qdrant_api_key,
        qdrant_timeout_seconds=settings.cpws_qdrant_timeout_seconds,
        embedding_base_url=settings.cpws_embedding_base_url,
        embedding_api_key=settings.cpws_embedding_api_key,
        embedding_model=settings.cpws_embedding_model,
        embedding_timeout_seconds=settings.cpws_embedding_timeout_seconds,
    )
