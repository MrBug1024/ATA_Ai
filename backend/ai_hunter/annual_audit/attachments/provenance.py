"""Immutable internal provenance manifests for generated artifacts."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .content_schemas import RenderResult, ResolvedDocumentPayload
from .context_service import GenerationContextSnapshot, canonical_json_bytes
from .fact_registry import FactResolution
from .quality_service import QualityReport

if TYPE_CHECKING:
    from .agent_graph import PreparedAttachment


class SlotProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str
    payload_sha256: str
    fact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    validation: str = "passed"


class FactProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_key: str
    value_sha256: str
    source_kind: str
    source_ref: dict[str, Any]
    evidence_refs: list[Any]
    revision: int
    status: str


class ArtifactProvenanceManifest(BaseModel):
    """Internal-only chain from artifact bytes to frozen facts and evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: str = "1.0"
    artifact_id: str
    report: dict[str, Any]
    context_snapshot_sha256: str
    template: dict[str, Any]
    renderer: dict[str, Any]
    model: dict[str, Any]
    slots: list[SlotProvenance]
    facts: list[FactProvenance]
    quality_report_sha256: str
    output_sha256: str

    @field_validator("artifact_id")
    @classmethod
    def validate_artifact_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("artifact_id is required")
        return normalized

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def build_provenance_manifest(
    *,
    artifact_id: str,
    context: GenerationContextSnapshot,
    payload: ResolvedDocumentPayload,
    fact_uses: tuple[FactResolution, ...] | list[FactResolution],
    render_result: RenderResult,
    quality_report: QualityReport,
    template_version_id: str,
    template_file_id: str,
    source_template_sha256: str,
    compiled_template_sha256: str,
    renderer: Mapping[str, Any],
    model: Mapping[str, Any] | None = None,
) -> ArtifactProvenanceManifest:
    slots = [
        SlotProvenance(
            slot_id=slot.slot_id,
            payload_sha256=hashlib.sha256(
                canonical_json_bytes({"kind": slot.kind, "value": slot.value})
            ).hexdigest(),
            fact_refs=list(slot.fact_refs),
            evidence_refs=list(slot.evidence_refs),
        )
        for slot in payload.slots
    ]
    facts = [
        FactProvenance(
            fact_key=fact.fact_key,
            value_sha256=fact.value_sha256,
            source_kind=fact.source_kind,
            source_ref=fact.source_ref,
            evidence_refs=fact.evidence_refs,
            revision=fact.revision,
            status=fact.status,
        )
        for fact in sorted(fact_uses, key=lambda item: (item.fact_key, item.revision))
    ]
    report = context.report.model_dump(mode="json", by_alias=True)
    return ArtifactProvenanceManifest(
        artifact_id=artifact_id,
        report=report,
        context_snapshot_sha256=context.snapshot_sha256,
        template={
            "version_id": str(template_version_id),
            "file_id": str(template_file_id),
            "source_sha256": source_template_sha256,
            "compiled_sha256": compiled_template_sha256,
        },
        renderer=dict(renderer),
        model=dict(model or {}),
        slots=slots,
        facts=facts,
        quality_report_sha256=quality_report.report_sha256,
        output_sha256=render_result.output_sha256,
    )


def build_prepared_provenance_manifest(
    *,
    artifact_id: str,
    prepared: "PreparedAttachment",
    render_result: RenderResult,
    quality_report: QualityReport,
    template_version_id: str,
    template_file_id: str,
    source_template_sha256: str,
    compiled_template_sha256: str,
    renderer: Mapping[str, Any],
    model: Mapping[str, Any] | None = None,
) -> ArtifactProvenanceManifest:
    """Job-service convenience entry point consuming ``PreparedAttachment``."""

    return build_provenance_manifest(
        artifact_id=artifact_id,
        context=prepared.context,
        payload=prepared.resolved_payload,
        fact_uses=prepared.fact_uses,
        render_result=render_result,
        quality_report=quality_report,
        template_version_id=template_version_id,
        template_file_id=template_file_id,
        source_template_sha256=source_template_sha256,
        compiled_template_sha256=compiled_template_sha256,
        renderer=renderer,
        model=model,
    )


def provenance_bytes(manifest: ArtifactProvenanceManifest) -> bytes:
    return manifest.canonical_bytes()


__all__ = [
    "ArtifactProvenanceManifest",
    "FactProvenance",
    "SlotProvenance",
    "build_prepared_provenance_manifest",
    "build_provenance_manifest",
    "provenance_bytes",
]
