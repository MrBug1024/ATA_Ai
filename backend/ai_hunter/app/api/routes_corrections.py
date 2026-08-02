"""权威文字订正与追溯接口（Tier 2 决策三）。

把会话内修正升级为案件级权威订正：列订正（含历史，供追溯审计）、人工录订正、撤销。
对话里的修正由 extract_correction 自动写库；这里给前端/运营人工管理与追溯入口。
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.permissions import require_module
from ..auth.tenancy import require_case_access
from ..services.correction_service import get_correction_service

router = APIRouter(
    tags=["corrections"],
    dependencies=[Depends(require_module("corrections"))],
    responses={403: {"description": "缺少 corrections 模块权限或无权访问该案件。"}},
)


class CorrectionCreateRequest(BaseModel):
    target: str = Field(description="修正作用的标的/对象（如某房产、某结论）")
    instruction: str = Field(description="强制修正指令")
    source_query: str = Field(default="", description="原始话术（可空）")
    operator_id: str = Field(default="", description="操作人 ID（账号体系上线前可空）")
    operator_name: str = Field(default="", description="操作人名称")
    scope: str = Field(default="全案", description="生效范围，默认全案")


class CorrectionModel(BaseModel):
    id: int = 0
    case_id: int = 0
    target: str = ""
    instruction: str = ""
    source_query: str = ""
    operator_id: str = ""
    operator_name: str = ""
    operator_meta: dict = Field(default_factory=dict, description="预留：账号体系角色/标签")
    scope: str = "全案"
    origin: str = "chat"
    status: str = Field(default="active", description="active / superseded / revoked")
    superseded_by: int | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class CorrectionListResponse(BaseModel):
    case_id: int = 0
    corrections: list[CorrectionModel] = Field(default_factory=list)


@router.get("/cases/{case_id}/corrections", summary="列案件权威订正（可含历史）",
            dependencies=[Depends(require_case_access)],
            response_model=CorrectionListResponse,
            description=("返回该案订正。默认只返 active（加载期实际应用的）；include_history=true "
                         "返回全部含 superseded（被同标的更新订正覆盖）/ revoked（人工撤销），供追溯审计。"))
async def list_corrections(case_id: int, include_history: bool = False) -> dict:
    rows = get_correction_service().list_corrections(case_id, include_history=include_history)
    return {"case_id": case_id, "corrections": rows}


@router.post("/cases/{case_id}/corrections", summary="人工录入一条权威订正",
             dependencies=[Depends(require_case_access)],
             response_model=CorrectionModel,
             description=("人工录入订正（origin=manual，status=active）。同 (case_id, target) 已有 active "
                          "订正会被自动置 superseded（最新权威覆盖），旧值保留作历史可追溯。"))
async def add_correction(case_id: int, payload: CorrectionCreateRequest) -> dict:
    return get_correction_service().add_correction(
        case_id,
        target=payload.target,
        instruction=payload.instruction,
        source_query=payload.source_query,
        operator_id=payload.operator_id,
        operator_name=payload.operator_name,
        scope=payload.scope,
        origin="manual",
    )


@router.post("/cases/{case_id}/corrections/{correction_id}/revoke", summary="撤销一条订正",
             dependencies=[Depends(require_case_access)],
             response_model=CorrectionModel,
             description="把一条订正置为 revoked，下次审计不再应用。不存在返回 404。")
async def revoke_correction(case_id: int, correction_id: int) -> dict:
    row = get_correction_service().revoke_correction(case_id, correction_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"订正不存在：case={case_id} id={correction_id}")
    return row
