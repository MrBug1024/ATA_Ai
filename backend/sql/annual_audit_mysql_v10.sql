-- Immutable, report-version-scoped citation manifests for annual-audit drafts.
--
-- The MySQL annual domain owns deterministic annual findings. It must not
-- write those IDs into PostgreSQL report_citation_map, whose foreign key
-- targets kg_claim. This manifest instead freezes the exact annual finding,
-- rule context and evidence snapshot used by one annual report version.
--
-- audit_report already has the unique parent key
-- (engagement_id, report_type, report_version). The composite foreign key
-- below makes every manifest row case/version scoped at the database layer.
-- annual_report_id, annual_finding_id and analysis_run_id are also retained
-- for direct lookup; the repository validates that they belong to this same
-- engagement before inserting or binding a row.

CREATE TABLE IF NOT EXISTS annual_report_citation_manifest (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  annual_report_id BIGINT UNSIGNED NOT NULL,
  report_type VARCHAR(64) NOT NULL,
  report_version INT NOT NULL,
  citation_id VARCHAR(128) NOT NULL,
  section_key VARCHAR(255) NOT NULL DEFAULT '',
  paragraph_key VARCHAR(255) NOT NULL DEFAULT '',
  annual_finding_id BIGINT UNSIGNED NULL,
  annual_finding_key CHAR(64) NOT NULL,
  analysis_run_id BIGINT UNSIGNED NULL,
  analysis_type VARCHAR(64) NULL,
  finding_type VARCHAR(64) NULL,
  risk_level VARCHAR(16) NULL,
  rule_metadata_json JSON NOT NULL,
  finding_metadata_json JSON NOT NULL,
  evidence_snapshot_json JSON NOT NULL,
  anchor_status VARCHAR(32) NOT NULL,
  snapshot_hash CHAR(64) NOT NULL,
  final_report_ref VARCHAR(1024) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_report_citation_version
    (engagement_id, report_type, report_version, citation_id),
  UNIQUE KEY uk_annual_report_citation_report_id
    (engagement_id, annual_report_id, citation_id),
  KEY idx_annual_report_citation_finding
    (engagement_id, annual_finding_id),
  KEY idx_annual_report_citation_finding_key
    (engagement_id, annual_finding_key),
  KEY idx_annual_report_citation_analysis_run
    (engagement_id, analysis_run_id),
  KEY idx_annual_report_citation_report_ref
    (engagement_id, final_report_ref(191)),
  CONSTRAINT fk_annual_report_citation_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id),
  CONSTRAINT fk_annual_report_citation_report_version
    FOREIGN KEY (engagement_id, report_type, report_version)
    REFERENCES audit_report (engagement_id, report_type, report_version),
  CONSTRAINT fk_annual_report_citation_report_id
    FOREIGN KEY (annual_report_id) REFERENCES audit_report (id),
  CONSTRAINT fk_annual_report_citation_finding
    FOREIGN KEY (annual_finding_id) REFERENCES annual_finding (id),
  CONSTRAINT fk_annual_report_citation_analysis_run
    FOREIGN KEY (analysis_run_id) REFERENCES annual_analysis_run (id),
  CONSTRAINT chk_annual_report_citation_anchor_status
    CHECK (anchor_status IN ('bound', 'partial', 'unbound', 'no_evidence'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO ata_schema_migration (version, description)
VALUES ('010', 'immutable annual report citation manifests')
ON DUPLICATE KEY UPDATE description = VALUES(description);
