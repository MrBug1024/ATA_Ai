-- File-backed annual-audit template versions.
-- Existing JSON columns remain only for backward compatibility.  A template
-- version is usable for attachment generation only when it has active files.

CREATE TABLE IF NOT EXISTS annual_audit_template_file (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  template_version_id BIGINT UNSIGNED NOT NULL,
  file_name VARCHAR(512) NOT NULL,
  file_ext VARCHAR(32) NOT NULL,
  content_type VARCHAR(255) NOT NULL DEFAULT 'application/octet-stream',
  storage_ref VARCHAR(2048) NOT NULL,
  storage_sha256 CHAR(64) NOT NULL,
  file_size BIGINT UNSIGNED NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_audit_template_file_name (template_version_id, file_name),
  KEY idx_annual_audit_template_file_status (template_version_id, status),
  CONSTRAINT fk_annual_audit_template_file_version
    FOREIGN KEY (template_version_id) REFERENCES annual_audit_template_version (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- v12 seeded JSON-only versions.  They must not remain active because they
-- are not real customer-uploaded templates.
UPDATE annual_audit_template t
LEFT JOIN annual_audit_template_version v
  ON v.template_id = t.id AND v.version_no = t.active_version_no
LEFT JOIN annual_audit_template_file f
  ON f.template_version_id = v.id AND f.status = 'active'
SET t.active_version_no = NULL
WHERE v.id IS NULL OR f.id IS NULL;

UPDATE annual_audit_template_version v
LEFT JOIN annual_audit_template_file f
  ON f.template_version_id = v.id AND f.status = 'active'
SET v.status = 'draft'
WHERE v.status = 'active' AND f.id IS NULL;

INSERT INTO ata_schema_migration (version, description)
VALUES ('013', 'file-backed annual-audit template versions')
ON DUPLICATE KEY UPDATE description = VALUES(description);
