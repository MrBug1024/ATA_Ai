CREATE TABLE IF NOT EXISTS doc_category_catalog (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    sort_order  INTEGER NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    fields      JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_file_doc_category (
    id            BIGSERIAL PRIMARY KEY,
    file_id       BIGINT NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    case_id       BIGINT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    category_code TEXT NOT NULL REFERENCES doc_category_catalog(code),
    match_source  TEXT NOT NULL DEFAULT 'manual',
    confidence    NUMERIC(5,4),
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_file_doc_category UNIQUE (file_id, category_code)
);

CREATE TABLE IF NOT EXISTS source_upload_batch (
    upload_batch_id TEXT PRIMARY KEY,
    case_id         BIGINT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    debtor_id       BIGINT NOT NULL DEFAULT 0,
    batch_name      TEXT NOT NULL DEFAULT '',
    doc_category    TEXT REFERENCES doc_category_catalog(code),
    operator_id     TEXT NOT NULL DEFAULT '',
    operator_name   TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'received',
    file_count      INTEGER NOT NULL DEFAULT 0,
    new_file_count  INTEGER NOT NULL DEFAULT 0,
    duplicate_file_count INTEGER NOT NULL DEFAULT 0,
    suspected_mismatch_file_count INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_file_upload_batch (
    id              BIGSERIAL PRIMARY KEY,
    upload_batch_id TEXT NOT NULL REFERENCES source_upload_batch(upload_batch_id) ON DELETE CASCADE,
    file_id         BIGINT NOT NULL REFERENCES source_file(id) ON DELETE CASCADE,
    file_name       TEXT NOT NULL DEFAULT '',
    file_sha256     CHAR(64) NOT NULL,
    duplicate_of    TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_file_upload_batch UNIQUE (upload_batch_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_doc_category_catalog_sort
    ON doc_category_catalog(sort_order, enabled);

CREATE INDEX IF NOT EXISTS idx_source_file_doc_category_case
    ON source_file_doc_category(case_id, category_code);

CREATE INDEX IF NOT EXISTS idx_source_file_doc_category_file
    ON source_file_doc_category(file_id);

CREATE INDEX IF NOT EXISTS idx_source_upload_batch_case
    ON source_upload_batch(case_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_upload_batch_category
    ON source_upload_batch(case_id, doc_category);

CREATE INDEX IF NOT EXISTS idx_source_file_upload_batch_file
    ON source_file_upload_batch(file_id);

INSERT INTO doc_category_catalog (code, name, description, sort_order, enabled, fields)
VALUES
    ('loan_contract', '贷款合同', '贷款主合同、借款合同、授信合同等', 1, TRUE, '["principal","interest","penalty","delayed_interest","total_claim","guarantee_type","collateral_desc","lien_priority","court_name","exec_case_no","litigation_status","guarantor_names"]'::jsonb),
    ('judgment', '判决书', '判决书、裁定书、调解书、执行裁定等法律文书', 2, TRUE, '["case_number","court_name","case_cause","doc_type","judgment_date","claim_amount","judgment_amount","execution_status","plaintiff","defendant","enforcement_deadline","court_level","case_type"]'::jsonb),
    ('financial_statement', '财务报表', '资产负债表、利润表、审计报告中的财务快照', 3, TRUE, '["report_period","report_type","other_receivables","prepayments","total_assets","total_liabilities","revenue","operating_cost","net_profit","tax_reported_revenue","tax_reported_cost"]'::jsonb),
    ('real_estate_cert', '不动产权证', '不动产权证、房产证、土地证等权属资料', 4, TRUE, '["property_owner","property_address","real_estate_cert_no","land_nature","total_building_area","land_use_area","property_usage","mortgage_status","seal_status","seal_expiry","lease_status","gross_value","has_title_objection","physical_occupation","lien_priority","sealing_court","lease_annual_rent","lease_start","lease_end"]'::jsonb),
    ('mining_permit', '采矿许可证', '采矿许可证、采矿权登记信息', 5, TRUE, '["mine_name","mine_location","permit_expiry","production_scale","mineral_type","mine_scale","mining_status","safety_permit_status","env_approval_status","mining_right_mortgage","mining_right_sealed","proved_reserves","estimated_value","transfer_base_price","in_ecological_redline"]'::jsonb),
    ('bank_statement', '银行流水', '银行流水、交易明细、回单签批链', 6, TRUE, '["transactions"]'::jsonb),
    ('guarantee_contract', '担保合同', '保证合同、担保合同、连带保证资料', 7, TRUE, '["entity_name","guarantor_type","guarantee_type","guarantee_scope","spouse_name"]'::jsonb),
    ('restructuring_plan', '煤矿重整方案', '破产重整方案、变价方案、分配方案等', 8, TRUE, '["mine_name","debtor_name","administrator","administrator_contact","investor_name","investor_contact","total_debt","secured_debt","unsecured_debt","employee_debt","tax_debt","proposed_recovery_rate","transfer_base_price","asset_list_summary","restructuring_timeline","court_name","case_number","key_conditions"]'::jsonb),
    ('exploration_report', '勘探报告', '勘探报告、地质报告、储量报告', 9, TRUE, '["mine_name","report_org","report_date","mineral_type","proved_reserves","controlled_reserves","inferred_resources","total_reserves","calorific_value","ash_content_pct","sulfur_content_pct","coal_type"]'::jsonb),
    ('environmental_approval', '环评批复', '环评批复、环境影响评价审批文件', 10, TRUE, '["mine_name","env_approval_status","production_scale","in_ecological_redline"]'::jsonb),
    ('court_general_query', '法院总对总', '法院总对总网络查控结果', 11, TRUE, '["target_name","inquiry_date","bank_deposits","real_estate_hits","vehicle_hits","securities_hits","insurance_hits","other_hits"]'::jsonb),
    ('lawyer_investigation', '律师调查报告', '律师实地调查、现场调查、经营核查报告', 12, TRUE, '["investigator","investigation_date","physical_address_status","employee_status","asset_on_site","lease_situation","investigation_conclusion","key_person_contacts","related_party_findings","asset_transfer_clues"]'::jsonb),
    ('mining_design_reclamation', '开采设计与复垦', '开采设计、复垦方案、矿山恢复治理资料', 13, TRUE, '["mine_name","annual_capacity","mining_status"]'::jsonb)
ON CONFLICT (code) DO UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    enabled = EXCLUDED.enabled,
    fields = EXCLUDED.fields,
    updated_at = now();
