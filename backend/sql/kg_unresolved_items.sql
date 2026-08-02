CREATE TABLE IF NOT EXISTS public.kg_unresolved_item (
    id                   BIGSERIAL PRIMARY KEY,
    case_id              BIGINT NOT NULL REFERENCES public.cases(case_id) ON DELETE CASCADE,
    extraction_run_id    BIGINT NOT NULL REFERENCES public.kg_extraction_run(id) ON DELETE CASCADE,
    upload_batch_id      TEXT NOT NULL DEFAULT '',
    material_event_id    TEXT NOT NULL DEFAULT '',
    item_type            TEXT NOT NULL,
    entity_name          TEXT NOT NULL DEFAULT '',
    entity_key           TEXT NOT NULL DEFAULT '',
    relation_key         TEXT NOT NULL DEFAULT '',
    entity_temp_id       TEXT NOT NULL DEFAULT '',
    relation_temp_id     TEXT NOT NULL DEFAULT '',
    claim_type           TEXT NOT NULL DEFAULT '',
    claim_text           TEXT NOT NULL DEFAULT '',
    relation_type        TEXT NOT NULL DEFAULT '',
    relation_label       TEXT NOT NULL DEFAULT '',
    missing_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason               TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'pending',
    payload              JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved_entity_id   BIGINT REFERENCES public.kg_entity(id) ON DELETE SET NULL,
    resolved_relation_id BIGINT REFERENCES public.kg_relation(id) ON DELETE SET NULL,
    resolved_claim_id    BIGINT REFERENCES public.kg_claim(id) ON DELETE SET NULL,
    resolved_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.kg_unresolved_item IS '图谱未决项表；保存因跨批依赖未满足、临时引用不自洽等原因暂时无法落库的 relation 或 claim，供后续批次补齐后回捞重放。';
COMMENT ON COLUMN public.kg_unresolved_item.id IS '未决项主键 ID。';
COMMENT ON COLUMN public.kg_unresolved_item.case_id IS '案件 ID；用于按案件归集未决 relation / claim。';
COMMENT ON COLUMN public.kg_unresolved_item.extraction_run_id IS '产生该未决项的抽取任务 ID；便于追踪是哪一轮 ingest / re_audit 生成的。';
COMMENT ON COLUMN public.kg_unresolved_item.upload_batch_id IS '触发该未决项的上传批次 ID；用于和补件批次、文件列表联动查看。';
COMMENT ON COLUMN public.kg_unresolved_item.material_event_id IS '触发该未决项的材料事件 ID；用于后续把未决治理挂到统一事件模型上。';
COMMENT ON COLUMN public.kg_unresolved_item.item_type IS '未决项类型；当前约定为 relation 或 claim。';
COMMENT ON COLUMN public.kg_unresolved_item.entity_name IS '未决项相关实体名称；跨批补齐时可作为名称级兜底锚点。';
COMMENT ON COLUMN public.kg_unresolved_item.entity_key IS '未决项相关实体稳定键；若已知，可作为跨批自动重连的一等锚点。';
COMMENT ON COLUMN public.kg_unresolved_item.relation_key IS '未决项相关关系稳定键；若已知，可用于后续精确回捞和重放。';
COMMENT ON COLUMN public.kg_unresolved_item.entity_temp_id IS '本批抽取时的临时实体 ID；用于回放本轮上下文和排查 temp_id 断链。';
COMMENT ON COLUMN public.kg_unresolved_item.relation_temp_id IS '本批抽取时的临时关系 ID；用于回放本轮上下文和排查 relation 断链。';
COMMENT ON COLUMN public.kg_unresolved_item.claim_type IS '若 item_type=claim，则记录 claim 类型。';
COMMENT ON COLUMN public.kg_unresolved_item.claim_text IS '若 item_type=claim，则记录 claim 原文，供人工复核和文本级回捞。';
COMMENT ON COLUMN public.kg_unresolved_item.relation_type IS '若 item_type=relation，则记录关系类型编码。';
COMMENT ON COLUMN public.kg_unresolved_item.relation_label IS '若 item_type=relation，则记录关系显示标签。';
COMMENT ON COLUMN public.kg_unresolved_item.missing_dependencies IS '当前缺失的依赖项列表；如 entity、relation、from_entity、to_entity。';
COMMENT ON COLUMN public.kg_unresolved_item.reason IS '未能在当前批次落库的直接原因，如 missing_graph_reference。';
COMMENT ON COLUMN public.kg_unresolved_item.status IS '未决治理状态；默认 pending，后续可扩展 resolved、ignored、replayed_failed 等。';
COMMENT ON COLUMN public.kg_unresolved_item.payload IS '原始未决明细 JSON；保留当前批次上下文，供后续回捞重放与问题排查。';
COMMENT ON COLUMN public.kg_unresolved_item.resolved_entity_id IS '若后续补齐成功，可回填最终关联的 entity_id。';
COMMENT ON COLUMN public.kg_unresolved_item.resolved_relation_id IS '若后续补齐成功，可回填最终关联的 relation_id。';
COMMENT ON COLUMN public.kg_unresolved_item.resolved_claim_id IS '若后续补齐成功，可回填最终落库的 claim_id。';
COMMENT ON COLUMN public.kg_unresolved_item.resolved_at IS '该未决项被成功解析或人工处理完成的时间。';
COMMENT ON COLUMN public.kg_unresolved_item.created_at IS '未决项创建时间。';
COMMENT ON COLUMN public.kg_unresolved_item.updated_at IS '未决项最近更新时间。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_unresolved_item_case_status_idx
    ON public.kg_unresolved_item(case_id, status, created_at DESC);

COMMENT ON INDEX public.kg_unresolved_item_case_status_idx IS '按案件与未决状态查看最新未决项的加速索引。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_unresolved_item_batch_idx
    ON public.kg_unresolved_item(upload_batch_id, created_at DESC);

COMMENT ON INDEX public.kg_unresolved_item_batch_idx IS '按上传批次查看该批次产生的未决项。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_unresolved_item_event_idx
    ON public.kg_unresolved_item(material_event_id, created_at DESC);

COMMENT ON INDEX public.kg_unresolved_item_event_idx IS '按材料事件查看该次补件引发的未决项。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_unresolved_item_entity_relation_idx
    ON public.kg_unresolved_item(case_id, entity_key, relation_key, status);

COMMENT ON INDEX public.kg_unresolved_item_entity_relation_idx IS '按实体键和关系键筛选待回捞的未决项，服务跨批补齐重放。';
