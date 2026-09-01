"""Annual-audit template attachment preparation core.

The package is deliberately side-effect free: repositories and job services
load inputs, then call these contracts to compose, resolve, render, validate,
and record provenance.
"""

from .agent_graph import (
    AttachmentPreparationGraph,
    PreparedAttachment,
    StructuredPayloadComposer,
    compose_document_payload,
    fact_registry_from_context,
    prepare_attachment,
)
from .content_schemas import (
    AttachmentContractError,
    AttachmentRenderError,
    BindingManifest,
    DocumentPayload,
    FactRefSegment,
    LiteralSegment,
    RenderResult,
    ResolvedDocumentPayload,
    SlotBinding,
    TextSegment,
)
from .context_service import (
    GenerationContextSnapshot,
    ReportSnapshot,
    build_generation_context_snapshot,
)
from .fact_registry import (
    ConflictedFactError,
    FactRecord,
    FactRegistry,
    FactResolution,
    MissingFactError,
)
from .financial_statements import (
    FinancialStatement,
    FinancialStatementApprovalError,
    FinancialStatementEvidenceRef,
    FinancialStatementLine,
    FinancialStatementNote,
    FinancialStatementNoteTieOut,
    FinancialStatementPackage,
    FinancialStatementReconciliation,
    FinancialStatementsContext,
    ReconciliationTerm,
    adapt_financial_statement_snapshot,
)
from .provenance import (
    ArtifactProvenanceManifest,
    build_prepared_provenance_manifest,
    build_provenance_manifest,
)
from .quality_service import (
    AttachmentQualityError,
    QualityReport,
    require_quality,
    sanitize_output_filename,
    validate_rendered_artifact,
)


__all__ = [
    "ArtifactProvenanceManifest",
    "AttachmentContractError",
    "AttachmentPreparationGraph",
    "AttachmentQualityError",
    "AttachmentRenderError",
    "BindingManifest",
    "ConflictedFactError",
    "DocumentPayload",
    "FactRecord",
    "FactRefSegment",
    "FactRegistry",
    "FactResolution",
    "FinancialStatement",
    "FinancialStatementApprovalError",
    "FinancialStatementEvidenceRef",
    "FinancialStatementLine",
    "FinancialStatementNote",
    "FinancialStatementNoteTieOut",
    "FinancialStatementPackage",
    "FinancialStatementReconciliation",
    "FinancialStatementsContext",
    "GenerationContextSnapshot",
    "LiteralSegment",
    "MissingFactError",
    "PreparedAttachment",
    "QualityReport",
    "RenderResult",
    "ReportSnapshot",
    "ResolvedDocumentPayload",
    "ReconciliationTerm",
    "SlotBinding",
    "StructuredPayloadComposer",
    "TextSegment",
    "build_generation_context_snapshot",
    "build_prepared_provenance_manifest",
    "build_provenance_manifest",
    "compose_document_payload",
    "fact_registry_from_context",
    "prepare_attachment",
    "require_quality",
    "sanitize_output_filename",
    "validate_rendered_artifact",
    "adapt_financial_statement_snapshot",
]
