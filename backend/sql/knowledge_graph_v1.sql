-- AI Hunter 数据可追溯与知识图谱 v1 初始化脚本
-- 用途：
-- 1. 为案件材料建立 文件 -> 页 -> chunk 的可追溯证据链路
-- 2. 为知识图谱建立 entity / relation / claim / evidence_link 的主数据结构
-- 3. 先落地在 PostgreSQL + pgvector 上，不引入新的图数据库基础设施
-- 4. 不删除任何现有对象，仅新增表、索引、注释与必要扩展

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

COMMENT ON EXTENSION vector IS 'pgvector 扩展，用于保存 source_chunk.embedding 向量并支撑后续 chunk 级相似度检索。';

CREATE TABLE IF NOT EXISTS public.source_file (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    entity_id BIGINT NOT NULL DEFAULT 0,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    file_sha256 CHAR(64) NOT NULL,
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    storage_ref TEXT NOT NULL DEFAULT '',
    ingest_payload_ref TEXT NOT NULL DEFAULT '',
    ocr_provider TEXT NOT NULL DEFAULT '',
    ocr_version TEXT NOT NULL DEFAULT '',
    parser_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.source_file IS '原始材料文件主表；一条记录代表某案件中的一个源文件，是页表、chunk表和后续证据回源的最上游锚点。';
COMMENT ON COLUMN public.source_file.id IS '文件主键 ID；供 source_page、source_chunk、kg_evidence_link 等下游表作为外键引用。';
COMMENT ON COLUMN public.source_file.case_id IS '案件 ID；用于把文件归属到具体案件，并支持案件级检索和隔离。';
COMMENT ON COLUMN public.source_file.entity_id IS '被审计单位实体 ID；由年度审计项目主数据确定，未知时保留 0。';
COMMENT ON COLUMN public.source_file.file_name IS '原始文件名；用于前端展示、人工核查和证据面板回显。';
COMMENT ON COLUMN public.source_file.file_type IS '文件业务类型；如 document、image、text，用于区分 OCR/直读策略。';
COMMENT ON COLUMN public.source_file.content_type IS '上传时的 MIME 类型；用于保留前端上传的原始文件类型信息。';
COMMENT ON COLUMN public.source_file.file_sha256 IS '原始文件二进制内容的 SHA256；用于同案文件去重与稳定识别。';
COMMENT ON COLUMN public.source_file.file_size_bytes IS '原始文件字节大小；用于运维排查、限流与异常文件识别。';
COMMENT ON COLUMN public.source_file.storage_ref IS '原始文件存储引用；可对接对象存储 key、本地路径或内部文件服务引用。';
COMMENT ON COLUMN public.source_file.ingest_payload_ref IS '与该文件相关的 ingest payload 引用；通常指向 heavy payload 中的上传批次信息。';
COMMENT ON COLUMN public.source_file.ocr_provider IS 'OCR 服务提供方；如内部 OCR、第三方 OCR，用于追踪文本来源。';
COMMENT ON COLUMN public.source_file.ocr_version IS 'OCR 解析版本号；用于回溯不同 OCR 版本造成的抽取差异。';
COMMENT ON COLUMN public.source_file.parser_version IS '文件切页、切 chunk、清洗文本所使用的解析器版本。';
COMMENT ON COLUMN public.source_file.status IS '文件记录状态；默认 active，后续可扩展为 archived、deleted_soft 等软状态。';
COMMENT ON COLUMN public.source_file.created_at IS '文件记录创建时间。';
COMMENT ON COLUMN public.source_file.updated_at IS '文件记录最后更新时间；文件元数据变更时应同步刷新。';

CREATE TABLE IF NOT EXISTS public.source_page (
    id BIGSERIAL PRIMARY KEY,
    file_id BIGINT NOT NULL REFERENCES public.source_file(id) ON DELETE CASCADE,
    page_no INT NOT NULL,
    page_text TEXT NOT NULL DEFAULT '',
    page_image_ref TEXT NOT NULL DEFAULT '',
    page_width INT NOT NULL DEFAULT 0,
    page_height INT NOT NULL DEFAULT 0,
    ocr_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.source_page IS '文件分页结果表；一条记录代表文件中的一页，是 bbox 坐标、页图预览和页级文本回源的基础。';
COMMENT ON COLUMN public.source_page.id IS '页主键 ID；供 source_chunk 通过 page_id 精确挂接到具体页。';
COMMENT ON COLUMN public.source_page.file_id IS '所属文件 ID；外键指向 source_file，文件删除时该文件页级记录自动级联删除。';
COMMENT ON COLUMN public.source_page.page_no IS '页码；从 1 开始，供前端 PDF 定位和后端页级检索使用。';
COMMENT ON COLUMN public.source_page.page_text IS '该页归并后的完整文本；可用于页级快速预览与文本兜底检索。';
COMMENT ON COLUMN public.source_page.page_image_ref IS '页图引用；供前端在 PDF/图片预览面板中按页加载底图。';
COMMENT ON COLUMN public.source_page.page_width IS '页图宽度；与 bbox 坐标一起决定前端高亮框的缩放计算。';
COMMENT ON COLUMN public.source_page.page_height IS '页图高度；与 bbox 坐标一起决定前端高亮框的缩放计算。';
COMMENT ON COLUMN public.source_page.ocr_blocks IS 'OCR 块级原始结果；保存文本块、行块或区域块，供 chunk 切分与定位重建使用。';
COMMENT ON COLUMN public.source_page.created_at IS '页记录创建时间。';

CREATE TABLE IF NOT EXISTS public.source_chunk (
    id BIGSERIAL PRIMARY KEY,
    chunk_id CHAR(64) NOT NULL UNIQUE,
    case_id BIGINT NOT NULL,
    file_id BIGINT NOT NULL REFERENCES public.source_file(id) ON DELETE CASCADE,
    page_id BIGINT NOT NULL REFERENCES public.source_page(id) ON DELETE CASCADE,
    page_no INT NOT NULL,
    chunk_index INT NOT NULL,
    chunk_type TEXT NOT NULL DEFAULT 'text',
    chunk_text TEXT NOT NULL,
    chunk_text_sha256 CHAR(64) NOT NULL,
    anchor_text TEXT NOT NULL DEFAULT '',
    bbox_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    span_start INT NOT NULL DEFAULT 0,
    span_end INT NOT NULL DEFAULT 0,
    token_count INT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.source_chunk IS '证据切片表；图谱、报告、Agent 回答都只能引用 chunk，不允许直接引用最终生成报告。';
COMMENT ON COLUMN public.source_chunk.id IS 'chunk 自增主键；主要供内部表连接与数据维护使用。';
COMMENT ON COLUMN public.source_chunk.chunk_id IS '稳定 chunk ID；建议由 case_id、file_sha256、page_no、chunk_index、chunk_text_sha256 组合哈希生成。';
COMMENT ON COLUMN public.source_chunk.case_id IS '案件 ID；用于按案件快速检索所有证据 chunk。';
COMMENT ON COLUMN public.source_chunk.file_id IS '所属文件 ID；外键指向 source_file。';
COMMENT ON COLUMN public.source_chunk.page_id IS '所属页 ID；外键指向 source_page，可精确回到文件中的某一页。';
COMMENT ON COLUMN public.source_chunk.page_no IS '页码冗余字段；便于无需 join source_page 即可完成常见页级查询。';
COMMENT ON COLUMN public.source_chunk.chunk_index IS '页内 chunk 顺序号；用于重建同页 chunk 的原始顺序。';
COMMENT ON COLUMN public.source_chunk.chunk_type IS 'chunk 类型；如 text、table、title、ocr_error，用于后续分类处理。';
COMMENT ON COLUMN public.source_chunk.chunk_text IS 'chunk 正文文本；LLM 抽取 entity/relation/claim 的直接输入事实源。';
COMMENT ON COLUMN public.source_chunk.chunk_text_sha256 IS 'chunk 文本 SHA256；用于比对文本是否变化，并参与 chunk_id 的稳定生成。';
COMMENT ON COLUMN public.source_chunk.anchor_text IS '证据锚文本；通常是便于人工识别的短句或截断预览。';
COMMENT ON COLUMN public.source_chunk.bbox_list IS '该 chunk 对应的坐标框列表；前端高亮、证据抽屉定位直接依赖该字段。';
COMMENT ON COLUMN public.source_chunk.span_start IS 'chunk 在 page_text 或上游切分文本中的起始字符位置。';
COMMENT ON COLUMN public.source_chunk.span_end IS 'chunk 在 page_text 或上游切分文本中的结束字符位置。';
COMMENT ON COLUMN public.source_chunk.token_count IS 'chunk 近似 token 数；用于后续抽取批量切分和上下文控制。';
COMMENT ON COLUMN public.source_chunk.metadata IS 'chunk 扩展元数据；可保存分类标签、OCR 置信度、切分策略等非固定属性。';
COMMENT ON COLUMN public.source_chunk.embedding IS 'chunk 向量；供后续 chunk 级混合检索、证据召回和相似段落搜索使用。';
COMMENT ON COLUMN public.source_chunk.created_at IS 'chunk 记录创建时间。';

CREATE TABLE IF NOT EXISTS public.kg_extraction_run (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    run_type TEXT NOT NULL DEFAULT 'ingest',
    trigger_source TEXT NOT NULL DEFAULT 'system',
    source_file_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    chunk_count INT NOT NULL DEFAULT 0,
    prompt_version TEXT NOT NULL DEFAULT '',
    model_provider TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

COMMENT ON TABLE public.kg_extraction_run IS '知识图谱抽取运行表；一条记录代表一次完整的图谱抽取任务，用于审计、重跑和问题排查。';
COMMENT ON COLUMN public.kg_extraction_run.id IS '抽取任务主键 ID；供 kg_claim 关联到具体哪一轮抽取。';
COMMENT ON COLUMN public.kg_extraction_run.case_id IS '案件 ID；表示本轮抽取针对哪个案件执行。';
COMMENT ON COLUMN public.kg_extraction_run.run_type IS '运行类型；如 ingest、rebuild、repair，用于区分首次抽取和重建任务。';
COMMENT ON COLUMN public.kg_extraction_run.trigger_source IS '触发来源；如 system、user、scheduler，表示由谁或什么流程触发。';
COMMENT ON COLUMN public.kg_extraction_run.source_file_ids IS '参与本轮抽取的文件 ID 列表；便于回溯本次图谱是基于哪些材料构建的。';
COMMENT ON COLUMN public.kg_extraction_run.chunk_count IS '本轮抽取实际处理的 chunk 数量。';
COMMENT ON COLUMN public.kg_extraction_run.prompt_version IS '本轮 LLM 抽取所使用的 prompt 版本。';
COMMENT ON COLUMN public.kg_extraction_run.model_provider IS '本轮抽取所使用的模型供应商，如 minimax、kimi、faker。';
COMMENT ON COLUMN public.kg_extraction_run.model_name IS '本轮抽取所使用的具体模型名称。';
COMMENT ON COLUMN public.kg_extraction_run.status IS '运行状态；如 running、completed、failed，用于任务跟踪。';
COMMENT ON COLUMN public.kg_extraction_run.error_message IS '失败或异常信息；运行成功时通常为空字符串。';
COMMENT ON COLUMN public.kg_extraction_run.started_at IS '抽取任务开始时间。';
COMMENT ON COLUMN public.kg_extraction_run.finished_at IS '抽取任务结束时间；未结束时为空。';

CREATE TABLE IF NOT EXISTS public.kg_entity (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    entity_key CHAR(64) NOT NULL,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    normalized_name TEXT NOT NULL DEFAULT '',
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_chunk_id CHAR(64) NOT NULL DEFAULT '',
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0,
    source_count INT NOT NULL DEFAULT 0,
    human_verified BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.kg_entity IS '案件级知识图谱实体表；保存人、企业、资产、合同、账户等可被关系连接的图谱节点。';
COMMENT ON COLUMN public.kg_entity.id IS '实体主键 ID；供 kg_relation 和业务查询引用。';
COMMENT ON COLUMN public.kg_entity.case_id IS '案件 ID；同名实体在不同案件中默认分开存储，避免跨案污染。';
COMMENT ON COLUMN public.kg_entity.entity_key IS '实体稳定键；建议由 case_id、entity_type、normalized_name 哈希生成，用于幂等 upsert。';
COMMENT ON COLUMN public.kg_entity.entity_type IS '实体类型；如 company、person、asset、contract、account。';
COMMENT ON COLUMN public.kg_entity.canonical_name IS '实体规范显示名；前端图谱和报告默认展示该名称。';
COMMENT ON COLUMN public.kg_entity.aliases IS '实体别名列表；保存简称、曾用名、OCR 变体等辅助归并信息。';
COMMENT ON COLUMN public.kg_entity.normalized_name IS '归一化名称；用于去空格、去噪、统一括号等后续实体合并计算。';
COMMENT ON COLUMN public.kg_entity.attributes IS '实体扩展属性；如统一社会信用代码、身份证号片段、资产编号等结构化信息。';
COMMENT ON COLUMN public.kg_entity.first_seen_chunk_id IS '首次发现该实体的 chunk_id；便于快速回源到最早出现位置。';
COMMENT ON COLUMN public.kg_entity.confidence IS '实体归一结果置信度；由抽取或归并流程给出。';
COMMENT ON COLUMN public.kg_entity.source_count IS '该实体被多少个证据 chunk 支撑或提及的计数。';
COMMENT ON COLUMN public.kg_entity.human_verified IS '是否已被人工确认；人工确认后可在后续重跑中作为高优先级事实。';
COMMENT ON COLUMN public.kg_entity.status IS '实体状态；默认 active，后续可扩展 merged、deprecated 等状态。';
COMMENT ON COLUMN public.kg_entity.created_at IS '实体记录创建时间。';
COMMENT ON COLUMN public.kg_entity.updated_at IS '实体记录最后更新时间。';

CREATE TABLE IF NOT EXISTS public.kg_relation (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    relation_key CHAR(64) NOT NULL,
    from_entity_id BIGINT NOT NULL REFERENCES public.kg_entity(id) ON DELETE CASCADE,
    to_entity_id BIGINT NOT NULL REFERENCES public.kg_entity(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    relation_label TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'directed',
    amount NUMERIC(20,2),
    amount_currency TEXT NOT NULL DEFAULT 'CNY',
    event_date DATE,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0,
    source_count INT NOT NULL DEFAULT 0,
    human_verified BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.kg_relation IS '案件级知识图谱关系表；保存实体之间的担保、股权、资金、诉讼、查封等边关系。';
COMMENT ON COLUMN public.kg_relation.id IS '关系主键 ID；供图谱查询和前端点击关系查看证据时使用。';
COMMENT ON COLUMN public.kg_relation.case_id IS '案件 ID；用于隔离不同案件中的关系网络。';
COMMENT ON COLUMN public.kg_relation.relation_key IS '关系稳定键；建议由 case_id、from_entity_key、to_entity_key、relation_type 等组合哈希生成。';
COMMENT ON COLUMN public.kg_relation.from_entity_id IS '关系起点实体 ID；通常对应主体、担保方、付款方或发起方。';
COMMENT ON COLUMN public.kg_relation.to_entity_id IS '关系终点实体 ID；通常对应被担保方、收款方、目标资产或被执行对象。';
COMMENT ON COLUMN public.kg_relation.relation_type IS '关系类型编码；如 guarantee、shareholding、bank_flow、litigation。';
COMMENT ON COLUMN public.kg_relation.relation_label IS '关系显示标签；供前端图谱边文案或报告表述直接使用。';
COMMENT ON COLUMN public.kg_relation.direction IS '关系方向；directed 表示有向边，undirected 表示无向边。';
COMMENT ON COLUMN public.kg_relation.amount IS '与该关系直接相关的金额；如交易金额、凭证金额或账户余额。';
COMMENT ON COLUMN public.kg_relation.amount_currency IS '金额币种；默认 CNY，可扩展其他币种。';
COMMENT ON COLUMN public.kg_relation.event_date IS '关系发生或生效日期；如转账日期、查封日期、合同签署日期。';
COMMENT ON COLUMN public.kg_relation.attributes IS '关系扩展属性；保存合同编号、比例、期限、法院案号等非固定字段。';
COMMENT ON COLUMN public.kg_relation.confidence IS '关系抽取或融合后的置信度。';
COMMENT ON COLUMN public.kg_relation.source_count IS '支撑该关系的证据数量或证据提及次数。';
COMMENT ON COLUMN public.kg_relation.human_verified IS '是否已被人工确认；人工确认后应视为更高优先级事实。';
COMMENT ON COLUMN public.kg_relation.status IS '关系状态；默认 active，可扩展 superseded、deprecated 等状态。';
COMMENT ON COLUMN public.kg_relation.created_at IS '关系记录创建时间。';
COMMENT ON COLUMN public.kg_relation.updated_at IS '关系记录最后更新时间。';

CREATE TABLE IF NOT EXISTS public.kg_claim (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    extraction_run_id BIGINT NOT NULL REFERENCES public.kg_extraction_run(id) ON DELETE CASCADE,
    entity_id BIGINT REFERENCES public.kg_entity(id) ON DELETE SET NULL,
    relation_id BIGINT REFERENCES public.kg_relation(id) ON DELETE SET NULL,
    claim_type TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_value JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0,
    prompt_version TEXT NOT NULL DEFAULT '',
    model_provider TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    parser_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.kg_claim IS '图谱断言表；一条记录代表模型或规则抽取出的一个原子判断，用于隔离大模型断言与最终图谱事实。';
COMMENT ON COLUMN public.kg_claim.id IS '断言主键 ID；前端 citation、人工审核和证据回源通常围绕该 ID 展开。';
COMMENT ON COLUMN public.kg_claim.case_id IS '案件 ID；用于断言级检索和案件隔离。';
COMMENT ON COLUMN public.kg_claim.extraction_run_id IS '所属抽取任务 ID；表示该 claim 来自哪一轮知识图谱抽取。';
COMMENT ON COLUMN public.kg_claim.entity_id IS '关联实体 ID；当 claim 描述的是某个单实体事实时填写，如“企业已被吊销”。';
COMMENT ON COLUMN public.kg_claim.relation_id IS '关联关系 ID；当 claim 描述的是某条关系事实时填写，如“甲为乙提供担保”。';
COMMENT ON COLUMN public.kg_claim.claim_type IS '断言类型；如 entity_fact、relation_fact、event_fact、risk_signal。';
COMMENT ON COLUMN public.kg_claim.claim_text IS '断言自然语言文本；供人工审核、报告引用和前端展示使用。';
COMMENT ON COLUMN public.kg_claim.claim_value IS '断言结构化值；可保存金额、日期、比例、状态枚举等解析后的结果。';
COMMENT ON COLUMN public.kg_claim.confidence IS '该断言的置信度；由抽取模型或规则评分给出。';
COMMENT ON COLUMN public.kg_claim.prompt_version IS '生成该断言时所使用的 prompt 版本。';
COMMENT ON COLUMN public.kg_claim.model_provider IS '生成该断言时所使用的模型厂商。';
COMMENT ON COLUMN public.kg_claim.model_name IS '生成该断言时所使用的具体模型名称。';
COMMENT ON COLUMN public.kg_claim.parser_version IS '生成该断言时所依赖的文本解析器版本。';
COMMENT ON COLUMN public.kg_claim.status IS '断言事实状态；默认 active，用于支持 superseded、invalid 等软失效语义。';
COMMENT ON COLUMN public.kg_claim.review_status IS '人工审核状态；如 pending、approved、rejected、corrected。';
COMMENT ON COLUMN public.kg_claim.created_at IS '断言记录创建时间。';
COMMENT ON COLUMN public.kg_claim.updated_at IS '断言记录最后更新时间。';

CREATE TABLE IF NOT EXISTS public.kg_evidence_link (
    id BIGSERIAL PRIMARY KEY,
    claim_id BIGINT NOT NULL REFERENCES public.kg_claim(id) ON DELETE CASCADE,
    chunk_id CHAR(64) NOT NULL REFERENCES public.source_chunk(chunk_id) ON DELETE CASCADE,
    file_id BIGINT NOT NULL REFERENCES public.source_file(id) ON DELETE CASCADE,
    page_no INT NOT NULL,
    quote_text TEXT NOT NULL DEFAULT '',
    bbox_list JSONB NOT NULL DEFAULT '[]'::jsonb,
    score NUMERIC(5,4) NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.kg_evidence_link IS '断言到证据 chunk 的映射表；是报告角标回源、图谱点击看证据和前端高亮定位的核心桥表。';
COMMENT ON COLUMN public.kg_evidence_link.id IS '证据映射主键 ID。';
COMMENT ON COLUMN public.kg_evidence_link.claim_id IS '关联 claim ID；表示该证据支撑哪一条断言。';
COMMENT ON COLUMN public.kg_evidence_link.chunk_id IS '关联 chunk_id；回源时优先通过该字段定位到 source_chunk。';
COMMENT ON COLUMN public.kg_evidence_link.file_id IS '所属文件 ID；供前端直接加载原文件或页图。';
COMMENT ON COLUMN public.kg_evidence_link.page_no IS '页码；便于前端直接跳页，无需额外 join source_page 才知道页号。';
COMMENT ON COLUMN public.kg_evidence_link.quote_text IS '证据引用文本；通常是该 chunk 中与 claim 最相关的原文片段。';
COMMENT ON COLUMN public.kg_evidence_link.bbox_list IS '证据高亮坐标列表；前端 PDF.js 或图片预览直接据此绘制高亮框。';
COMMENT ON COLUMN public.kg_evidence_link.score IS '证据与断言的匹配分数；用于多条证据排序和主证据挑选。';
COMMENT ON COLUMN public.kg_evidence_link.created_at IS '证据映射创建时间。';

CREATE TABLE IF NOT EXISTS public.report_citation_map (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    report_ref TEXT NOT NULL,
    citation_id TEXT NOT NULL,
    claim_id BIGINT NOT NULL REFERENCES public.kg_claim(id) ON DELETE CASCADE,
    report_section TEXT NOT NULL DEFAULT '',
    ordinal INT NOT NULL DEFAULT 0,
    paragraph_index INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.report_citation_map IS '报告引用映射表；把某一版报告里的 citation_id 映射到具体 claim_id，供前端点击角标后精确回源。';
COMMENT ON COLUMN public.report_citation_map.id IS '映射主键 ID。';
COMMENT ON COLUMN public.report_citation_map.case_id IS '案件 ID；用于案件级隔离与查询。';
COMMENT ON COLUMN public.report_citation_map.report_ref IS '报告引用 ID；通常对应 final_report heavy payload ref。';
COMMENT ON COLUMN public.report_citation_map.citation_id IS '报告内角标 ID；例如 1、2、3。';
COMMENT ON COLUMN public.report_citation_map.claim_id IS '被该角标引用的 claim_id。';
COMMENT ON COLUMN public.report_citation_map.report_section IS '角标所在报告段或区域；如 report_part_a、report_part_b、kg_trace_appendix。';
COMMENT ON COLUMN public.report_citation_map.ordinal IS '本报告内的角标顺序号；通常与 citation_id 对应。';
COMMENT ON COLUMN public.report_citation_map.paragraph_index IS '角标所在段落序号；暂未精确切分时可保留 0。';
COMMENT ON COLUMN public.report_citation_map.created_at IS '映射记录创建时间。';

CREATE TABLE IF NOT EXISTS public.kg_reconciliation_ledger (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    action TEXT NOT NULL DEFAULT 'ADD',
    new_claim_id BIGINT NOT NULL REFERENCES public.kg_claim(id) ON DELETE CASCADE,
    superseded_claim_id BIGINT REFERENCES public.kg_claim(id) ON DELETE SET NULL,
    new_relation_id BIGINT REFERENCES public.kg_relation(id) ON DELETE SET NULL,
    superseded_relation_id BIGINT REFERENCES public.kg_relation(id) ON DELETE SET NULL,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.kg_reconciliation_ledger IS '图谱增量对账台账；记录新增 claim 如何通过 ADD 或 OVERRIDE 影响历史结论。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.id IS '增量对账台账主键 ID。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.case_id IS '案件 ID；用于案件级查询本案所有历史对账记录。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.action IS '对账动作；ADD 表示新增补充，OVERRIDE 表示推翻旧结论。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.new_claim_id IS '本次新增 claim_id；表示哪条新断言触发了本次对账。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.superseded_claim_id IS '若为 OVERRIDE，则记录被软失效的旧 claim_id。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.new_relation_id IS '本次新增 claim 所关联的新 relation_id；无关系型 claim 时可为空。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.superseded_relation_id IS '若本次同时推翻旧 relation，则记录其 relation_id。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.rationale IS '对账原因说明；供前端展示“为什么这条旧结论失效了”。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.evidence_chunk_ids IS '支撑本次裁决的新增证据 chunk_id 列表。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.decision_payload IS '结构化裁决保留字段；可存 matched_by、llm 决策原文摘要等附加信息。';
COMMENT ON COLUMN public.kg_reconciliation_ledger.created_at IS '台账记录创建时间。';

COMMIT;

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS source_file_case_sha256_ux
    ON public.source_file(case_id, file_sha256);

COMMENT ON INDEX public.source_file_case_sha256_ux IS '同一案件内按文件 SHA256 去重的唯一索引，避免重复摄入完全相同的文件。';

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS source_page_file_page_no_ux
    ON public.source_page(file_id, page_no);

COMMENT ON INDEX public.source_page_file_page_no_ux IS '同一文件内页码唯一索引，保证每个 file_id + page_no 只对应一条页记录。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS source_chunk_case_id_idx
    ON public.source_chunk(case_id);

COMMENT ON INDEX public.source_chunk_case_id_idx IS '按案件检索所有证据 chunk 的加速索引。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS source_chunk_file_page_idx
    ON public.source_chunk(file_id, page_no);

COMMENT ON INDEX public.source_chunk_file_page_idx IS '按文件和页码回源 chunk 的加速索引，服务前端分页证据定位。';

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS kg_entity_case_entity_key_ux
    ON public.kg_entity(case_id, entity_key);

COMMENT ON INDEX public.kg_entity_case_entity_key_ux IS '案件内实体稳定键唯一索引，用于实体 upsert 与归并幂等。';

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS kg_relation_case_relation_key_ux
    ON public.kg_relation(case_id, relation_key);

COMMENT ON INDEX public.kg_relation_case_relation_key_ux IS '案件内关系稳定键唯一索引，用于关系 upsert 与归并幂等。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_relation_case_from_to_idx
    ON public.kg_relation(case_id, from_entity_id, to_entity_id);

COMMENT ON INDEX public.kg_relation_case_from_to_idx IS '按案件与起止实体检索关系边的加速索引，服务子图和关系追踪查询。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_claim_case_id_idx
    ON public.kg_claim(case_id);

COMMENT ON INDEX public.kg_claim_case_id_idx IS '按案件检索 claim 的加速索引，服务报告 citation 和人工审核列表。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_claim_relation_id_idx
    ON public.kg_claim(relation_id);

COMMENT ON INDEX public.kg_claim_relation_id_idx IS '按 relation_id 查询支撑断言的加速索引，服务点击关系查看证据。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_evidence_link_claim_id_idx
    ON public.kg_evidence_link(claim_id);

COMMENT ON INDEX public.kg_evidence_link_claim_id_idx IS '按 claim_id 查询证据列表的加速索引，是角标回源的主入口索引。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_evidence_link_chunk_id_idx
    ON public.kg_evidence_link(chunk_id);

COMMENT ON INDEX public.kg_evidence_link_chunk_id_idx IS '按 chunk_id 查询被哪些断言引用的加速索引。';

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS report_citation_map_report_ref_citation_id_uq
    ON public.report_citation_map(report_ref, citation_id);

COMMENT ON INDEX public.report_citation_map_report_ref_citation_id_uq IS '同一份报告里每个 citation_id 必须唯一，供前端点击角标后精准命中。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS report_citation_map_case_id_report_ref_idx
    ON public.report_citation_map(case_id, report_ref);

COMMENT ON INDEX public.report_citation_map_case_id_report_ref_idx IS '按案件和报告引用检索该版报告全部 citation 映射。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS report_citation_map_claim_id_idx
    ON public.report_citation_map(claim_id);

COMMENT ON INDEX public.report_citation_map_claim_id_idx IS '按 claim_id 回查被哪些报告引用，用于审计与排查。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_reconciliation_ledger_case_created_idx
    ON public.kg_reconciliation_ledger(case_id, created_at DESC);

COMMENT ON INDEX public.kg_reconciliation_ledger_case_created_idx IS '按案件查看最近增量对账记录的加速索引。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_reconciliation_ledger_new_claim_idx
    ON public.kg_reconciliation_ledger(new_claim_id);

COMMENT ON INDEX public.kg_reconciliation_ledger_new_claim_idx IS '按新增 claim 查询其引发的对账记录。';

CREATE INDEX CONCURRENTLY IF NOT EXISTS kg_reconciliation_ledger_superseded_claim_idx
    ON public.kg_reconciliation_ledger(superseded_claim_id);

COMMENT ON INDEX public.kg_reconciliation_ledger_superseded_claim_idx IS '按旧 claim 查询其何时被何条新结论替代。';
