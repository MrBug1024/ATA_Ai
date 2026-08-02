"""AI 复盘接口（Tier1-3 Phase 2-A）。

POST /cases/{id}/review：对案件做"预期 vs 实际"回款对账复盘。
驱动同一条主图（intent=review → review_graph），因此复盘报告与对话路径
享受完全一致的持久化（conversation_messages 全文 + final_report_ref）、
历史可取回、靠 intent=review 区分。额外返回结构化三视角对账指标供看板用。
"""

from __future__ import annotations

from typing import Any

import anyio
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth.identity import Identity
from ..auth.permissions import require_module
from ..auth.tenancy import get_tenancy_service, require_case_access
from ..graph.context_loader import resolve_final_report
from ..settings import get_settings

router = APIRouter(
    tags=["review"],
    dependencies=[Depends(require_module("review"))],
    responses={403: {"description": "缺少 review 模块权限、无权访问案件或无权管理指定会话。"}},
)


class ReviewRequest(BaseModel):
    thread_id: str = Field(default="", description="会话线程 id；不传则用 review-case-{id}（复盘独立线程）")
    query: str = Field(default="", description="自定义复盘指令；不传用默认'对案件X做回款复盘对账'")


class ReviewResponse(BaseModel):
    thread_id: str
    case_id: int
    intent: str = ""
    final_report: str = Field(default="", description="复盘报告全文（已持久化，可从历史取回）")
    review_metrics: dict = Field(default_factory=dict, description="确定性三视角对账：总量/时点/按处置路径")


def _invoke_review(case_id: int, thread_id: str, query: str) -> dict[str, Any]:
    # 复用 routes_chat 编译好的同步主图（共用 checkpointer 连接池），避免重复编译/建池。
    from .routes_chat import graph

    graph_input = {"query": query, "current_case_id": case_id, "thread_id": thread_id}
    return graph.invoke(graph_input, config={"configurable": {"thread_id": thread_id}})


@router.post("/cases/{case_id}/review", summary="AI 回款复盘对账", response_model=ReviewResponse,
             description=("对案件做预期 vs 实际回款对账复盘：三视角对账(总量/时点/按处置路径) + "
                          "差异归因 + 经验规则建议。复盘报告复用报告持久化链路，历史可取回。"
                          "只读对账：不改 case_progress、不抽任务、不种子化预期。"))
async def run_review(
    case_id: int,
    payload: ReviewRequest | None = None,
    identity: Identity = Depends(require_case_access),
) -> ReviewResponse:
    payload = payload or ReviewRequest()
    thread_id = (payload.thread_id or "").strip() or f"review-case-{case_id}"
    query = (payload.query or "").strip() or f"对案件{case_id}做回款复盘对账"
    settings = get_settings()
    if settings.auth_enabled:
        await anyio.to_thread.run_sync(
            lambda: get_tenancy_service().ensure_thread_for_invoke(identity, thread_id, case_id)
        )

    result = await anyio.to_thread.run_sync(lambda: _invoke_review(case_id, thread_id, query))
    if settings.auth_enabled:
        await anyio.to_thread.run_sync(
            lambda: get_tenancy_service().update_thread_metadata(
                thread_id,
                last_intent=str(result.get("intent", "review") or "review"),
                title=query[:50],
            )
        )

    review_metrics = ((result.get("review_context") or {}).get("metrics")) or {}
    final_report = resolve_final_report(result) or result.get("final_report", "") or ""
    return ReviewResponse(
        thread_id=thread_id,
        case_id=case_id,
        intent=result.get("intent", ""),
        final_report=final_report,
        review_metrics=review_metrics,
    )
