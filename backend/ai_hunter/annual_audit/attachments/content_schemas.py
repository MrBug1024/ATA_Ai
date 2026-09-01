"""Typed contracts for deterministic annual-audit attachment preparation.

Agents may provide connective prose, but authoritative identifiers, dates, and
amounts enter a document through ``FactRefSegment``.  Renderers only receive a
``ResolvedDocumentPayload`` whose fact references have already been replaced by
the deterministic fact registry.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_FACT_KEY_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\[\])?(?:\.[a-z][a-z0-9_]*(?:\[\])?)*$"
)
_FACT_KEY_FRAGMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[a-z][a-z0-9_]*(?:\[\])?\.)+"
    r"[a-z][a-z0-9_]*(?:\[\])?(?![A-Za-z0-9_])"
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMANTIC_EXTERNAL_TEXT_FORBIDDEN = re.compile(
    r"(?:\b(?:case|report|evidence|storage|object|source_file|source_page|chunk|claim)"
    r"_?(?:id|ref)\b|\b(?:minio|s3|file)://|"
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b)",
    re.IGNORECASE,
)


def _validate_identifier(value: str) -> str:
    normalized = value.strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"invalid identifier: {value!r}")
    return normalized


def _unique_nonempty(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


class AttachmentContractError(ValueError):
    """Raised when a payload or binding violates the attachment contract."""


class AttachmentRenderError(RuntimeError):
    """Raised when a deterministic renderer cannot produce a valid artifact."""


class MissingRendererDependency(AttachmentRenderError):
    """Raised when an explicitly selected renderer dependency is unavailable."""


class TextSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=100_000)


class FactRefSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["fact_ref"] = "fact_ref"
    fact_ref: str
    render_as: Literal["display", "raw"] = "display"

    @field_validator("fact_ref")
    @classmethod
    def validate_fact_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not _FACT_KEY_RE.fullmatch(normalized):
            raise ValueError(f"invalid fact reference: {value!r}")
        return normalized


class LiteralSegment(BaseModel):
    """A typed non-authoritative literal used for labels and derived values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["literal"] = "literal"
    value: Any

    @field_validator("value")
    @classmethod
    def validate_json_scalar(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool, Decimal, date, datetime)):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        raise ValueError("literal segment values must be finite JSON scalars, dates, or decimals")


PayloadSegment = Annotated[
    TextSegment | LiteralSegment | FactRefSegment,
    Field(discriminator="kind"),
]


class NarrativeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    kind: Literal["paragraph", "heading", "list_item"] = "paragraph"
    segments: list[PayloadSegment] = Field(min_length=1, max_length=1_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=1_000)
    requires_evidence: bool = True

    _validate_block_id = field_validator("block_id")(_validate_identifier)
    _normalize_refs = field_validator("evidence_refs")(_unique_nonempty)


class TableCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segments: list[PayloadSegment] = Field(min_length=1, max_length=1_000)
    data_type: Literal["auto", "text", "number", "date", "boolean"] = "auto"
    number_format: str | None = Field(default=None, max_length=128)


class TableRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cells: dict[str, TableCell] = Field(min_length=1, max_length=1_000)
    fact_refs: list[str] = Field(default_factory=list, max_length=1_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=1_000)

    @field_validator("cells")
    @classmethod
    def validate_cell_names(cls, values: dict[str, TableCell]) -> dict[str, TableCell]:
        for name in values:
            _validate_identifier(name)
        return values

    _normalize_refs = field_validator("evidence_refs")(_unique_nonempty)

    @field_validator("fact_refs")
    @classmethod
    def validate_fact_refs(cls, values: list[str]) -> list[str]:
        normalized = _unique_nonempty(values)
        for value in normalized:
            if not _FACT_KEY_RE.fullmatch(value):
                raise ValueError(f"invalid fact reference: {value!r}")
        return normalized


class ScalarSlotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["scalar"] = "scalar"
    slot_id: str
    segments: list[PayloadSegment] = Field(min_length=1, max_length=1_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=1_000)

    _validate_slot_id = field_validator("slot_id")(_validate_identifier)
    _normalize_refs = field_validator("evidence_refs")(_unique_nonempty)


class NarrativeSlotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["narrative_blocks"] = "narrative_blocks"
    slot_id: str
    blocks: list[NarrativeBlock] = Field(min_length=1, max_length=2_000)

    _validate_slot_id = field_validator("slot_id")(_validate_identifier)


class TableSlotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["table_rows"] = "table_rows"
    slot_id: str
    rows: list[TableRow] = Field(default_factory=list, max_length=100_000)
    source_fact_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=1_000)

    _validate_slot_id = field_validator("slot_id")(_validate_identifier)
    _normalize_evidence_refs = field_validator("evidence_refs")(_unique_nonempty)

    @field_validator("source_fact_ref")
    @classmethod
    def validate_source_fact_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _FACT_KEY_RE.fullmatch(normalized):
            raise ValueError(f"invalid fact reference: {value!r}")
        return normalized


SlotPayload = Annotated[
    ScalarSlotPayload | NarrativeSlotPayload | TableSlotPayload,
    Field(discriminator="kind"),
]


class DocumentPayload(BaseModel):
    """Agent-produced content that still contains authoritative fact references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    document_code: str
    slots: list[SlotPayload] = Field(min_length=1, max_length=10_000)

    _validate_document_code = field_validator("document_code")(_validate_identifier)

    @model_validator(mode="after")
    def validate_unique_slots(self) -> "DocumentPayload":
        duplicates = _duplicates([slot.slot_id for slot in self.slots])
        if duplicates:
            raise ValueError(f"duplicate payload slots: {', '.join(duplicates)}")
        return self

    @property
    def slot_map(self) -> dict[str, SlotPayload]:
        return {slot.slot_id: slot for slot in self.slots}


class SlotBinding(BaseModel):
    """One immutable mapping from a semantic slot to an explicit file target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str
    target: str = Field(min_length=3, max_length=1_024)
    value_type: Literal["scalar", "narrative_blocks", "table_rows"]
    source: str = Field(default="", max_length=512)
    required: bool = True
    style_policy: Literal[
        "inherit_template",
        "clone_prototype_row",
        "explicit",
    ] = "inherit_template"
    missing_policy: Literal[
        "block",
        "omit_slot",
        "omit_sentence",
        "empty",
    ] = "block"
    overflow_policy: Literal[
        "error",
        "continue_paragraphs",
        "extend_rows",
        "truncate",
        "shrink_font",
    ] = "error"
    options: dict[str, Any] = Field(default_factory=dict)

    _validate_slot_id = field_validator("slot_id")(_validate_identifier)

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.count(":") < 2:
            raise ValueError("slot target must be an explicit '<format>:<kind>:<locator>'")
        if any(character in normalized for character in ("\x00", "\r", "\n")):
            raise ValueError("slot target contains control characters")
        return normalized

    @model_validator(mode="after")
    def validate_required_policy(self) -> "SlotBinding":
        if self.required and self.missing_policy != "block":
            raise ValueError("required slots must use missing_policy='block'")
        composition_mode = self.options.get("composition_mode", "deterministic")
        if not isinstance(composition_mode, str) or composition_mode not in {
            "deterministic",
            "semantic",
        }:
            raise ValueError(
                "slot options.composition_mode must be 'deterministic' or 'semantic'"
            )
        semantic_keys = {
            "semantic_instruction",
            "allowed_fact_refs",
            "fact_ref_labels",
        }
        if composition_mode != "semantic" and semantic_keys & set(self.options):
            raise ValueError(
                "semantic slot options require composition_mode='semantic'"
            )
        if composition_mode == "semantic":
            if self.value_type != "narrative_blocks":
                raise ValueError(
                    "semantic composition is only supported for narrative_blocks slots"
                )
            instruction = self.options.get("semantic_instruction")
            if (
                not isinstance(instruction, str)
                or not instruction.strip()
                or len(instruction.strip()) > 4_000
            ):
                raise ValueError(
                    "semantic slots require options.semantic_instruction (1-4000 chars)"
                )
            fact_refs = self.options.get("allowed_fact_refs")
            if not isinstance(fact_refs, list) or not fact_refs:
                raise ValueError(
                    "semantic slots require a non-empty options.allowed_fact_refs list"
                )
            normalized_refs = _unique_nonempty(fact_refs)
            if len(normalized_refs) != len(fact_refs):
                raise ValueError("semantic allowed_fact_refs must be unique and non-empty")
            for fact_ref in normalized_refs:
                if not _FACT_KEY_RE.fullmatch(fact_ref):
                    raise ValueError(f"invalid semantic fact reference: {fact_ref!r}")
            labels = self.options.get("fact_ref_labels")
            if not isinstance(labels, dict) or set(labels) != set(normalized_refs):
                raise ValueError(
                    "semantic slots require fact_ref_labels for exactly every allowed_fact_ref"
                )
            if any(
                not isinstance(label, str)
                or not label.strip()
                or len(label.strip()) > 200
                for label in labels.values()
            ):
                raise ValueError("semantic fact_ref_labels must contain 1-200 char labels")
            external_text = [instruction.strip(), *(label.strip() for label in labels.values())]
            if any(
                _SEMANTIC_EXTERNAL_TEXT_FORBIDDEN.search(value)
                or _FACT_KEY_FRAGMENT_RE.search(value)
                for value in external_text
            ):
                raise ValueError(
                    "semantic instructions and labels cannot expose internal identifiers"
                )
            if self.options.get("require_fact_refs") is False:
                raise ValueError("semantic slots cannot disable require_fact_refs")
        return self

    @property
    def composition_mode(self) -> Literal["deterministic", "semantic"]:
        return str(self.options.get("composition_mode", "deterministic"))  # type: ignore[return-value]

    @property
    def semantic_instruction(self) -> str:
        return str(self.options.get("semantic_instruction") or "").strip()

    @property
    def allowed_fact_refs(self) -> tuple[str, ...]:
        values = self.options.get("allowed_fact_refs") or []
        return tuple(str(value).strip() for value in values if str(value).strip())

    @property
    def fact_ref_labels(self) -> dict[str, str]:
        values = self.options.get("fact_ref_labels") or {}
        return {str(key): str(value).strip() for key, value in values.items()}


class BindingManifest(BaseModel):
    """Confirmed, renderer-executable template contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1.0"] = "1.0"
    document_code: str
    source_template_sha256: str = ""
    binding_sha256: str = ""
    slots: list[SlotBinding] = Field(min_length=1, max_length=10_000)
    fixed_regions: list[str] = Field(default_factory=list)
    forbidden_output_patterns: list[str] = Field(
        default_factory=lambda: ["[[cite:", "evidence_id", "chunk_id", "claim_id"]
    )
    allowed_modified_parts: list[str] = Field(default_factory=list)

    _validate_document_code = field_validator("document_code")(_validate_identifier)

    @field_validator("source_template_sha256")
    @classmethod
    def validate_template_sha(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized and not _SHA256_RE.fullmatch(normalized):
            raise ValueError("source_template_sha256 must contain 64 lowercase hex characters")
        return normalized

    @field_validator("binding_sha256")
    @classmethod
    def validate_binding_sha(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized and not _SHA256_RE.fullmatch(normalized):
            raise ValueError("binding_sha256 must contain 64 lowercase hex characters")
        return normalized

    @model_validator(mode="after")
    def validate_unique_slots(self) -> "BindingManifest":
        duplicate_slots = _duplicates([slot.slot_id for slot in self.slots])
        duplicate_targets = _duplicates([slot.target for slot in self.slots])
        if duplicate_slots:
            raise ValueError(f"duplicate manifest slots: {', '.join(duplicate_slots)}")
        if duplicate_targets:
            raise ValueError(f"duplicate manifest targets: {', '.join(duplicate_targets)}")
        return self

    @property
    def slot_map(self) -> dict[str, SlotBinding]:
        return {slot.slot_id: slot for slot in self.slots}


class ResolvedSlotPayload(BaseModel):
    """Renderer-facing value with provenance kept outside ``value``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str
    kind: Literal["scalar", "narrative_blocks", "table_rows"]
    value: Any
    fact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    _validate_slot_id = field_validator("slot_id")(_validate_identifier)
    _normalize_fact_refs = field_validator("fact_refs")(_unique_nonempty)
    _normalize_evidence_refs = field_validator("evidence_refs")(_unique_nonempty)


class ResolvedDocumentPayload(BaseModel):
    """Deterministic renderer input after every fact reference is resolved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    document_code: str
    slots: list[ResolvedSlotPayload]

    _validate_document_code = field_validator("document_code")(_validate_identifier)

    @model_validator(mode="after")
    def validate_unique_slots(self) -> "ResolvedDocumentPayload":
        if _duplicates([slot.slot_id for slot in self.slots]):
            raise ValueError("resolved payload contains duplicate slots")
        return self

    @property
    def slot_map(self) -> dict[str, ResolvedSlotPayload]:
        return {slot.slot_id: slot for slot in self.slots}


@dataclass(frozen=True)
class RenderResult:
    """In-memory output of one format renderer."""

    data: bytes
    extension: Literal[".docx", ".xlsx", ".md", ".pdf"]
    content_type: str
    source_template_sha256: str
    modified_parts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def output_sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def ensure_payload_matches_manifest(
    payload: DocumentPayload | ResolvedDocumentPayload,
    manifest: BindingManifest,
) -> None:
    if payload.document_code != manifest.document_code:
        raise AttachmentContractError(
            f"payload document_code {payload.document_code!r} does not match manifest "
            f"{manifest.document_code!r}"
        )
    payload_slots = payload.slot_map
    manifest_slots = manifest.slot_map
    undeclared = sorted(set(payload_slots) - set(manifest_slots))
    missing = sorted(
        binding.slot_id
        for binding in manifest.slots
        if binding.required and binding.slot_id not in payload_slots
    )
    mismatched = sorted(
        slot_id
        for slot_id in set(payload_slots) & set(manifest_slots)
        if payload_slots[slot_id].kind != manifest_slots[slot_id].value_type
    )
    if undeclared:
        raise AttachmentContractError(f"payload contains undeclared slots: {', '.join(undeclared)}")
    if missing:
        raise AttachmentContractError(f"payload is missing required slots: {', '.join(missing)}")
    if mismatched:
        raise AttachmentContractError(f"payload slot types do not match manifest: {', '.join(mismatched)}")


def verify_source_template(template_bytes: bytes, manifest: BindingManifest) -> str:
    digest = hashlib.sha256(template_bytes).hexdigest()
    if manifest.source_template_sha256 and digest != manifest.source_template_sha256:
        raise AttachmentContractError("source template SHA-256 does not match the binding manifest")
    return digest


__all__ = [
    "AttachmentContractError",
    "AttachmentRenderError",
    "BindingManifest",
    "DocumentPayload",
    "FactRefSegment",
    "LiteralSegment",
    "MissingRendererDependency",
    "NarrativeBlock",
    "NarrativeSlotPayload",
    "PayloadSegment",
    "RenderResult",
    "ResolvedDocumentPayload",
    "ResolvedSlotPayload",
    "ScalarSlotPayload",
    "SlotBinding",
    "SlotPayload",
    "TableCell",
    "TableRow",
    "TableSlotPayload",
    "TextSegment",
    "ensure_payload_matches_manifest",
    "verify_source_template",
]
