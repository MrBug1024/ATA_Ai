CREATE TABLE IF NOT EXISTS public.material_event (
    material_event_id TEXT PRIMARY KEY,
    case_id           BIGINT NOT NULL REFERENCES public.cases(case_id) ON DELETE CASCADE,
    debtor_id         BIGINT NOT NULL DEFAULT 0,
    upload_batch_id   TEXT NOT NULL DEFAULT '',
    event_type        TEXT NOT NULL DEFAULT 'supplement_upload',
    status            TEXT NOT NULL DEFAULT 'received',
    batch_name        TEXT NOT NULL DEFAULT '',
    doc_category      TEXT NOT NULL DEFAULT '',
    operator_id       TEXT NOT NULL DEFAULT '',
    operator_name     TEXT NOT NULL DEFAULT '',
    file_count        INTEGER NOT NULL DEFAULT 0,
    records_inserted  INTEGER NOT NULL DEFAULT 0,
    event_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message     TEXT NOT NULL DEFAULT '',
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    failed_at         TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.material_event IS '材料事件表；描述一次上传或追加补件事件的最小边界，用于把批次、状态、增量影响与后续演进展示挂到统一事件对象上。';
COMMENT ON COLUMN public.material_event.material_event_id IS '材料事件主键；当前默认由 material-event:{upload_batch_id} 生成。';
COMMENT ON COLUMN public.material_event.case_id IS '所属案件 ID。';
COMMENT ON COLUMN public.material_event.debtor_id IS '所属债务人 ID；未知时允许为 0。';
COMMENT ON COLUMN public.material_event.upload_batch_id IS '关联上传批次 ID；与 source_upload_batch 保持一对一或等价关系。';
COMMENT ON COLUMN public.material_event.event_type IS '事件类型；当前最小约定为 supplement_upload。';
COMMENT ON COLUMN public.material_event.status IS '事件状态；当前最小约定为 received、processing、completed、failed。';
COMMENT ON COLUMN public.material_event.batch_name IS '操作员侧批次名称。';
COMMENT ON COLUMN public.material_event.doc_category IS '本次事件处理的卷宗类别。';
COMMENT ON COLUMN public.material_event.operator_id IS '触发该事件的操作员 ID。';
COMMENT ON COLUMN public.material_event.operator_name IS '触发该事件的操作员名称。';
COMMENT ON COLUMN public.material_event.file_count IS '本次事件上传文件数。';
COMMENT ON COLUMN public.material_event.records_inserted IS '本次事件经 ingest / parse 后新增或更新的结构化记录数。';
COMMENT ON COLUMN public.material_event.event_payload IS '事件扩展载荷；保留类别识别、状态摘要、结论变化等后续字段。';
COMMENT ON COLUMN public.material_event.error_message IS '失败事件的错误信息；成功时为空。';
COMMENT ON COLUMN public.material_event.started_at IS '事件进入 processing 的时间。';
COMMENT ON COLUMN public.material_event.completed_at IS '事件处理完成时间。';
COMMENT ON COLUMN public.material_event.failed_at IS '事件失败时间。';
COMMENT ON COLUMN public.material_event.created_at IS '事件创建时间。';
COMMENT ON COLUMN public.material_event.updated_at IS '事件最近更新时间。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS material_event_case_created_idx
    ON public.material_event(case_id, created_at DESC);

COMMENT ON INDEX public.material_event_case_created_idx IS '按案件查看最近材料事件列表。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS material_event_batch_idx
    ON public.material_event(upload_batch_id, created_at DESC);

COMMENT ON INDEX public.material_event_batch_idx IS '按上传批次查看材料事件。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS material_event_status_idx
    ON public.material_event(status, created_at DESC);

COMMENT ON INDEX public.material_event_status_idx IS '按状态查看最近材料事件。';
