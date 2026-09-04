"""Shared state definition for the main orchestration graph."""

import operator
from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


def merge_section_refs(
    existing: dict[str, str] | None, new: dict[str, str] | None
) -> dict[str, str]:
    """Merge per-section report refs from parallel section nodes（后者覆盖同 id）。"""
    return {**(existing or {}), **(new or {})}


def merge_conversation_log(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge conversation log entries, deduplicating by entry ``id``.

    Each entry is expected to carry a unique ``id`` (set by
    :func:`persist_conversation_memory`).  When the same id is already
    present we skip the duplicate, preventing repeats caused by retries
    or redundant graph invocations.
    """
    if not existing:
        return list(new) if new else []
    if not new:
        return list(existing)
    existing_ids = {e.get("id") for e in existing if e.get("id")}
    merged = list(existing)
    for entry in new:
        if entry.get("id") not in existing_ids:
            merged.append(entry)
            existing_ids.add(entry.get("id"))
    return merged

from .schemas import (
    CaseDocCategoryStatusModel,
    CorrectionLedgerItemModel,
    DocCategoryCatalogModel,
    ExtractionClaimModel,
    ExtractedEntityModel,
    ExtractedRelationModel,
    FullContextResultModel,
    ParseDocumentResultModel,
    ReconciliationLedgerItemModel,
    RouteDecisionModel,
    SourceChunkModel,
    TaskItemModel,
    CitationCoverageModel,
    DemoCaseTraceValidationResponseModel,
    TraceItemModel,
    UnresolvedClaimItemModel,
    UnresolvedRelationItemModel,
    ValidateDocCategoryResultModel,
    WriteCommandModel,
)


Intent = Literal["full_audit", "drilldown", "re_audit"]


class FileItem(TypedDict, total=False):
    name: str
    url: str
    type: str
    extension: str
    content_type: str
    content: str
    doc_category: str
    upload_batch_id: str
    file_hash: str
    file_size: int
    content_ref: str
    duplicate_of: str
    storage_ref: str
    storage_provider: str
    storage_bucket: str
    storage_key: str
    storage_etag: str
    storage_version: str


class TaskItem(TypedDict, total=False):
    action: str
    role: str
    deadline: str
    deliverable: str
    priority: str


class BusinessLineContext(TypedDict, total=False):
    """Compact per-line execution projection; heavy outputs remain behind refs."""

    phase: str
    business_line: str
    capability: str
    executor: str
    access_mode: str
    status: str
    output_ref: str
    summary: str
    task_count: int
    correction_count: int


class AuditGraphState(TypedDict, total=False):
    thread_id: str
    user_id: str
    query: str
    client_turn_id: str
    regenerate: bool
    selected_assistant_turn_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    # Append-only, display-only conversation log holding the FULL assistant
    # answer per turn. Kept separate from `messages` (which stays lean for LLM
    # memory) and is never trimmed, so the history API can return full replies.
    conversation_log: Annotated[list[dict[str, Any]], merge_conversation_log]
    memory_context: str
    memory_summary: str
    # Structured, compact multi-turn focus used to resolve phrases such as
    # "这些结果" and "按刚才的计划继续" without trusting the browser to resend
    # the entire conversation. Heavy report/evidence payloads remain behind refs.
    conversation_focus: dict[str, Any]
    case_switched: bool

    current_case_id: int
    current_entity_id: int
    current_entity_name: str
    doc_category: str
    batch_name: str
    upload_batch_id: str
    material_event_id: str
    operator_id: str
    operator_name: str
    identity_context: dict[str, Any]
    write_command: dict[str, Any] | WriteCommandModel

    uploaded_files: list[FileItem]
    ingest_payload_ref: str
    ingest_payload_summary: str
    txt_contents: list[str]
    csv_contents: list[str]
    md_contents: list[str]
    document_ocr_contents: list[str]
    image_ocr_contents: list[str]
    ocr_layout_results: list[dict[str, Any]]
    aggregated_text_ref: str
    aggregated_text_summary: str
    aggregated_text: str

    parse_summary: str
    categories_found: list[str]
    recognized_categories: list[str]
    file_classifications: list[dict[str, Any]]
    unclassified_files: list[str]
    records_inserted: int
    parse_document_result_ref: str
    parse_document_result: dict[str, Any] | ParseDocumentResultModel
    doc_category_catalog: dict[str, Any] | DocCategoryCatalogModel
    case_doc_category_status: dict[str, Any] | CaseDocCategoryStatusModel
    missing_categories: list[str]
    duplicate_files: list[str]
    suspected_mismatch_files: list[str]
    new_files: list[str]
    text_file_content_refs: dict[str, str]
    upload_batch_summary: dict[str, Any]
    annual_import_summary: dict[str, Any]
    material_event_summary: dict[str, Any]
    defer_upload_batch_completion: bool
    doc_category_validation: dict[str, Any] | ValidateDocCategoryResultModel
    chunk_batch_ref: str
    chunk_batch_summary: str
    chunk_ids: list[str]
    annual_evidence_binding_summary: dict[str, Any]

    intent: Intent
    route_decision: dict[str, Any] | RouteDecisionModel
    execution_route: dict[str, Any]
    business_line_plan: dict[str, Any]
    business_line_result: dict[str, Any]
    operator_context: BusinessLineContext
    audit_context: BusinessLineContext
    supervision_context: BusinessLineContext
    common_context: BusinessLineContext
    full_context_ref: str
    full_context_summary: str
    full_context_json: str
    full_context_data: dict[str, Any] | FullContextResultModel

    computed_metrics_ref: str

    # 年审报告各段文本 heavy ref（section_id -> ref）。
    report_section_refs: Annotated[dict[str, str], merge_section_refs]

    report_part_a_ref: str
    report_part_a_summary: str
    report_part_a: str
    report_part_b_ref: str
    report_part_b_summary: str
    report_part_b: str
    final_report_ref: str
    final_report_summary: str
    final_report: str
    # Per-turn display metadata. These are reset before every invocation so
    # a later response cannot inherit an earlier response's evidence drawer.
    assistant_message_id: str
    response_evidence_index: str
    response_trace_candidates: list[dict[str, Any]]
    # Exact tool output scopes for this assistant reply. They are never
    # reconstructed from conversation text or a project's newest run.
    response_analysis_runs: list[dict[str, Any]]
    response_evidence_tool_results: list[dict[str, Any]]
    response_citation_coverage: dict[str, Any] | CitationCoverageModel
    citation_entries: list[dict[str, Any]]
    annual_report_manifest: dict[str, Any]
    citation_manifest_binding: dict[str, Any]
    trace_items: list[dict[str, Any] | TraceItemModel]
    citation_coverage: dict[str, Any] | CitationCoverageModel
    demo_trace_validation: dict[str, Any] | DemoCaseTraceValidationResponseModel
    user_corrections: list[str]
    correction_records: list[dict[str, Any] | CorrectionLedgerItemModel]

    extracted_tasks: list[TaskItem | TaskItemModel]
    kg_extraction_run_id: int
    kg_entities: list[dict[str, Any] | ExtractedEntityModel]
    kg_relations: list[dict[str, Any] | ExtractedRelationModel]
    kg_claims: list[dict[str, Any] | ExtractionClaimModel]
    kg_summary: str
    kg_subgraph_ref: str
    case_material_sources: list[dict[str, Any]]
    superseded_claim_ids: list[int]
    superseded_relation_ids: list[int]
    reconciliation_items: list[dict[str, Any] | ReconciliationLedgerItemModel]
    unresolved_relations: list[dict[str, Any] | UnresolvedRelationItemModel]
    unresolved_claims: list[dict[str, Any] | UnresolvedClaimItemModel]
    source_chunks: list[dict[str, Any] | SourceChunkModel]
    task_create_result: dict[str, Any]
    artifacts: dict[str, Any]
    attachment_job: dict[str, Any]
    agent_output: str

    errors: list[str]
