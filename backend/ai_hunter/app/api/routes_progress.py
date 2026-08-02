"""回款闭环与进度看板路由（Tier1-3 Phase 1）。"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.progress_service import get_progress_service


from ..auth.permissions import require_module  # noqa: E402
from ..auth.tenancy import require_case_access

router = APIRouter(
    tags=["progress"],
    dependencies=[Depends(require_module("progress"))],
    responses={403: {"description": "缺少 progress 模块权限或无权访问该案件。"}},
)


class ProgressUpdateRequest(BaseModel):
    stage: str | None = Field(default=None, description="案件阶段（资料录入/智能初选/实地尽调/投委会决策/资产确权/执行处置/审计复盘/已归档）")
    status: str | None = Field(default=None, description="进行中/暂停/已结案/已归档")
    risk_alerts: list[dict] | None = Field(default=None, description="风险提示列表")
    expected_recovery_total: float | None = Field(default=None, description="预期回款总额（元）")
    profit_distributable: float | None = Field(default=None, description="可分配利润（元）")
    profit_distributed: float | None = Field(default=None, description="已分配利润（元）")
    report_ref: str | None = Field(default=None, description="预期来源报告引用")


class RecoveryCreateRequest(BaseModel):
    amount: float = Field(description="收款金额（元）")
    recovered_at: str = Field(description="收款日期 YYYY-MM-DD")
    disposal_path: str = Field(default="", description="清算拍卖/破产重整/协商和解/执行/其它")
    related_task_id: str = Field(default="", description="关联 SOP 任务 id")
    source_desc: str = Field(default="", description="来源说明")
    operator: str = Field(default="", description="经办人")
    note: str = Field(default="", description="备注")


class ForecastItem(BaseModel):
    tranche: str = Field(default="", description="T1/T2/T3 或处置路径")
    expected_amount: float = Field(default=0, description="预期金额（元）")
    expected_date: str | None = Field(default=None, description="预期到期日 YYYY-MM-DD")
    basis: str = Field(default="人工", description="依据：报告NPV / 人工")


class ForecastSeedRequest(BaseModel):
    report_ref: str = Field(default="", description="来源报告引用")
    tranches: list[ForecastItem] = Field(default_factory=list, description="预期回款分档列表")


# ── 响应模型（供 Swagger 展示；字段均带默认值，兼容部分聚合结果）──────────────
class ReminderModel(BaseModel):
    type: str = Field(default="", description="提醒类型：催收 / 利润分配 / 待确认收款")
    level: str = Field(default="", description="级别：warn / info / high")
    message: str = Field(default="", description="提醒文案")


class ProgressBoardResponse(BaseModel):
    case_id: int = 0
    stage: str | None = Field(default=None, description="案件阶段")
    status: str | None = Field(default=None, description="案件状态")
    risk_alerts: list[dict] = Field(default_factory=list, description="风险提示（报告自动聚合 + 人工）")
    expected_recovery_total: float = Field(default=0, description="预期回款总额（元，供计算）")
    expected_recovery_total_wan: str = Field(default="", description="预期回款总额（万元/4位/无千分位，供展示）")
    actual_recovery_total: float = Field(default=0, description="实际收款总额（元，仅计已确认）")
    actual_recovery_total_wan: str = Field(default="", description="实际收款总额（万元，供展示）")
    recovery_ratio_pct: float = Field(default=0, description="回收率（实收/预期，%）")
    profit_distributable: float = 0
    profit_distributable_wan: str = ""
    profit_distributed: float = 0
    profit_distributed_wan: str = ""
    report_ref: str = ""
    forecasts: list[dict] = Field(default_factory=list, description="预期回款分档")
    records: list[dict] = Field(default_factory=list, description="实收明细（含 status=pending 待确认）")
    reminders: list[ReminderModel] = Field(default_factory=list, description="催收/利润/待确认提醒")
    params: dict = Field(default_factory=dict, description="本次提醒规则参数（逾期天数/利润阈值）")


class RecoveryRecordModel(BaseModel):
    id: int = 0
    case_id: int = 0
    amount: float = 0
    recovered_at: datetime.date | None = None
    disposal_path: str = ""
    related_task_id: str = ""
    source_desc: str = ""
    operator: str = ""
    note: str = ""
    status: str = Field(default="confirmed", description="confirmed=已计入 / pending=自动抽取待确认")
    origin: str = Field(default="manual", description="manual / ingest_material / chat")


class RecoveryListResponse(BaseModel):
    case_id: int = 0
    records: list[RecoveryRecordModel] = Field(default_factory=list)


class ForecastListResponse(BaseModel):
    case_id: int = 0
    forecasts: list[dict] = Field(default_factory=list)


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"日期格式应为 YYYY-MM-DD：{s}")


@router.get("/cases/{case_id}/progress", summary="进度看板聚合", response_model=ProgressBoardResponse,
            dependencies=[Depends(require_case_access)],
            description=("回款闭环看板：返回案件阶段/状态/风险提示/预期·实际回款汇总/回收率/预期分档/"
                         "实收明细(含待确认)/催收·利润·待确认提醒。提醒规则可由 env 配置"
                         "（RECOVERY_OVERDUE_DAYS / PROFIT_DISTRIBUTION_THRESHOLD_PCT）。"))
async def get_progress_board(case_id: int) -> dict:
    return get_progress_service().build_board(case_id)


@router.put("/cases/{case_id}/progress", summary="更新案件进度",
            dependencies=[Depends(require_case_access)],
            description="更新阶段/状态/风险提示/利润等（只更新传入字段）。阶段/状态非法值返回 422。")
async def update_progress(case_id: int, payload: ProgressUpdateRequest) -> dict:
    try:
        return get_progress_service().upsert_progress(case_id, **payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/cases/{case_id}/recovery", summary="记一笔实际收款", response_model=RecoveryRecordModel,
             dependencies=[Depends(require_case_access)],
             description="人工录入一笔实收（status=confirmed，直接计入实收总额）。日期格式 YYYY-MM-DD。")
async def add_recovery(case_id: int, payload: RecoveryCreateRequest) -> dict:
    return get_progress_service().add_recovery(
        case_id,
        amount=payload.amount,
        recovered_at=_parse_date(payload.recovered_at),
        disposal_path=payload.disposal_path,
        related_task_id=payload.related_task_id,
        source_desc=payload.source_desc,
        operator=payload.operator,
        note=payload.note,
    )


@router.get("/cases/{case_id}/recovery", summary="实际收款明细列表（含待确认）", response_model=RecoveryListResponse,
            dependencies=[Depends(require_case_access)],
            description="返回该案件全部实收记录；status=pending 为自动抽取待确认（未计入总额）。")
async def list_recovery(case_id: int) -> dict:
    return {"case_id": case_id, "records": get_progress_service().list_recovery(case_id)}


@router.post("/cases/{case_id}/recovery/{record_id}/confirm", response_model=RecoveryRecordModel,
             dependencies=[Depends(require_case_access)],
             summary="确认一笔自动抽取的待确认收款",
             description="把自动抽取(pending)的收款确认为 confirmed，确认后计入实收总额。不存在返回 404。")
async def confirm_recovery(case_id: int, record_id: int) -> dict:
    rec = get_progress_service().confirm_recovery(case_id, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"收款记录不存在：case={case_id} id={record_id}")
    return rec


@router.post("/cases/{case_id}/forecast", summary="写入/种子化预期回款",
             dependencies=[Depends(require_case_access)],
             description="写入预期回款分档（人工，basis=人工）。报告出完后系统会自动按 NPV 三档种子化(basis=报告NPV)。")
async def seed_forecast(case_id: int, payload: ForecastSeedRequest) -> dict:
    tranches = [
        {**t.model_dump(exclude={"expected_date"}), "expected_date": _parse_date(t.expected_date)}
        for t in payload.tranches
    ]
    n = get_progress_service().seed_forecast(case_id, report_ref=payload.report_ref, tranches=tranches)
    return {"case_id": case_id, "seeded": n}


@router.get("/cases/{case_id}/forecast", summary="预期回款列表", response_model=ForecastListResponse,
            dependencies=[Depends(require_case_access)],
            description="返回预期回款分档（含报告NPV种子 + 人工）。")
async def list_forecast(case_id: int) -> dict:
    return {"case_id": case_id, "forecasts": get_progress_service().list_forecast(case_id)}
