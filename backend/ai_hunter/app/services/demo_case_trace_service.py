"""Validation helpers for the demo-case citation -> evidence -> page-anchor chain."""

from __future__ import annotations

from functools import lru_cache

from ..graph.schemas import DemoCaseTraceValidationResponseModel
from .kg_service import get_kg_service


class DemoCaseTraceService:
    """Validate whether one report version is ready for evidence-drilldown demos."""

    def validate_report_trace(
        self,
        *,
        case_id: int,
        report_ref: str,
        citation_ids: list[str] | None = None,
    ) -> DemoCaseTraceValidationResponseModel:
        if case_id <= 0 or not report_ref.strip():
            return DemoCaseTraceValidationResponseModel(
                case_id=case_id,
                report_ref=report_ref,
                ready=False,
                issues=["missing_case_id_or_report_ref"],
            )

        kg_service = get_kg_service()
        rows = kg_service.list_report_citations(
            case_id=case_id,
            report_ref=report_ref,
            citation_ids=citation_ids,
        )
        if not rows:
            return DemoCaseTraceValidationResponseModel(
                case_id=case_id,
                report_ref=report_ref,
                ready=False,
                issues=["no_report_citations_found"],
            )

        checks: list[dict[str, object]] = []
        aggregated_issues: list[str] = []
        passed = 0
        for row in rows:
            citation_id = str(row.get("citation_id", "") or "")
            claim_id = int(row.get("claim_id", 0) or 0)
            claim_text = str(row.get("claim_text", "") or "")
            issues: list[str] = []
            evidences = kg_service.fetch_claim_evidence(claim_id, case_id=case_id) if claim_id > 0 else []
            if claim_id <= 0:
                issues.append("claim_not_resolved")
            if not evidences:
                issues.append("claim_has_no_evidence")

            evidence_count = len(evidences)
            anchor_count = 0
            file_id = 0
            page_no = 0
            if evidences:
                primary = _normalize_evidence_item(evidences[0])
                file_id = int(primary.get("file_id", 0) or 0)
                page_no = int(primary.get("page_no", 0) or 0)
                if not (primary.get("source_file_url", "") or ""):
                    issues.append("missing_source_file_url")
                if not (primary.get("bbox_list") or []):
                    issues.append("missing_bbox_list")
                if file_id <= 0 or page_no <= 0:
                    issues.append("invalid_file_or_page")
                if file_id > 0 and page_no > 0:
                    anchors = kg_service.fetch_page_anchors(
                        file_id=file_id,
                        page_no=page_no,
                        chunk_id=str(primary.get("chunk_id", "") or ""),
                    )
                    anchor_count = len(anchors)
                    if not anchors:
                        issues.append("page_anchor_not_found")
                    else:
                        if not (anchors[0].get("source_file_url") or anchors[0].get("storage_ref") or ""):
                            issues.append("anchor_missing_source_file_url")
                        primary_anchor_bboxes = anchors[0].get("bbox_list") or []
                        if not primary_anchor_bboxes:
                            issues.append("anchor_missing_bbox_list")

            ok = len(issues) == 0
            if ok:
                passed += 1
            else:
                aggregated_issues.append(f"[{citation_id or '?'}] " + ",".join(issues))
            checks.append(
                {
                    "citation_id": citation_id,
                    "claim_id": claim_id,
                    "claim_text": claim_text,
                    "ok": ok,
                    "evidence_count": evidence_count,
                    "anchor_count": anchor_count,
                    "file_id": file_id,
                    "page_no": page_no,
                    "issues": issues,
                }
            )

        total = len(checks)
        failed = max(total - passed, 0)
        return DemoCaseTraceValidationResponseModel(
            case_id=case_id,
            report_ref=report_ref,
            ready=total > 0 and failed == 0,
            total_citations=total,
            passed_citations=passed,
            failed_citations=failed,
            checks=checks,
            issues=aggregated_issues,
        )


@lru_cache(maxsize=1)
def get_demo_case_trace_service() -> DemoCaseTraceService:
    """Return a cached demo-case trace validator."""
    return DemoCaseTraceService()


def _normalize_evidence_item(item: object) -> dict[str, object]:
    """Support both pydantic models and plain dict evidence payloads."""
    if hasattr(item, "model_dump"):
        return dict(item.model_dump())
    if isinstance(item, dict):
        return dict(item)
    return {}
