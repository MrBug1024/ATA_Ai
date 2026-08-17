-- Production annual-financial-statement-audit execution and governance.
--
-- This migration deliberately stores project execution separately from
-- deterministic analysis output. It never treats an AI draft, a historical
-- case template, or an absent document as audit evidence.

CREATE TABLE IF NOT EXISTS annual_engagement_profile (
  engagement_id BIGINT UNSIGNED NOT NULL,
  profile_version INT UNSIGNED NOT NULL DEFAULT 1,
  acceptance_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  independence_status VARCHAR(32) NOT NULL DEFAULT 'pending',
  data_classification VARCHAR(64) NULL,
  data_residency VARCHAR(128) NULL,
  model_data_policy VARCHAR(64) NULL,
  profile_json JSON NOT NULL,
  created_by VARCHAR(128) NOT NULL,
  updated_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (engagement_id),
  KEY idx_annual_profile_gate (acceptance_status, independence_status),
  CONSTRAINT fk_annual_profile_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_program_item (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  program_version VARCHAR(64) NOT NULL,
  procedure_code VARCHAR(64) NOT NULL,
  phase VARCHAR(64) NOT NULL,
  cycle VARCHAR(128) NOT NULL,
  procedure_name VARCHAR(255) NOT NULL,
  assertions_json JSON NULL,
  risk_area VARCHAR(255) NULL,
  required_material_categories_json JSON NULL,
  requires_evidence BOOLEAN NOT NULL DEFAULT TRUE,
  status VARCHAR(32) NOT NULL DEFAULT 'not_started',
  sample_plan_json JSON NULL,
  evidence_refs_json JSON NULL,
  exception_count INT UNSIGNED NOT NULL DEFAULT 0,
  alternative_procedures_json JSON NULL,
  conclusion_text LONGTEXT NULL,
  not_applicable_reason TEXT NULL,
  prepared_by VARCHAR(128) NULL,
  prepared_at DATETIME(6) NULL,
  reviewed_by VARCHAR(128) NULL,
  reviewed_at DATETIME(6) NULL,
  policy_binding_id BIGINT UNSIGNED NULL,
  revision INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_program_item (engagement_id, procedure_code),
  KEY idx_annual_program_status (engagement_id, status, phase),
  CONSTRAINT fk_annual_program_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_program_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  procedure_code VARCHAR(64) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  before_json JSON NULL,
  after_json JSON NULL,
  actor_user_id VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_annual_program_event (engagement_id, procedure_code, created_at),
  CONSTRAINT fk_annual_program_event_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_confirmation (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  procedure_code VARCHAR(64) NOT NULL,
  counterparty_name VARCHAR(255) NOT NULL,
  confirmation_type VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'planned',
  auditor_controlled_delivery BOOLEAN NOT NULL DEFAULT FALSE,
  request_evidence_refs_json JSON NULL,
  response_evidence_refs_json JSON NULL,
  reliability_assessment TEXT NULL,
  exception_description TEXT NULL,
  alternative_procedures_json JSON NULL,
  conclusion_text TEXT NULL,
  prepared_by VARCHAR(128) NULL,
  reviewed_by VARCHAR(128) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_annual_confirmation (engagement_id, procedure_code, status),
  CONSTRAINT fk_annual_confirmation_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_finding_resolution (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  finding_id BIGINT UNSIGNED NOT NULL,
  resolution_status VARCHAR(32) NOT NULL DEFAULT 'open',
  resolution_type VARCHAR(64) NULL,
  resolution_note TEXT NULL,
  evidence_refs_json JSON NULL,
  resolved_by VARCHAR(128) NULL,
  resolved_at DATETIME(6) NULL,
  reviewed_by VARCHAR(128) NULL,
  reviewed_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_finding_resolution (finding_id),
  KEY idx_annual_finding_resolution (engagement_id, resolution_status),
  CONSTRAINT fk_annual_finding_resolution_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id),
  CONSTRAINT fk_annual_finding_resolution_finding
    FOREIGN KEY (finding_id) REFERENCES annual_finding (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_review_decision (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  review_level VARCHAR(32) NOT NULL,
  decision VARCHAR(32) NOT NULL,
  decision_note TEXT NULL,
  scope_json JSON NULL,
  reviewer_user_id VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_annual_review_decision (engagement_id, review_level, created_at),
  CONSTRAINT fk_annual_review_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_knowledge_document (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  document_code VARCHAR(128) NOT NULL,
  title VARCHAR(512) NOT NULL,
  authority_type VARCHAR(32) NOT NULL,
  source_issuer VARCHAR(255) NOT NULL,
  source_url VARCHAR(2048) NULL,
  source_hash CHAR(64) NULL,
  scope_json JSON NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  created_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_knowledge_document_code (document_code),
  KEY idx_annual_knowledge_document_status (authority_type, status),
  CHECK (authority_type IN ('law', 'accounting_standard', 'auditing_standard',
    'regulatory_guidance', 'firm_methodology', 'industry_guidance', 'case_reference'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_knowledge_version (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  document_id BIGINT UNSIGNED NOT NULL,
  version_no INT UNSIGNED NOT NULL,
  source_url VARCHAR(2048) NOT NULL,
  source_hash CHAR(64) NOT NULL,
  publication_date DATE NULL,
  effective_from DATE NULL,
  effective_to DATE NULL,
  supersedes_version_id BIGINT UNSIGNED NULL,
  content_text LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  review_status VARCHAR(32) NOT NULL DEFAULT 'draft',
  reviewed_by VARCHAR(128) NULL,
  reviewed_at DATETIME(6) NULL,
  approved_by VARCHAR(128) NULL,
  approved_at DATETIME(6) NULL,
  change_summary TEXT NULL,
  created_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_knowledge_version (document_id, version_no),
  KEY idx_annual_knowledge_version_eligibility
    (review_status, effective_from, effective_to),
  CONSTRAINT fk_annual_knowledge_version_document
    FOREIGN KEY (document_id) REFERENCES annual_knowledge_document (id),
  CONSTRAINT fk_annual_knowledge_version_supersedes
    FOREIGN KEY (supersedes_version_id) REFERENCES annual_knowledge_version (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_knowledge_chunk (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  knowledge_version_id BIGINT UNSIGNED NOT NULL,
  chunk_no INT UNSIGNED NOT NULL,
  locator VARCHAR(255) NULL,
  heading VARCHAR(512) NULL,
  content_text LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  metadata_json JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_knowledge_chunk (knowledge_version_id, chunk_no),
  KEY idx_annual_knowledge_chunk_version (knowledge_version_id),
  CONSTRAINT fk_annual_knowledge_chunk_version
    FOREIGN KEY (knowledge_version_id) REFERENCES annual_knowledge_version (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_knowledge_release (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  release_code VARCHAR(128) NOT NULL,
  release_version VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  effective_from DATE NULL,
  effective_to DATE NULL,
  approval_note TEXT NULL,
  approved_by VARCHAR(128) NULL,
  approved_at DATETIME(6) NULL,
  created_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_knowledge_release (release_code, release_version),
  KEY idx_annual_knowledge_release_eligibility
    (status, effective_from, effective_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_knowledge_release_item (
  release_id BIGINT UNSIGNED NOT NULL,
  knowledge_version_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (release_id, knowledge_version_id),
  CONSTRAINT fk_annual_knowledge_release_item_release
    FOREIGN KEY (release_id) REFERENCES annual_knowledge_release (id),
  CONSTRAINT fk_annual_knowledge_release_item_version
    FOREIGN KEY (knowledge_version_id) REFERENCES annual_knowledge_version (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_ruleset (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ruleset_code VARCHAR(128) NOT NULL,
  version VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  scope_json JSON NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  effective_from DATE NULL,
  effective_to DATE NULL,
  approved_by VARCHAR(128) NULL,
  approved_at DATETIME(6) NULL,
  created_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_audit_ruleset (ruleset_code, version),
  KEY idx_annual_ruleset_eligibility (status, effective_from, effective_to)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_rule (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ruleset_id BIGINT UNSIGNED NOT NULL,
  rule_code VARCHAR(128) NOT NULL,
  rule_type VARCHAR(32) NOT NULL,
  name VARCHAR(512) NOT NULL,
  authority_locator VARCHAR(512) NULL,
  knowledge_version_id BIGINT UNSIGNED NULL,
  applicability_json JSON NULL,
  preconditions_json JSON NULL,
  evidence_requirements_json JSON NULL,
  logic_json JSON NULL,
  exception_handling_json JSON NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_audit_rule (ruleset_id, rule_code),
  KEY idx_annual_rule_type (ruleset_id, rule_type, status),
  CONSTRAINT fk_annual_rule_ruleset
    FOREIGN KEY (ruleset_id) REFERENCES annual_audit_ruleset (id),
  CONSTRAINT fk_annual_rule_knowledge_version
    FOREIGN KEY (knowledge_version_id) REFERENCES annual_knowledge_version (id),
  CHECK (rule_type IN ('mandatory_requirement', 'firm_methodology',
    'data_check', 'risk_signal'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_engagement_policy_binding (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  knowledge_release_id BIGINT UNSIGNED NULL,
  ruleset_id BIGINT UNSIGNED NULL,
  binding_status VARCHAR(32) NOT NULL DEFAULT 'draft',
  reporting_period_date DATE NOT NULL,
  bound_by VARCHAR(128) NULL,
  bound_at DATETIME(6) NULL,
  snapshot_json JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_annual_policy_binding (engagement_id, binding_status),
  CONSTRAINT fk_annual_binding_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id),
  CONSTRAINT fk_annual_binding_knowledge_release
    FOREIGN KEY (knowledge_release_id) REFERENCES annual_knowledge_release (id),
  CONSTRAINT fk_annual_binding_ruleset
    FOREIGN KEY (ruleset_id) REFERENCES annual_audit_ruleset (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_release_gate (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  gate_status VARCHAR(32) NOT NULL,
  blockers_json JSON NOT NULL,
  snapshot_json JSON NOT NULL,
  evaluated_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_annual_release_gate (engagement_id, gate_status, created_at),
  CONSTRAINT fk_annual_release_gate_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_issuance (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  gate_id BIGINT UNSIGNED NOT NULL,
  report_artifact_ref VARCHAR(2048) NOT NULL,
  report_artifact_sha256 CHAR(64) NOT NULL,
  signing_attestation BOOLEAN NOT NULL DEFAULT FALSE,
  signed_by VARCHAR(128) NOT NULL,
  signed_at DATETIME(6) NOT NULL,
  opinion_type VARCHAR(64) NOT NULL,
  issuance_note TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_issuance_engagement (engagement_id),
  CONSTRAINT fk_annual_issuance_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id),
  CONSTRAINT fk_annual_issuance_gate
    FOREIGN KEY (gate_id) REFERENCES annual_release_gate (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS annual_audit_archive (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  engagement_id BIGINT UNSIGNED NOT NULL,
  issuance_id BIGINT UNSIGNED NOT NULL,
  archive_manifest_ref VARCHAR(2048) NOT NULL,
  archive_manifest_sha256 CHAR(64) NOT NULL,
  archive_completed_at DATETIME(6) NOT NULL,
  retention_until DATE NOT NULL,
  archived_by VARCHAR(128) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_annual_archive_engagement (engagement_id),
  CONSTRAINT fk_annual_archive_engagement
    FOREIGN KEY (engagement_id) REFERENCES audit_engagement (id),
  CONSTRAINT fk_annual_archive_issuance
    FOREIGN KEY (issuance_id) REFERENCES annual_audit_issuance (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO ata_schema_migration (version, description)
VALUES ('009', 'annual audit execution, evidence, review, issuance and knowledge governance')
ON DUPLICATE KEY UPDATE description = VALUES(description);
