-- ============================================================================
-- 拿包前业务线：资产包筛选与投决（快筛模式）数据模型 v1
-- 设计依据：docs/business/拿包前业务线-资产包筛选与投决.md §8.2 / §8.7
-- 变更备忘：sql/screening_tables 备忘 v1.md
--
-- 依赖约定（影子 case 路线，详见文档 §8.7）：
--   建包时同步在 cases 表预建影子 case（case_type='资产包'，status='筛选中'，
--   notes 带 {"biz_stage":"pre_acquisition","package_id":...}），
--   筛选期 ingest / 知识图谱 / 文件数据全部挂该 case_id；
--   拿包转化仅将 cases.status 翻为 '进行中'，放弃则翻为 '已放弃'。
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. packages —— 资产包（商机）主表
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.packages (
    package_id       BIGSERIAL PRIMARY KEY,
    package_name     TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT '公库' CHECK (source IN ('公库', '私库')),
    seller_org       TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'screening'
                     CHECK (status IN ('screening', 'dropped', 'acquired', 'converted')),
    case_id          BIGINT NOT NULL REFERENCES public.cases(case_id),
    household_count  INTEGER NOT NULL DEFAULT 0,
    total_principal  NUMERIC(18,2),
    total_claim      NUMERIC(18,2),
    asking_price     NUMERIC(18,2),
    region           TEXT NOT NULL DEFAULT '',
    dropped_reason   TEXT NOT NULL DEFAULT '',
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.packages IS '资产包（商机）主表；拿包前筛选阶段的根实体，与影子 case 一对一（1 包 = 1 case），漏斗统计（看包→尽调→拿包）以本表 status 为准。';
COMMENT ON COLUMN public.packages.package_id IS '资产包主键。';
COMMENT ON COLUMN public.packages.package_name IS '资产包名称（挂牌名称或内部命名）。';
COMMENT ON COLUMN public.packages.source IS '包来源渠道：公库=公开挂牌，私库=私下议价/定向。';
COMMENT ON COLUMN public.packages.seller_org IS '出让方机构（商业银行/AMC 等）。';
COMMENT ON COLUMN public.packages.status IS '商机状态：screening=筛选中，dropped=已放弃，acquired=拿包成功（已受让待转化），converted=已转正式 case（影子 case 状态已翻为进行中）。';
COMMENT ON COLUMN public.packages.case_id IS '影子 case ID；建包时即在 cases 表预建（case_type=资产包，status=筛选中），筛选期卷宗/图谱数据全部挂此 ID，转化时只翻 cases.status，不迁移数据。';
COMMENT ON COLUMN public.packages.household_count IS '包内债权户数（《指引》优选 3—10 户）。';
COMMENT ON COLUMN public.packages.total_principal IS '包内债权本金合计（元）。';
COMMENT ON COLUMN public.packages.total_claim IS '包内债权本息合计（元）；收购折扣率统一基于本息计算。';
COMMENT ON COLUMN public.packages.asking_price IS '挂牌价/出让方报价（元）；私库可为空。';
COMMENT ON COLUMN public.packages.region IS '资产主要所在区域（用于区域能级评分与法拍数据匹配）。';
COMMENT ON COLUMN public.packages.dropped_reason IS '放弃原因；status=dropped 时填写（一票否决命中/评分不足/价格谈不拢等）。';
COMMENT ON COLUMN public.packages.metadata IS '扩展载荷；保留挂牌编号、尽调截止日、竞价轮次等后续字段。';

-- ----------------------------------------------------------------------------
-- 2. screening_item_catalog —— 评分项目录（《指引》评分表的执行化定义）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.screening_item_catalog (
    item_key     TEXT PRIMARY KEY,
    dimension    TEXT NOT NULL,
    name         TEXT NOT NULL,
    criteria     TEXT NOT NULL DEFAULT '',
    check_points TEXT NOT NULL DEFAULT '',
    max_score    NUMERIC(4,1) NOT NULL,
    is_veto      BOOLEAN NOT NULL DEFAULT FALSE,
    automation   TEXT NOT NULL DEFAULT 'llm' CHECK (automation IN ('rule', 'llm', 'manual')),
    sort_order   INTEGER NOT NULL,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.screening_item_catalog IS '评分项目录；《不良资产债权项目筛选与评估指引》100 分评分表的执行化定义，scorecard 明细按本目录逐项生成，总分=各维度满分之和（20+28+22+15+15=100）。';
COMMENT ON COLUMN public.screening_item_catalog.item_key IS '评分项编码（维度.条目，如 compliance.limitation_period）。';
COMMENT ON COLUMN public.screening_item_catalog.dimension IS '所属维度编码：compliance=合规合法性(20)，collateral=抵质押担保实力(28)，debtor=债务主体与保证人(22)，environment=行业与区域环境(15)，disposal=处置效率与收益预期(15)。';
COMMENT ON COLUMN public.screening_item_catalog.name IS '评分项中文名（与《指引》评分表一致）。';
COMMENT ON COLUMN public.screening_item_catalog.criteria IS '评分标准（《指引》原文档位描述）。';
COMMENT ON COLUMN public.screening_item_catalog.check_points IS '核查要点（《指引》原文）。';
COMMENT ON COLUMN public.screening_item_catalog.max_score IS '该项满分。';
COMMENT ON COLUMN public.screening_item_catalog.is_veto IS '是否一票否决项；命中即终止评分直接否决，且强制人工确认。';
COMMENT ON COLUMN public.screening_item_catalog.automation IS '自动化方式（文档 §8.4）：rule=纯规则代码算，llm=LLM 预填+证据角标，manual=人工为主机器留白。';
COMMENT ON COLUMN public.screening_item_catalog.sort_order IS '展示排序。';
COMMENT ON COLUMN public.screening_item_catalog.enabled IS '是否启用；评分表调整时停用旧项而非删除，保历史可解释。';

-- ----------------------------------------------------------------------------
-- 3. screening_scorecards —— 评分卡主表（一包多版本）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.screening_scorecards (
    scorecard_id    BIGSERIAL PRIMARY KEY,
    package_id      BIGINT NOT NULL REFERENCES public.packages(package_id) ON DELETE CASCADE,
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
    total_score     NUMERIC(5,1),
    grade           TEXT CHECK (grade IN ('A', 'B', 'C', 'D')),
    veto_triggered  BOOLEAN NOT NULL DEFAULT FALSE,
    decision        TEXT NOT NULL DEFAULT '' ,
    confirmed_by    TEXT NOT NULL DEFAULT '',
    confirmed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_screening_scorecards_pkg_ver UNIQUE (package_id, version)
);

COMMENT ON TABLE public.screening_scorecards IS '评分卡主表；一个包可多版本（卷宗补充/重评即开新版本），draft 为机器预填态，confirmed 为老板定稿态。';
COMMENT ON COLUMN public.screening_scorecards.scorecard_id IS '评分卡主键。';
COMMENT ON COLUMN public.screening_scorecards.package_id IS '所属资产包 ID。';
COMMENT ON COLUMN public.screening_scorecards.version IS '版本号；同包递增，重评不覆盖旧版本。';
COMMENT ON COLUMN public.screening_scorecards.status IS '评分卡状态：draft=机器预填待人工，confirmed=已定稿（总分/评级/结论锁定，明细不再可改）。';
COMMENT ON COLUMN public.screening_scorecards.total_score IS '当前总分；draft 态为机器建议分合计，confirmed 态为人工确认分合计（确认分缺省取建议分）。';
COMMENT ON COLUMN public.screening_scorecards.grade IS '评级（《指引》门槛）：A≥85 优质，B 70–84 中等，C 65–69 风险偏高，D<65 直接放弃；准入门槛 ≥65。';
COMMENT ON COLUMN public.screening_scorecards.veto_triggered IS '是否触发一票否决；为 TRUE 时无论总分多少均建议否决。';
COMMENT ON COLUMN public.screening_scorecards.decision IS '投决结论；confirmed 时落定：acquire=拿包，drop=放弃，空=未决。';
COMMENT ON COLUMN public.screening_scorecards.confirmed_by IS '定稿人（老板角色）。';
COMMENT ON COLUMN public.screening_scorecards.confirmed_at IS '定稿时间。';

-- ----------------------------------------------------------------------------
-- 4. screening_scorecard_items —— 评分明细（机器预填字段与人工确认字段分列）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.screening_scorecard_items (
    id                  BIGSERIAL PRIMARY KEY,
    scorecard_id        BIGINT NOT NULL REFERENCES public.screening_scorecards(scorecard_id) ON DELETE CASCADE,
    item_key            TEXT NOT NULL REFERENCES public.screening_item_catalog(item_key),
    suggested_score     NUMERIC(4,1),
    confidence          NUMERIC(5,4),
    suggested_rationale TEXT NOT NULL DEFAULT '',
    evidence_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,
    veto_hit            BOOLEAN,
    confirmed_score     NUMERIC(4,1),
    confirmed_by        TEXT NOT NULL DEFAULT '',
    modify_reason       TEXT NOT NULL DEFAULT '',
    confirmed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_screening_scorecard_items UNIQUE (scorecard_id, item_key)
);

COMMENT ON TABLE public.screening_scorecard_items IS '评分明细；每张评分卡按 screening_item_catalog 逐项一行，机器预填（suggested_*）与人工确认（confirmed_*）字段分列、改分留痕。';
COMMENT ON COLUMN public.screening_scorecard_items.scorecard_id IS '所属评分卡 ID。';
COMMENT ON COLUMN public.screening_scorecard_items.item_key IS '评分项编码；满分/是否一票否决/自动化方式以目录表为准。';
COMMENT ON COLUMN public.screening_scorecard_items.suggested_score IS '机器建议得分；automation=manual 的项为 NULL（机器留白，仅给参考材料）。';
COMMENT ON COLUMN public.screening_scorecard_items.confidence IS '机器建议的置信度（0~1）；rule 项恒为 1。';
COMMENT ON COLUMN public.screening_scorecard_items.suggested_rationale IS '机器给分理由（用于人工复核时快速判断）。';
COMMENT ON COLUMN public.screening_scorecard_items.evidence_refs IS '证据角标数组；元素结构与报告引用链一致，经 POST /evidence/resolve 渲染页图+bbox，每一分可点开看出处。';
COMMENT ON COLUMN public.screening_scorecard_items.veto_hit IS '一票否决命中判定（仅 is_veto 项有值）：TRUE=命中红线，NULL=机器无法判定；命中或无法判定均需人工确认。';
COMMENT ON COLUMN public.screening_scorecard_items.confirmed_score IS '人工确认得分；NULL 表示尚未人工处理，定稿时缺省取建议分（一票否决项不允许缺省，必须显式确认）。';
COMMENT ON COLUMN public.screening_scorecard_items.confirmed_by IS '确认/改分人；律师专业意见也走此通道留痕。';
COMMENT ON COLUMN public.screening_scorecard_items.modify_reason IS '改分理由；confirmed_score 与 suggested_score 不一致时必填。';
COMMENT ON COLUMN public.screening_scorecard_items.confirmed_at IS '确认时间。';

-- ----------------------------------------------------------------------------
-- 5. pricing_params —— 定价参数表（版本化，归口财务/投决维护）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.pricing_params (
    id             BIGSERIAL PRIMARY KEY,
    param_key      TEXT NOT NULL,
    param_group    TEXT NOT NULL DEFAULT 'pricing'
                   CHECK (param_group IN ('pricing', 'liquidation_discount')),
    param_value    NUMERIC(12,6) NOT NULL,
    effective_from DATE NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    note           TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pricing_params_key_ver UNIQUE (param_key, version)
);

COMMENT ON TABLE public.pricing_params IS '定价参数表；资金成本/处置成本/税费及快速变现折扣系数，按生效日期版本化，只增不改不删——测算结果通过参数快照可追溯到当时用的哪一版。';
COMMENT ON COLUMN public.pricing_params.param_key IS '参数编码：pricing 组如 funding_cost_rate/disposal_cost_rate/tax_rate；liquidation_discount 组按资产类型如 discount_residential/discount_commercial/discount_industrial/discount_equipment/discount_equity/discount_receivable。';
COMMENT ON COLUMN public.pricing_params.param_group IS '参数分组：pricing=底线公式成本项（年化率/费率），liquidation_discount=快速变现折扣系数（尽调估值×系数=快速变现值，文档 §8.7 开放点 3）。';
COMMENT ON COLUMN public.pricing_params.param_value IS '参数值；费率/系数均为小数（如 0.08 表示 8%，0.70 表示 7 折）。';
COMMENT ON COLUMN public.pricing_params.effective_from IS '生效日期；测算时取 effective_from<=测算日 中版本号最大的一条。';
COMMENT ON COLUMN public.pricing_params.version IS '版本号；同 param_key 递增。';
COMMENT ON COLUMN public.pricing_params.note IS '版本说明（调整原因/依据）。';
COMMENT ON COLUMN public.pricing_params.created_by IS '维护人；归口财务/投决委员会，不是开发。';

-- ----------------------------------------------------------------------------
-- 6. screening_economics —— 回收与收益测算结果（一包多次情景测算）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.screening_economics (
    id                 BIGSERIAL PRIMARY KEY,
    package_id         BIGINT NOT NULL REFERENCES public.packages(package_id) ON DELETE CASCADE,
    scorecard_id       BIGINT REFERENCES public.screening_scorecards(scorecard_id),
    baseline_valuation NUMERIC(18,2),
    liquidation_value  NUMERIC(18,2),
    est_recovery_low   NUMERIC(18,2),
    est_recovery_high  NUMERIC(18,2),
    est_period_months  INTEGER,
    purchase_price     NUMERIC(18,2),
    moic               NUMERIC(8,4),
    irr_low            NUMERIC(8,4),
    irr_high           NUMERIC(8,4),
    bottomline_pass    BOOLEAN,
    params_snapshot    JSONB NOT NULL DEFAULT '{}'::jsonb,
    overrides          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by         TEXT NOT NULL DEFAULT '',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.screening_economics IS '回收与收益测算结果；一包可多行（不同收购价情景反复测算），每行冻结当时所用参数快照，供复盘评估还原测算依据。';
COMMENT ON COLUMN public.screening_economics.package_id IS '所属资产包 ID。';
COMMENT ON COLUMN public.screening_economics.scorecard_id IS '测算时依据的评分卡；可为空（评分前的粗测）。';
COMMENT ON COLUMN public.screening_economics.baseline_valuation IS '估值基线（元）；一期取尽调报告估值合计，经人工确认（文档 §7 决策③A+D）。';
COMMENT ON COLUMN public.screening_economics.liquidation_value IS '快速变现值（元）=估值基线×按资产类型的折扣系数加权；《指引》要求充足率按快速变现值算，非市场价。';
COMMENT ON COLUMN public.screening_economics.est_recovery_low IS '预期回收金额下界（元）。';
COMMENT ON COLUMN public.screening_economics.est_recovery_high IS '预期回收金额上界（元）。';
COMMENT ON COLUMN public.screening_economics.est_period_months IS '预期回收周期（月）；《指引》理想 12—24，审慎 24—36，>36 需高收益补偿。';
COMMENT ON COLUMN public.screening_economics.purchase_price IS '本情景的拟收购价（元）。';
COMMENT ON COLUMN public.screening_economics.moic IS '回收倍数 MOIC=预期回收中值/收购价。';
COMMENT ON COLUMN public.screening_economics.irr_low IS '年化收益率 IRR 下界（小数）。';
COMMENT ON COLUMN public.screening_economics.irr_high IS '年化收益率 IRR 上界（小数）。';
COMMENT ON COLUMN public.screening_economics.bottomline_pass IS '底线公式校验：预期回收≥收购价+资金成本+处置成本+税费。';
COMMENT ON COLUMN public.screening_economics.params_snapshot IS '本次测算所用参数完整快照（含各 param_key 的值与版本号），保证可追溯。';
COMMENT ON COLUMN public.screening_economics.overrides IS '单笔参数覆盖留痕：{param_key:{value,reason,by}}；空对象表示全部走参数表默认。';
COMMENT ON COLUMN public.screening_economics.created_by IS '测算发起人。';

-- ----------------------------------------------------------------------------
-- 索引
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_packages_status
    ON public.packages(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_packages_case
    ON public.packages(case_id);

CREATE INDEX IF NOT EXISTS idx_screening_scorecards_pkg
    ON public.screening_scorecards(package_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_screening_scorecard_items_card
    ON public.screening_scorecard_items(scorecard_id);

CREATE INDEX IF NOT EXISTS idx_pricing_params_key_eff
    ON public.pricing_params(param_key, effective_from DESC, version DESC);

CREATE INDEX IF NOT EXISTS idx_screening_economics_pkg
    ON public.screening_economics(package_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- 种子数据 1：评分项目录（《指引》第二部分评分表，19 项合计 100 分）
-- ----------------------------------------------------------------------------
INSERT INTO public.screening_item_catalog
    (item_key, dimension, name, criteria, check_points, max_score, is_veto, automation, sort_order)
VALUES
    ('compliance.claim_authenticity', 'compliance', '债权真实性',
     '合同、借据、担保文件等核心资料完整、真实、一致。',
     '是否存在"阴阳合同"、虚假债权？', 6, TRUE, 'llm', 1),
    ('compliance.limitation_period', 'compliance', '诉讼时效',
     '主债权及担保债权均在诉讼时效内，催收记录连续完整。',
     '时效过期直接 0 分并触发否决。', 5, TRUE, 'rule', 2),
    ('compliance.transferability', 'compliance', '转让合法性',
     '无禁止转让条款，抵质押已有效登记，可随主债权转让。',
     '是否存在国防、军工等特殊限制？', 5, TRUE, 'llm', 3),
    ('compliance.prohibited_scope', 'compliance', '合规禁入审查',
     '不涉及僵尸企业、过剩产能、刑事犯罪等监管红线。',
     '触发任一红线直接否决。', 4, TRUE, 'llm', 4),
    ('collateral.guarantee_type', 'collateral', '担保方式',
     '住宅/商业抵押（8 分）；工业地产/上市公司股权质押（6 分）；纯保证/信用（2-4 分）。',
     '抵押物是否为第一顺位？', 8, FALSE, 'llm', 5),
    ('collateral.lien_priority_seizure', 'collateral', '抵押顺位与查封',
     '首封且首抵（7 分）；首抵非首封（5 分）；轮候抵押（2-3 分）。',
     '首封权是否为其他债权人？处置难度增加。', 7, FALSE, 'llm', 6),
    ('collateral.coverage_ratio', 'collateral', '抵押充足率',
     '(抵押物快速估值/债权本息)≥70%（6 分）；50%-70%（4 分）；<50%（1-2 分）。',
     '估值需采用快速变现价值，而非市场价。', 6, FALSE, 'rule', 7),
    ('collateral.liquidity', 'collateral', '资产变现能力',
     '核心城区、通用性强、无租赁/纠纷（7 分）；位置一般（5 分）；偏远/专用/有纠纷（1-3 分）。',
     '是否存在长期租约、违建、占用等情况？', 7, FALSE, 'llm', 8),
    ('debtor.entity_nature', 'debtor', '主体性质',
     '国企/大型上市/龙头民企（7 分）；地方平台/优质民企（5 分）；一般民企（3 分）；空壳/小微（1 分）。',
     '是否存在复杂的关联关系或隐性债务？', 7, FALSE, 'llm', 9),
    ('debtor.going_concern', 'debtor', '持续经营能力',
     '正常经营，有稳定现金流（6 分）；部分停产，有收入（4 分）；已停业/失联（0-1 分）。',
     '水、电、税、员工社保缴纳是否正常？', 6, FALSE, 'llm', 10),
    ('debtor.credit_history', 'debtor', '信用与历史行为',
     '无失信、无逃废债记录（5 分）；有涉诉但非恶意（3 分）；有恶意逃废债记录（0 分）。',
     '查询执行信息网、失信人名单。', 5, FALSE, 'llm', 11),
    ('debtor.guarantor_capacity', 'debtor', '保证人代偿能力',
     '净资产充足，经营稳定，代偿意愿强（4 分）；代偿能力弱或无（1-2 分）。',
     '保证人是否也同时是主要债务人？', 4, FALSE, 'manual', 12),
    ('environment.industry_outlook', 'environment', '行业景气度',
     '民生刚需/基建/新能源等政策支持行业（6 分）；一般制造业/商贸（4 分）；产能过剩/政策限制（2 分）。',
     '债务人主业是否属于"新质生产力"相关领域？', 6, FALSE, 'llm', 13),
    ('environment.region_tier', 'environment', '区域经济能级',
     '一线/强二线城市（5 分）；普通省会/强三线（3 分）；四五线/县域（1-2 分）。',
     '当地房价及二手房流动性如何？', 5, FALSE, 'rule', 14),
    ('environment.judicial_efficiency', 'environment', '司法执行环境',
     '司法效率高、地方保护弱（4 分）；一般（2-3 分）；执行难、保护主义强（1 分）。',
     '咨询当地律师或同行，了解法院实际执行情况。', 4, FALSE, 'manual', 15),
    ('disposal.legal_status', 'disposal', '当前法律状态',
     '已进入执行阶段（5 分）；已判决/未申请执行（3 分）；未诉（1-2 分）。',
     '是否存在执行异议、案外人异议等障碍？', 5, FALSE, 'llm', 16),
    ('disposal.purchase_discount', 'disposal', '收购折扣率',
     '≤3 折（5 分）；3-4 折（3 分）；4-5 折（1 分）；>5 折（0 分）。',
     '折扣是基于本金还是本息？统一基于本息。', 5, FALSE, 'rule', 17),
    ('disposal.recovery_period', 'disposal', '预期回收周期',
     '12-24 个月（3 分）；24-36 个月（2 分）；>36 个月（1 分）。',
     '结合处置路径综合判断。', 3, FALSE, 'llm', 18),
    ('disposal.exit_paths', 'disposal', '处置路径多样性',
     '3 条及以上清晰路径（2 分）；2 条路径（1 分）；仅 1 条（0 分）。',
     '除司法拍卖外，是否有重组、转让可能？', 2, FALSE, 'manual', 19)
ON CONFLICT (item_key) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 种子数据 2：定价参数示例初值
-- 注意：以下数值均为占位示例，启用测算前必须由财务/投决覆盖确认（开新版本），
--       note 字段已标注；快速变现折扣系数后续由法拍历史数据校准（文档 §8.6 二期）。
-- ----------------------------------------------------------------------------
INSERT INTO public.pricing_params
    (param_key, param_group, param_value, effective_from, version, note, created_by)
VALUES
    ('funding_cost_rate',    'pricing', 0.080000, '2026-06-10', 1, '示例初值（年化资金成本率），生效前必须由财务确认', 'system'),
    ('disposal_cost_rate',   'pricing', 0.050000, '2026-06-10', 1, '示例初值（处置成本占预期回收比例），生效前必须由财务确认', 'system'),
    ('tax_rate',             'pricing', 0.060000, '2026-06-10', 1, '示例初值（综合税费率），生效前必须由财务确认', 'system'),
    ('discount_residential', 'liquidation_discount', 0.700000, '2026-06-10', 1, '住宅快速变现折扣示例初值，待法拍数据校准', 'system'),
    ('discount_commercial',  'liquidation_discount', 0.600000, '2026-06-10', 1, '商业地产快速变现折扣示例初值，待法拍数据校准', 'system'),
    ('discount_industrial',  'liquidation_discount', 0.500000, '2026-06-10', 1, '工业厂房/土地快速变现折扣示例初值，待法拍数据校准', 'system'),
    ('discount_equipment',   'liquidation_discount', 0.400000, '2026-06-10', 1, '设备快速变现折扣示例初值，待法拍数据校准', 'system'),
    ('discount_equity',      'liquidation_discount', 0.500000, '2026-06-10', 1, '股权快速变现折扣示例初值，待法拍数据校准', 'system'),
    ('discount_receivable',  'liquidation_discount', 0.300000, '2026-06-10', 1, '应收账款快速变现折扣示例初值，待法拍数据校准', 'system')
ON CONFLICT (param_key, version) DO NOTHING;
