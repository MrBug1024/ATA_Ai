"""司法时效看板接口（Tier 2-5）。

GET /cases/{id}/deadline-board：调审计 deadline-scan 引擎 → 确定性归一为
「倒计时 + 红黄绿四级」结构化看板。倒计时实时计算，红黄绿阈值 env 可配
（DEADLINE_RED_DAYS / DEADLINE_YELLOW_DAYS）。报告第 4 段是定格叙述，本接口供前端
渲染可刷新的红黄绿看板。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth.permissions import require_module
from ..auth.tenancy import require_case_access
from ..graph.deadline_board import compute_deadline_board

router = APIRouter(
    tags=["deadline"],
    dependencies=[Depends(require_module("deadline"))],
    responses={403: {"description": "缺少 deadline 模块权限或无权访问该案件。"}},
)
LOGGER = logging.getLogger(__name__)


class DeadlineBoardResponse(BaseModel):
    case_id: int = 0
    available: bool = Field(default=True, description="时效扫描是否可用；审计引擎不可达时为 false")
    today: str = ""
    thresholds: dict = Field(default_factory=dict, description="红黄绿阈值（天）：red_days / yellow_days")
    counts: dict = Field(default_factory=dict, description="各级计数：expired/red/yellow/safe/unknown/total")
    groups: dict = Field(
        default_factory=dict,
        description="四级分组（+unknown），每项含 type/due_date/remaining_days/related_asset/action/level",
    )


@router.get("/cases/{case_id}/deadline-board", summary="司法时效看板（红黄绿+倒计时）",
            dependencies=[Depends(require_case_access)],
            response_model=DeadlineBoardResponse,
            description=("调审计 deadline-scan 引擎并确定性归一为四级看板：已过期/红/黄/安全(+未知)。"
                         "剩余天数实时计算，红黄绿阈值由 env 配置(DEADLINE_RED_DAYS/DEADLINE_YELLOW_DAYS)。"
                         "审计引擎不可达时返回空看板 available=false，不报 500。"))
async def get_deadline_board(case_id: int) -> dict:
    try:
        from ..services.audit_api import get_audit_api_client

        scan = get_audit_api_client().audit_deadline_scan_sync(case_id)
        board = compute_deadline_board(scan if isinstance(scan, dict) else {})
        return {"case_id": case_id, "available": True, **board}
    except Exception as exc:  # noqa: BLE001 — 审计引擎不可达 → 空看板降级
        LOGGER.warning("deadline_board_failed case=%s error=%s", case_id, str(exc)[:160])
        empty = compute_deadline_board({})
        return {"case_id": case_id, "available": False, **empty}
