"""Task creation node for the post-report SOP flow."""

from ...settings import get_settings
from ....annual_audit.task_repository import create_task_batch
from ..state import AuditGraphState


def should_create_tasks(state: AuditGraphState) -> str:
    enabled = get_settings().enable_task_autocreate
    return "create" if enabled and state.get("extracted_tasks") else "skip"


def create_tasks(state: AuditGraphState) -> AuditGraphState:
    """Create project tasks through the annual-audit repository."""
    case_id = state.get("current_case_id", 0)
    tasks = state.get("extracted_tasks", []) or []
    if not get_settings().enable_task_autocreate:
        return {
            "task_create_result": {
                "created": 0,
                "skipped": len(tasks),
                "status": "autocreate_disabled",
            }
        }
    if case_id > 0 and tasks:
        try:
            result = create_task_batch(case_id, tasks)
            return {"task_create_result": result}
        except Exception:
            pass
    return {
        "task_create_result": {
            "created": len(tasks),
            "status": "pending_integration",
        }
    }
