"""LangChain task tools backed by the FastAPI task service."""

from langchain_core.tools import tool

from ..services.task_api import get_task_api_client
from .summary_utils import build_tool_error, build_tool_result


@tool
def create_task_batch(case_id: int, tasks: list[dict]) -> str:
    """Create a batch of SOP tasks for a given case."""
    try:
        return build_tool_result(
            "create_task_batch",
            get_task_api_client().create_batch_sync(case_id, tasks),
            next_hint="如需继续处理任务，请指定查看、指派或更新状态。",
        )
    except Exception as exc:
        return build_tool_error("create_task_batch", exc)


@tool
def manage_tasks(
    action: str,
    case_id: int,
    task_id: int | None = None,
    new_status: str | None = None,
    completion_note: str | None = None,
    assigned_to: str | None = None,
    filter_status: str | None = None,
) -> str:
    """List, assign, update, or summarize tasks for a case."""
    try:
        payload = {
            "case_id": case_id,
            "action": action,
            "task_id": task_id,
            "new_status": new_status,
            "completion_note": completion_note,
            "assigned_to": assigned_to,
            "filter_status": filter_status,
        }
        return build_tool_result(
            "manage_tasks",
            get_task_api_client().manage_sync(payload),
            next_hint="如需继续任务操作，请明确任务编号、状态或责任人。",
        )
    except Exception as exc:
        return build_tool_error("manage_tasks", exc)
