"""Domain-neutral chunk retrieval over the shared PostgreSQL + pgvector store.

The service owns only retrieval mechanics.  A business domain supplies the
project ID, embedding and query wording; no NPA or annual-audit ontology is
imported here.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row

from ai_hunter.platform_core import validate_domain

from ..settings import Settings, get_settings


def _embedding_literal(values: Sequence[float], *, dimension: int) -> str:
    if len(values) != dimension:
        raise ValueError(f"embedding dimension must be {dimension}")
    normalized: list[str] = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("embedding contains a non-finite value")
        normalized.append(format(number, ".9g"))
    return "[" + ",".join(normalized) + "]"


def _normalize_hit(row: dict[str, Any], *, domain_code: str, project_id: int) -> dict[str, Any]:
    return {
        "domain_code": domain_code,
        "project_id": project_id,
        "chunk_id": str(row.get("chunk_id") or ""),
        "file_id": int(row.get("file_id") or 0),
        "page_id": int(row.get("page_id") or 0),
        "page_no": int(row.get("page_no") or 0),
        "file_name": str(row.get("file_name") or ""),
        "content_type": str(row.get("content_type") or ""),
        "storage_ref": str(row.get("storage_ref") or ""),
        "chunk_text": str(row.get("chunk_text") or ""),
        "anchor_text": str(row.get("anchor_text") or ""),
        "bbox_list": row.get("bbox_list") or [],
        "similarity": float(row.get("similarity") or 0),
    }


def search_source_chunks_by_text(
    *,
    project_id: int,
    query: str,
    limit: int = 8,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return project-scoped text hits without relying on an embedding service."""

    resolved = settings or get_settings()
    domain_code = validate_domain(resolved.business_domain)
    normalized_query = str(query or "").strip()
    if project_id <= 0 or not normalized_query:
        return []
    pattern = f"%{normalized_query[:300]}%"
    with psycopg.connect(resolved.postgres_checkpointer_dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT sc.chunk_id, sc.file_id, sc.page_id, sc.page_no,
                   sc.chunk_text, sc.anchor_text, sc.bbox_list,
                   sf.file_name, sf.content_type, sf.storage_ref,
                   1.0 AS similarity
            FROM public.source_chunk sc
            JOIN public.source_file sf ON sf.id = sc.file_id
            WHERE sc.case_id = %s
              AND sf.status = 'active'
              AND (sc.chunk_text ILIKE %s OR sc.anchor_text ILIKE %s)
            ORDER BY sc.page_no, sc.chunk_index
            LIMIT %s
            """,
            (project_id, pattern, pattern, max(1, min(int(limit), 50))),
        ).fetchall()
    return [_normalize_hit(dict(row), domain_code=domain_code, project_id=project_id) for row in rows]


def search_source_chunks_by_embedding(
    *,
    project_id: int,
    embedding: Sequence[float],
    limit: int = 8,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return project-scoped nearest chunks using pgvector cosine distance."""

    resolved = settings or get_settings()
    domain_code = validate_domain(resolved.business_domain)
    if project_id <= 0:
        return []
    vector = _embedding_literal(embedding, dimension=int(resolved.annual_embedding_dimension))
    with psycopg.connect(resolved.postgres_checkpointer_dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT sc.chunk_id, sc.file_id, sc.page_id, sc.page_no,
                   sc.chunk_text, sc.anchor_text, sc.bbox_list,
                   sf.file_name, sf.content_type, sf.storage_ref,
                   1 - (sc.embedding <=> %s::vector) AS similarity
            FROM public.source_chunk sc
            JOIN public.source_file sf ON sf.id = sc.file_id
            WHERE sc.case_id = %s
              AND sf.status = 'active'
              AND sc.embedding IS NOT NULL
            ORDER BY sc.embedding <=> %s::vector
            LIMIT %s
            """,
            (vector, project_id, vector, max(1, min(int(limit), 50))),
        ).fetchall()
    return [_normalize_hit(dict(row), domain_code=domain_code, project_id=project_id) for row in rows]


def search_source_chunks(
    *,
    project_id: int,
    query: str = "",
    embedding: Sequence[float] | None = None,
    limit: int = 8,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Use vector retrieval when supplied, otherwise deterministic text retrieval."""

    if embedding:
        return search_source_chunks_by_embedding(
            project_id=project_id,
            embedding=embedding,
            limit=limit,
            settings=settings,
        )
    return search_source_chunks_by_text(
        project_id=project_id,
        query=query,
        limit=limit,
        settings=settings,
    )


__all__ = [
    "search_source_chunks",
    "search_source_chunks_by_embedding",
    "search_source_chunks_by_text",
]
