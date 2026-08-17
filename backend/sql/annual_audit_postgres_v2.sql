-- Expanded annual-audit material catalogue for the full financial-statement
-- audit programme. Existing customer workpapers remain reference material and
-- do not satisfy a category merely by being present.

INSERT INTO public.doc_category_catalog (
    code, name, description, sort_order, enabled, fields
) VALUES
    ('engagement_acceptance', '承接、续约及独立性资料', '客户背景、承接评价、独立性声明、业务约定书及冲突检查记录', 10, TRUE, '["document_type","effective_date","signer"]'::jsonb),
    ('governance_minutes', '治理层及管理层会议资料', '股东会、董事会、监事会、管理层会议纪要及重大决议', 11, TRUE, '["meeting_date","meeting_type","topic"]'::jsonb),
    ('general_ledger', '总账及明细账', '完整总账、明细账、辅助核算和账套导出', 12, TRUE, '["account_code","account_name","posting_date","voucher_no","amount"]'::jsonb),
    ('accounts_payable', '应付账款及采购往来明细', '供应商余额、账龄、采购往来及未到票资料', 13, TRUE, '["supplier_name","document_no","occurrence_date","due_date","balance"]'::jsonb),
    ('purchase_support', '采购及付款支持性资料', '采购合同、订单、验收、入库、发票、付款申请和付款凭证', 14, TRUE, '["supplier_name","contract_no","invoice_no","acceptance_date","amount"]'::jsonb),
    ('inventory_records', '存货台账及库龄资料', '存货收发存明细、库龄、成本、跌价准备及第三方保管资料', 15, TRUE, '["sku","warehouse","quantity","unit_cost","book_amount"]'::jsonb),
    ('inventory_count', '盘点及实物核查资料', '存货、固定资产、现金等实物盘点表、监盘记录和差异处理', 16, TRUE, '["count_date","location","item_code","book_quantity","count_quantity"]'::jsonb),
    ('payroll_hr', '薪酬、人事及社保资料', '员工花名册、劳动合同、工资表、社保公积金和奖金资料', 17, TRUE, '["employee_id","period","gross_pay","social_security"]'::jsonb),
    ('fixed_assets', '固定资产及长期资产台账', '固定资产、在建工程、无形资产、使用权资产、折旧摊销明细', 18, TRUE, '["asset_code","asset_name","acquisition_date","original_cost","depreciation"]'::jsonb),
    ('asset_rights', '资产权属及担保资料', '产权证书、抵押质押、租赁合同、保险及权利受限资料', 19, TRUE, '["asset_name","right_type","certificate_no","restriction"]'::jsonb),
    ('related_parties', '关联方及关联交易资料', '关联方清单、关联关系、关联交易协议、定价和披露资料', 20, TRUE, '["counterparty","relationship","transaction_type","amount"]'::jsonb),
    ('legal_contingencies', '诉讼、担保及或有事项资料', '律师函、诉讼仲裁、担保、承诺、行政处罚及或有事项清单', 21, TRUE, '["matter_name","status","estimated_amount","disclosure_required"]'::jsonb),
    ('subsequent_events', '期后事项资料', '资产负债表日后重大合同、交易、会议纪要、公告及调整资料', 22, TRUE, '["event_date","event_type","financial_impact","adjusting_event"]'::jsonb),
    ('going_concern', '持续经营评价资料', '预算、现金流预测、融资安排、债务契约和持续经营改善计划', 23, TRUE, '["forecast_period","cash_flow","financing_source","assumption"]'::jsonb),
    ('adjustments', '审计调整及错报汇总资料', '审计调整分录、已更正和未更正错报、管理层拒绝调整说明', 24, TRUE, '["adjustment_no","account_code","amount","corrected_status"]'::jsonb),
    ('management_representation', '管理层声明及批准资料', '管理层声明书、财务报表批准记录和授权签署资料', 25, TRUE, '["statement_date","signer","financial_statement_approved_at"]'::jsonb)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    enabled = EXCLUDED.enabled,
    fields = EXCLUDED.fields,
    updated_at = now();
