"""Task backend client for batch creation and task management."""

from ..settings import get_settings
from .base import BaseAPIClient


class TaskAPIClient(BaseAPIClient):
    """Wrappers around the task service endpoints."""

    async def create_batch(self, case_id: int, tasks: list[dict]) -> dict:
        return await self.post_json("/api/tasks/create-batch", {"case_id": case_id, "tasks": tasks})

    async def manage(self, payload: dict) -> dict:
        return await self.post_json("/api/tasks/manage", payload)

    def create_batch_sync(self, case_id: int, tasks: list[dict]) -> dict:
        return self.post_json_sync("/api/tasks/create-batch", {"case_id": case_id, "tasks": tasks})

    def manage_sync(self, payload: dict) -> dict:
        return self.post_json_sync("/api/tasks/manage", payload)


def get_task_api_client() -> TaskAPIClient:
    """Build the task client from environment settings."""
    settings = get_settings()
    return TaskAPIClient(
        base_url=settings.task_api_base_url or settings.unified_api_base_url,
        timeout_seconds=settings.audit_api_timeout_seconds,
        token=settings.audit_api_token,
    )
