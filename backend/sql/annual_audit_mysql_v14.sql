-- Generic template management: one logical template can have many versions,
-- and each version owns the uploaded files that make up that template.

SET @add_business_line = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE()
     AND table_name = 'annual_audit_template'
     AND column_name = 'business_line') = 0,
  'ALTER TABLE annual_audit_template ADD COLUMN business_line VARCHAR(128) NOT NULL DEFAULT ''annual_audit'' AFTER name',
  'SELECT 1'
);
PREPARE stmt FROM @add_business_line;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @drop_type_index = IF(
  (SELECT COUNT(*) FROM information_schema.statistics
   WHERE table_schema = DATABASE()
     AND table_name = 'annual_audit_template'
     AND index_name = 'uk_annual_audit_template_type') > 0,
  'ALTER TABLE annual_audit_template DROP INDEX uk_annual_audit_template_type',
  'SELECT 1'
);
PREPARE stmt FROM @drop_type_index;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @add_usage = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE()
     AND table_name = 'annual_audit_template_file'
     AND column_name = 'template_usage') = 0,
  'ALTER TABLE annual_audit_template_file ADD COLUMN template_usage VARCHAR(128) NOT NULL DEFAULT '''' AFTER file_size',
  'SELECT 1'
);
PREPARE stmt FROM @add_usage;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @add_remark = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE()
     AND table_name = 'annual_audit_template_file'
     AND column_name = 'remark') = 0,
  'ALTER TABLE annual_audit_template_file ADD COLUMN remark VARCHAR(1024) NOT NULL DEFAULT '''' AFTER template_usage',
  'SELECT 1'
);
PREPARE stmt FROM @add_remark;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE annual_audit_template
SET business_line = COALESCE(NULLIF(business_line, ''), NULLIF(template_type, ''), 'annual_audit');

-- Remove the JSON-only seed records from v12.  Customer-created versions or
-- versions that already contain files are preserved.
DELETE v
FROM annual_audit_template_version v
JOIN annual_audit_template t ON t.id = v.template_id
LEFT JOIN annual_audit_template_file f
  ON f.template_version_id = v.id AND f.status = 'active'
WHERE t.created_by = 'system'
  AND t.template_code IN (
    'annual_audit_report', 'annual_financial_statements', 'annual_notes',
    'annual_audit_workpaper', 'annual_management_letter'
  )
  AND f.id IS NULL;

DELETE t
FROM annual_audit_template t
LEFT JOIN annual_audit_template_version v ON v.template_id = t.id
WHERE t.created_by = 'system'
  AND t.template_code IN (
    'annual_audit_report', 'annual_financial_statements', 'annual_notes',
    'annual_audit_workpaper', 'annual_management_letter'
  )
  AND v.id IS NULL;

INSERT INTO ata_schema_migration (version, description)
VALUES ('014', 'generic template version and file management')
ON DUPLICATE KEY UPDATE description = VALUES(description);
