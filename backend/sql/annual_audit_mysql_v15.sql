-- Normalize the generic registry's selectable business-line key.
-- Activation exclusivity is enforced transactionally by the repository so
-- legacy rows from v14 can be upgraded without losing their files.

UPDATE annual_audit_template
SET business_line = 'annual_audit',
    template_type = 'annual_audit'
WHERE LOWER(TRIM(business_line)) IN (
  'annual_audit',
  'annual audit',
  '年度审计',
  '年度财务报表审计',
  '年度财务报表审计业务'
);

INSERT INTO ata_schema_migration (version, description)
VALUES ('015', 'normalize selectable template types and annual-audit type key')
ON DUPLICATE KEY UPDATE description = VALUES(description);
