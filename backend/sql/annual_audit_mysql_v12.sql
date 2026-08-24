-- Versioned annual-audit template registry and post-review attachment packages.
-- The JSON columns here are retained for migration compatibility.  Migration
-- v13 adds the actual uploaded template files used by attachment generation.

CREATE TABLE IF NOT EXISTS annual_audit_template (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  template_code VARCHAR(128) NOT NULL,
  template_type VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  description VARCHAR(1024) NOT NULL DEFAULT '',
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  active_version_no INT UNSIGNED NULL,
  created_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_audit_template_code (template_code),
  UNIQUE KEY uk_annual_audit_template_type (template_type),
  KEY idx_annual_audit_template_type_status (template_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_template_version (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  template_id BIGINT UNSIGNED NOT NULL,
  version_no INT UNSIGNED NOT NULL,
  version_label VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  content_json JSON NOT NULL,
  field_schema_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_by VARCHAR(128) NOT NULL,
  published_by VARCHAR(128) NULL,
  published_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_audit_template_version (template_id, version_no),
  KEY idx_annual_audit_template_version_status (template_id, status),
  CONSTRAINT fk_annual_audit_template_version_template
    FOREIGN KEY (template_id) REFERENCES annual_audit_template (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_attachment_package (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  package_version INT UNSIGNED NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  template_snapshot_json JSON NOT NULL,
  artifact_refs_json JSON NOT NULL,
  created_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_audit_attachment_package_version (engagement_id, package_version),
  CONSTRAINT fk_annual_audit_attachment_package_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO annual_audit_template
  (template_code, template_type, name, description, status, created_by)
VALUES
  ('annual_audit_report', 'annual_report', '年度审计报告模板', '年度财务报表审计报告草稿及交付版式', 'active', 'system'),
  ('annual_financial_statements', 'financial_statements', '财务报表模板', '年度财务报表及核心审计数据汇总模板', 'active', 'system'),
  ('annual_notes', 'notes', '财务报表附注模板', '财务报表附注交付模板', 'active', 'system'),
  ('annual_audit_workpaper', 'audit_workpaper', '审计工作底稿模板', '审计循环工作底稿模板', 'active', 'system'),
  ('annual_management_letter', 'management_letter', '管理建议书模板', '基于已确认审计结果的管理建议书模板', 'active', 'system')
ON DUPLICATE KEY UPDATE template_code = VALUES(template_code);

INSERT INTO annual_audit_template_version
  (template_id, version_no, version_label, status, content_json, field_schema_json, content_hash, created_by)
SELECT id, 1, 'customer-audit-report-v2', 'active',
  '{"title":"年度财务报表审计报告","formats":["docx"],"sections":["项目范围","审计结果","审计结论"]}', '{}',
  SHA2('{"formats":["docx"],"sections":["项目范围","审计结果","审计结论"],"title":"年度财务报表审计报告"}', 256), 'system'
FROM annual_audit_template WHERE template_code = 'annual_audit_report'
ON DUPLICATE KEY UPDATE template_id = VALUES(template_id);
INSERT INTO annual_audit_template_version
  (template_id, version_no, version_label, status, content_json, field_schema_json, content_hash, created_by)
SELECT id, 1, 'customer-financial-statements-v1', 'active',
  '{"title":"年度财务报表","sheet_name":"财务报表","formats":["xlsx"]}', '{}',
  SHA2('{"formats":["xlsx"],"sheet_name":"财务报表","title":"年度财务报表"}', 256), 'system'
FROM annual_audit_template WHERE template_code = 'annual_financial_statements'
ON DUPLICATE KEY UPDATE template_id = VALUES(template_id);
INSERT INTO annual_audit_template_version
  (template_id, version_no, version_label, status, content_json, field_schema_json, content_hash, created_by)
SELECT id, 1, 'customer-notes-v1', 'active',
  '{"title":"财务报表附注","formats":["docx"],"sections":["编制基础","重要会计政策","主要报表项目说明"]}', '{}',
  SHA2('{"formats":["docx"],"sections":["编制基础","重要会计政策","主要报表项目说明"],"title":"财务报表附注"}', 256), 'system'
FROM annual_audit_template WHERE template_code = 'annual_notes'
ON DUPLICATE KEY UPDATE template_id = VALUES(template_id);
INSERT INTO annual_audit_template_version
  (template_id, version_no, version_label, status, content_json, field_schema_json, content_hash, created_by)
SELECT id, 1, 'customer-workpaper-2023-v1', 'active',
  '{"title":"审计工作底稿","formats":["xlsx"],"sheet_name":"底稿"}', '{}',
  SHA2('{"formats":["xlsx"],"sheet_name":"底稿","title":"审计工作底稿"}', 256), 'system'
FROM annual_audit_template WHERE template_code = 'annual_audit_workpaper'
ON DUPLICATE KEY UPDATE template_id = VALUES(template_id);
INSERT INTO annual_audit_template_version
  (template_id, version_no, version_label, status, content_json, field_schema_json, content_hash, created_by)
SELECT id, 1, 'customer-management-letter-v1', 'active',
  '{"title":"管理建议书","formats":["docx"]}', '{}',
  SHA2('{"formats":["docx"],"title":"管理建议书"}', 256), 'system'
FROM annual_audit_template WHERE template_code = 'annual_management_letter'
ON DUPLICATE KEY UPDATE template_id = VALUES(template_id);

UPDATE annual_audit_template t
SET active_version_no = 1
WHERE active_version_no IS NULL
  AND EXISTS (
    SELECT 1 FROM annual_audit_template_version v
    WHERE v.template_id = t.id AND v.version_no = 1
  );

INSERT INTO ata_schema_migration (version, description)
VALUES ('012', 'versioned annual-audit templates and confirmed attachment packages')
ON DUPLICATE KEY UPDATE description = VALUES(description);
