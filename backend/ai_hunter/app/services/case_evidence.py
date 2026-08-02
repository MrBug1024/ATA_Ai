"""Read-only selection of evidence anchored in the current case materials."""

from __future__ import annotations

import re
from typing import Any


_GENERIC_EVIDENCE_TERMS = {
    "查看",
    "案件",
    "本案",
    "证据",
    "原文",
    "引用",
    "角标",
    "卷宗",
    "追溯",
}


def evidence_query_terms(query: str) -> set[str]:
    terms: set[str] = set()
    for token in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", query.lower()):
        if token.isdigit():
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            terms.update(token[index : index + 2] for index in range(max(0, len(token) - 1)))
        elif len(token) >= 2:
            terms.add(token)
    return {term for term in terms if term not in _GENERIC_EVIDENCE_TERMS}


def rank_case_evidence(
    trace_items: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Flatten and rank case-bound evidence without consulting external corpora."""
    citation_match = re.search(r"(?:角标|引用|citation|\[)\s*(\d+)\]?", query, re.IGNORECASE)
    claim_match = re.search(r"(?:claim|断言)[编号#\s:]*(\d+)", query, re.IGNORECASE)
    citation_id = citation_match.group(1) if citation_match else ""
    claim_id = int(claim_match.group(1)) if claim_match else 0
    terms = evidence_query_terms(query)
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    order = 0
    for trace in trace_items:
        if not isinstance(trace, dict):
            continue
        for evidence in trace.get("evidences") or []:
            if not isinstance(evidence, dict):
                continue
            item = {
                "citation_id": str(trace.get("citation_id", "") or ""),
                "claim_id": int(trace.get("claim_id", 0) or 0),
                "claim_text": str(trace.get("claim_text", "") or ""),
                "chunk_id": str(evidence.get("chunk_id", "") or ""),
                "file_id": int(evidence.get("file_id", 0) or 0),
                "file_name": str(evidence.get("file_name", "") or ""),
                "page_no": int(evidence.get("page_no", 0) or 0),
                "quote_text": str(evidence.get("quote_text", "") or ""),
                "bbox_list": evidence.get("bbox_list") if isinstance(evidence.get("bbox_list"), list) else [],
                "page_image_ref": str(evidence.get("page_image_ref", "") or ""),
                "source_file_url": str(evidence.get("source_file_url", "") or ""),
                "content_type": str(evidence.get("content_type", "") or ""),
            }
            searchable = " ".join((item["claim_text"], item["file_name"], item["quote_text"])).lower()
            score = sum(1 for term in terms if term in searchable)
            if citation_id and item["citation_id"] == citation_id:
                score += 100
            if claim_id and item["claim_id"] == claim_id:
                score += 100
            ranked.append((score, -order, item))
            order += 1
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item for _score, _order, item in ranked[: max(1, min(limit, 20))]]
