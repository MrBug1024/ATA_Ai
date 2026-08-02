-- ============================================================================
-- AI 猎手 — 任务管理模块（补丁）
-- 报告输出后自动生成结构化任务 + 对话中可追踪/更新状态
-- ============================================================================

CREATE TABLE tasks (
    task_id         BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    -- 任务内容
    task_no         INT,                              -- 任务序号（报告中的任务N）
    action          TEXT NOT NULL,                    -- 动作简述
    detail          TEXT,                             -- 详细说明
    -- 分派
    assigned_role   TEXT,                             -- 执行角色：法务/调查/审计
    assigned_to     TEXT,                             -- 具体指派人（可空，后续填）
    -- 时限
    deadline        DATE,                             -- 推荐完成时限
    -- 验收
    deliverable     TEXT,                             -- 验收交付物描述
    -- 状态
    status          TEXT DEFAULT '待执行' CHECK (status IN ('待执行','进行中','已完成','已取消','逾期')),
    priority        TEXT DEFAULT '中' CHECK (priority IN ('紧急','高','中','低')),
    -- 关联
    source_engine   TEXT,                             -- 来源引擎：engine_1/engine_2/engine_3/engine_4/manual
    related_alert_id BIGINT,                          -- 关联时效预警ID（如有）
    -- 执行记录
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    completion_note TEXT,                             -- 完成备注/回执说明
    -- 元数据
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

COMMENT ON TABLE tasks IS '任务督办表：审计报告SOP自动生成的结构化任务，支持状态追踪和验收闭环';
COMMENT ON COLUMN tasks.task_id IS '任务唯一标识';
COMMENT ON COLUMN tasks.case_id IS '所属案件ID';
COMMENT ON COLUMN tasks.task_no IS '任务序号（对应报告中的任务N）';
COMMENT ON COLUMN tasks.action IS '动作简述（如：申请续封XX厂房）';
COMMENT ON COLUMN tasks.detail IS '详细操作说明';
COMMENT ON COLUMN tasks.assigned_role IS '执行角色：法务/调查/审计';
COMMENT ON COLUMN tasks.assigned_to IS '具体指派人姓名（可后续填入）';
COMMENT ON COLUMN tasks.deadline IS '推荐完成时限';
COMMENT ON COLUMN tasks.deliverable IS '验收交付物（如：续封裁定书/立案通知书）';
COMMENT ON COLUMN tasks.status IS '任务状态：待执行/进行中/已完成/已取消/逾期';
COMMENT ON COLUMN tasks.priority IS '优先级：紧急/高/中/低';
COMMENT ON COLUMN tasks.source_engine IS '任务来源引擎：engine_1/engine_2/engine_3/engine_4/manual';
COMMENT ON COLUMN tasks.related_alert_id IS '关联时效预警ID（来源于deadline_alerts的任务）';
COMMENT ON COLUMN tasks.started_at IS '实际开始时间';
COMMENT ON COLUMN tasks.completed_at IS '实际完成时间';
COMMENT ON COLUMN tasks.completion_note IS '完成备注/回执说明/结果摘要';
COMMENT ON COLUMN tasks.created_at IS '记录创建时间';
COMMENT ON COLUMN tasks.updated_at IS '记录最后更新时间';

CREATE INDEX idx_tasks_case ON tasks(case_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_deadline ON tasks(deadline);
CREATE INDEX idx_tasks_priority ON tasks(priority);
