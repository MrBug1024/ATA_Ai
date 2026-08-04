from ..state import AuditGraphState


def should_ingest_files(state: AuditGraphState) -> str:
    return "ingest" if state.get("uploaded_files") else "skip"


def summarize_ingest_result(state: AuditGraphState) -> AuditGraphState:
    summary = state.get("parse_summary", "")
    annual_import = state.get("annual_import_summary") or {}
    if annual_import:
        imported = annual_import.get("imported") or []
        labels = "、".join(
            sorted({str(item.get("dataset_label") or "") for item in imported if item.get("dataset_label")})
        )
        structured_summary = (
            f"年审结构化导入：新增 {int(annual_import.get('new_row_count') or 0)} 行"
            f"{f'（{labels}）' if labels else ''}。"
        )
        if annual_import.get("errors"):
            structured_summary += f"另有 {len(annual_import['errors'])} 个附件需复核。"
        summary = "\n".join(part for part in (summary, structured_summary) if part)
    if not summary:
        return {}
    return {
        "agent_output": summary,
    }
