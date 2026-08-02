from ..state import AuditGraphState


def should_ingest_files(state: AuditGraphState) -> str:
    return "ingest" if state.get("uploaded_files") else "skip"


def summarize_ingest_result(state: AuditGraphState) -> AuditGraphState:
    summary = state.get("parse_summary", "")
    if not summary:
        return {}
    return {
        "agent_output": summary,
    }
