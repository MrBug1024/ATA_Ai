"""Deterministic fact selection and ``fact_ref`` resolution.

The registry implements the authority order defined by the annual-audit
attachment contract.  Lower-priority material or narrative candidates cannot
override engagement master data or an approved correction.  Conflicting values
at the same authority level are always surfaced instead of guessed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .content_schemas import (
    AttachmentContractError,
    BindingManifest,
    DocumentPayload,
    FactRefSegment,
    LiteralSegment,
    NarrativeSlotPayload,
    ResolvedDocumentPayload,
    ResolvedSlotPayload,
    ScalarSlotPayload,
    SlotBinding,
    TableSlotPayload,
    TextSegment,
    ensure_payload_matches_manifest,
)


DEFAULT_SOURCE_PRIORITIES: dict[str, int] = {
    "project_master": 10,
    "engagement_master": 10,
    "master": 10,
    "profile": 10,
    "approved_correction": 20,
    "correction": 20,
    "manual_review": 25,
    "report_snapshot": 30,
    "report": 30,
    "calculation": 30,
    "audit_program": 40,
    "program": 40,
    "finding": 40,
    "release_gate": 40,
    "material_extraction": 50,
    "material": 50,
    "conversation": 60,
    "report_draft": 60,
    "narrative": 60,
}
USABLE_FACT_STATUSES = frozenset({"confirmed", "approved"})


class FactResolutionError(AttachmentContractError):
    """Base class for a fact that cannot be deterministically resolved."""

    def __init__(self, fact_key: str, message: str) -> None:
        self.fact_key = fact_key
        super().__init__(message)


class MissingFactError(FactResolutionError):
    def __init__(self, fact_key: str) -> None:
        super().__init__(fact_key, f"required fact is missing or unconfirmed: {fact_key}")


class ConflictedFactError(FactResolutionError):
    def __init__(self, fact_key: str) -> None:
        super().__init__(fact_key, f"authoritative fact is conflicted: {fact_key}")


class FactRecord(BaseModel):
    """One versioned fact candidate loaded from a deterministic source."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    fact_key: str
    value: Any
    display_value: str | None = None
    data_type: str = "auto"
    status: str = "candidate"
    source_kind: str
    source_ref: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[Any] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)
    is_current: bool = True
    reviewed_by: str | None = None

    @field_validator("fact_key", "source_kind", "status")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("fact_key, source_kind, and status must not be blank")
        return normalized


class FactResolution(BaseModel):
    """Frozen record of the exact fact version selected for rendering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_key: str
    value: Any
    display_value: str
    status: str
    source_kind: str
    source_ref: dict[str, Any]
    evidence_refs: list[Any]
    revision: int
    value_sha256: str


@dataclass(frozen=True)
class ResolvedPayloadBundle:
    payload: ResolvedDocumentPayload
    fact_uses: tuple[FactResolution, ...]


class FactRegistry:
    """In-memory, side-effect-free registry of versioned annual-audit facts."""

    def __init__(
        self,
        facts: Iterable[FactRecord | Mapping[str, Any]] = (),
        *,
        source_priorities: Mapping[str, int] | None = None,
    ) -> None:
        self._priorities = {**DEFAULT_SOURCE_PRIORITIES, **dict(source_priorities or {})}
        self._facts: dict[str, list[FactRecord]] = {}
        for fact in facts:
            self.add(fact)

    def add(self, fact: FactRecord | Mapping[str, Any]) -> None:
        record = fact if isinstance(fact, FactRecord) else FactRecord.model_validate(fact)
        self._facts.setdefault(record.fact_key, []).append(record)

    def source_priority(self, source_kind: str) -> int:
        return int(self._priorities.get(source_kind, 100))

    def resolve(self, fact_key: str) -> FactResolution:
        current = [record for record in self._facts.get(fact_key, ()) if record.is_current]
        eligible = [
            record
            for record in current
            if record.status in USABLE_FACT_STATUSES or record.status == "conflicted"
        ]
        if not eligible:
            raise MissingFactError(fact_key)

        best_priority = min(self.source_priority(record.source_kind) for record in eligible)
        authoritative = [
            record
            for record in eligible
            if self.source_priority(record.source_kind) == best_priority
        ]
        if any(record.status == "conflicted" for record in authoritative):
            raise ConflictedFactError(fact_key)

        usable = [record for record in authoritative if record.status in USABLE_FACT_STATUSES]
        if not usable:
            raise MissingFactError(fact_key)
        fingerprints = {_canonical_sha(record.value) for record in usable}
        if len(fingerprints) != 1:
            raise ConflictedFactError(fact_key)

        selected = max(
            usable,
            key=lambda record: (
                record.revision,
                record.status == "approved",
                record.source_kind,
            ),
        )
        return FactResolution(
            fact_key=selected.fact_key,
            value=copy.deepcopy(selected.value),
            display_value=(
                selected.display_value
                if selected.display_value not in (None, "")
                else _display_value(selected.value)
            ),
            status=selected.status,
            source_kind=selected.source_kind,
            source_ref=copy.deepcopy(selected.source_ref),
            evidence_refs=copy.deepcopy(selected.evidence_refs),
            revision=selected.revision,
            value_sha256=_canonical_sha(selected.value),
        )

    def confirmed_snapshot(self) -> dict[str, Any]:
        """Return a stable context projection of every currently resolvable fact."""

        snapshot: dict[str, Any] = {}
        for fact_key in sorted(self._facts):
            try:
                resolution = self.resolve(fact_key)
            except FactResolutionError:
                continue
            snapshot[fact_key] = resolution.model_dump(mode="json")
        return snapshot

    def frozen_snapshot(self) -> dict[str, Any]:
        """Freeze every current candidate so missing and conflict stay distinct."""

        snapshot: dict[str, Any] = {}
        for fact_key in sorted(self._facts):
            records = sorted(
                (record for record in self._facts[fact_key] if record.is_current),
                key=lambda record: (
                    self.source_priority(record.source_kind),
                    record.source_kind,
                    record.revision,
                    _canonical_sha(record.value),
                ),
            )
            entry: dict[str, Any] = {
                "candidates": [record.model_dump(mode="python") for record in records],
            }
            try:
                resolution = self.resolve(fact_key)
                entry.update(resolution.model_dump(mode="python"))
                entry["resolution_status"] = "resolved"
            except ConflictedFactError:
                entry["resolution_status"] = "conflicted"
            except MissingFactError:
                entry["resolution_status"] = "unconfirmed"
            snapshot[fact_key] = entry
        return snapshot

    def resolve_document_payload(
        self,
        payload: DocumentPayload,
        manifest: BindingManifest,
    ) -> ResolvedPayloadBundle:
        ensure_payload_matches_manifest(payload, manifest)
        resolved_slots: list[ResolvedSlotPayload] = []
        fact_uses: dict[tuple[str, int, str], FactResolution] = {}

        for binding in manifest.slots:
            slot = payload.slot_map.get(binding.slot_id)
            if slot is None:
                continue
            resolved = self._resolve_slot(slot, binding)
            if resolved is None:
                continue
            resolved_slots.append(resolved[0])
            for resolution in resolved[1]:
                fact_uses[(
                    resolution.fact_key,
                    resolution.revision,
                    resolution.value_sha256,
                )] = resolution

        return ResolvedPayloadBundle(
            payload=ResolvedDocumentPayload(
                document_code=payload.document_code,
                slots=resolved_slots,
            ),
            fact_uses=tuple(
                fact_uses[key]
                for key in sorted(fact_uses, key=lambda item: (item[0], item[1], item[2]))
            ),
        )

    def _resolve_slot(
        self,
        slot: ScalarSlotPayload | NarrativeSlotPayload | TableSlotPayload,
        binding: SlotBinding,
    ) -> tuple[ResolvedSlotPayload, list[FactResolution]] | None:
        if isinstance(slot, ScalarSlotPayload):
            try:
                value, resolutions = self._resolve_segments(slot.segments)
            except MissingFactError:
                value = self._handle_missing(binding)
                if value is _OMIT:
                    return None
                resolutions = []
            evidence = [*slot.evidence_refs, *_resolution_evidence_tokens(resolutions)]
            return (
                ResolvedSlotPayload(
                    slot_id=slot.slot_id,
                    kind=slot.kind,
                    value=value,
                    fact_refs=[item.fact_key for item in resolutions],
                    evidence_refs=evidence,
                ),
                resolutions,
            )

        if isinstance(slot, NarrativeSlotPayload):
            blocks: list[dict[str, Any]] = []
            resolutions: list[FactResolution] = []
            evidence: list[str] = []
            for block in slot.blocks:
                try:
                    text, block_resolutions = self._resolve_segments(block.segments)
                except MissingFactError:
                    if binding.required or binding.missing_policy == "block":
                        raise
                    if binding.missing_policy == "empty":
                        text, block_resolutions = "", []
                    else:
                        continue
                blocks.append({"kind": block.kind, "text": str(text)})
                resolutions.extend(block_resolutions)
                evidence.extend(block.evidence_refs)
                evidence.extend(_resolution_evidence_tokens(block_resolutions))
            if not blocks and binding.required:
                raise MissingFactError(binding.source or binding.slot_id)
            if not blocks and binding.missing_policy == "omit_slot":
                return None
            return (
                ResolvedSlotPayload(
                    slot_id=slot.slot_id,
                    kind=slot.kind,
                    value=blocks,
                    fact_refs=[item.fact_key for item in resolutions],
                    evidence_refs=evidence,
                ),
                resolutions,
            )

        if slot.source_fact_ref:
            resolution = self.resolve(slot.source_fact_ref)
            if not isinstance(resolution.value, list) or any(
                not isinstance(row, Mapping) for row in resolution.value
            ):
                raise FactResolutionError(
                    slot.source_fact_ref,
                    f"table fact must resolve to a list of objects: {slot.source_fact_ref}",
                )
            value = [copy.deepcopy(dict(row)) for row in resolution.value]
            return (
                ResolvedSlotPayload(
                    slot_id=slot.slot_id,
                    kind=slot.kind,
                    value=value,
                    fact_refs=[resolution.fact_key],
                    evidence_refs=[
                        *slot.evidence_refs,
                        *_resolution_evidence_tokens([resolution]),
                    ],
                ),
                [resolution],
            )

        rows: list[dict[str, Any]] = []
        resolutions = []
        evidence: list[str] = list(slot.evidence_refs)
        for row in slot.rows:
            resolved_row: dict[str, Any] = {}
            row_resolutions: list[FactResolution] = [
                self.resolve(fact_ref) for fact_ref in row.fact_refs
            ]
            try:
                for key, cell in row.cells.items():
                    value, cell_resolutions = self._resolve_segments(cell.segments)
                    resolved_row[key] = value
                    row_resolutions.extend(cell_resolutions)
            except MissingFactError:
                if binding.required or binding.missing_policy == "block":
                    raise
                if binding.missing_policy == "empty":
                    resolved_row = {key: "" for key in row.cells}
                    row_resolutions = []
                else:
                    continue
            rows.append(resolved_row)
            resolutions.extend(row_resolutions)
            evidence.extend(row.evidence_refs)
            evidence.extend(_resolution_evidence_tokens(row_resolutions))
        if not rows and binding.required:
            raise MissingFactError(binding.source or binding.slot_id)
        if not rows and binding.missing_policy == "omit_slot":
            return None
        return (
            ResolvedSlotPayload(
                slot_id=slot.slot_id,
                kind=slot.kind,
                value=rows,
                fact_refs=[item.fact_key for item in resolutions],
                evidence_refs=evidence,
            ),
            resolutions,
        )

    def _resolve_segments(
        self,
        segments: list[TextSegment | LiteralSegment | FactRefSegment],
    ) -> tuple[Any, list[FactResolution]]:
        if len(segments) == 1 and isinstance(segments[0], LiteralSegment):
            return copy.deepcopy(segments[0].value), []
        if len(segments) == 1 and isinstance(segments[0], FactRefSegment):
            resolution = self.resolve(segments[0].fact_ref)
            value = (
                copy.deepcopy(resolution.value)
                if segments[0].render_as == "raw"
                else resolution.display_value
            )
            return value, [resolution]

        parts: list[str] = []
        resolutions: list[FactResolution] = []
        for segment in segments:
            if isinstance(segment, TextSegment):
                parts.append(segment.text)
                continue
            if isinstance(segment, LiteralSegment):
                parts.append(_display_value(segment.value))
                continue
            resolution = self.resolve(segment.fact_ref)
            resolutions.append(resolution)
            parts.append(
                resolution.display_value
                if segment.render_as == "display"
                else _display_value(resolution.value)
            )
        return "".join(parts), resolutions

    @staticmethod
    def _handle_missing(binding: SlotBinding) -> object | str:
        if binding.required or binding.missing_policy == "block":
            raise MissingFactError(binding.source or binding.slot_id)
        if binding.missing_policy == "empty":
            return ""
        return _OMIT


_OMIT = object()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _canonical_sha(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _display_value(value: Any) -> str:
    normalized = _json_safe(value)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "" if normalized is None else str(normalized)


def evidence_token(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        source_file = value.get("source_file_id") or value.get("file_id") or ""
        page = value.get("source_page_id") or value.get("page_no") or ""
        chunk = value.get("source_chunk_id") or value.get("chunk_id") or ""
        if source_file or page or chunk:
            return f"file:{source_file};page:{page};chunk:{chunk}"
    return f"evidence:{_canonical_sha(value)}"


def _resolution_evidence_tokens(resolutions: Iterable[FactResolution]) -> list[str]:
    return [
        token
        for resolution in resolutions
        for reference in resolution.evidence_refs
        if (token := evidence_token(reference))
    ]


__all__ = [
    "ConflictedFactError",
    "DEFAULT_SOURCE_PRIORITIES",
    "FactRecord",
    "FactRegistry",
    "FactResolution",
    "FactResolutionError",
    "MissingFactError",
    "ResolvedPayloadBundle",
    "USABLE_FACT_STATUSES",
    "evidence_token",
]
