"""Accountant-facing evidence candidates for one annual-audit engagement.

The API built on this service exposes stable source and locator choices.  It
keeps database identifiers out of free-form user input while preserving the
canonical evidence-reference shape used by execution and review services.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .storage import postgres_connection


MAX_CANDIDATES = 200
MAX_LOCATORS_PER_FILE = 5


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def infer_source_quality(file_name: str) -> dict[str, str]:
    """Return a conservative provenance hint from the original file name.

    This is intentionally a hint, never an evidence-acceptance decision.  A
    reviewer still decides whether the selected material is appropriate for
    the procedure being documented.
    """

    normalized = str(file_name or "").strip().lower()
    if any(marker in normalized for marker in ("模板", "模版", "template", "样表")):
        return {
            "code": "template",
            "label": "模板",
            "reason": "模板用于生成或参考，不能作为本项目审计证据。",
        }
    if any(marker in normalized for marker in ("派生", "拆分", "重排", "联调", "演示数据")):
        return {
            "code": "derived",
            "label": "派生资料",
            "reason": "文件名表明资料可能由其他底稿或数据重组而来，需要核验原始来源。",
        }
    if any(marker in normalized for marker in ("审计底稿", "工作底稿", "审计小结", "复核表")):
        return {
            "code": "auditor_generated",
            "label": "审计人员形成",
            "reason": "底稿记录程序和结论，但不能替代其引用的原始资料或外部证据。",
        }
    if "回函" in normalized:
        return {
            "code": "external_candidate",
            "label": "外部证据候选",
            "reason": "仍需核验回函是否由审计人员控制的渠道直接取得。",
        }
    return {
        "code": "unverified_source",
        "label": "来源待核验",
        "reason": "系统已接收文件，审计人员仍需确认来源、期间、完整性和适用性。",
    }


def _locator_from_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = _json_value(row.get("metadata"), {})
    metadata = metadata if isinstance(metadata, dict) else {}
    source_locator: dict[str, Any] = {
        "source_file_id": int(row["file_id"]),
        "source_page_id": int(row["source_page_id"]),
        "page_no": int(row["page_no"]),
    }
    for key in ("sheet_name", "cell_range", "row_number", "row_start"):
        value = metadata.get(key)
        if value not in (None, ""):
            source_locator[key] = value
    anchor = str(row.get("anchor_text") or row.get("chunk_text") or "").strip()
    return {
        "source_file_id": int(row["file_id"]),
        "source_page_id": int(row["source_page_id"]),
        "source_chunk_id": str(row.get("source_chunk_id") or ""),
        "source_locator": source_locator,
        "label": anchor[:160] or f"第 {source_locator['page_no']} 页",
    }


def list_evidence_candidates(
    engagement_id: int,
    *,
    query: str = "",
    limit: int = 100,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """List source files and ready-made locators owned by an engagement."""

    if int(engagement_id) <= 0:
        raise ValueError("engagement_id 必须为正整数")
    normalized_query = str(query or "").strip()
    normalized_limit = min(max(int(limit or 100), 1), MAX_CANDIDATES)
    wildcard = f"%{normalized_query}%"
    resolved = settings or get_settings()

    with postgres_connection(resolved) as connection:
        file_rows = connection.execute(
            """
            SELECT
              sf.id, sf.file_name, sf.content_type, sf.file_size_bytes,
              sf.created_at, COUNT(DISTINCT sp.id) AS page_count,
              COUNT(DISTINCT sc.id) AS chunk_count,
              MIN(sp.id) AS first_page_id, MIN(sp.page_no) AS first_page_no,
              COALESCE(
                jsonb_agg(DISTINCT
                  jsonb_build_object(
                    'code', category.category_code,
                    'name', catalog.name,
                    'match_source', category.match_source,
                    'confidence', category.confidence
                  )
                ) FILTER (WHERE category.category_code IS NOT NULL),
                '[]'::jsonb
              ) AS categories
            FROM public.source_file sf
            LEFT JOIN public.source_page sp ON sp.file_id = sf.id
            LEFT JOIN public.source_chunk sc ON sc.file_id = sf.id
            LEFT JOIN public.source_file_doc_category category ON category.file_id = sf.id
            LEFT JOIN public.doc_category_catalog catalog ON catalog.code = category.category_code
            WHERE sf.case_id = %s
              AND sf.status = 'active'
              AND (
                %s = '' OR sf.file_name ILIKE %s OR
                EXISTS (
                  SELECT 1
                  FROM public.source_file_doc_category searched_category
                  JOIN public.doc_category_catalog searched_catalog
                    ON searched_catalog.code = searched_category.category_code
                  WHERE searched_category.file_id = sf.id
                    AND (searched_category.category_code ILIKE %s OR searched_catalog.name ILIKE %s)
                )
              )
            GROUP BY sf.id, sf.file_name, sf.content_type, sf.file_size_bytes, sf.created_at
            ORDER BY sf.created_at DESC, sf.id DESC
            LIMIT %s
            """,
            (
                engagement_id,
                normalized_query,
                wildcard,
                wildcard,
                wildcard,
                normalized_limit,
            ),
        ).fetchall()
        file_ids = [int(row["id"]) for row in file_rows]
        locator_rows = (
            connection.execute(
                """
                WITH ranked AS (
                  SELECT
                    sc.file_id, sc.chunk_id AS source_chunk_id,
                    sc.page_id AS source_page_id, sc.page_no,
                    sc.anchor_text, sc.chunk_text, sc.metadata,
                    row_number() OVER (
                      PARTITION BY sc.file_id
                      ORDER BY sc.page_no, sc.chunk_index, sc.id
                    ) AS locator_rank
                  FROM public.source_chunk sc
                  WHERE sc.case_id = %s AND sc.file_id = ANY(%s)
                )
                SELECT * FROM ranked
                WHERE locator_rank <= %s
                ORDER BY file_id, locator_rank
                """,
                (engagement_id, file_ids, MAX_LOCATORS_PER_FILE),
            ).fetchall()
            if file_ids
            else []
        )

    locators_by_file: dict[int, list[dict[str, Any]]] = {}
    for raw_row in locator_rows:
        row = dict(raw_row)
        locators_by_file.setdefault(int(row["file_id"]), []).append(_locator_from_row(row))

    candidates: list[dict[str, Any]] = []
    for raw_row in file_rows:
        row = dict(raw_row)
        file_id = int(row["id"])
        locator_options = locators_by_file.get(file_id, [])
        if not locator_options and row.get("first_page_id"):
            page_no = int(row.get("first_page_no") or 1)
            locator_options = [
                {
                    "source_file_id": file_id,
                    "source_page_id": int(row["first_page_id"]),
                    "source_locator": {
                        "source_file_id": file_id,
                        "source_page_id": int(row["first_page_id"]),
                        "page_no": page_no,
                    },
                    "label": f"第 {page_no} 页",
                }
            ]
        categories = _json_value(row.get("categories"), [])
        if not isinstance(categories, list):
            categories = []
        candidates.append(
            {
                "source_file_id": file_id,
                "file_name": str(row.get("file_name") or ""),
                "content_type": str(row.get("content_type") or ""),
                "file_size_bytes": int(row.get("file_size_bytes") or 0),
                "created_at": _json_safe(row.get("created_at")),
                "page_count": int(row.get("page_count") or 0),
                "chunk_count": int(row.get("chunk_count") or 0),
                "categories": [
                    {key: _json_safe(value) for key, value in category.items()}
                    for category in categories
                    if isinstance(category, dict)
                ],
                "source_quality": infer_source_quality(str(row.get("file_name") or "")),
                "locator_options": locator_options,
                "default_reference": locator_options[0] if locator_options else None,
                "needs_manual_locator": not locator_options,
            }
        )
    return {
        "case_id": engagement_id,
        "query": normalized_query,
        "items": candidates,
        "total": len(candidates),
        "limit": normalized_limit,
    }


__all__ = ["infer_source_quality", "list_evidence_candidates"]
