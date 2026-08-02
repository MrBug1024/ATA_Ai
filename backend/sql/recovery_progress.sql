-- 回款闭环与进度看板（Tier1-3 Phase 1）
-- 三表：案件进度(一案一行) / 实际收款明细 / 预期回款(种子自报告 NPV)。
-- 与 ai_hunter 共用同一库，首次部署执行本文件。

-- 1) 案件进度：生命周期阶段 + 风险 + 预期/实际回款汇总 + 利润
CREATE TABLE IF NOT EXISTS public.case_progress (
    case_id                 BIGINT PRIMARY KEY REFERENCES public.cases(case_id) ON DELETE CASCADE,
    stage                   TEXT NOT NULL DEFAULT '资料录入'
        CHECK (stage IN ('资料录入','智能初选','实地尽调','投委会决策','资产确权','执行处置','审计复盘','已归档')),
    status                  TEXT NOT NULL DEFAULT '进行中'
        CHECK (status IN ('进行中','暂停','已结案','已归档')),
    risk_alerts             JSONB NOT NULL DEFAULT '[]'::jsonb,
    expected_recovery_total NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 预期回款总额(种子自报告，可调)
    actual_recovery_total   NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 实际收款汇总(由 recovery_record 缓存)
    profit_distributable    NUMERIC(18,2) NOT NULL DEFAULT 0,
    profit_distributed      NUMERIC(18,2) NOT NULL DEFAULT 0,
    report_ref              TEXT NOT NULL DEFAULT '',           -- 预期来源报告引用
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.case_progress IS '案件进度看板主表(一案一行)：阶段/状态/风险/预期·实际回款/利润。';
COMMENT ON COLUMN public.case_progress.stage IS '案件阶段(会议业务全流程八阶段)。';
COMMENT ON COLUMN public.case_progress.risk_alerts IS '风险提示列表(报告归零/盲估/缺卷/时效红项 + 人工)。';
COMMENT ON COLUMN public.case_progress.expected_recovery_total IS '预期回款总额(种子自报告 NPV，可人工调)。';
COMMENT ON COLUMN public.case_progress.actual_recovery_total IS '实际收款汇总(由 recovery_record 汇总缓存)。';
COMMENT ON COLUMN public.case_progress.report_ref IS '预期回款来源的报告引用 final_report_ref。';

-- 2) 实际收款明细(一笔一行)
CREATE TABLE IF NOT EXISTS public.recovery_record (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT NOT NULL REFERENCES public.cases(case_id) ON DELETE CASCADE,
    amount          NUMERIC(18,2) NOT NULL,          -- 收款金额(元)
    recovered_at    DATE NOT NULL,
    disposal_path   TEXT NOT NULL DEFAULT '',        -- 清算拍卖/破产重整/协商和解/执行/其它
    related_task_id TEXT NOT NULL DEFAULT '',        -- 关联 SOP 任务 id(外部 task API，可空)
    source_desc     TEXT NOT NULL DEFAULT '',
    operator        TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'confirmed'
        CHECK (status IN ('confirmed','pending')),   -- 人工录=confirmed；LLM自动抽取=pending(需人工确认后才计入)
    origin          TEXT NOT NULL DEFAULT 'manual',   -- manual / ingest_material / chat
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.recovery_record IS '实际收款明细：金额/日期/处置路径/关联 SOP 任务。status=pending 为自动抽取待确认，不计入汇总。';
-- 兼容已部署库
ALTER TABLE public.recovery_record ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'confirmed';
ALTER TABLE public.recovery_record ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'manual';
CREATE INDEX IF NOT EXISTS idx_recovery_record_case ON public.recovery_record(case_id, recovered_at DESC);

-- 3) 预期回款(种子自报告 NPV 三档，可人工调)
CREATE TABLE IF NOT EXISTS public.recovery_forecast (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT NOT NULL REFERENCES public.cases(case_id) ON DELETE CASCADE,
    tranche         TEXT NOT NULL DEFAULT '',        -- T1/T2/T3 或处置路径
    expected_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expected_date   DATE,
    basis           TEXT NOT NULL DEFAULT '报告NPV', -- 报告NPV / 人工
    report_ref      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.recovery_forecast IS '预期回款：种子自报告数值引擎 NPV 三档，可人工调整。';
CREATE INDEX IF NOT EXISTS idx_recovery_forecast_case ON public.recovery_forecast(case_id, created_at DESC);
