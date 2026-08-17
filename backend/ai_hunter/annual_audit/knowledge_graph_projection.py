"""Project deterministic annual-audit findings into the platform graph.

The annual-audit MySQL records remain the authoritative audit facts.  This
module creates a traceable graph projection only for findings that already
have a canonical platform evidence anchor.  It deliberately does not infer
entities, relationships, or citations from similar-looking text.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from ai_hunter.app.services.graph_identity import (
    build_entity_key,
    build_relation_key,
    normalize_entity_name,
)
from ai_hunter.app.services.kg_service import get_kg_service

from .evidence_service import _evidence_item


LOGGER = logging.getLogger(__name__)

MAX_PROJECTED_FINDINGS = 20


def annual_finding_key(finding: dict[str, Any]) -> str:
    """Return a stable identity for one deterministic rule result.

    The key intentionally excludes the MySQL row ID and analysis-run ID.  A
    recomputation with the exact same rule result reuses the graph claim,
    while changed evidence, amount, conclusion, or risk level becomes a new
    projection.
    """

    references: list[dict[str, Any]] = []
    for reference in finding.get("evidence_refs") or []:
        if not isinstance(reference, dict):
            continue
        locator = reference.get("source_locator")
        if not isinstance(locator, dict):
            continue
        references.append(
            {
                "chunk_id": str(locator.get("source_chunk_id") or ""),
                "file_id": int(locator.get("source_file_id") or 0),
                "page_id": int(locator.get("source_page_id") or 0),
                "page_no": int(locator.get("page_no") or 0),
                "sheet_name": str(locator.get("sheet_name") or ""),
                "row_start": int(locator.get("row_start") or locator.get("row_number") or 0),
                "row_end": int(locator.get("row_end") or locator.get("row_number") or 0),
                "cell_range": str(locator.get("cell_range") or ""),
            }
        )
    payload = {
        "finding_type": str(finding.get("finding_type") or ""),
        "risk_level": str(finding.get("risk_level") or ""),
        "title": str(finding.get("title") or ""),
        "description": str(finding.get("description") or ""),
        "amount": str(finding.get("amount") or ""),
        "references": sorted(
            references,
            key=lambda item: (
                item["chunk_id"],
                item["file_id"],
                item["page_id"],
                item["sheet_name"],
                item["row_start"],
            ),
        ),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def project_annual_findings_to_knowledge_graph(
    *,
    case_id: int,
    entity_name: str,
    findings: list[dict[str, Any]],
    analysis_rules_version: str = "",
    kg_service: Any | None = None,
) -> dict[str, Any]:
    """Persist graph mirrors for bound rule findings and return report traces.

    A failed projection never makes an annual report fail.  The caller can
    still render the authoritative deterministic finding without an inline
    citation, and the evidence coverage gate remains blocked until canonical
    binding is available.
    """

    candidates = _build_candidates(findings)
    if not candidates or case_id <= 0:
        return {
            "trace_by_finding_key": {},
            "projected_count": 0,
            "unprojected_count": len(findings),
        }

    service = kg_service or get_kg_service()
    try:
        return _persist_projection(
            service=service,
            case_id=case_id,
            entity_name=entity_name,
            candidates=candidates,
            analysis_rules_version=analysis_rules_version,
        )
    except Exception:
        LOGGER.exception("annual_finding_graph_projection_failed case_id=%s", case_id)
        return {
            "trace_by_finding_key": {},
            "projected_count": 0,
            "unprojected_count": len(findings),
        }


def _build_candidates(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for finding in findings[:MAX_PROJECTED_FINDINGS]:
        if not isinstance(finding, dict):
            continue
        evidences = _bound_evidences(finding)
        if not evidences:
            continue
        finding_key = annual_finding_key(finding)
        title = str(finding.get("title") or "").strip()
        description = str(finding.get("description") or "").strip()
        claim_text = "：".join(part for part in (title, description) if part)
        if not claim_text:
            continue
        candidates.append(
            {
                "finding": finding,
                "finding_key": finding_key,
                "claim_text": claim_text,
                "evidences": evidences,
            }
        )
    return candidates


def _bound_evidences(finding: dict[str, Any]) -> list[dict[str, Any]]:
    evidences: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    for ordinal, reference in enumerate(finding.get("evidence_refs") or [], start=1):
        if not isinstance(reference, dict):
            continue
        evidence = _evidence_item(reference, ordinal)
        if evidence is None or not _is_bound_evidence(evidence):
            continue
        chunk_id = str(evidence.get("chunk_id") or "")
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        evidences.append(evidence)
    return evidences


def _is_bound_evidence(evidence: dict[str, Any]) -> bool:
    return bool(
        str(evidence.get("chunk_id") or "")
        and int(evidence.get("file_id") or 0) > 0
        and int(evidence.get("source_page_id") or 0) > 0
    )


def _persist_projection(
    *,
    service: Any,
    case_id: int,
    entity_name: str,
    candidates: list[dict[str, Any]],
    analysis_rules_version: str,
) -> dict[str, Any]:
    normalized_entity_name = normalize_entity_name(entity_name) or f"年审项目{case_id}"
    audited_entity_key = build_entity_key(
        case_id=case_id,
        entity_type="company",
        normalized_name=normalized_entity_name,
    )
    entity_rows = [
        {
            "entity_key": audited_entity_key,
            "entity_type": "company",
            "canonical_name": entity_name or normalized_entity_name,
            "aliases": [],
            "normalized_name": normalized_entity_name,
            "attributes": {
                "domain": "annual_audit",
                "role": "audited_entity",
                "engagement_id": case_id,
            },
            "first_seen_chunk_id": str(candidates[0]["evidences"][0]["chunk_id"]),
            "confidence": 1.0,
            "source_count": len(candidates),
            "human_verified": False,
            "status": "active",
        }
    ]
    for candidate in candidates:
        finding = candidate["finding"]
        entity_rows.append(
            {
                "entity_key": _finding_entity_key(case_id, candidate["finding_key"]),
                "entity_type": "audit_finding",
                "canonical_name": str(finding.get("title") or "待核查事项"),
                "aliases": [],
                "normalized_name": normalize_entity_name(str(finding.get("title") or "")),
                "attributes": {
                    "domain": "annual_audit",
                    "role": "deterministic_finding",
                    "annual_finding_key": candidate["finding_key"],
                    "annual_finding_id": int(finding.get("finding_id") or 0),
                    "finding_type": str(finding.get("finding_type") or ""),
                    "risk_level": str(finding.get("risk_level") or ""),
                    "analysis_run_id": int(finding.get("analysis_run_id") or 0),
                },
                "first_seen_chunk_id": str(candidate["evidences"][0]["chunk_id"]),
                "confidence": 1.0,
                "source_count": len(candidate["evidences"]),
                "human_verified": False,
                "status": "active",
            }
        )

    persisted_entities = service.upsert_entities(case_id=case_id, rows=entity_rows)
    entity_ids = _returned_ids_by_key(entity_rows, persisted_entities, key_name="entity_key")
    audited_entity_id = entity_ids.get(audited_entity_key, 0)
    if audited_entity_id <= 0:
        raise ValueError("annual audited entity projection was not persisted")

    relation_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        finding = candidate["finding"]
        finding_entity_key = _finding_entity_key(case_id, candidate["finding_key"])
        finding_entity_id = entity_ids.get(finding_entity_key, 0)
        if finding_entity_id <= 0:
            raise ValueError("annual finding entity projection was not persisted")
        relation_label = "存在审计风险事项"
        relation_rows.append(
            {
                "relation_key": build_relation_key(
                    case_id=case_id,
                    relation_type="audit_finding",
                    from_entity_key=audited_entity_key,
                    to_entity_key=finding_entity_key,
                    relation_label=relation_label,
                ),
                "from_entity_id": audited_entity_id,
                "to_entity_id": finding_entity_id,
                "relation_type": "audit_finding",
                "relation_label": relation_label,
                "direction": "directed",
                "amount": finding.get("amount"),
                "amount_currency": "CNY",
                "event_date": None,
                "attributes": {
                    "domain": "annual_audit",
                    "annual_finding_key": candidate["finding_key"],
                    "annual_finding_id": int(finding.get("finding_id") or 0),
                    "finding_type": str(finding.get("finding_type") or ""),
                    "risk_level": str(finding.get("risk_level") or ""),
                },
                "confidence": 1.0,
                "source_count": len(candidate["evidences"]),
                "human_verified": False,
                "status": "active",
            }
        )
    persisted_relations = service.upsert_relations(case_id=case_id, rows=relation_rows)
    relation_ids = _returned_ids_by_key(relation_rows, persisted_relations, key_name="relation_key")

    existing_by_finding_key = _existing_projection_claims(
        service=service,
        case_id=case_id,
        finding_keys=[candidate["finding_key"] for candidate in candidates],
    )
    missing_candidates = [
        candidate
        for candidate in candidates
        if candidate["finding_key"] not in existing_by_finding_key
    ]
    claims_by_finding_key = dict(existing_by_finding_key)
    if missing_candidates:
        source_file_ids = sorted(
            {
                int(evidence["file_id"])
                for candidate in missing_candidates
                for evidence in candidate["evidences"]
            }
        )
        source_chunk_ids = {
            str(evidence["chunk_id"])
            for candidate in missing_candidates
            for evidence in candidate["evidences"]
        }
        run_id = service.create_extraction_run(
            case_id=case_id,
            run_type="annual_rule_projection",
            trigger_source="annual_audit",
            source_file_ids=source_file_ids,
            chunk_count=len(source_chunk_ids),
            prompt_version=analysis_rules_version or "annual-rules",
            model_provider="deterministic",
            model_name="annual-rule-engine",
            status="running",
        )
        try:
            claim_rows: list[dict[str, Any]] = []
            for candidate in missing_candidates:
                finding = candidate["finding"]
                finding_entity_key = _finding_entity_key(case_id, candidate["finding_key"])
                relation_key = str(
                    next(
                        row["relation_key"]
                        for row in relation_rows
                        if row["attributes"]["annual_finding_key"] == candidate["finding_key"]
                    )
                )
                claim_rows.append(
                    {
                        "entity_id": entity_ids[finding_entity_key],
                        "relation_id": relation_ids.get(relation_key),
                        "claim_type": "risk_signal",
                        "claim_text": candidate["claim_text"],
                        "claim_value": {
                            "source_kind": "annual_rule",
                            "annual_finding_key": candidate["finding_key"],
                            "annual_finding_id": int(finding.get("finding_id") or 0),
                            "analysis_run_id": int(finding.get("analysis_run_id") or 0),
                            "finding_type": str(finding.get("finding_type") or ""),
                            "risk_level": str(finding.get("risk_level") or ""),
                            "amount": str(finding.get("amount") or ""),
                            "rules_version": analysis_rules_version,
                        },
                        "confidence": 1.0,
                        "status": "active",
                        "review_status": "pending",
                    }
                )
            persisted_claims = service.insert_claims(
                case_id=case_id,
                extraction_run_id=run_id,
                rows=claim_rows,
                prompt_version=analysis_rules_version or "annual-rules",
                model_provider="deterministic",
                model_name="annual-rule-engine",
                parser_version="annual-rule-projection-v1",
            )
            evidence_rows: list[dict[str, Any]] = []
            for candidate, persisted_claim in zip(missing_candidates, persisted_claims, strict=False):
                claim_id = int(persisted_claim.get("id") or 0)
                if claim_id <= 0:
                    raise ValueError("annual finding claim projection was not persisted")
                claims_by_finding_key[candidate["finding_key"]] = {
                    "claim_id": claim_id,
                    "entity_id": int(
                        persisted_claim.get("entity_id")
                        or entity_ids[_finding_entity_key(case_id, candidate["finding_key"])]
                    ),
                }
                evidence_rows.extend(
                    {
                        "claim_id": claim_id,
                        "chunk_id": str(evidence["chunk_id"]),
                        "file_id": int(evidence["file_id"]),
                        "page_no": int(evidence.get("page_no") or 0),
                        "quote_text": str(evidence.get("quote_text") or ""),
                        "bbox_list": list(evidence.get("bbox_list") or []),
                        "score": 1.0,
                    }
                    for evidence in candidate["evidences"]
                )
            if evidence_rows:
                service.insert_evidence_links(evidence_rows)
            service.complete_extraction_run(run_id)
        except Exception as exc:
            try:
                service.fail_extraction_run(run_id, str(exc)[:500])
            except Exception:
                LOGGER.exception("annual_finding_graph_projection_fail_mark_failed run_id=%s", run_id)
            raise

    trace_by_finding_key: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        projection = claims_by_finding_key.get(candidate["finding_key"]) or {}
        claim_id = int(projection.get("claim_id") or 0)
        if claim_id <= 0:
            continue
        entity_id = int(
            projection.get("entity_id")
            or entity_ids.get(_finding_entity_key(case_id, candidate["finding_key"]), 0)
        )
        trace_by_finding_key[candidate["finding_key"]] = {
            "citation_id": "",
            "claim_id": claim_id,
            "claim_type": "risk_signal",
            "claim_text": candidate["claim_text"],
            "confidence": 1.0,
            "entity_id": entity_id,
            "_graph_backed": True,
            "evidences": [{**evidence, "entity_id": entity_id} for evidence in candidate["evidences"]],
        }
    return {
        "trace_by_finding_key": trace_by_finding_key,
        "projected_count": len(trace_by_finding_key),
        "unprojected_count": max(len(candidates) - len(trace_by_finding_key), 0),
    }


def _finding_entity_key(case_id: int, finding_key: str) -> str:
    return build_entity_key(
        case_id=case_id,
        entity_type="audit_finding",
        normalized_name=finding_key,
    )


def _returned_ids_by_key(
    source_rows: list[dict[str, Any]],
    persisted_rows: list[dict[str, Any]],
    *,
    key_name: str,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for source, persisted in zip(source_rows, persisted_rows, strict=False):
        key = str(persisted.get(key_name) or source.get(key_name) or "")
        identifier = int(persisted.get("id") or 0)
        if key and identifier > 0:
            result[key] = identifier
    return result


def _existing_projection_claims(
    *,
    service: Any,
    case_id: int,
    finding_keys: list[str],
) -> dict[str, dict[str, int]]:
    finder = getattr(service, "find_active_annual_projection_claims", None)
    if not callable(finder):
        return {}
    rows = finder(case_id=case_id, finding_keys=finding_keys)
    result: dict[str, dict[str, int]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        finding_key = str(row.get("annual_finding_key") or "")
        claim_id = int(row.get("id") or row.get("claim_id") or 0)
        if finding_key and finding_key not in result and claim_id > 0:
            result[finding_key] = {
                "claim_id": claim_id,
                "entity_id": int(row.get("entity_id") or 0),
            }
    return result


__all__ = [
    "annual_finding_key",
    "project_annual_findings_to_knowledge_graph",
]
