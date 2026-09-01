from langchain_core.messages import RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from ..routers import extract_case_id
from ..state import AuditGraphState, FileItem


def normalize_input(state: AuditGraphState) -> AuditGraphState:
    files = state.get("uploaded_files") or []
    normalized_files: list[FileItem] = []
    query = (state.get("query") or "").strip()
    historical_case_id = state.get("current_case_id", 0)
    requested_case_id = extract_case_id(query)
    case_switched = bool(
        requested_case_id
        and historical_case_id
        and requested_case_id != historical_case_id
    )
    conversation_focus = dict(state.get("conversation_focus") or {})
    if state.get("final_report_ref") or state.get("final_report") or state.get("final_report_summary"):
        conversation_focus["report_exists"] = True
        conversation_focus["final_report_ref"] = str(state.get("final_report_ref") or "")
    previous_route = state.get("route_decision") or {}
    if hasattr(previous_route, "model_dump"):
        previous_route = previous_route.model_dump()
    if isinstance(previous_route, dict) and previous_route:
        conversation_focus["last_route_decision"] = previous_route

    for file_item in files:
        # Filter out empty file objects (no name, url, or content)
        name = file_item.get("name", "")
        url = file_item.get("url", "")
        content = file_item.get("content", "")
        if not name and not url and not content:
            continue
        
        extension = ""
        if "." in name:
            extension = "." + name.rsplit(".", 1)[-1].lower()
        normalized_files.append(
            {
                "name": name,
                "url": url,
                "type": file_item.get("type", "document"),
                "extension": file_item.get("extension", extension),
                "content_type": file_item.get("content_type", ""),
                "content": content,
                "content_ref": file_item.get("content_ref", ""),
                "doc_category": file_item.get("doc_category", ""),
                "upload_batch_id": file_item.get("upload_batch_id", ""),
                "file_hash": file_item.get("file_hash", ""),
                "file_size": file_item.get("file_size", 0),
                "duplicate_of": file_item.get("duplicate_of", ""),
                "storage_ref": file_item.get("storage_ref", ""),
                "storage_provider": file_item.get("storage_provider", ""),
                "storage_bucket": file_item.get("storage_bucket", ""),
                "storage_key": file_item.get("storage_key", ""),
                "storage_etag": file_item.get("storage_etag", ""),
                "storage_version": file_item.get("storage_version", ""),
            }
        )

    normalized: AuditGraphState = {
        "thread_id": state.get("thread_id", ""),
        "query": query,
        "uploaded_files": normalized_files,
        "messages": state.get("messages", []),
        "errors": state.get("errors", []),
        "case_switched": case_switched,
        "client_turn_id": state.get("client_turn_id", ""),
        "regenerate": state.get("regenerate", False),
        "selected_assistant_turn_id": state.get("selected_assistant_turn_id", ""),
        "conversation_focus": conversation_focus,
        # A checkpoint holds long-lived case context as well as the last
        # response. The fields below are response-scoped, not case-scoped:
        # retaining them would make a new answer expose the previous answer's
        # report reference, citations, or unresolved-item badges.
        "final_report_ref": "",
        "final_report_summary": "",
        "final_report": "",
        "assistant_message_id": "",
        "response_evidence_index": "",
        "response_trace_candidates": [],
        "response_analysis_runs": [],
        "response_evidence_tool_results": [],
        "response_citation_coverage": {},
        "citation_entries": [],
        "annual_report_manifest": {},
        "citation_manifest_binding": {},
        "trace_items": [],
        "citation_coverage": {},
        "reconciliation_items": [],
        "unresolved_relations": [],
        "unresolved_claims": [],
        "agent_output": "",
        "business_line_plan": {},
        "business_line_result": {},
        "artifacts": {},
        "extracted_tasks": [],
        "task_create_result": {},
        "attachment_job": {},
    }

    if case_switched:
        normalized.update(
            {
                "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "memory_context": "",
                "memory_summary": "",
                "conversation_focus": {},
                "current_case_id": requested_case_id,
                "current_entity_id": 0,
                "current_entity_name": "",
                "doc_category": "",
                "batch_name": "",
                "upload_batch_id": "",
                "operator_id": "",
                "operator_name": "",
                "ingest_payload_ref": "",
                "ingest_payload_summary": "",
                "full_context_json": "",
                "full_context_data": {},
                "full_context_ref": "",
                "full_context_summary": "",
                "report_part_a_ref": "",
                "report_part_a_summary": "",
                "report_part_a": "",
                "report_part_b_ref": "",
                "report_part_b_summary": "",
                "report_part_b": "",
                "final_report_ref": "",
                "final_report_summary": "",
                "final_report": "",
                "trace_items": [],
                "agent_output": "",
                "parse_summary": "",
                "parse_document_result_ref": "",
                "parse_document_result": {},
                "doc_category_catalog": {},
                "case_doc_category_status": {},
                "missing_categories": [],
                "duplicate_files": [],
                "suspected_mismatch_files": [],
                "new_files": [],
                "text_file_content_refs": {},
                "upload_batch_summary": {},
                "doc_category_validation": {},
                "chunk_batch_ref": "",
                "chunk_batch_summary": "",
                "chunk_ids": [],
                "aggregated_text_ref": "",
                "aggregated_text_summary": "",
                "aggregated_text": "",
                "txt_contents": [],
                "csv_contents": [],
                "md_contents": [],
                "document_ocr_contents": [],
                "image_ocr_contents": [],
                "ocr_layout_results": [],
                "kg_extraction_run_id": 0,
                "kg_entities": [],
                "kg_relations": [],
                "kg_claims": [],
                "kg_summary": "",
                "kg_subgraph_ref": "",
                "case_material_sources": [],
                "superseded_claim_ids": [],
                "superseded_relation_ids": [],
                "reconciliation_items": [],
                "source_chunks": [],
                "user_corrections": [],
                "correction_records": [],
                "extracted_tasks": [],
                "task_create_result": {},
            }
        )

    return normalized
