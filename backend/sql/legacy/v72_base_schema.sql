-- ============================================================================
--
--   AI 猎手：不良资产全量穿透与博弈决策系统
--   完整建库脚本 V7.2 Final — PostgreSQL + pgvector
--
-- ============================================================================
--
--  36张表 | 5个视图 | 3个函数 | 84个索引
--
--  执行前提：PostgreSQL ≥ 15, pgvector ≥ 0.7.0
--  中文全文检索建议安装 zhparser 或 pg_jieba
--
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;


-- ============================================================================
-- SECTION 1：案件基座层
-- ============================================================================

CREATE TABLE cases (
    case_id         BIGSERIAL PRIMARY KEY,
    case_name       TEXT NOT NULL,
    case_type       TEXT CHECK (case_type IN ('单户','资产包','破产重整','执转破')),
    status          TEXT DEFAULT '进行中',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    notes           JSONB
);
COMMENT ON TABLE cases IS '案件主表：每个不良资产包/债权项目一条记录';
COMMENT ON COLUMN cases.case_id IS '案件唯一标识（自增主键）';
COMMENT ON COLUMN cases.case_name IS '资产包/项目名称';
COMMENT ON COLUMN cases.case_type IS '案件类型：单户｜资产包｜破产重整｜执转破';
COMMENT ON COLUMN cases.status IS '案件状态：进行中/已结案/暂停';
COMMENT ON COLUMN cases.created_at IS '记录创建时间';
COMMENT ON COLUMN cases.updated_at IS '记录最后更新时间';
COMMENT ON COLUMN cases.notes IS '备注及附加信息（JSON格式）';

-- --------------------------------------------------

CREATE TABLE debtors (
    debtor_id               BIGSERIAL PRIMARY KEY,
    case_id                 BIGINT REFERENCES cases(case_id),
    entity_name             TEXT NOT NULL,
    former_names            TEXT[],
    uscc                    VARCHAR(18),
    legal_representative    TEXT,
    established_date        DATE,
    operating_status        TEXT,
    registered_address      TEXT,
    actual_address          TEXT,
    phone                   TEXT,
    registered_capital      NUMERIC(18,2),
    paid_in_capital         NUMERIC(18,2),
    industry                TEXT,
    actual_controller       TEXT,
    ultimate_beneficiary    TEXT,
    data_source             TEXT,
    raw_api_response        JSONB,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE debtors IS '债务人主表：模块A 11项基础要素 + DNA画像穿透字段';
COMMENT ON COLUMN debtors.debtor_id IS '债务人唯一标识';
COMMENT ON COLUMN debtors.case_id IS '所属案件ID';
COMMENT ON COLUMN debtors.entity_name IS '债务人名称';
COMMENT ON COLUMN debtors.former_names IS '历史曾用名（数组）';
COMMENT ON COLUMN debtors.uscc IS '统一社会信用代码（18位）';
COMMENT ON COLUMN debtors.legal_representative IS '法定代表人姓名';
COMMENT ON COLUMN debtors.established_date IS '公司成立日期';
COMMENT ON COLUMN debtors.operating_status IS '经营状态：存续/吊销/注销/停业';
COMMENT ON COLUMN debtors.registered_address IS '注册地址';
COMMENT ON COLUMN debtors.actual_address IS '实际经营地址';
COMMENT ON COLUMN debtors.phone IS '联系电话';
COMMENT ON COLUMN debtors.registered_capital IS '注册资本（万元）';
COMMENT ON COLUMN debtors.paid_in_capital IS '实缴资本（万元）';
COMMENT ON COLUMN debtors.industry IS '行业类型：制造/商贸/房开/矿业等';
COMMENT ON COLUMN debtors.actual_controller IS '实际控制人姓名';
COMMENT ON COLUMN debtors.ultimate_beneficiary IS '最终受益人姓名';
COMMENT ON COLUMN debtors.data_source IS '数据来源：aiqicha/qichacha/manual';
COMMENT ON COLUMN debtors.raw_api_response IS '原始API返回JSON留档';
COMMENT ON COLUMN debtors.created_at IS '记录创建时间';
COMMENT ON COLUMN debtors.updated_at IS '记录最后更新时间';

CREATE INDEX idx_debtors_case ON debtors(case_id);
CREATE INDEX idx_debtors_uscc ON debtors(uscc);
CREATE INDEX idx_debtors_name_trgm ON debtors USING gin(entity_name gin_trgm_ops);

-- --------------------------------------------------

CREATE TABLE guarantors (
    guarantor_id    BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    guarantor_type  TEXT CHECK (guarantor_type IN ('企业保证人','自然人保证人')),
    entity_name     TEXT NOT NULL,
    uscc            VARCHAR(18),
    id_number_hash  TEXT,
    legal_rep       TEXT,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    guarantee_type  TEXT,
    guarantee_scope TEXT,
    guarantee_period_start DATE,
    guarantee_period_end   DATE,
    spouse_name     TEXT,
    spouse_id_hash  TEXT,
    spouse_phone    TEXT,
    spouse_email    TEXT,
    has_property    BOOLEAN,
    has_vehicle     BOOLEAN,
    has_company     BOOLEAN,
    asset_summary   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE guarantors IS '保证人表：企业/自然人保证人信息及配偶信息';
COMMENT ON COLUMN guarantors.guarantor_id IS '保证人唯一标识';
COMMENT ON COLUMN guarantors.case_id IS '所属案件ID';
COMMENT ON COLUMN guarantors.guarantor_type IS '保证人类型：企业保证人/自然人保证人';
COMMENT ON COLUMN guarantors.entity_name IS '保证人名称（企业名或个人姓名）';
COMMENT ON COLUMN guarantors.uscc IS '统一社会信用代码（企业保证人）';
COMMENT ON COLUMN guarantors.id_number_hash IS '身份证号哈希（自然人保证人，脱敏存储）';
COMMENT ON COLUMN guarantors.legal_rep IS '法定代表人（企业保证人）';
COMMENT ON COLUMN guarantors.phone IS '联系电话';
COMMENT ON COLUMN guarantors.email IS '联系邮箱';
COMMENT ON COLUMN guarantors.address IS '联系地址';
COMMENT ON COLUMN guarantors.guarantee_type IS '保证方式：一般保证/连带保证';
COMMENT ON COLUMN guarantors.guarantee_scope IS '保证范围描述';
COMMENT ON COLUMN guarantors.guarantee_period_start IS '保证期间起始日';
COMMENT ON COLUMN guarantors.guarantee_period_end IS '保证期间终止日';
COMMENT ON COLUMN guarantors.spouse_name IS '配偶姓名（自然人保证人）';
COMMENT ON COLUMN guarantors.spouse_id_hash IS '配偶身份证号哈希';
COMMENT ON COLUMN guarantors.spouse_phone IS '配偶电话';
COMMENT ON COLUMN guarantors.spouse_email IS '配偶邮箱';
COMMENT ON COLUMN guarantors.has_property IS '名下是否有房产';
COMMENT ON COLUMN guarantors.has_vehicle IS '名下是否有车辆';
COMMENT ON COLUMN guarantors.has_company IS '名下是否有企业';
COMMENT ON COLUMN guarantors.asset_summary IS '资产概况描述';
COMMENT ON COLUMN guarantors.created_at IS '记录创建时间';

CREATE INDEX idx_guar_case ON guarantors(case_id);
CREATE INDEX idx_guar_name ON guarantors(entity_name);

-- --------------------------------------------------

CREATE TABLE contacts (
    contact_id      BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    role            TEXT NOT NULL,
    org_name        TEXT,
    person_name     TEXT,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE contacts IS '通用联系人表：破产管理人/重整投资人/代理律师/法官等';
COMMENT ON COLUMN contacts.contact_id IS '联系人唯一标识';
COMMENT ON COLUMN contacts.case_id IS '所属案件ID';
COMMENT ON COLUMN contacts.role IS '角色：破产管理人/重整投资人/代理律师/法官/调查员';
COMMENT ON COLUMN contacts.org_name IS '所属机构名称';
COMMENT ON COLUMN contacts.person_name IS '联系人姓名';
COMMENT ON COLUMN contacts.phone IS '联系电话';
COMMENT ON COLUMN contacts.email IS '联系邮箱';
COMMENT ON COLUMN contacts.address IS '联系地址';
COMMENT ON COLUMN contacts.notes IS '备注';
COMMENT ON COLUMN contacts.created_at IS '记录创建时间';

CREATE INDEX idx_contacts_case ON contacts(case_id);
CREATE INDEX idx_contacts_role ON contacts(role);

-- --------------------------------------------------

CREATE TABLE related_persons (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    person_name     TEXT NOT NULL,
    id_number_hash  TEXT,
    relation_type   TEXT,
    related_to      TEXT,
    phone           TEXT,
    email           TEXT,
    known_enterprises TEXT[],
    risk_tag        TEXT[],
    notes           TEXT
);
COMMENT ON TABLE related_persons IS 'V7.2 DNA关联人表：配偶/子女/前员工/司机等，追踪窗口期异常行为';
COMMENT ON COLUMN related_persons.id IS '记录唯一标识';
COMMENT ON COLUMN related_persons.case_id IS '所属案件ID';
COMMENT ON COLUMN related_persons.person_name IS '关联人姓名';
COMMENT ON COLUMN related_persons.id_number_hash IS '身份证号哈希（脱敏）';
COMMENT ON COLUMN related_persons.relation_type IS '与债务人关系：配偶/子女/前员工/司机/亲属/商业伙伴';
COMMENT ON COLUMN related_persons.related_to IS '关联的债务人或实控人名称';
COMMENT ON COLUMN related_persons.phone IS '联系电话';
COMMENT ON COLUMN related_persons.email IS '联系邮箱';
COMMENT ON COLUMN related_persons.known_enterprises IS '名下已知企业列表（数组）';
COMMENT ON COLUMN related_persons.risk_tag IS '风险标签数组：窗口期受让资产/突击入股等';
COMMENT ON COLUMN related_persons.notes IS '备注';

CREATE INDEX idx_rp_case ON related_persons(case_id);
CREATE INDEX idx_rp_name ON related_persons(person_name);
CREATE INDEX idx_rp_id_hash ON related_persons(id_number_hash);

-- --------------------------------------------------

CREATE TABLE case_assessments (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    repayment_willingness TEXT CHECK (repayment_willingness IN ('强','一般','弱','无','待判断')),
    collection_difficulty TEXT CHECK (collection_difficulty IN ('低','中','高')),
    estimated_recovery_rate NUMERIC(6,4),
    disposal_strategy TEXT,
    disposal_detail   TEXT,
    assessed_by     TEXT,
    assessed_date   DATE,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE case_assessments IS '清收评估表：偿债能力与处置策略判断';
COMMENT ON COLUMN case_assessments.id IS '评估记录唯一标识';
COMMENT ON COLUMN case_assessments.case_id IS '所属案件ID';
COMMENT ON COLUMN case_assessments.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN case_assessments.repayment_willingness IS '还款意愿：强/一般/弱/无/待判断';
COMMENT ON COLUMN case_assessments.collection_difficulty IS '清收难度：低/中/高';
COMMENT ON COLUMN case_assessments.estimated_recovery_rate IS '预计回收率（0.0000~1.0000）';
COMMENT ON COLUMN case_assessments.disposal_strategy IS '处置建议：诉讼/执行/谈判/转让/追加股东/破产重整';
COMMENT ON COLUMN case_assessments.disposal_detail IS '处置方案详细说明';
COMMENT ON COLUMN case_assessments.assessed_by IS '评估人';
COMMENT ON COLUMN case_assessments.assessed_date IS '评估日期';
COMMENT ON COLUMN case_assessments.created_at IS '记录创建时间';


-- ============================================================================
-- SECTION 2：工商数据层（纯结构化，不向量化）
-- ============================================================================

CREATE TABLE enterprises (
    enterprise_id   BIGSERIAL PRIMARY KEY,
    uscc            VARCHAR(18) UNIQUE,
    entity_name     TEXT NOT NULL,
    legal_rep       TEXT,
    registered_addr TEXT,
    phone           TEXT,
    established     DATE,
    status          TEXT,
    reg_capital     NUMERIC(18,2),
    paid_capital    NUMERIC(18,2),
    industry_code   TEXT,
    industry_name   TEXT,
    addr_hash       TEXT,
    phone_hash      TEXT,
    data_source     TEXT NOT NULL,
    api_fetched_at  TIMESTAMPTZ,
    raw_response    JSONB,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE enterprises IS '企业实体统一表：爱企查/企查查API数据归一化存储';
COMMENT ON COLUMN enterprises.enterprise_id IS '企业唯一标识';
COMMENT ON COLUMN enterprises.uscc IS '统一社会信用代码（唯一约束，去重主键）';
COMMENT ON COLUMN enterprises.entity_name IS '企业名称';
COMMENT ON COLUMN enterprises.legal_rep IS '法定代表人';
COMMENT ON COLUMN enterprises.registered_addr IS '注册地址';
COMMENT ON COLUMN enterprises.phone IS '联系电话';
COMMENT ON COLUMN enterprises.established IS '成立日期';
COMMENT ON COLUMN enterprises.status IS '经营状态：存续/注销/吊销';
COMMENT ON COLUMN enterprises.reg_capital IS '注册资本（万元）';
COMMENT ON COLUMN enterprises.paid_capital IS '实缴资本（万元）';
COMMENT ON COLUMN enterprises.industry_code IS '行业代码';
COMMENT ON COLUMN enterprises.industry_name IS '行业名称';
COMMENT ON COLUMN enterprises.addr_hash IS '地址标准化哈希，用于引擎2"同地址"匹配';
COMMENT ON COLUMN enterprises.phone_hash IS '电话归一化哈希，用于引擎2"同电话"匹配';
COMMENT ON COLUMN enterprises.data_source IS '数据来源：aiqicha/qichacha';
COMMENT ON COLUMN enterprises.api_fetched_at IS 'API拉取时间';
COMMENT ON COLUMN enterprises.raw_response IS '原始API返回JSON完整留档';
COMMENT ON COLUMN enterprises.created_at IS '记录创建时间';
COMMENT ON COLUMN enterprises.updated_at IS '记录最后更新时间';

CREATE INDEX idx_enterprises_name_trgm ON enterprises USING gin(entity_name gin_trgm_ops);
CREATE INDEX idx_enterprises_addr_hash ON enterprises(addr_hash);
CREATE INDEX idx_enterprises_phone_hash ON enterprises(phone_hash);
CREATE INDEX idx_enterprises_legal_rep ON enterprises(legal_rep);

-- --------------------------------------------------

CREATE TABLE shareholders (
    id              BIGSERIAL PRIMARY KEY,
    enterprise_id   BIGINT REFERENCES enterprises(enterprise_id),
    shareholder_name TEXT NOT NULL,
    shareholder_type TEXT CHECK (shareholder_type IN ('自然人','企业','其他')),
    shareholder_uscc VARCHAR(18),
    share_ratio     NUMERIC(8,4),
    subscribed_amt  NUMERIC(18,2),
    paid_amt        NUMERIC(18,2),
    is_actual_ctrl  BOOLEAN DEFAULT false,
    data_source     TEXT,
    snapshot_date   DATE
);
COMMENT ON TABLE shareholders IS '股东关系表：图遍历核心，支持递归CTE穿透控制链';
COMMENT ON COLUMN shareholders.id IS '记录唯一标识';
COMMENT ON COLUMN shareholders.enterprise_id IS '所属企业ID';
COMMENT ON COLUMN shareholders.shareholder_name IS '股东名称（自然人或法人）';
COMMENT ON COLUMN shareholders.shareholder_type IS '股东类型：自然人/企业/其他';
COMMENT ON COLUMN shareholders.shareholder_uscc IS '企业股东的统一社会信用代码（用于递归穿透）';
COMMENT ON COLUMN shareholders.share_ratio IS '持股比例（0.0000~100.0000%）';
COMMENT ON COLUMN shareholders.subscribed_amt IS '认缴出资额（万元）';
COMMENT ON COLUMN shareholders.paid_amt IS '实缴出资额（万元）';
COMMENT ON COLUMN shareholders.is_actual_ctrl IS '是否为实际控制人';
COMMENT ON COLUMN shareholders.data_source IS '数据来源';
COMMENT ON COLUMN shareholders.snapshot_date IS '数据快照日期（追踪历史变更）';

CREATE INDEX idx_sh_enterprise ON shareholders(enterprise_id);
CREATE INDEX idx_sh_name ON shareholders(shareholder_name);
CREATE INDEX idx_sh_uscc ON shareholders(shareholder_uscc);

-- --------------------------------------------------

CREATE TABLE executives (
    id              BIGSERIAL PRIMARY KEY,
    enterprise_id   BIGINT REFERENCES enterprises(enterprise_id),
    person_name     TEXT NOT NULL,
    id_number_hash  TEXT,
    position        TEXT,
    appointment_date DATE,
    departure_date  DATE,
    data_source     TEXT,
    snapshot_date   DATE
);
COMMENT ON TABLE executives IS '董监高表：交叉任职穿透核心，用于引擎4白手套拆解';
COMMENT ON COLUMN executives.id IS '记录唯一标识';
COMMENT ON COLUMN executives.enterprise_id IS '所属企业ID';
COMMENT ON COLUMN executives.person_name IS '姓名';
COMMENT ON COLUMN executives.id_number_hash IS '身份证号哈希（脱敏但可关联同一人）';
COMMENT ON COLUMN executives.position IS '职务：董事/监事/总经理/财务负责人';
COMMENT ON COLUMN executives.appointment_date IS '任职日期';
COMMENT ON COLUMN executives.departure_date IS '离任日期（NULL表示在任）';
COMMENT ON COLUMN executives.data_source IS '数据来源';
COMMENT ON COLUMN executives.snapshot_date IS '数据快照日期';

CREATE INDEX idx_exec_enterprise ON executives(enterprise_id);
CREATE INDEX idx_exec_person ON executives(person_name);
CREATE INDEX idx_exec_id_hash ON executives(id_number_hash);

-- --------------------------------------------------

CREATE TABLE biz_changes (
    id              BIGSERIAL PRIMARY KEY,
    enterprise_id   BIGINT REFERENCES enterprises(enterprise_id),
    change_date     DATE,
    change_item     TEXT,
    before_content  TEXT,
    after_content   TEXT,
    data_source     TEXT
);
COMMENT ON TABLE biz_changes IS '工商变更记录表：追踪资产转移窗口期的法人/股东/地址异常变更';
COMMENT ON COLUMN biz_changes.id IS '记录唯一标识';
COMMENT ON COLUMN biz_changes.enterprise_id IS '所属企业ID';
COMMENT ON COLUMN biz_changes.change_date IS '变更日期';
COMMENT ON COLUMN biz_changes.change_item IS '变更事项：法定代表人/股东/注册资本/地址等';
COMMENT ON COLUMN biz_changes.before_content IS '变更前内容';
COMMENT ON COLUMN biz_changes.after_content IS '变更后内容';
COMMENT ON COLUMN biz_changes.data_source IS '数据来源';

CREATE INDEX idx_biz_changes_ent ON biz_changes(enterprise_id);
CREATE INDEX idx_biz_changes_date ON biz_changes(change_date);
CREATE INDEX idx_biz_changes_item ON biz_changes(change_item);


-- ============================================================================
-- SECTION 3：法律文书层（结构化 + 向量化双层架构）
-- ============================================================================

CREATE TABLE legal_documents (
    doc_id          BIGSERIAL PRIMARY KEY,
    case_number     TEXT,
    court_name      TEXT,
    court_level     TEXT,
    case_type       TEXT,
    case_cause      TEXT,
    doc_type        TEXT,
    judgment_date   DATE,
    publish_date    DATE,
    plaintiff       TEXT[],
    defendant       TEXT[],
    third_party     TEXT[],
    claim_amount    NUMERIC(18,2),
    judgment_amount NUMERIC(18,2),
    execution_status TEXT,
    enforcement_deadline DATE,
    tags            TEXT[],
    involves_asset_transfer BOOLEAN DEFAULT false,
    involves_shell_company  BOOLEAN DEFAULT false,
    full_text       TEXT,
    source_url      TEXT,
    crawl_batch     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE legal_documents IS '法律文书结构化主表：从裁判文书网增量采集，规则引擎提取结构化字段';
COMMENT ON COLUMN legal_documents.doc_id IS '文书唯一标识';
COMMENT ON COLUMN legal_documents.case_number IS '案号，如(2023)京01民终1234号';
COMMENT ON COLUMN legal_documents.court_name IS '审理法院名称';
COMMENT ON COLUMN legal_documents.court_level IS '法院层级：基层/中级/高级/最高';
COMMENT ON COLUMN legal_documents.case_type IS '案件类别：民事/刑事/行政/执行';
COMMENT ON COLUMN legal_documents.case_cause IS '案由：金融借款合同纠纷/执行异议等';
COMMENT ON COLUMN legal_documents.doc_type IS '文书类型：判决书/裁定书/调解书/执行裁定/通知书';
COMMENT ON COLUMN legal_documents.judgment_date IS '裁判日期';
COMMENT ON COLUMN legal_documents.publish_date IS '文书网公开日期';
COMMENT ON COLUMN legal_documents.plaintiff IS '原告/申请人姓名数组';
COMMENT ON COLUMN legal_documents.defendant IS '被告/被申请人/被执行人姓名数组';
COMMENT ON COLUMN legal_documents.third_party IS '第三人姓名数组';
COMMENT ON COLUMN legal_documents.claim_amount IS '诉请金额（元）';
COMMENT ON COLUMN legal_documents.judgment_amount IS '判决金额（元）';
COMMENT ON COLUMN legal_documents.execution_status IS '执行状态：执行中/终本/已结案';
COMMENT ON COLUMN legal_documents.enforcement_deadline IS '执行时效关键日期（引擎3时效监控）';
COMMENT ON COLUMN legal_documents.tags IS '自动标签数组：虚假租赁/保单避债/拒执罪等';
COMMENT ON COLUMN legal_documents.involves_asset_transfer IS '是否涉及资产转移行为';
COMMENT ON COLUMN legal_documents.involves_shell_company IS '是否涉及空壳公司';
COMMENT ON COLUMN legal_documents.full_text IS '完整文书正文（全文检索兜底用）';
COMMENT ON COLUMN legal_documents.source_url IS '文书网原始链接';
COMMENT ON COLUMN legal_documents.crawl_batch IS '采集批次号（增量更新控制）';
COMMENT ON COLUMN legal_documents.created_at IS '记录创建时间';
COMMENT ON COLUMN legal_documents.updated_at IS '记录最后更新时间';

CREATE INDEX idx_ld_case_number ON legal_documents(case_number);
CREATE INDEX idx_ld_court ON legal_documents(court_name);
CREATE INDEX idx_ld_type ON legal_documents(case_type, doc_type);
CREATE INDEX idx_ld_date ON legal_documents(judgment_date);
CREATE INDEX idx_ld_deadline ON legal_documents(enforcement_deadline);
CREATE INDEX idx_ld_tags ON legal_documents USING gin(tags);
CREATE INDEX idx_ld_plaintiff ON legal_documents USING gin(plaintiff);
CREATE INDEX idx_ld_defendant ON legal_documents USING gin(defendant);
CREATE INDEX idx_ld_fulltext ON legal_documents USING gin(to_tsvector('simple', coalesce(full_text, '')));

-- --------------------------------------------------

CREATE TABLE doc_chunks (
    chunk_id        BIGSERIAL PRIMARY KEY,
    doc_id          BIGINT REFERENCES legal_documents(doc_id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,
    chunk_text      TEXT NOT NULL,
    section_type    TEXT,
    embedding       vector(1024),
    case_number     TEXT,
    case_cause      TEXT,
    judgment_date   DATE,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE doc_chunks IS '文书分块向量表：正文按段落类型切分后存入，embedding列供pgvector语义检索';
COMMENT ON COLUMN doc_chunks.chunk_id IS '分块唯一标识';
COMMENT ON COLUMN doc_chunks.doc_id IS '所属文书ID';
COMMENT ON COLUMN doc_chunks.chunk_index IS '块序号（同一文书内排序）';
COMMENT ON COLUMN doc_chunks.chunk_text IS '分块正文（建议500~1000字/块）';
COMMENT ON COLUMN doc_chunks.section_type IS '所属段落类型：事实认定/裁判理由/判决主文/执行依据';
COMMENT ON COLUMN doc_chunks.embedding IS 'BGE-large-zh-v1.5生成的1024维向量';
COMMENT ON COLUMN doc_chunks.case_number IS '冗余案号（避免频繁JOIN）';
COMMENT ON COLUMN doc_chunks.case_cause IS '冗余案由';
COMMENT ON COLUMN doc_chunks.judgment_date IS '冗余裁判日期';
COMMENT ON COLUMN doc_chunks.created_at IS '记录创建时间';

CREATE INDEX idx_chunks_embedding ON doc_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200);
CREATE INDEX idx_chunks_doc ON doc_chunks(doc_id);
CREATE INDEX idx_chunks_section ON doc_chunks(section_type);

-- --------------------------------------------------

CREATE TABLE case_document_links (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    doc_id          BIGINT REFERENCES legal_documents(doc_id),
    relevance_type  TEXT,
    linked_by       TEXT DEFAULT 'system',
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(case_id, doc_id)
);
COMMENT ON TABLE case_document_links IS '文书-案件关联表：多对多关系，同一文书可关联多个案件';
COMMENT ON COLUMN case_document_links.id IS '记录唯一标识';
COMMENT ON COLUMN case_document_links.case_id IS '案件ID';
COMMENT ON COLUMN case_document_links.doc_id IS '文书ID';
COMMENT ON COLUMN case_document_links.relevance_type IS '关联类型：direct(直接相关)/reference(参考判例)/counter(对手方案件)';
COMMENT ON COLUMN case_document_links.linked_by IS '关联创建方式：system/manual';
COMMENT ON COLUMN case_document_links.created_at IS '记录创建时间';

-- --------------------------------------------------

CREATE TABLE source_documents (
    doc_id          BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    file_name       TEXT NOT NULL,
    file_type       TEXT,
    file_category   TEXT,
    file_path       TEXT,
    file_size_kb    INT,
    page_count      INT,
    scan_quality    TEXT CHECK (scan_quality IN ('清晰','模糊','缺页','需重扫','未扫描')),
    needs_rescan    BOOLEAN DEFAULT false,
    rescan_reason   TEXT,
    source_org      TEXT,
    obtained_date   DATE,
    obtained_by     TEXT,
    is_referenced_in_legal_opinion BOOLEAN DEFAULT false,
    is_captured     BOOLEAN DEFAULT false,
    capture_gap_note TEXT,
    tags            TEXT[],
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE source_documents IS '原始文件管理表：卷宗级管控，追踪扫描质量和法律意见书引用完整性';
COMMENT ON COLUMN source_documents.doc_id IS '文件唯一标识';
COMMENT ON COLUMN source_documents.case_id IS '所属案件ID';
COMMENT ON COLUMN source_documents.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN source_documents.file_name IS '文件名';
COMMENT ON COLUMN source_documents.file_type IS '文件格式：PDF/Word/照片/复印件/扫描件';
COMMENT ON COLUMN source_documents.file_category IS '文件分类：贷款合同/诉讼文件/执行文件/权证/重整方案/勘探报告/环评批复/律师调查报告/法院总对总';
COMMENT ON COLUMN source_documents.file_path IS '文件存储路径';
COMMENT ON COLUMN source_documents.file_size_kb IS '文件大小（KB）';
COMMENT ON COLUMN source_documents.page_count IS '页数';
COMMENT ON COLUMN source_documents.scan_quality IS '扫描质量：清晰/模糊/缺页/需重扫/未扫描';
COMMENT ON COLUMN source_documents.needs_rescan IS '是否需要重新扫描';
COMMENT ON COLUMN source_documents.rescan_reason IS '需重扫原因';
COMMENT ON COLUMN source_documents.source_org IS '来源机构：银行/AMC/法院/律师';
COMMENT ON COLUMN source_documents.obtained_date IS '获取日期';
COMMENT ON COLUMN source_documents.obtained_by IS '获取人';
COMMENT ON COLUMN source_documents.is_referenced_in_legal_opinion IS '法律意见书是否引用了此文件';
COMMENT ON COLUMN source_documents.is_captured IS '该文件是否已入库/抓取';
COMMENT ON COLUMN source_documents.capture_gap_note IS '缺失说明（补救：纸质卷查找/法院调档）';
COMMENT ON COLUMN source_documents.tags IS '标签数组';
COMMENT ON COLUMN source_documents.notes IS '备注';
COMMENT ON COLUMN source_documents.created_at IS '记录创建时间';
COMMENT ON COLUMN source_documents.updated_at IS '记录最后更新时间';

CREATE INDEX idx_sd_case ON source_documents(case_id);
CREATE INDEX idx_sd_category ON source_documents(file_category);
CREATE INDEX idx_sd_quality ON source_documents(scan_quality) WHERE needs_rescan = true;
CREATE INDEX idx_sd_legal_ref ON source_documents(is_referenced_in_legal_opinion) WHERE is_referenced_in_legal_opinion = true AND is_captured = false;


-- ============================================================================
-- SECTION 4：资产与债权层
-- ============================================================================

CREATE TABLE claims (
    claim_id        BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    principal       NUMERIC(18,2),
    interest        NUMERIC(18,2),
    penalty         NUMERIC(18,2),
    delayed_interest NUMERIC(18,2),
    total_claim     NUMERIC(18,2),
    priority_amount NUMERIC(18,2),
    general_amount  NUMERIC(18,2),
    guarantee_type  TEXT,
    collateral_desc TEXT,
    lien_priority   INT,
    court_name      TEXT,
    exec_case_no    TEXT,
    litigation_status TEXT,
    has_effective_judgment BOOLEAN,
    first_seal_status TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE claims IS '债权明细表：本金/利息/担保/诉讼状态完整记录';
COMMENT ON COLUMN claims.claim_id IS '债权唯一标识';
COMMENT ON COLUMN claims.case_id IS '所属案件ID';
COMMENT ON COLUMN claims.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN claims.principal IS '债权本金（元）';
COMMENT ON COLUMN claims.interest IS '利息（元）';
COMMENT ON COLUMN claims.penalty IS '罚息（元）';
COMMENT ON COLUMN claims.delayed_interest IS '迟延履行利息（截至交易基准日）';
COMMENT ON COLUMN claims.total_claim IS '债权总额（元）';
COMMENT ON COLUMN claims.priority_amount IS '优先债权金额（元）';
COMMENT ON COLUMN claims.general_amount IS '一般债权金额（元）';
COMMENT ON COLUMN claims.guarantee_type IS '担保方式：信用/抵押/质押/保证';
COMMENT ON COLUMN claims.collateral_desc IS '抵押物/质押物概况描述';
COMMENT ON COLUMN claims.lien_priority IS '抵押顺位';
COMMENT ON COLUMN claims.court_name IS '执行法院';
COMMENT ON COLUMN claims.exec_case_no IS '执行案号';
COMMENT ON COLUMN claims.litigation_status IS '诉讼状态：未诉/已诉/已判/执行中/终本';
COMMENT ON COLUMN claims.has_effective_judgment IS '有无生效判决';
COMMENT ON COLUMN claims.first_seal_status IS '有无首封财产';
COMMENT ON COLUMN claims.created_at IS '记录创建时间';

-- --------------------------------------------------

CREATE TABLE real_estate_evaluations (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    report_org      TEXT,
    report_date     DATE,
    project_name    TEXT,
    property_location TEXT,
    -- 一、基础信息
    total_building_area     NUMERIC(14,2),
    land_use_area           NUMERIC(14,2),
    floor_area_ratio        NUMERIC(6,2),
    green_ratio             NUMERIC(6,2),
    built_year              INT,
    building_structure      TEXT,
    physical_newness_rate   NUMERIC(6,2),
    location_maturity       TEXT,
    -- 二、权属信息
    property_owner          TEXT,
    property_address        TEXT,
    floor_number            TEXT,
    door_number             TEXT,
    real_estate_cert_no     TEXT,
    house_cert_no           TEXT,
    land_cert_no            TEXT,
    is_independent_title    BOOLEAN,
    land_nature             TEXT,
    title_start_date        DATE,
    remaining_land_years    INT,
    mortgage_status         TEXT,
    mortgagee               TEXT,
    lien_priority           INT,
    seal_status             TEXT,
    sealing_court           TEXT,
    seal_expiry             DATE,
    co_owner_info           TEXT,
    has_title_objection     BOOLEAN DEFAULT false,
    -- 三、物理特征
    property_usage          TEXT,
    fire_safety_accepted    BOOLEAN,
    seismic_level           TEXT,
    structural_safety       TEXT,
    last_renovation_year    INT,
    maintenance_condition   TEXT,
    -- 四~八、专项评价（JSONB）
    parking_details         JSONB,
    shop_details            JSONB,
    industrial_land_details JSONB,
    factory_details         JSONB,
    office_details          JSONB,
    -- 九、风险评估
    risk_policy             TEXT,
    risk_environment        TEXT,
    risk_legal              TEXT,
    risk_market             TEXT,
    risk_operation          TEXT,
    -- 十、综合评价
    overall_rating          TEXT,
    core_advantages         TEXT,
    main_risks              TEXT,
    improvement_suggestions TEXT,
    evaluator               TEXT,
    evaluation_date         DATE,
    reviewer                TEXT,
    review_date             DATE,
    -- 审计引擎对接
    lease_status            TEXT,
    lease_start             DATE,
    lease_end               DATE,
    lease_annual_rent       NUMERIC(18,2),
    objection_status        TEXT,
    physical_occupation     TEXT,
    nearby_unit_price       NUMERIC(12,2),
    liquidity_months        INT,
    gross_value             NUMERIC(18,2),
    discount_factors        JSONB,
    net_value               NUMERIC(18,2),
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE real_estate_evaluations IS '不动产评价全量表：10个维度95项指标完整映射，含停车场/商铺/厂房/办公楼专项';
COMMENT ON COLUMN real_estate_evaluations.id IS '记录唯一标识';
COMMENT ON COLUMN real_estate_evaluations.case_id IS '所属案件ID';
COMMENT ON COLUMN real_estate_evaluations.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN real_estate_evaluations.report_org IS '填报单位';
COMMENT ON COLUMN real_estate_evaluations.report_date IS '报表日期';
COMMENT ON COLUMN real_estate_evaluations.project_name IS '项目名称';
COMMENT ON COLUMN real_estate_evaluations.property_location IS '位置';
COMMENT ON COLUMN real_estate_evaluations.total_building_area IS '总建筑面积（㎡）';
COMMENT ON COLUMN real_estate_evaluations.land_use_area IS '土地使用权面积（㎡）';
COMMENT ON COLUMN real_estate_evaluations.floor_area_ratio IS '容积率';
COMMENT ON COLUMN real_estate_evaluations.green_ratio IS '绿化率（%）';
COMMENT ON COLUMN real_estate_evaluations.built_year IS '建成年代';
COMMENT ON COLUMN real_estate_evaluations.building_structure IS '建筑结构：框架/砖混/钢结构';
COMMENT ON COLUMN real_estate_evaluations.physical_newness_rate IS '物理成新率（%）';
COMMENT ON COLUMN real_estate_evaluations.location_maturity IS '地段成熟度：成熟/较成熟/一般/不成熟';
COMMENT ON COLUMN real_estate_evaluations.property_owner IS '物权人';
COMMENT ON COLUMN real_estate_evaluations.property_address IS '物业坐落';
COMMENT ON COLUMN real_estate_evaluations.floor_number IS '楼层';
COMMENT ON COLUMN real_estate_evaluations.door_number IS '门牌号';
COMMENT ON COLUMN real_estate_evaluations.real_estate_cert_no IS '不动产权证号';
COMMENT ON COLUMN real_estate_evaluations.house_cert_no IS '房产证号';
COMMENT ON COLUMN real_estate_evaluations.land_cert_no IS '土地证号';
COMMENT ON COLUMN real_estate_evaluations.is_independent_title IS '是否独立产权';
COMMENT ON COLUMN real_estate_evaluations.land_nature IS '土地性质：出让/划拨';
COMMENT ON COLUMN real_estate_evaluations.title_start_date IS '权属起始日期';
COMMENT ON COLUMN real_estate_evaluations.remaining_land_years IS '剩余土地使用年限（年）';
COMMENT ON COLUMN real_estate_evaluations.mortgage_status IS '抵押状态：无抵押/有抵押';
COMMENT ON COLUMN real_estate_evaluations.mortgagee IS '抵押权人';
COMMENT ON COLUMN real_estate_evaluations.lien_priority IS '抵押顺位';
COMMENT ON COLUMN real_estate_evaluations.seal_status IS '查封状态：无查封/有查封';
COMMENT ON COLUMN real_estate_evaluations.sealing_court IS '查封法院';
COMMENT ON COLUMN real_estate_evaluations.seal_expiry IS '查封到期日（引擎3时效预警触发点）';
COMMENT ON COLUMN real_estate_evaluations.co_owner_info IS '共有权人信息';
COMMENT ON COLUMN real_estate_evaluations.has_title_objection IS '有无权属异议';
COMMENT ON COLUMN real_estate_evaluations.property_usage IS '物业用途：商业/工业/办公/住宅';
COMMENT ON COLUMN real_estate_evaluations.fire_safety_accepted IS '消防规划竣工验收：已验收/未验收';
COMMENT ON COLUMN real_estate_evaluations.seismic_level IS '抗震设防等级';
COMMENT ON COLUMN real_estate_evaluations.structural_safety IS '房屋结构安全性：安全/一般/危险';
COMMENT ON COLUMN real_estate_evaluations.last_renovation_year IS '最近装修时间（年）';
COMMENT ON COLUMN real_estate_evaluations.maintenance_condition IS '维护状况：良好/一般/较差';
COMMENT ON COLUMN real_estate_evaluations.parking_details IS '停车场专项评价（JSONB 15项）：is_independent_title, is_civil_defense, parking_count, parking_ratio, can_register_separately, single_space_size_m, property_fee_per_unit, traffic_efficiency, turnover_rate_per_day, temp_parking_fee_hourly, monthly_rent, sale_price_per_unit, lease_status, rental_yield_pct';
COMMENT ON COLUMN real_estate_evaluations.shop_details IS '商铺专项评价（JSONB 15项）：shop_type, floor, competitor_vacancy_pct, vacancy_months, business_type, frontage_m, depth_m, ceiling_height_m, floor_load_kg_sqm, has_flue_water_gas, has_parking, property_fee, current_rent, nearby_avg_price, rental_yield_pct';
COMMENT ON COLUMN real_estate_evaluations.industrial_land_details IS '工业土地专项评价（JSONB 11项）：is_industrial_park, far, building_density_pct, green_rate_pct, industry_access, facilities, traffic_condition, property_fee, nearby_rent, nearby_avg_price, rental_yield_pct';
COMMENT ON COLUMN real_estate_evaluations.factory_details IS '厂房专项评价（JSONB 12项）：structure, ceiling_height_m, column_span_m, has_overhead_crane, power_capacity_kva, env_assessment_accepted, emission_permit, productivity, property_fee, nearby_rent, nearby_avg_price, rental_yield_pct';
COMMENT ON COLUMN real_estate_evaluations.office_details IS '园区办公楼专项评价（JSONB 13项）：office_area_sqm, decoration, has_independent_entrance, usability, connected_to_factory, can_register_separately, industry_clustering, nearby_facilities_maturity, competitor_vacancy_pct, property_fee, nearby_rent, nearby_avg_price, rental_yield_pct';
COMMENT ON COLUMN real_estate_evaluations.risk_policy IS '政策风险：低/中/高';
COMMENT ON COLUMN real_estate_evaluations.risk_environment IS '环境风险：低/中/高';
COMMENT ON COLUMN real_estate_evaluations.risk_legal IS '法律纠纷风险：低/中/高';
COMMENT ON COLUMN real_estate_evaluations.risk_market IS '市场波动风险：低/中/高';
COMMENT ON COLUMN real_estate_evaluations.risk_operation IS '运营管理风险：低/中/高';
COMMENT ON COLUMN real_estate_evaluations.overall_rating IS '整体评价结果：优秀/良好/一般/较差';
COMMENT ON COLUMN real_estate_evaluations.core_advantages IS '核心优势描述';
COMMENT ON COLUMN real_estate_evaluations.main_risks IS '主要风险点描述';
COMMENT ON COLUMN real_estate_evaluations.improvement_suggestions IS '总体改进建议';
COMMENT ON COLUMN real_estate_evaluations.evaluator IS '评价人员';
COMMENT ON COLUMN real_estate_evaluations.evaluation_date IS '评价日期';
COMMENT ON COLUMN real_estate_evaluations.reviewer IS '审核人员';
COMMENT ON COLUMN real_estate_evaluations.review_date IS '审核日期';
COMMENT ON COLUMN real_estate_evaluations.lease_status IS '★★租赁状态（引擎2瑕疵挤水核心）';
COMMENT ON COLUMN real_estate_evaluations.lease_start IS '租赁起始日';
COMMENT ON COLUMN real_estate_evaluations.lease_end IS '租赁到期日';
COMMENT ON COLUMN real_estate_evaluations.lease_annual_rent IS '年租金（元）';
COMMENT ON COLUMN real_estate_evaluations.objection_status IS '案外人异议状态';
COMMENT ON COLUMN real_estate_evaluations.physical_occupation IS '实际占用情况描述';
COMMENT ON COLUMN real_estate_evaluations.nearby_unit_price IS '周边成交均价（元/㎡）';
COMMENT ON COLUMN real_estate_evaluations.liquidity_months IS '预计变现周期（月）';
COMMENT ON COLUMN real_estate_evaluations.gross_value IS '账面/评估价值（元）';
COMMENT ON COLUMN real_estate_evaluations.discount_factors IS '瑕疵折扣因子（JSONB）如{"长租约":-0.5,"案外人异议":-0.3}';
COMMENT ON COLUMN real_estate_evaluations.net_value IS '去毒后净值（元）';
COMMENT ON COLUMN real_estate_evaluations.created_at IS '记录创建时间';
COMMENT ON COLUMN real_estate_evaluations.updated_at IS '记录最后更新时间';

CREATE INDEX idx_ree_case ON real_estate_evaluations(case_id);
CREATE INDEX idx_ree_seal_expiry ON real_estate_evaluations(seal_expiry);
CREATE INDEX idx_ree_rating ON real_estate_evaluations(overall_rating);
CREATE INDEX idx_ree_usage ON real_estate_evaluations(property_usage);
CREATE INDEX idx_ree_mortgage ON real_estate_evaluations(mortgage_status);
CREATE INDEX idx_ree_cert ON real_estate_evaluations(real_estate_cert_no);

-- --------------------------------------------------

CREATE TABLE mining_evaluations (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    report_org      TEXT,
    report_date     DATE,
    mine_name       TEXT,
    mine_location   TEXT,
    -- 一、合规与权属
    permit_validity_years   NUMERIC(6,2),
    permit_expiry           DATE,
    production_scale        NUMERIC(12,2),
    mining_right_payment    TEXT,
    mining_right_fee        TEXT,
    resource_tax            TEXT,
    compensation_fee        TEXT,
    env_treatment_deposit   TEXT,
    safety_permit_status    TEXT,
    env_approval_status     TEXT,
    emission_permit_status  TEXT,
    land_procedures         TEXT,
    forest_procedures       TEXT,
    mineral_area_compliance TEXT,
    in_ecological_redline   BOOLEAN DEFAULT false,
    in_prohibited_zone      BOOLEAN DEFAULT false,
    is_obsolete_capacity    BOOLEAN DEFAULT false,
    community_impact        TEXT,
    mining_status           TEXT,
    is_legal_mining         BOOLEAN DEFAULT true,
    major_violations        BOOLEAN DEFAULT false,
    permit_renewal_history  TEXT,
    mining_right_mortgage   TEXT,
    mining_right_sealed     TEXT,
    env_penalties_5yr       BOOLEAN DEFAULT false,
    safety_accident_history TEXT,
    area_dispute            BOOLEAN DEFAULT false,
    -- 二、资源禀赋
    proved_reserves         NUMERIC(14,2),
    controlled_reserves     NUMERIC(14,2),
    inferred_resources      NUMERIC(14,2),
    total_reserves          NUMERIC(14,2),
    recoverable_reserves    NUMERIC(14,2),
    reserves_credibility    TEXT,
    calorific_value         NUMERIC(8,2),
    ash_content_pct         NUMERIC(6,2),
    sulfur_content_pct      NUMERIC(6,3),
    volatile_matter_pct     NUMERIC(6,2),
    coal_type               TEXT,
    caking_index            TEXT,
    washability             TEXT,
    coal_quality_stability  TEXT,
    geological_conditions   JSONB,
    -- 三、开采与运营经济性
    mining_recovery_rate    NUMERIC(6,2),
    processing_recovery_rate NUMERIC(6,2),
    ore_dilution_rate       NUMERIC(6,2),
    annual_capacity         NUMERIC(12,2),
    actual_capacity_rate    NUMERIC(6,2),
    cost_mining_per_ton     NUMERIC(10,2),
    cost_washing_per_ton    NUMERIC(10,2),
    cost_labor_per_ton      NUMERIC(10,2),
    cost_safety_per_ton     NUMERIC(10,2),
    cost_env_per_ton        NUMERIC(10,2),
    cost_depreciation_per_ton NUMERIC(10,2),
    cost_tax_per_ton        NUMERIC(10,2),
    cost_total_per_ton      NUMERIC(10,2),
    price_per_ton           NUMERIC(10,2),
    gross_margin_per_ton    NUMERIC(10,2),
    net_profit              NUMERIC(14,2),
    cash_flow_status        TEXT,
    operation_details       JSONB,
    -- 四、市场与行业风险
    market_risk_details     JSONB,
    -- 五、变现与处置能力
    disposal_details        JSONB,
    -- 六、综合评价
    overall_rating          TEXT,
    core_resource_advantages TEXT,
    core_operation_advantages TEXT,
    main_compliance_risks   TEXT,
    main_market_risks       TEXT,
    main_operation_risks    TEXT,
    improvement_suggestions TEXT,
    investment_value        TEXT,
    evaluator               TEXT,
    evaluation_date         DATE,
    reviewer                TEXT,
    review_date             DATE,
    -- 审计引擎对接
    mineral_type            TEXT,
    mine_scale              TEXT,
    estimated_value         NUMERIC(18,2),
    transfer_base_price     NUMERIC(18,2),  -- 破产协议转让底价（用于价值倒挂探测）
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE mining_evaluations IS '采矿许可证评价全量表：6个维度120项指标完整映射，含资源禀赋/运营经济性/市场风险/变现能力';
COMMENT ON COLUMN mining_evaluations.id IS '记录唯一标识';
COMMENT ON COLUMN mining_evaluations.case_id IS '所属案件ID';
COMMENT ON COLUMN mining_evaluations.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN mining_evaluations.report_org IS '填报单位';
COMMENT ON COLUMN mining_evaluations.report_date IS '报表日期';
COMMENT ON COLUMN mining_evaluations.mine_name IS '矿名';
COMMENT ON COLUMN mining_evaluations.mine_location IS '矿区位置';
COMMENT ON COLUMN mining_evaluations.permit_validity_years IS '采矿许可证有效期（年）';
COMMENT ON COLUMN mining_evaluations.permit_expiry IS '采矿许可证到期日（引擎3时效预警触发点）';
COMMENT ON COLUMN mining_evaluations.production_scale IS '证载生产规模（万吨/年）';
COMMENT ON COLUMN mining_evaluations.mining_right_payment IS '采矿权价款缴纳：已缴清/部分缴纳/未缴纳';
COMMENT ON COLUMN mining_evaluations.mining_right_fee IS '采矿权使用费缴纳：已缴清/部分缴纳/未缴纳';
COMMENT ON COLUMN mining_evaluations.resource_tax IS '资源税缴纳：正常/欠缴';
COMMENT ON COLUMN mining_evaluations.compensation_fee IS '补偿费缴纳：正常/欠缴';
COMMENT ON COLUMN mining_evaluations.env_treatment_deposit IS '环境治理金缴纳：足额/不足额/未缴纳';
COMMENT ON COLUMN mining_evaluations.safety_permit_status IS '安全生产许可证状态：有效/即将到期/已过期';
COMMENT ON COLUMN mining_evaluations.env_approval_status IS '环评批复文件状态：有/无/过期';
COMMENT ON COLUMN mining_evaluations.emission_permit_status IS '排污许可证状态：有效/即将到期/已过期';
COMMENT ON COLUMN mining_evaluations.land_procedures IS '土地手续：齐全/部分齐全/缺失';
COMMENT ON COLUMN mining_evaluations.forest_procedures IS '林地手续：齐全/部分齐全/缺失';
COMMENT ON COLUMN mining_evaluations.mineral_area_compliance IS '矿种规模矿区合规性：合规/部分合规/不合规';
COMMENT ON COLUMN mining_evaluations.in_ecological_redline IS '是否在生态红线内（true=重大风险）';
COMMENT ON COLUMN mining_evaluations.in_prohibited_zone IS '是否在禁采区内（true=重大风险）';
COMMENT ON COLUMN mining_evaluations.is_obsolete_capacity IS '是否属于淘汰落后产能（true=重大风险）';
COMMENT ON COLUMN mining_evaluations.community_impact IS '社区人文宗教影响：无/较小/较大';
COMMENT ON COLUMN mining_evaluations.mining_status IS '开采状态：已投产≥1年/试生产/未投产';
COMMENT ON COLUMN mining_evaluations.is_legal_mining IS '是否合法开采';
COMMENT ON COLUMN mining_evaluations.major_violations IS '有无重大违法违规记录';
COMMENT ON COLUMN mining_evaluations.permit_renewal_history IS '证照续期历史：顺利/一般/困难';
COMMENT ON COLUMN mining_evaluations.mining_right_mortgage IS '采矿权抵押状态：无抵押/有抵押';
COMMENT ON COLUMN mining_evaluations.mining_right_sealed IS '采矿权查封状态：无查封/有查封';
COMMENT ON COLUMN mining_evaluations.env_penalties_5yr IS '近5年有无环保处罚记录';
COMMENT ON COLUMN mining_evaluations.safety_accident_history IS '安全生产事故记录：无/一般事故/重大事故';
COMMENT ON COLUMN mining_evaluations.area_dispute IS '有无矿区范围争议';
COMMENT ON COLUMN mining_evaluations.proved_reserves IS '探明储量（万吨）';
COMMENT ON COLUMN mining_evaluations.controlled_reserves IS '控制储量（万吨）';
COMMENT ON COLUMN mining_evaluations.inferred_resources IS '推断资源量（万吨）';
COMMENT ON COLUMN mining_evaluations.total_reserves IS '备案总储量（万吨）';
COMMENT ON COLUMN mining_evaluations.recoverable_reserves IS '可采储量（万吨）';
COMMENT ON COLUMN mining_evaluations.reserves_credibility IS '资源储量可信度：高/中/低';
COMMENT ON COLUMN mining_evaluations.calorific_value IS '发热量（cal/g）';
COMMENT ON COLUMN mining_evaluations.ash_content_pct IS '灰分（%）';
COMMENT ON COLUMN mining_evaluations.sulfur_content_pct IS '硫分（%）';
COMMENT ON COLUMN mining_evaluations.volatile_matter_pct IS '挥发分（%）';
COMMENT ON COLUMN mining_evaluations.coal_type IS '煤种：优质煤/普通煤/劣质煤';
COMMENT ON COLUMN mining_evaluations.caking_index IS '粘结指数';
COMMENT ON COLUMN mining_evaluations.washability IS '可选性：易选/中等/难选';
COMMENT ON COLUMN mining_evaluations.coal_quality_stability IS '煤质稳定性：稳定/一般/波动大';
COMMENT ON COLUMN mining_evaluations.geological_conditions IS '地质条件（JSONB 15项）：burial_depth_m, dip_angle_deg, seam_thickness_m, geological_complexity, hydrogeology, gas_level, ground_pressure, roof_stability, coal_dust_explosive, mining_area_km2, mining_elevation_m, workface_count, remaining_years, resource_recovery_history';
COMMENT ON COLUMN mining_evaluations.mining_recovery_rate IS '采矿回采率（%）';
COMMENT ON COLUMN mining_evaluations.processing_recovery_rate IS '选矿回收率（%）';
COMMENT ON COLUMN mining_evaluations.ore_dilution_rate IS '矿石贫化率（%）';
COMMENT ON COLUMN mining_evaluations.annual_capacity IS '年核定产能（万吨/年）';
COMMENT ON COLUMN mining_evaluations.actual_capacity_rate IS '实际达产率（%）';
COMMENT ON COLUMN mining_evaluations.cost_mining_per_ton IS '吨煤开采成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.cost_washing_per_ton IS '吨煤洗选成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.cost_labor_per_ton IS '吨煤人工成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.cost_safety_per_ton IS '吨煤安全成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.cost_env_per_ton IS '吨煤环保成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.cost_depreciation_per_ton IS '吨煤折旧成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.cost_tax_per_ton IS '吨煤税费成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.cost_total_per_ton IS '吨煤总成本（元/吨）';
COMMENT ON COLUMN mining_evaluations.price_per_ton IS '吨煤售价（元/吨）';
COMMENT ON COLUMN mining_evaluations.gross_margin_per_ton IS '吨煤毛利（元/吨）';
COMMENT ON COLUMN mining_evaluations.net_profit IS '净利润（万元）';
COMMENT ON COLUMN mining_evaluations.cash_flow_status IS '现金流状况：良好/一般/紧张';
COMMENT ON COLUMN mining_evaluations.operation_details IS '运营细节（JSONB 10项）：equipment_aging, main_equipment_years, staff_turnover_pct, supply_chain_stability, construction_period_years, fixed_assets_invested, tech_upgrade_capital_needed, existing_debt, external_guarantees, contingent_liabilities';
COMMENT ON COLUMN mining_evaluations.market_risk_details IS '市场与行业风险（JSONB 16项）：coal_price_volatility_3yr, price_forecast_3yr, supply_demand, policy_regulation, regional_competition, discount_rate_pct, mining_right_equity_coeff, geological_risk_coeff, regional_policy_direction, long_term_client_pct, client_stability, transport_radius_km, transport_cost_per_ton, transport_route_stability, price_impact_coeff, renewable_substitution_risk';
COMMENT ON COLUMN mining_evaluations.disposal_details IS '变现与处置能力（JSONB 14项）：is_mainstream_mineral, regional_trading_activity, historical_deals, quick_transfer_feasible, needs_resource_integration, buyer_entry_barrier, scale_integration_opportunity, industry_chain_integration, consolidation_opportunity, similar_deal_cycle_months, transfer_approval_months, disposal_tax_cost, potential_buyer_market_size, cancellation_integration_cost';
COMMENT ON COLUMN mining_evaluations.overall_rating IS '整体评价结果：优秀/良好/一般/较差';
COMMENT ON COLUMN mining_evaluations.core_resource_advantages IS '核心资源优势';
COMMENT ON COLUMN mining_evaluations.core_operation_advantages IS '核心运营优势';
COMMENT ON COLUMN mining_evaluations.main_compliance_risks IS '主要合规风险';
COMMENT ON COLUMN mining_evaluations.main_market_risks IS '主要市场风险';
COMMENT ON COLUMN mining_evaluations.main_operation_risks IS '主要运营风险';
COMMENT ON COLUMN mining_evaluations.improvement_suggestions IS '总体改进建议';
COMMENT ON COLUMN mining_evaluations.investment_value IS '投资价值评估：高/中/低';
COMMENT ON COLUMN mining_evaluations.evaluator IS '评价人员';
COMMENT ON COLUMN mining_evaluations.evaluation_date IS '评价日期';
COMMENT ON COLUMN mining_evaluations.reviewer IS '审核人员';
COMMENT ON COLUMN mining_evaluations.review_date IS '审核日期';
COMMENT ON COLUMN mining_evaluations.mineral_type IS '矿种';
COMMENT ON COLUMN mining_evaluations.mine_scale IS '矿山规模：大型/中型/小型';
COMMENT ON COLUMN mining_evaluations.estimated_value IS '采矿权整体估值（元）';
COMMENT ON COLUMN mining_evaluations.transfer_base_price IS '破产协议转让底价（元），用于矿权价值倒挂探测（引擎2脱水逻辑）';
COMMENT ON COLUMN mining_evaluations.created_at IS '记录创建时间';
COMMENT ON COLUMN mining_evaluations.updated_at IS '记录最后更新时间';

CREATE INDEX idx_me_case ON mining_evaluations(case_id);
CREATE INDEX idx_me_permit_expiry ON mining_evaluations(permit_expiry);
CREATE INDEX idx_me_rating ON mining_evaluations(overall_rating);
CREATE INDEX idx_me_status ON mining_evaluations(mining_status);
CREATE INDEX idx_me_coal_type ON mining_evaluations(coal_type);
CREATE INDEX idx_me_sealed ON mining_evaluations(mining_right_sealed);

-- --------------------------------------------------

CREATE TABLE hidden_assets (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    asset_category  TEXT,
    description     TEXT,
    target_company  TEXT,
    share_ratio     NUMERIC(8,4),
    frozen_status   TEXT,
    sub_debtor      TEXT,
    ar_amount       NUMERIC(18,2),
    contract_no     TEXT,
    book_value      NUMERIC(18,2),
    assessed_value  NUMERIC(18,2),
    discovery_method TEXT,
    vehicle_plate   TEXT,
    vehicle_type    TEXT,
    vehicle_brand_model TEXT,
    actual_user     TEXT,
    insurance_checked BOOLEAN,
    equipment_model TEXT,
    equipment_condition TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE hidden_assets IS '隐形资产表：动产/股权/知识产权/应收账款/车辆/设备等非显性资产';
COMMENT ON COLUMN hidden_assets.id IS '记录唯一标识';
COMMENT ON COLUMN hidden_assets.case_id IS '所属案件ID';
COMMENT ON COLUMN hidden_assets.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN hidden_assets.asset_category IS '资产大类：动产/对外投资/股权/知识产权/行政许可/应收账款/不动产权益';
COMMENT ON COLUMN hidden_assets.description IS '资产描述';
COMMENT ON COLUMN hidden_assets.target_company IS '投资目标公司名称（股权类资产）';
COMMENT ON COLUMN hidden_assets.share_ratio IS '持股比例（%）';
COMMENT ON COLUMN hidden_assets.frozen_status IS '股权状态：冻结/质押/正常';
COMMENT ON COLUMN hidden_assets.sub_debtor IS '次债务人名称（应收账款类）';
COMMENT ON COLUMN hidden_assets.ar_amount IS '应收账款金额（元）';
COMMENT ON COLUMN hidden_assets.contract_no IS '合同号（三单合一审计用）';
COMMENT ON COLUMN hidden_assets.book_value IS '账面价值（元）';
COMMENT ON COLUMN hidden_assets.assessed_value IS '评估价值（元）';
COMMENT ON COLUMN hidden_assets.discovery_method IS '发现方式：manual/残差分析/DNA穿透/考古发现';
COMMENT ON COLUMN hidden_assets.vehicle_plate IS '车牌号（车辆类资产）';
COMMENT ON COLUMN hidden_assets.vehicle_type IS '车辆类型：轿车/货车/船舶/工程机械';
COMMENT ON COLUMN hidden_assets.vehicle_brand_model IS '品牌型号';
COMMENT ON COLUMN hidden_assets.actual_user IS '实际使用人（非本人名下车辆排查用）';
COMMENT ON COLUMN hidden_assets.insurance_checked IS '保险记录是否已核查';
COMMENT ON COLUMN hidden_assets.equipment_model IS '设备型号（设备类资产）';
COMMENT ON COLUMN hidden_assets.equipment_condition IS '设备状态：良好/一般/老化/报废';
COMMENT ON COLUMN hidden_assets.created_at IS '记录创建时间';

-- --------------------------------------------------

CREATE TABLE financial_investments (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    holder_name     TEXT NOT NULL,
    holder_type     TEXT,
    investment_type TEXT NOT NULL,
    institution     TEXT,
    product_name    TEXT,
    account_no_masked TEXT,
    invested_amount NUMERIC(18,2),
    current_value   NUMERIC(18,2),
    frozen_status   TEXT,
    maturity_date   DATE,
    physical_asset_type TEXT,
    appraisal_value NUMERIC(18,2),
    appraiser       TEXT,
    storage_location TEXT,
    is_nominee_held BOOLEAN DEFAULT false,
    nominee_name    TEXT,
    beneficial_owner TEXT,
    data_source     TEXT,
    evidence_doc_id BIGINT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE financial_investments IS '金融投资与理财资产表：银行理财/私募/信托/股票/高值实物/代持股权';
COMMENT ON COLUMN financial_investments.id IS '记录唯一标识';
COMMENT ON COLUMN financial_investments.case_id IS '所属案件ID';
COMMENT ON COLUMN financial_investments.holder_name IS '持有人姓名';
COMMENT ON COLUMN financial_investments.holder_type IS '持有人类型：债务人/保证人/配偶/关联人';
COMMENT ON COLUMN financial_investments.investment_type IS '投资类型：银行理财/私募基金/信托计划/期货账户/股票账户/保险保单';
COMMENT ON COLUMN financial_investments.institution IS '金融机构名称';
COMMENT ON COLUMN financial_investments.product_name IS '产品名称';
COMMENT ON COLUMN financial_investments.account_no_masked IS '脱敏账号';
COMMENT ON COLUMN financial_investments.invested_amount IS '投入金额（元）';
COMMENT ON COLUMN financial_investments.current_value IS '当前价值（元）';
COMMENT ON COLUMN financial_investments.frozen_status IS '冻结状态：已冻结/未冻结/部分冻结';
COMMENT ON COLUMN financial_investments.maturity_date IS '到期日';
COMMENT ON COLUMN financial_investments.physical_asset_type IS '高值实物类型：古玩字画/珠宝玉石/黄金/奢侈品';
COMMENT ON COLUMN financial_investments.appraisal_value IS '鉴定价值（元）';
COMMENT ON COLUMN financial_investments.appraiser IS '鉴定机构名称';
COMMENT ON COLUMN financial_investments.storage_location IS '存放地点';
COMMENT ON COLUMN financial_investments.is_nominee_held IS '是否他人代持';
COMMENT ON COLUMN financial_investments.nominee_name IS '代持人姓名';
COMMENT ON COLUMN financial_investments.beneficial_owner IS '实际受益人姓名';
COMMENT ON COLUMN financial_investments.data_source IS '数据来源：法院总对总/银行回函/证券交易所/手工调查';
COMMENT ON COLUMN financial_investments.evidence_doc_id IS '关联证据文件ID';
COMMENT ON COLUMN financial_investments.notes IS '备注';
COMMENT ON COLUMN financial_investments.created_at IS '记录创建时间';

CREATE INDEX idx_fi_case ON financial_investments(case_id);
CREATE INDEX idx_fi_holder ON financial_investments(holder_name);
CREATE INDEX idx_fi_type ON financial_investments(investment_type);

-- --------------------------------------------------

CREATE TABLE digital_assets (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    holder_name     TEXT NOT NULL,
    asset_type      TEXT NOT NULL,
    platform        TEXT,
    account_id_masked TEXT,
    estimated_value NUMERIC(18,2),
    valuation_basis TEXT,
    wallet_address  TEXT,
    crypto_type     TEXT,
    crypto_amount   NUMERIC(24,8),
    membership_type TEXT,
    membership_org  TEXT,
    transferable    BOOLEAN,
    discovery_method TEXT,
    evidence_doc_id BIGINT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE digital_assets IS '虚拟与数字资产表：游戏账号/直播账号/NFT/虚拟货币/高端会员权益';
COMMENT ON COLUMN digital_assets.id IS '记录唯一标识';
COMMENT ON COLUMN digital_assets.case_id IS '所属案件ID';
COMMENT ON COLUMN digital_assets.holder_name IS '持有人姓名';
COMMENT ON COLUMN digital_assets.asset_type IS '资产类型：游戏账号/直播账号/社交媒体大V/NFT数字藏品/虚拟货币/会员权益/手机靓号';
COMMENT ON COLUMN digital_assets.platform IS '平台名称';
COMMENT ON COLUMN digital_assets.account_id_masked IS '脱敏账号';
COMMENT ON COLUMN digital_assets.estimated_value IS '估值（元）';
COMMENT ON COLUMN digital_assets.valuation_basis IS '估值依据';
COMMENT ON COLUMN digital_assets.wallet_address IS '虚拟货币钱包地址';
COMMENT ON COLUMN digital_assets.crypto_type IS '币种：BTC/ETH/USDT等';
COMMENT ON COLUMN digital_assets.crypto_amount IS '持有数量';
COMMENT ON COLUMN digital_assets.membership_type IS '会员类型：高尔夫/高端会所/航空里程/酒店会籍';
COMMENT ON COLUMN digital_assets.membership_org IS '会员所属机构';
COMMENT ON COLUMN digital_assets.transferable IS '是否可转让';
COMMENT ON COLUMN digital_assets.discovery_method IS '发现方式：社交平台检索/法院调查令/区块链分析';
COMMENT ON COLUMN digital_assets.evidence_doc_id IS '关联证据文件ID';
COMMENT ON COLUMN digital_assets.notes IS '备注';
COMMENT ON COLUMN digital_assets.created_at IS '记录创建时间';

CREATE INDEX idx_da_case ON digital_assets(case_id);
CREATE INDEX idx_da_type ON digital_assets(asset_type);

-- --------------------------------------------------

CREATE TABLE overseas_assets (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    holder_name     TEXT NOT NULL,
    entry_exit_checked BOOLEAN DEFAULT false,
    travel_frequency   TEXT,
    frequent_destinations TEXT[],
    avg_stay_days      INT,
    offshore_bank_accounts TEXT,
    offshore_company   TEXT,
    offshore_company_jurisdiction TEXT,
    offshore_equity_pct NUMERIC(8,4),
    overseas_property  TEXT,
    overseas_property_location TEXT,
    overseas_insurance TEXT,
    insurance_cash_value NUMERIC(18,2),
    judicial_assistance_status TEXT,
    assistance_treaty TEXT,
    discovery_method TEXT,
    evidence_doc_id BIGINT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE overseas_assets IS '境外资产线索表：出入境记录/离岸公司/海外房产/境外保单';
COMMENT ON COLUMN overseas_assets.id IS '记录唯一标识';
COMMENT ON COLUMN overseas_assets.case_id IS '所属案件ID';
COMMENT ON COLUMN overseas_assets.holder_name IS '资产持有人姓名';
COMMENT ON COLUMN overseas_assets.entry_exit_checked IS '出入境记录是否已核查';
COMMENT ON COLUMN overseas_assets.travel_frequency IS '出行频率：频繁/偶尔/无记录';
COMMENT ON COLUMN overseas_assets.frequent_destinations IS '常去目的地数组';
COMMENT ON COLUMN overseas_assets.avg_stay_days IS '平均停留天数';
COMMENT ON COLUMN overseas_assets.offshore_bank_accounts IS '境外银行账户信息';
COMMENT ON COLUMN overseas_assets.offshore_company IS '离岸公司名称';
COMMENT ON COLUMN overseas_assets.offshore_company_jurisdiction IS '离岸公司注册地：BVI/开曼/新加坡等';
COMMENT ON COLUMN overseas_assets.offshore_equity_pct IS '持股比例（%）';
COMMENT ON COLUMN overseas_assets.overseas_property IS '海外房产描述';
COMMENT ON COLUMN overseas_assets.overseas_property_location IS '海外房产所在地';
COMMENT ON COLUMN overseas_assets.overseas_insurance IS '境外保险保单信息';
COMMENT ON COLUMN overseas_assets.insurance_cash_value IS '保单现金价值（元）';
COMMENT ON COLUMN overseas_assets.judicial_assistance_status IS '司法协助状态：已申请/进行中/已完成/未启动';
COMMENT ON COLUMN overseas_assets.assistance_treaty IS '适用司法协助条约';
COMMENT ON COLUMN overseas_assets.discovery_method IS '发现方式';
COMMENT ON COLUMN overseas_assets.evidence_doc_id IS '关联证据文件ID';
COMMENT ON COLUMN overseas_assets.notes IS '备注';
COMMENT ON COLUMN overseas_assets.created_at IS '记录创建时间';

CREATE INDEX idx_oa_case ON overseas_assets(case_id);
CREATE INDEX idx_oa_holder ON overseas_assets(holder_name);


-- ============================================================================
-- SECTION 5：审计引擎数据层
-- ============================================================================

CREATE TABLE transaction_signatures (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    doc_ref         TEXT,
    txn_date        DATE,
    txn_amount      NUMERIC(18,2),
    txn_direction   TEXT CHECK (txn_direction IN ('in','out')),
    counterparty    TEXT,
    maker           TEXT,
    reviewer        TEXT,
    approver        TEXT,
    is_related_party BOOLEAN DEFAULT false,
    has_invoice     BOOLEAN,
    routing_tag     TEXT,
    retention_seconds BIGINT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE transaction_signatures IS '银行流水/凭证签字人表：模块B物理痕迹提取，引擎4白手套拆解数据源';
COMMENT ON COLUMN transaction_signatures.id IS '记录唯一标识';
COMMENT ON COLUMN transaction_signatures.case_id IS '所属案件ID';
COMMENT ON COLUMN transaction_signatures.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN transaction_signatures.doc_ref IS '凭证编号/银行回单号';
COMMENT ON COLUMN transaction_signatures.txn_date IS '交易日期';
COMMENT ON COLUMN transaction_signatures.txn_amount IS '交易金额（元）';
COMMENT ON COLUMN transaction_signatures.txn_direction IS '资金方向：in(流入)/out(流出)';
COMMENT ON COLUMN transaction_signatures.counterparty IS '交易对手名称';
COMMENT ON COLUMN transaction_signatures.maker IS '制单人（签字链第一环）';
COMMENT ON COLUMN transaction_signatures.reviewer IS '复核人（签字链第二环）';
COMMENT ON COLUMN transaction_signatures.approver IS '审批签字人（签字链第三环，白手套突破口）';
COMMENT ON COLUMN transaction_signatures.is_related_party IS '是否流向关联方';
COMMENT ON COLUMN transaction_signatures.has_invoice IS '是否有对应发票';
COMMENT ON COLUMN transaction_signatures.routing_tag IS '路由标签：正常/疑似体外循环/转运节点';
COMMENT ON COLUMN transaction_signatures.retention_seconds IS '资金滞留时间（秒），用于滞留熵ΔT计算';
COMMENT ON COLUMN transaction_signatures.created_at IS '记录创建时间';

CREATE INDEX idx_ts_case ON transaction_signatures(case_id);
CREATE INDEX idx_ts_date ON transaction_signatures(txn_date);
CREATE INDEX idx_ts_counterparty ON transaction_signatures(counterparty);
CREATE INDEX idx_ts_approver ON transaction_signatures(approver);
CREATE INDEX idx_ts_routing ON transaction_signatures(routing_tag);

-- --------------------------------------------------

CREATE TABLE financial_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    report_period   TEXT,
    report_type     TEXT,
    other_receivables   NUMERIC(18,2),
    prepayments         NUMERIC(18,2),
    total_assets        NUMERIC(18,2),
    total_liabilities   NUMERIC(18,2),
    net_assets          NUMERIC(18,2),
    revenue             NUMERIC(18,2),
    operating_cost      NUMERIC(18,2),
    net_profit          NUMERIC(18,2),
    tax_reported_revenue    NUMERIC(18,2),
    tax_reported_cost       NUMERIC(18,2),
    cf_reconstructed    NUMERIC(18,2),
    epsilon             NUMERIC(18,2),
    epsilon_pct         NUMERIC(8,4),
    epsilon_verdict     TEXT,
    raw_data            JSONB,
    created_at          TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE financial_snapshots IS '财务快照表：引擎1时序基线轧差数据源，含税务-流水残差ε演算结果';
COMMENT ON COLUMN financial_snapshots.id IS '记录唯一标识';
COMMENT ON COLUMN financial_snapshots.case_id IS '所属案件ID';
COMMENT ON COLUMN financial_snapshots.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN financial_snapshots.report_period IS '报告期间：如2019-12/2020-06';
COMMENT ON COLUMN financial_snapshots.report_type IS '报表类型：资产负债表/利润表/现金流量表';
COMMENT ON COLUMN financial_snapshots.other_receivables IS '其他应收款（元）★轧差核心科目';
COMMENT ON COLUMN financial_snapshots.prepayments IS '预付账款（元）★轧差核心科目';
COMMENT ON COLUMN financial_snapshots.total_assets IS '资产总额（元）';
COMMENT ON COLUMN financial_snapshots.total_liabilities IS '负债总额（元）';
COMMENT ON COLUMN financial_snapshots.net_assets IS '净资产（元）';
COMMENT ON COLUMN financial_snapshots.revenue IS '营业收入（元）';
COMMENT ON COLUMN financial_snapshots.operating_cost IS '营业成本（元）';
COMMENT ON COLUMN financial_snapshots.net_profit IS '净利润（元）';
COMMENT ON COLUMN financial_snapshots.tax_reported_revenue IS '税务申报营收（元）——用于交叉审计';
COMMENT ON COLUMN financial_snapshots.tax_reported_cost IS '税务申报成本（元）——用于交叉审计';
COMMENT ON COLUMN financial_snapshots.cf_reconstructed IS '还原经营性现金流CF_recon（元）';
COMMENT ON COLUMN financial_snapshots.epsilon IS '税务-流水残差ε绝对值（元）';
COMMENT ON COLUMN financial_snapshots.epsilon_pct IS '残差百分比';
COMMENT ON COLUMN financial_snapshots.epsilon_verdict IS '残差判定：正常(<10%)/预警(10-30%)/体外循环(>30%)';
COMMENT ON COLUMN financial_snapshots.raw_data IS '原始财务数据JSON留档';
COMMENT ON COLUMN financial_snapshots.created_at IS '记录创建时间';

CREATE INDEX idx_fs_case ON financial_snapshots(case_id);
CREATE INDEX idx_fs_period ON financial_snapshots(report_period);
CREATE INDEX idx_fs_verdict ON financial_snapshots(epsilon_verdict);

-- --------------------------------------------------

CREATE TABLE delta_audit_results (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    baseline_period TEXT,
    explosion_period TEXT,
    account_item    TEXT,
    baseline_value  NUMERIC(18,2),
    explosion_value NUMERIC(18,2),
    delta           NUMERIC(18,2),
    loan_injection  NUMERIC(18,2),
    match_ratio     NUMERIC(8,4),
    routing_target  TEXT,
    verdict         TEXT,
    evidence_refs   JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE delta_audit_results IS '轧差审计结果表：引擎1输出，基点vs爆点跨期差额分析';
COMMENT ON COLUMN delta_audit_results.id IS '记录唯一标识';
COMMENT ON COLUMN delta_audit_results.case_id IS '所属案件ID';
COMMENT ON COLUMN delta_audit_results.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN delta_audit_results.baseline_period IS '基点期间（贷款前一年度）';
COMMENT ON COLUMN delta_audit_results.explosion_period IS '爆点期间（贷款当年度）';
COMMENT ON COLUMN delta_audit_results.account_item IS '审计科目：其他应收款/预付账款';
COMMENT ON COLUMN delta_audit_results.baseline_value IS '基点值（元）';
COMMENT ON COLUMN delta_audit_results.explosion_value IS '爆点值（元）';
COMMENT ON COLUMN delta_audit_results.delta IS '跨期差额Delta（元）';
COMMENT ON COLUMN delta_audit_results.loan_injection IS '同期贷款注入额（元）';
COMMENT ON COLUMN delta_audit_results.match_ratio IS '吻合度 = delta/loan_injection';
COMMENT ON COLUMN delta_audit_results.routing_target IS '资金最终流向描述';
COMMENT ON COLUMN delta_audit_results.verdict IS '定性结论：空壳化抽逃/体外循环/正常波动';
COMMENT ON COLUMN delta_audit_results.evidence_refs IS '证据引用JSON：{"page":12,"signer":"张三"}';
COMMENT ON COLUMN delta_audit_results.created_at IS '记录创建时间';

-- --------------------------------------------------

CREATE TABLE deadline_alerts (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    alert_type      TEXT,
    deadline_date   DATE NOT NULL,
    days_remaining  INT,
    severity        TEXT,
    related_asset   TEXT,
    action_required TEXT,
    is_resolved     BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE deadline_alerts IS '时效预警表：引擎3程序命门，监控查封/采矿证/安全证/排污证到期';
COMMENT ON COLUMN deadline_alerts.id IS '预警记录唯一标识';
COMMENT ON COLUMN deadline_alerts.case_id IS '所属案件ID';
COMMENT ON COLUMN deadline_alerts.alert_type IS '预警类型：执行续封/采矿证到期/诉讼时效/查封到期/安全生产许可证即将到期/排污许可证即将到期';
COMMENT ON COLUMN deadline_alerts.deadline_date IS '截止日期';
COMMENT ON COLUMN deadline_alerts.days_remaining IS '剩余天数（自动计算）';
COMMENT ON COLUMN deadline_alerts.severity IS '严重级别：red(<60天)/yellow(<180天)/green';
COMMENT ON COLUMN deadline_alerts.related_asset IS '关联资产描述';
COMMENT ON COLUMN deadline_alerts.action_required IS '需采取的行动';
COMMENT ON COLUMN deadline_alerts.is_resolved IS '是否已处理';
COMMENT ON COLUMN deadline_alerts.created_at IS '记录创建时间';

CREATE INDEX idx_da_deadline ON deadline_alerts(deadline_date);
CREATE INDEX idx_da_severity ON deadline_alerts(severity);

-- --------------------------------------------------

CREATE TABLE repayment_behaviors (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    payment_date    DATE,
    payment_amount  NUMERIC(18,2),
    principal_ratio NUMERIC(8,6),
    is_performative BOOLEAN DEFAULT false,
    pattern_tag     TEXT,
    notes           TEXT
);
COMMENT ON TABLE repayment_behaviors IS '偿债行为分析表：引擎4心理指纹识别，检测表演性还款';
COMMENT ON COLUMN repayment_behaviors.id IS '记录唯一标识';
COMMENT ON COLUMN repayment_behaviors.case_id IS '所属案件ID';
COMMENT ON COLUMN repayment_behaviors.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN repayment_behaviors.payment_date IS '还款日期';
COMMENT ON COLUMN repayment_behaviors.payment_amount IS '还款金额（元）';
COMMENT ON COLUMN repayment_behaviors.principal_ratio IS '还款/本金比（<0.0001即表演性还款）';
COMMENT ON COLUMN repayment_behaviors.is_performative IS '是否为表演性还款（掩盖拒执罪的刑事防御动作）';
COMMENT ON COLUMN repayment_behaviors.pattern_tag IS '行为模式标签：表演性周期汇入/实质还款/选择性还款';
COMMENT ON COLUMN repayment_behaviors.notes IS '备注';


-- ============================================================================
-- SECTION 6：资金流向穿透层
-- ============================================================================

CREATE TABLE bank_accounts (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    account_holder  TEXT NOT NULL,
    holder_type     TEXT,
    holder_relation TEXT,
    bank_name       TEXT NOT NULL,
    bank_type       TEXT,
    account_number_masked TEXT,
    account_type    TEXT,
    account_status  TEXT,
    statements_obtained BOOLEAN DEFAULT false,
    statement_period    TEXT,
    statement_doc_id    BIGINT,
    balance_at_inquiry  NUMERIC(18,2),
    inquiry_date        DATE,
    has_large_transactions BOOLEAN,
    is_closed_before_exec BOOLEAN DEFAULT false,
    pre_close_outflow     NUMERIC(18,2),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE bank_accounts IS '银行账户全量清单：覆盖国有大行/股份制/城商行/互联网银行全类型';
COMMENT ON COLUMN bank_accounts.id IS '记录唯一标识';
COMMENT ON COLUMN bank_accounts.case_id IS '所属案件ID';
COMMENT ON COLUMN bank_accounts.account_holder IS '账户持有人姓名';
COMMENT ON COLUMN bank_accounts.holder_type IS '持有人类型：债务人/保证人/配偶/关联人/亲属';
COMMENT ON COLUMN bank_accounts.holder_relation IS '与债务人关系';
COMMENT ON COLUMN bank_accounts.bank_name IS '银行名称';
COMMENT ON COLUMN bank_accounts.bank_type IS '银行类型：国有大行/股份制/城商行/农商行/互联网银行';
COMMENT ON COLUMN bank_accounts.account_number_masked IS '脱敏账号（**** **** **** 1234）';
COMMENT ON COLUMN bank_accounts.account_type IS '账户类型：借记卡/信用卡/对公账户/养老金账户/公积金关联卡';
COMMENT ON COLUMN bank_accounts.account_status IS '账户状态：正常/冻结/销户';
COMMENT ON COLUMN bank_accounts.statements_obtained IS '流水是否已获取';
COMMENT ON COLUMN bank_accounts.statement_period IS '已获取流水时段';
COMMENT ON COLUMN bank_accounts.statement_doc_id IS '流水文件关联source_documents.doc_id';
COMMENT ON COLUMN bank_accounts.balance_at_inquiry IS '查询时余额（元）';
COMMENT ON COLUMN bank_accounts.inquiry_date IS '余额查询日期';
COMMENT ON COLUMN bank_accounts.has_large_transactions IS '有无大额异常交易';
COMMENT ON COLUMN bank_accounts.is_closed_before_exec IS '是否在执行前销户（高度可疑）';
COMMENT ON COLUMN bank_accounts.pre_close_outflow IS '销户前资金流出总额（元）';
COMMENT ON COLUMN bank_accounts.notes IS '备注';
COMMENT ON COLUMN bank_accounts.created_at IS '记录创建时间';

CREATE INDEX idx_ba_case ON bank_accounts(case_id);
CREATE INDEX idx_ba_holder ON bank_accounts(account_holder);
CREATE INDEX idx_ba_bank_type ON bank_accounts(bank_type);

-- --------------------------------------------------

CREATE TABLE digital_payment_accounts (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    account_holder  TEXT NOT NULL,
    holder_type     TEXT,
    platform        TEXT NOT NULL,
    platform_type   TEXT,
    account_id_masked TEXT,
    bound_bank_cards TEXT[],
    credit_product  TEXT,
    credit_limit    NUMERIC(18,2),
    outstanding_balance NUMERIC(18,2),
    repayment_status TEXT,
    has_pos_merchant BOOLEAN DEFAULT false,
    pos_settlement_account TEXT,
    qr_code_merchant BOOLEAN DEFAULT false,
    statements_obtained BOOLEAN DEFAULT false,
    statement_period TEXT,
    total_inflow    NUMERIC(18,2),
    total_outflow   NUMERIC(18,2),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE digital_payment_accounts IS '第三方支付与新型金融账户表：微信支付/支付宝/云闪付/互联网银行/消费信贷/POS收款';
COMMENT ON COLUMN digital_payment_accounts.id IS '记录唯一标识';
COMMENT ON COLUMN digital_payment_accounts.case_id IS '所属案件ID';
COMMENT ON COLUMN digital_payment_accounts.account_holder IS '账户持有人姓名';
COMMENT ON COLUMN digital_payment_accounts.holder_type IS '持有人类型：债务人/保证人/配偶/关联人';
COMMENT ON COLUMN digital_payment_accounts.platform IS '平台名称：微信支付/支付宝/云闪付/微众银行/网商银行/京东金融';
COMMENT ON COLUMN digital_payment_accounts.platform_type IS '平台类型：第三方支付/互联网银行/消费信贷/聚合支付';
COMMENT ON COLUMN digital_payment_accounts.account_id_masked IS '脱敏账号';
COMMENT ON COLUMN digital_payment_accounts.bound_bank_cards IS '绑定银行卡列表（脱敏）';
COMMENT ON COLUMN digital_payment_accounts.credit_product IS '消费信贷产品名称：花呗/借呗/白条';
COMMENT ON COLUMN digital_payment_accounts.credit_limit IS '授信额度（元）';
COMMENT ON COLUMN digital_payment_accounts.outstanding_balance IS '未还余额（元）';
COMMENT ON COLUMN digital_payment_accounts.repayment_status IS '还款状态：正常/逾期/结清';
COMMENT ON COLUMN digital_payment_accounts.has_pos_merchant IS '是否有POS商户';
COMMENT ON COLUMN digital_payment_accounts.pos_settlement_account IS 'POS结算账户';
COMMENT ON COLUMN digital_payment_accounts.qr_code_merchant IS '是否有聚合支付收款码';
COMMENT ON COLUMN digital_payment_accounts.statements_obtained IS '流水是否已获取';
COMMENT ON COLUMN digital_payment_accounts.statement_period IS '已获取流水时段';
COMMENT ON COLUMN digital_payment_accounts.total_inflow IS '期间总流入（元）';
COMMENT ON COLUMN digital_payment_accounts.total_outflow IS '期间总流出（元）';
COMMENT ON COLUMN digital_payment_accounts.notes IS '备注';
COMMENT ON COLUMN digital_payment_accounts.created_at IS '记录创建时间';

CREATE INDEX idx_dpa_case ON digital_payment_accounts(case_id);
CREATE INDEX idx_dpa_platform ON digital_payment_accounts(platform);

-- --------------------------------------------------

CREATE TABLE abnormal_transactions (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    source_account_id BIGINT,
    source_type     TEXT,
    txn_date        TIMESTAMPTZ,
    txn_amount      NUMERIC(18,2),
    txn_direction   TEXT,
    counterparty    TEXT,
    counterparty_relation TEXT,
    abnormal_patterns TEXT[],
    suspicion_level TEXT CHECK (suspicion_level IN ('高','中','低')),
    suspicion_reason TEXT,
    linked_audit_id BIGINT,
    evidence_doc_id BIGINT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE abnormal_transactions IS '异常交易标记表：从银行/支付流水中筛出的异常模式标记';
COMMENT ON COLUMN abnormal_transactions.id IS '记录唯一标识';
COMMENT ON COLUMN abnormal_transactions.case_id IS '所属案件ID';
COMMENT ON COLUMN abnormal_transactions.source_account_id IS '来源账户ID（bank_accounts或digital_payment_accounts）';
COMMENT ON COLUMN abnormal_transactions.source_type IS '来源类型：bank/digital_payment';
COMMENT ON COLUMN abnormal_transactions.txn_date IS '交易时间';
COMMENT ON COLUMN abnormal_transactions.txn_amount IS '交易金额（元）';
COMMENT ON COLUMN abnormal_transactions.txn_direction IS '资金方向：in/out';
COMMENT ON COLUMN abnormal_transactions.counterparty IS '交易对手名称';
COMMENT ON COLUMN abnormal_transactions.counterparty_relation IS '对手与债务人关系：配偶/父母/子女/关联企业/不明';
COMMENT ON COLUMN abnormal_transactions.abnormal_patterns IS '异常特征标签数组：夜间频繁转账/固定日期大额转出/整数金额/亲属大额往来';
COMMENT ON COLUMN abnormal_transactions.suspicion_level IS '可疑程度：高/中/低';
COMMENT ON COLUMN abnormal_transactions.suspicion_reason IS '可疑原因说明';
COMMENT ON COLUMN abnormal_transactions.linked_audit_id IS '关联审计引擎结果ID';
COMMENT ON COLUMN abnormal_transactions.evidence_doc_id IS '关联证据文件ID';
COMMENT ON COLUMN abnormal_transactions.created_at IS '记录创建时间';

CREATE INDEX idx_at_case ON abnormal_transactions(case_id);
CREATE INDEX idx_at_suspicion ON abnormal_transactions(suspicion_level);
CREATE INDEX idx_at_patterns ON abnormal_transactions USING gin(abnormal_patterns);


-- ============================================================================
-- SECTION 7：人员追踪与家庭排查层
-- ============================================================================

CREATE TABLE person_tracking (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    target_name     TEXT NOT NULL,
    target_type     TEXT,
    target_id_hash  TEXT,
    has_call_records        BOOLEAN,
    call_record_period      TEXT,
    has_base_station_data   BOOLEAN,
    last_known_location     TEXT,
    location_precision      TEXT,
    social_platforms_checked TEXT[],
    social_media_findings   TEXT,
    hukou_address           TEXT,
    residence_permit_addr   TEXT,
    children_school         TEXT,
    current_employer_via_social_insurance TEXT,
    current_employer_via_housing_fund    TEXT,
    current_employer_via_tax             TEXT,
    vehicle_violations_checked BOOLEAN,
    etc_records_checked     BOOLEAN,
    last_vehicle_activity   TEXT,
    missing_person_declaration BOOLEAN DEFAULT false,
    missing_since           DATE,
    police_coordination     BOOLEAN DEFAULT false,
    judicial_detention_applied BOOLEAN DEFAULT false,
    judicial_detention_result TEXT,
    court_investigation_order_no TEXT,
    investigation_order_date    DATE,
    investigation_order_scope   TEXT,
    evidence_doc_ids        BIGINT[],
    notes                   TEXT,
    updated_at              TIMESTAMPTZ DEFAULT now(),
    created_at              TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE person_tracking IS '人员下落追踪表：覆盖通讯轨迹/行政社会数据/法律程序施压三个维度';
COMMENT ON COLUMN person_tracking.id IS '记录唯一标识';
COMMENT ON COLUMN person_tracking.case_id IS '所属案件ID';
COMMENT ON COLUMN person_tracking.target_name IS '被追踪人姓名';
COMMENT ON COLUMN person_tracking.target_type IS '被追踪人类型：债务人/保证人/实控人/关联人';
COMMENT ON COLUMN person_tracking.target_id_hash IS '身份证号哈希';
COMMENT ON COLUMN person_tracking.has_call_records IS '是否已获取手机通话记录';
COMMENT ON COLUMN person_tracking.call_record_period IS '通话记录获取时段';
COMMENT ON COLUMN person_tracking.has_base_station_data IS '是否已获取基站定位数据';
COMMENT ON COLUMN person_tracking.last_known_location IS '最后已知位置';
COMMENT ON COLUMN person_tracking.location_precision IS '定位精度：小区级/街道级/城市级';
COMMENT ON COLUMN person_tracking.social_platforms_checked IS '已检索社交平台列表';
COMMENT ON COLUMN person_tracking.social_media_findings IS '社交平台发现摘要';
COMMENT ON COLUMN person_tracking.hukou_address IS '户籍地址';
COMMENT ON COLUMN person_tracking.residence_permit_addr IS '居住证办理地址';
COMMENT ON COLUMN person_tracking.children_school IS '子女就读学校';
COMMENT ON COLUMN person_tracking.current_employer_via_social_insurance IS '社保缴纳单位（推断当前雇主）';
COMMENT ON COLUMN person_tracking.current_employer_via_housing_fund IS '公积金缴存单位（推断当前雇主）';
COMMENT ON COLUMN person_tracking.current_employer_via_tax IS '个税申报单位（推断当前雇主）';
COMMENT ON COLUMN person_tracking.vehicle_violations_checked IS '车辆违章记录是否已查';
COMMENT ON COLUMN person_tracking.etc_records_checked IS '高速ETC通行记录是否已查';
COMMENT ON COLUMN person_tracking.last_vehicle_activity IS '最后车辆活动记录';
COMMENT ON COLUMN person_tracking.missing_person_declaration IS '是否已申请宣告失踪';
COMMENT ON COLUMN person_tracking.missing_since IS '失联起始日期';
COMMENT ON COLUMN person_tracking.police_coordination IS '是否已申请公安联控';
COMMENT ON COLUMN person_tracking.judicial_detention_applied IS '是否已申请司法拘留';
COMMENT ON COLUMN person_tracking.judicial_detention_result IS '司法拘留结果';
COMMENT ON COLUMN person_tracking.court_investigation_order_no IS '法院调查令编号';
COMMENT ON COLUMN person_tracking.investigation_order_date IS '调查令签发日期';
COMMENT ON COLUMN person_tracking.investigation_order_scope IS '调查令覆盖范围';
COMMENT ON COLUMN person_tracking.evidence_doc_ids IS '关联证据文件ID数组';
COMMENT ON COLUMN person_tracking.notes IS '备注';
COMMENT ON COLUMN person_tracking.updated_at IS '记录最后更新时间';
COMMENT ON COLUMN person_tracking.created_at IS '记录创建时间';

CREATE INDEX idx_pt_case ON person_tracking(case_id);
CREATE INDEX idx_pt_target ON person_tracking(target_name);

-- --------------------------------------------------

CREATE TABLE family_asset_investigation (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    marital_status  TEXT,
    spouse_name     TEXT,
    spouse_id_hash  TEXT,
    marriage_date   DATE,
    divorce_date    DATE,
    divorce_agreement_reviewed BOOLEAN DEFAULT false,
    divorce_asset_split TEXT,
    is_suspicious_divorce BOOLEAN DEFAULT false,
    revocation_filed BOOLEAN DEFAULT false,
    joint_properties TEXT,
    joint_vehicles  TEXT,
    joint_deposits  NUMERIC(18,2),
    debtor_share_pct NUMERIC(6,4) DEFAULT 0.5,
    minor_children_assets_checked BOOLEAN DEFAULT false,
    minor_child_name TEXT,
    minor_child_property TEXT,
    minor_child_deposits NUMERIC(18,2),
    funding_source_verified BOOLEAN DEFAULT false,
    is_disguised_holding BOOLEAN DEFAULT false,
    evidence_doc_ids BIGINT[],
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE family_asset_investigation IS '婚姻家庭财产排查表：夫妻共同财产/离婚协议审查/未成年子女代持排查';
COMMENT ON COLUMN family_asset_investigation.id IS '记录唯一标识';
COMMENT ON COLUMN family_asset_investigation.case_id IS '所属案件ID';
COMMENT ON COLUMN family_asset_investigation.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN family_asset_investigation.marital_status IS '婚姻状况：已婚/离婚/丧偶/未婚';
COMMENT ON COLUMN family_asset_investigation.spouse_name IS '配偶姓名';
COMMENT ON COLUMN family_asset_investigation.spouse_id_hash IS '配偶身份证号哈希';
COMMENT ON COLUMN family_asset_investigation.marriage_date IS '结婚日期';
COMMENT ON COLUMN family_asset_investigation.divorce_date IS '离婚日期';
COMMENT ON COLUMN family_asset_investigation.divorce_agreement_reviewed IS '离婚协议是否已审查';
COMMENT ON COLUMN family_asset_investigation.divorce_asset_split IS '离婚财产分割方式：正常分割/净身出户/低价转让/无偿赠与';
COMMENT ON COLUMN family_asset_investigation.is_suspicious_divorce IS '是否疑似恶意离婚转移资产';
COMMENT ON COLUMN family_asset_investigation.revocation_filed IS '是否已申请撤销恶意财产分割协议';
COMMENT ON COLUMN family_asset_investigation.joint_properties IS '夫妻共同房产概况';
COMMENT ON COLUMN family_asset_investigation.joint_vehicles IS '夫妻共同车辆概况';
COMMENT ON COLUMN family_asset_investigation.joint_deposits IS '夫妻共同存款（元）';
COMMENT ON COLUMN family_asset_investigation.debtor_share_pct IS '债务人享有的共同财产份额（通常50%）';
COMMENT ON COLUMN family_asset_investigation.minor_children_assets_checked IS '未成年子女名下资产是否已核查';
COMMENT ON COLUMN family_asset_investigation.minor_child_name IS '未成年子女姓名';
COMMENT ON COLUMN family_asset_investigation.minor_child_property IS '子女名下房产';
COMMENT ON COLUMN family_asset_investigation.minor_child_deposits IS '子女名下大额存款（元）';
COMMENT ON COLUMN family_asset_investigation.funding_source_verified IS '出资来源是否已核实';
COMMENT ON COLUMN family_asset_investigation.is_disguised_holding IS '是否为债务人恶意代持';
COMMENT ON COLUMN family_asset_investigation.evidence_doc_ids IS '关联证据文件ID数组';
COMMENT ON COLUMN family_asset_investigation.notes IS '备注';
COMMENT ON COLUMN family_asset_investigation.created_at IS '记录创建时间';

CREATE INDEX idx_fai_case ON family_asset_investigation(case_id);

-- --------------------------------------------------

CREATE TABLE related_party_investigation (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    interviewee_name TEXT,
    interviewee_type TEXT,
    interview_date  DATE,
    interview_summary TEXT,
    key_leads       TEXT[],
    forced_audit_applied BOOLEAN DEFAULT false,
    audit_firm      TEXT,
    capital_verification_result TEXT,
    capital_flight_amount NUMERIC(18,2),
    capital_flight_method TEXT,
    related_entity_name TEXT,
    transaction_type TEXT,
    transaction_amount NUMERIC(18,2),
    is_arm_length   BOOLEAN,
    suspicion_tag   TEXT,
    evidence_doc_ids BIGINT[],
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE related_party_investigation IS '关联交易与企业异常排查表：矛盾关系人访谈/强制审计/关联企业资金往来';
COMMENT ON COLUMN related_party_investigation.id IS '记录唯一标识';
COMMENT ON COLUMN related_party_investigation.case_id IS '所属案件ID';
COMMENT ON COLUMN related_party_investigation.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN related_party_investigation.interviewee_name IS '被访谈人姓名';
COMMENT ON COLUMN related_party_investigation.interviewee_type IS '被访谈人类型：离职员工/前合作伙伴/离异配偶/前供应商';
COMMENT ON COLUMN related_party_investigation.interview_date IS '访谈日期';
COMMENT ON COLUMN related_party_investigation.interview_summary IS '访谈内容摘要';
COMMENT ON COLUMN related_party_investigation.key_leads IS '获取的线索要点数组';
COMMENT ON COLUMN related_party_investigation.forced_audit_applied IS '是否已申请企业强制审计';
COMMENT ON COLUMN related_party_investigation.audit_firm IS '审计机构名称';
COMMENT ON COLUMN related_party_investigation.capital_verification_result IS '资本金核查结果';
COMMENT ON COLUMN related_party_investigation.capital_flight_amount IS '抽逃出资金额（元）';
COMMENT ON COLUMN related_party_investigation.capital_flight_method IS '抽逃出资方式';
COMMENT ON COLUMN related_party_investigation.related_entity_name IS '关联企业名称';
COMMENT ON COLUMN related_party_investigation.transaction_type IS '交易类型：资金往来/担保/业务往来/资产转让';
COMMENT ON COLUMN related_party_investigation.transaction_amount IS '交易金额（元）';
COMMENT ON COLUMN related_party_investigation.is_arm_length IS '是否公允交易';
COMMENT ON COLUMN related_party_investigation.suspicion_tag IS '嫌疑标签：正常/疑似转移/确认转移';
COMMENT ON COLUMN related_party_investigation.evidence_doc_ids IS '关联证据文件ID数组';
COMMENT ON COLUMN related_party_investigation.notes IS '备注';
COMMENT ON COLUMN related_party_investigation.created_at IS '记录创建时间';

CREATE INDEX idx_rpi_case ON related_party_investigation(case_id);


-- ============================================================================
-- SECTION 8：司法风控与数据源管控层
-- ============================================================================

CREATE TABLE risk_profiles (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    debtor_id       BIGINT REFERENCES debtors(debtor_id),
    total_lawsuits      INT,
    as_defendant_count  INT,
    execution_records   INT,
    zhongben_cases      INT,
    is_dishonest        BOOLEAN DEFAULT false,
    is_consumption_limited BOOLEAN DEFAULT false,
    sealed_frozen_count INT,
    admin_penalties     INT,
    tax_arrears         NUMERIC(18,2),
    social_insurance_arrears NUMERIC(18,2),
    is_operating        BOOLEAN,
    social_insurance_headcount INT,
    annual_revenue      NUMERIC(18,2),
    annual_profit       NUMERIC(18,2),
    cash_flow_status    TEXT,
    executable_assets   TEXT,
    data_source         TEXT,
    snapshot_date       DATE,
    created_at          TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE risk_profiles IS '司法风控画像表：模块D 10项司法风险指标 + 经营能力评判';
COMMENT ON COLUMN risk_profiles.id IS '记录唯一标识';
COMMENT ON COLUMN risk_profiles.case_id IS '所属案件ID';
COMMENT ON COLUMN risk_profiles.debtor_id IS '关联债务人ID';
COMMENT ON COLUMN risk_profiles.total_lawsuits IS '涉诉案件总数';
COMMENT ON COLUMN risk_profiles.as_defendant_count IS '作为被告案件数';
COMMENT ON COLUMN risk_profiles.execution_records IS '被执行人记录数';
COMMENT ON COLUMN risk_profiles.zhongben_cases IS '终本案件数';
COMMENT ON COLUMN risk_profiles.is_dishonest IS '是否为失信被执行人';
COMMENT ON COLUMN risk_profiles.is_consumption_limited IS '是否被限制高消费';
COMMENT ON COLUMN risk_profiles.sealed_frozen_count IS '查封/冻结/抵押记录数';
COMMENT ON COLUMN risk_profiles.admin_penalties IS '行政处罚记录数（环保/安监/税务等）';
COMMENT ON COLUMN risk_profiles.tax_arrears IS '欠税金额（元）';
COMMENT ON COLUMN risk_profiles.social_insurance_arrears IS '欠社保金额（元）';
COMMENT ON COLUMN risk_profiles.is_operating IS '是否正常经营';
COMMENT ON COLUMN risk_profiles.social_insurance_headcount IS '社保缴纳人数';
COMMENT ON COLUMN risk_profiles.annual_revenue IS '年营收（元）';
COMMENT ON COLUMN risk_profiles.annual_profit IS '年利润（元）';
COMMENT ON COLUMN risk_profiles.cash_flow_status IS '现金流判断：好/一般/差/无';
COMMENT ON COLUMN risk_profiles.executable_assets IS '可执行财产判断：有/无/待查';
COMMENT ON COLUMN risk_profiles.data_source IS '数据来源';
COMMENT ON COLUMN risk_profiles.snapshot_date IS '数据快照日期';
COMMENT ON COLUMN risk_profiles.created_at IS '记录创建时间';

-- --------------------------------------------------

CREATE TABLE data_source_checklist (
    id              BIGSERIAL PRIMARY KEY,
    case_id         BIGINT REFERENCES cases(case_id),
    target_name     TEXT NOT NULL,
    target_type     TEXT,
    source_category TEXT NOT NULL,
    source_name     TEXT NOT NULL,
    query_status    TEXT DEFAULT '未查' CHECK (query_status IN ('未查','已申请调查令','查询中','已获取','无结果','不适用')),
    query_date      DATE,
    requires_court_order BOOLEAN DEFAULT false,
    court_order_no  TEXT,
    has_findings    BOOLEAN,
    finding_summary TEXT,
    finding_amount  NUMERIC(18,2),
    result_doc_id   BIGINT,
    compliance_note TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
COMMENT ON TABLE data_source_checklist IS '数据源排查状态追踪表：19个预置数据源检查项，覆盖企业经营/金融资产/关联控制/特殊资产';
COMMENT ON COLUMN data_source_checklist.id IS '记录唯一标识';
COMMENT ON COLUMN data_source_checklist.case_id IS '所属案件ID';
COMMENT ON COLUMN data_source_checklist.target_name IS '查询对象名称';
COMMENT ON COLUMN data_source_checklist.target_type IS '对象类型：债务人/保证人/实控人/配偶/关联企业';
COMMENT ON COLUMN data_source_checklist.source_category IS '数据源分类：企业经营/金融资产/关联控制/特殊资产';
COMMENT ON COLUMN data_source_checklist.source_name IS '具体数据源名称';
COMMENT ON COLUMN data_source_checklist.query_status IS '排查状态：未查/已申请调查令/查询中/已获取/无结果/不适用';
COMMENT ON COLUMN data_source_checklist.query_date IS '查询日期';
COMMENT ON COLUMN data_source_checklist.requires_court_order IS '是否需要法院调查令';
COMMENT ON COLUMN data_source_checklist.court_order_no IS '调查令编号';
COMMENT ON COLUMN data_source_checklist.has_findings IS '是否有发现';
COMMENT ON COLUMN data_source_checklist.finding_summary IS '发现摘要';
COMMENT ON COLUMN data_source_checklist.finding_amount IS '涉及金额（元）';
COMMENT ON COLUMN data_source_checklist.result_doc_id IS '结果文件关联source_documents.doc_id';
COMMENT ON COLUMN data_source_checklist.compliance_note IS '合规提示';
COMMENT ON COLUMN data_source_checklist.notes IS '备注';
COMMENT ON COLUMN data_source_checklist.created_at IS '记录创建时间';
COMMENT ON COLUMN data_source_checklist.updated_at IS '记录最后更新时间';

CREATE INDEX idx_dsc_case ON data_source_checklist(case_id);
CREATE INDEX idx_dsc_status ON data_source_checklist(query_status);
CREATE INDEX idx_dsc_source ON data_source_checklist(source_category, source_name);


-- ============================================================================
-- SECTION 9：增量同步控制
-- ============================================================================

CREATE TABLE crawl_logs (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        TEXT UNIQUE NOT NULL,
    source          TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    total_fetched   INT DEFAULT 0,
    total_inserted  INT DEFAULT 0,
    total_updated   INT DEFAULT 0,
    total_errors    INT DEFAULT 0,
    error_details   JSONB,
    status          TEXT DEFAULT 'running'
);
COMMENT ON TABLE crawl_logs IS '采集任务日志表：追踪法律文书/工商数据增量采集状态';
COMMENT ON COLUMN crawl_logs.id IS '记录唯一标识';
COMMENT ON COLUMN crawl_logs.batch_id IS '采集批次号（唯一）';
COMMENT ON COLUMN crawl_logs.source IS '数据源：wenshu/aiqicha/qichacha';
COMMENT ON COLUMN crawl_logs.started_at IS '任务开始时间';
COMMENT ON COLUMN crawl_logs.finished_at IS '任务结束时间';
COMMENT ON COLUMN crawl_logs.total_fetched IS '本批次拉取总数';
COMMENT ON COLUMN crawl_logs.total_inserted IS '本批次新增数';
COMMENT ON COLUMN crawl_logs.total_updated IS '本批次更新数';
COMMENT ON COLUMN crawl_logs.total_errors IS '本批次错误数';
COMMENT ON COLUMN crawl_logs.error_details IS '错误详情JSON';
COMMENT ON COLUMN crawl_logs.status IS '任务状态：running/completed/failed';

-- --------------------------------------------------

CREATE TABLE embedding_queue (
    id              BIGSERIAL PRIMARY KEY,
    doc_id          BIGINT REFERENCES legal_documents(doc_id),
    chunk_id        BIGINT,
    status          TEXT DEFAULT 'pending',
    retry_count     INT DEFAULT 0,
    error_msg       TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    processed_at    TIMESTAMPTZ
);
COMMENT ON TABLE embedding_queue IS 'Embedding生成队列表：异步向量化任务管理';
COMMENT ON COLUMN embedding_queue.id IS '记录唯一标识';
COMMENT ON COLUMN embedding_queue.doc_id IS '关联文书ID';
COMMENT ON COLUMN embedding_queue.chunk_id IS '关联分块ID（NULL=待分块，有值=待embedding）';
COMMENT ON COLUMN embedding_queue.status IS '任务状态：pending/processing/done/error';
COMMENT ON COLUMN embedding_queue.retry_count IS '重试次数';
COMMENT ON COLUMN embedding_queue.error_msg IS '错误信息';
COMMENT ON COLUMN embedding_queue.created_at IS '任务创建时间';
COMMENT ON COLUMN embedding_queue.processed_at IS '任务完成时间';

CREATE INDEX idx_eq_status ON embedding_queue(status);


-- ============================================================================
-- SECTION 10：函数
-- ============================================================================

-- F1：语义检索函数
CREATE OR REPLACE FUNCTION search_similar_chunks(
    query_embedding vector(1024),
    match_count INT DEFAULT 10,
    similarity_threshold FLOAT DEFAULT 0.7,
    filter_case_cause TEXT DEFAULT NULL,
    filter_section TEXT DEFAULT NULL
)
RETURNS TABLE (
    chunk_id BIGINT, doc_id BIGINT, case_number TEXT,
    section_type TEXT, chunk_text TEXT, similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT dc.chunk_id, dc.doc_id, dc.case_number, dc.section_type, dc.chunk_text,
           1 - (dc.embedding <=> query_embedding) AS similarity
    FROM doc_chunks dc
    WHERE (filter_case_cause IS NULL OR dc.case_cause = filter_case_cause)
      AND (filter_section IS NULL OR dc.section_type = filter_section)
      AND 1 - (dc.embedding <=> query_embedding) > similarity_threshold
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION search_similar_chunks IS '语义检索函数：输入查询向量，返回最相关的法律文书分块，支持按案由和段落类型过滤';

-- F2：时效预警自动刷新
CREATE OR REPLACE FUNCTION refresh_deadline_alerts()
RETURNS void AS $$
BEGIN
    UPDATE deadline_alerts
    SET days_remaining = deadline_date - CURRENT_DATE,
        severity = CASE
            WHEN deadline_date - CURRENT_DATE < 60 THEN 'red'
            WHEN deadline_date - CURRENT_DATE < 180 THEN 'yellow'
            ELSE 'green' END
    WHERE is_resolved = false;

    INSERT INTO deadline_alerts (case_id, alert_type, deadline_date, days_remaining, severity, related_asset, action_required)
    SELECT re.case_id, '查封到期', re.seal_expiry, re.seal_expiry - CURRENT_DATE,
        CASE WHEN re.seal_expiry - CURRENT_DATE < 60 THEN 'red' WHEN re.seal_expiry - CURRENT_DATE < 180 THEN 'yellow' ELSE 'green' END,
        coalesce(re.project_name,'') || ' - ' || coalesce(re.property_address,''), '申请续封'
    FROM real_estate_evaluations re
    WHERE re.seal_expiry IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM deadline_alerts da WHERE da.case_id = re.case_id AND da.alert_type = '查封到期'
          AND da.related_asset = coalesce(re.project_name,'') || ' - ' || coalesce(re.property_address,''))
    ON CONFLICT DO NOTHING;

    INSERT INTO deadline_alerts (case_id, alert_type, deadline_date, days_remaining, severity, related_asset, action_required)
    SELECT me.case_id, '采矿证到期', me.permit_expiry, me.permit_expiry - CURRENT_DATE,
        CASE WHEN me.permit_expiry - CURRENT_DATE < 60 THEN 'red' WHEN me.permit_expiry - CURRENT_DATE < 180 THEN 'yellow' ELSE 'green' END,
        coalesce(me.mine_name,'') || ' - ' || coalesce(me.mineral_type,''), '跟进采矿权续期或处置'
    FROM mining_evaluations me
    WHERE me.permit_expiry IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM deadline_alerts da WHERE da.case_id = me.case_id AND da.alert_type = '采矿证到期'
          AND da.related_asset = coalesce(me.mine_name,'') || ' - ' || coalesce(me.mineral_type,''))
    ON CONFLICT DO NOTHING;

    INSERT INTO deadline_alerts (case_id, alert_type, deadline_date, days_remaining, severity, related_asset, action_required)
    SELECT me.case_id, '安全生产许可证即将到期', CURRENT_DATE + 90, 90, 'yellow', coalesce(me.mine_name,''), '核查安全生产许可证有效期并续期'
    FROM mining_evaluations me WHERE me.safety_permit_status = '即将到期'
      AND NOT EXISTS (SELECT 1 FROM deadline_alerts da WHERE da.case_id = me.case_id AND da.alert_type = '安全生产许可证即将到期')
    ON CONFLICT DO NOTHING;

    INSERT INTO deadline_alerts (case_id, alert_type, deadline_date, days_remaining, severity, related_asset, action_required)
    SELECT me.case_id, '排污许可证即将到期', CURRENT_DATE + 90, 90, 'yellow', coalesce(me.mine_name,''), '核查排污许可证有效期并续期'
    FROM mining_evaluations me WHERE me.emission_permit_status = '即将到期'
      AND NOT EXISTS (SELECT 1 FROM deadline_alerts da WHERE da.case_id = me.case_id AND da.alert_type = '排污许可证即将到期')
    ON CONFLICT DO NOTHING;
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION refresh_deadline_alerts IS '时效预警自动刷新：更新剩余天数，自动从不动产/采矿权/安全证/排污证生成到期预警';

-- F3：数据源检查项批量初始化
CREATE OR REPLACE FUNCTION init_data_source_checklist(p_case_id BIGINT, p_target_name TEXT, p_target_type TEXT)
RETURNS void AS $$
BEGIN
    INSERT INTO data_source_checklist (case_id, target_name, target_type, source_category, source_name, requires_court_order, compliance_note) VALUES
    (p_case_id, p_target_name, p_target_type, '企业经营', '中征应收账款融资服务平台', true, '依法查询，用于确认企业偿债能力'),
    (p_case_id, p_target_name, p_target_type, '企业经营', '税务开票系统', true, '依法查询，用于确认企业偿债能力'),
    (p_case_id, p_target_name, p_target_type, '企业经营', '社保缴纳系统', true, '需依法协查，避免违规获取'),
    (p_case_id, p_target_name, p_target_type, '企业经营', '公积金缴存系统', true, '需依法协查，避免违规获取'),
    (p_case_id, p_target_name, p_target_type, '企业经营', '水电煤气大户台账', true, '需依法协查，避免违规获取'),
    (p_case_id, p_target_name, p_target_type, '金融资产', '基金备案系统', true, '需法院调查令'),
    (p_case_id, p_target_name, p_target_type, '金融资产', '信托备案系统', true, '需法院调查令'),
    (p_case_id, p_target_name, p_target_type, '金融资产', '资管产品备案系统', true, '需法院调查令'),
    (p_case_id, p_target_name, p_target_type, '金融资产', '动产融资统一登记公示系统', false, '公开可查，重点标注质押状态'),
    (p_case_id, p_target_name, p_target_type, '金融资产', '知识产权质押登记系统', false, '公开可查，重点标注质押状态'),
    (p_case_id, p_target_name, p_target_type, '关联控制', '企业受益所有人备案系统', false, '公开可查，结合线索交叉验证'),
    (p_case_id, p_target_name, p_target_type, '关联控制', '失信被执行人关联查询', false, '公开可查，结合线索交叉验证'),
    (p_case_id, p_target_name, p_target_type, '关联控制', '裁判文书网', false, '公开可查，留存相关文书作为依据'),
    (p_case_id, p_target_name, p_target_type, '关联控制', '执行信息公开网', false, '公开可查，留存相关文书作为依据'),
    (p_case_id, p_target_name, p_target_type, '特殊资产', '国有资产交易平台', false, '公开可查，重点核查交易价格合理性'),
    (p_case_id, p_target_name, p_target_type, '特殊资产', '二手车备案系统', false, '公开可查，重点核查交易价格合理性'),
    (p_case_id, p_target_name, p_target_type, '特殊资产', '二手房备案系统', false, '公开可查，重点核查交易价格合理性'),
    (p_case_id, p_target_name, p_target_type, '特殊资产', '海关进出口数据', true, '需依法协查，确认权益变现能力'),
    (p_case_id, p_target_name, p_target_type, '特殊资产', '特许经营权登记（取水/林权/电信/排污）', true, '需依法协查，确认权益变现能力');
END;
$$ LANGUAGE plpgsql;
COMMENT ON FUNCTION init_data_source_checklist IS '数据源检查项批量初始化：一键为指定案件和对象生成19个预置数据源检查项，含合规提示和调查令要求';


-- ============================================================================
-- SECTION 11：视图
-- ============================================================================

CREATE OR REPLACE VIEW v_five_same_audit AS
SELECT a.enterprise_id AS ent_a_id, a.entity_name AS ent_a_name,
       b.enterprise_id AS ent_b_id, b.entity_name AS ent_b_name,
       (CASE WHEN a.addr_hash = b.addr_hash AND a.addr_hash IS NOT NULL THEN 1 ELSE 0 END) AS same_addr,
       (CASE WHEN a.phone_hash = b.phone_hash AND a.phone_hash IS NOT NULL THEN 1 ELSE 0 END) AS same_phone,
       (CASE WHEN a.legal_rep = b.legal_rep AND a.legal_rep IS NOT NULL THEN 1 ELSE 0 END) AS same_legal_rep,
       (CASE WHEN EXISTS (SELECT 1 FROM executives ea JOIN executives eb ON ea.person_name = eb.person_name
            WHERE ea.enterprise_id = a.enterprise_id AND eb.enterprise_id = b.enterprise_id
              AND ea.departure_date IS NULL AND eb.departure_date IS NULL) THEN 1 ELSE 0 END) AS same_executive,
       (CASE WHEN a.industry_code = b.industry_code AND a.industry_code IS NOT NULL THEN 1 ELSE 0 END) AS same_industry
FROM enterprises a CROSS JOIN enterprises b WHERE a.enterprise_id < b.enterprise_id;
COMMENT ON VIEW v_five_same_audit IS '五同特征审计视图（引擎2）：自动计算任意两家企业的同地址/同电话/同法人/同高管/同行业打分';

CREATE OR REPLACE VIEW v_legal_opinion_gaps AS
SELECT case_id, file_name, file_category, scan_quality, capture_gap_note
FROM source_documents WHERE is_referenced_in_legal_opinion = true AND is_captured = false;
COMMENT ON VIEW v_legal_opinion_gaps IS '法律意见书引用缺失视图：列出法律意见书引用但尚未入库的文件清单';

CREATE OR REPLACE VIEW v_mining_compliance_flags AS
SELECT me.case_id, me.mine_name,
    (CASE WHEN me.in_ecological_redline THEN 1 ELSE 0 END + CASE WHEN me.in_prohibited_zone THEN 1 ELSE 0 END
     + CASE WHEN me.is_obsolete_capacity THEN 1 ELSE 0 END + CASE WHEN me.major_violations THEN 1 ELSE 0 END
     + CASE WHEN me.env_penalties_5yr THEN 1 ELSE 0 END + CASE WHEN me.area_dispute THEN 1 ELSE 0 END
     + CASE WHEN me.is_legal_mining = false THEN 1 ELSE 0 END
     + CASE WHEN me.safety_permit_status IN ('已过期','即将到期') THEN 1 ELSE 0 END
     + CASE WHEN me.env_approval_status IN ('无','过期') THEN 1 ELSE 0 END
     + CASE WHEN me.emission_permit_status IN ('已过期','即将到期') THEN 1 ELSE 0 END
     + CASE WHEN me.mining_right_payment IN ('未缴纳','部分缴纳') THEN 1 ELSE 0 END
     + CASE WHEN me.resource_tax = '欠缴' THEN 1 ELSE 0 END
     + CASE WHEN me.compensation_fee = '欠缴' THEN 1 ELSE 0 END) AS red_flag_count,
    me.in_ecological_redline, me.in_prohibited_zone, me.is_obsolete_capacity, me.major_violations,
    me.safety_permit_status, me.env_approval_status, me.emission_permit_status,
    me.mining_right_payment, me.resource_tax, me.compensation_fee,
    me.safety_accident_history, me.permit_renewal_history, me.overall_rating
FROM mining_evaluations me;
COMMENT ON VIEW v_mining_compliance_flags IS '采矿权合规红旗计数器：自动汇总13项合规风险指标，一眼识别高风险矿权';

CREATE OR REPLACE VIEW v_investigation_progress AS
SELECT c.case_id, c.case_name,
    (SELECT count(*) FROM data_source_checklist d WHERE d.case_id = c.case_id) AS total_sources,
    (SELECT count(*) FROM data_source_checklist d WHERE d.case_id = c.case_id AND d.query_status = '已获取') AS sources_completed,
    (SELECT count(*) FROM data_source_checklist d WHERE d.case_id = c.case_id AND d.query_status = '未查') AS sources_pending,
    (SELECT count(*) FROM source_documents s WHERE s.case_id = c.case_id AND s.is_referenced_in_legal_opinion = true) AS legal_ref_total,
    (SELECT count(*) FROM source_documents s WHERE s.case_id = c.case_id AND s.is_referenced_in_legal_opinion = true AND s.is_captured = true) AS legal_ref_captured,
    (SELECT count(*) FROM source_documents s WHERE s.case_id = c.case_id AND s.needs_rescan = true) AS files_need_rescan,
    (SELECT count(*) FROM person_tracking p WHERE p.case_id = c.case_id) AS persons_tracked,
    (SELECT count(*) FROM bank_accounts b WHERE b.case_id = c.case_id) AS bank_accounts_found,
    (SELECT count(*) FROM digital_payment_accounts dp WHERE dp.case_id = c.case_id) AS digital_accounts_found,
    (SELECT count(*) FROM abnormal_transactions at2 WHERE at2.case_id = c.case_id AND at2.suspicion_level = '高') AS high_suspicion_txns,
    (SELECT count(*) FROM financial_investments fi WHERE fi.case_id = c.case_id) AS financial_assets_found,
    (SELECT count(*) FROM digital_assets da3 WHERE da3.case_id = c.case_id) AS digital_assets_found,
    (SELECT count(*) FROM overseas_assets oa WHERE oa.case_id = c.case_id) AS overseas_leads,
    (SELECT count(*) FROM deadline_alerts dl WHERE dl.case_id = c.case_id AND dl.severity = 'red' AND dl.is_resolved = false) AS red_alerts
FROM cases c;
COMMENT ON VIEW v_investigation_progress IS '案件排查完成度仪表盘：实时汇总数据源排查/文件完整性/人员追踪/资产发现/时效预警进度';

CREATE OR REPLACE VIEW v_case_todo_list AS
SELECT case_id, '文件管理' AS category, '需重新扫描: ' || file_name AS todo_item, 'high' AS priority FROM source_documents WHERE needs_rescan = true
UNION ALL SELECT case_id, '文件管理', '法律意见书引用缺失: ' || file_name, 'critical' FROM source_documents WHERE is_referenced_in_legal_opinion = true AND is_captured = false
UNION ALL SELECT case_id, '数据源排查', source_category || ' - ' || source_name || ' [' || target_name || ']', CASE WHEN requires_court_order THEN 'medium' ELSE 'low' END FROM data_source_checklist WHERE query_status = '未查'
UNION ALL SELECT case_id, '时效预警', alert_type || ': ' || related_asset || ' (剩余' || days_remaining || '天)', 'critical' FROM deadline_alerts WHERE severity = 'red' AND is_resolved = false
UNION ALL SELECT case_id, '资金穿透', '高度可疑交易: ' || counterparty || ' ¥' || txn_amount::TEXT, 'high' FROM abnormal_transactions WHERE suspicion_level = '高';
COMMENT ON VIEW v_case_todo_list IS '案件待办事项聚合视图：自动汇聚缺失文件/未查数据源/红色时效/可疑交易为统一待办列表';


-- ============================================================================
-- 建库完成
-- 36张表 | 5个视图 | 3个函数 | 84个索引 | 全列COMMENT
-- ============================================================================
