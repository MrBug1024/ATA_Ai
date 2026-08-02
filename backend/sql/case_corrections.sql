-- 文字修正 → 权威订正 + 可追溯（Tier 2 决策三）
-- 把会话内 prompt 叠加升级为案件级权威订正：写库、加载期应用、跨会话/跨人生效、可追溯。
-- 与 ai_hunter 共用同一库，首次部署执行本文件。

CREATE TABLE IF NOT EXISTS public.case_correction (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT NOT NULL,
    target          TEXT NOT NULL DEFAULT '',          -- 修正作用的标的/对象
    instruction     TEXT NOT NULL DEFAULT '',          -- 强制修正指令
    source_query    TEXT NOT NULL DEFAULT '',          -- 触发修正的原始用户话术
    operator_id     TEXT NOT NULL DEFAULT '',          -- 操作人 ID（账号体系上线前可空）
    operator_name   TEXT NOT NULL DEFAULT '',          -- 操作人名称
    operator_meta   JSONB NOT NULL DEFAULT '{}'::jsonb, -- 预留：关联 Tier3 账号体系的角色/标签（多选），账号上线后回填
    scope           TEXT NOT NULL DEFAULT '全案',       -- 生效范围（默认全案，可为某资产/某段，free text）
    origin          TEXT NOT NULL DEFAULT 'chat',       -- 来源：chat（对话抽取）/ manual（接口人工录入）
    status          TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','superseded','revoked')),
    superseded_by   BIGINT,                            -- 被哪条订正覆盖（自动 supersede 时回填）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.case_correction IS
'案件权威文字订正表（决策三）：每条记录一次人工/对话订正，写库后由 fetch_full_context 在加载期应用，跨会话/跨人生效，全程可追溯。';
COMMENT ON COLUMN public.case_correction.target IS '修正作用的标的/对象（如某房产、某结论）。';
COMMENT ON COLUMN public.case_correction.instruction IS '强制修正指令（优先级高于原始数据）。';
COMMENT ON COLUMN public.case_correction.source_query IS '触发修正的原始用户话术，供追溯。';
COMMENT ON COLUMN public.case_correction.operator_meta IS '预留字段：账号体系上线后回填操作人角色/专业标签（多选），用于人岗匹配与分权审计。';
COMMENT ON COLUMN public.case_correction.scope IS '生效范围，默认“全案”。';
COMMENT ON COLUMN public.case_correction.status IS 'active=生效中 / superseded=被同标的更新订正覆盖 / revoked=人工撤销。';
COMMENT ON COLUMN public.case_correction.superseded_by IS '自动 supersede 时指向覆盖它的新订正 id。';

-- 查某案存活（active）订正：加载期应用走这个；按时间倒序（最新优先）。
CREATE INDEX IF NOT EXISTS idx_case_correction_active
    ON public.case_correction(case_id, created_at DESC)
    WHERE status = 'active';

-- 按案件全量查（含历史）：供追溯审计接口。
CREATE INDEX IF NOT EXISTS idx_case_correction_case
    ON public.case_correction(case_id, created_at DESC);
