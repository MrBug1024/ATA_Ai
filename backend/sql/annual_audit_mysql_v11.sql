-- One frozen annual-report version can be delivered in multiple chat turns.
-- Keep those opaque payload refs in a separate table so binding a later
-- response never mutates the immutable citation snapshots themselves.

CREATE TABLE IF NOT EXISTS annual_report_citation_delivery_ref (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  annual_report_id BIGINT UNSIGNED NOT NULL,
  report_type VARCHAR(64) NOT NULL,
  report_version INT NOT NULL,
  final_report_ref VARCHAR(1024) NOT NULL,
  final_report_ref_hash CHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_report_citation_delivery_ref
    (engagement_id, final_report_ref_hash),
  KEY idx_annual_report_citation_delivery_version
    (engagement_id, annual_report_id, report_type, report_version),
  CONSTRAINT fk_annual_report_citation_delivery_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id),
  CONSTRAINT fk_annual_report_citation_delivery_report_version
    FOREIGN KEY (engagement_id, report_type, report_version)
    REFERENCES audit_report (engagement_id, report_type, report_version),
  CONSTRAINT fk_annual_report_citation_delivery_report_id
    FOREIGN KEY (annual_report_id) REFERENCES audit_report (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO ata_schema_migration (version, description)
VALUES ('011', 'immutable annual report citation delivery references')
ON DUPLICATE KEY UPDATE description = VALUES(description);
