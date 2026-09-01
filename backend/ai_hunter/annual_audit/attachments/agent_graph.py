"""Pure preparation graph for structured annual-audit attachment payloads.

This module intentionally has no database, object-storage, Celery, or model
provider dependency.  A job service may inject a structured composer backed by
an LLM; its output is immediately validated by the same deterministic contract
used for context-only composition.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .content_schemas import (
    AttachmentContractError,
    BindingManifest,
    DocumentPayload,
    FactRefSegment,
    LiteralSegment,
    NarrativeBlock,
    NarrativeSlotPayload,
    ScalarSlotPayload,
    ResolvedDocumentPayload,
    TableCell,
    TableRow,
    TableSlotPayload,
    TextSegment,
)
from .context_service import GenerationContextSnapshot
from .fact_registry import (
    FactRecord,
    FactRegistry,
    FactResolution,
    MissingFactError,
    evidence_token,
)
from .quality_service import QualityIssue, validate_payload_contract


class StructuredPayloadComposer(Protocol):
    """Narrow interface implemented by a model-backed structured composer."""

    def compose(
        self,
        *,
        binding_manifest: BindingManifest,
        context: GenerationContextSnapshot,
    ) -> DocumentPayload | Mapping[str, Any]: ...


_MODEL_TEXT_FORBIDDEN = re.compile(
    r"(?:\b(?:minio|s3|file)://|\b[A-Za-z]:\\|(?:^|\s)/(?:etc|tmp|var|home)/|"
    r"\{[{%#]|\[\[|\b(?:powershell|cmd\.exe|/bin/sh|bash\s+-c)\b)",
    re.IGNORECASE,
)
_MODEL_TEXT_QUANTITATIVE = re.compile(
    r"(?:[0-9０-９]|[%％¥￥$€£]|\b(?:rmb|cny|usd|eur|percent|percentage|"
    r"dollars?|yuan|renminbi)\b|人民币|美元|欧元|百分之|"
    r"[〇零一二三四五六七八九十百千万亿两]+(?:年|月|日|季度|个月|天|元|万元|亿元))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PreparedAttachment:
    """Renderer-ready, provenance-complete output of the preparation graph."""

    document_payload: DocumentPayload
    resolved_payload: ResolvedDocumentPayload
    context: GenerationContextSnapshot
    context_snapshot_sha256: str
    fact_uses: tuple[FactResolution, ...]
    quality_issues: tuple[QualityIssue, ...] = ()


@dataclass(frozen=True)
class SemanticCompositionContract:
    request: dict[str, Any]
    slot_alias_to_id: dict[str, str]
    fact_alias_to_ref: dict[str, str]
    allowed_fact_aliases_by_slot: dict[str, frozenset[str]]


def compose_document_payload(
    binding_manifest: BindingManifest,
    context: GenerationContextSnapshot,
    *,
    composer: StructuredPayloadComposer | None = None,
) -> DocumentPayload:
    """Compose a typed ``DocumentPayload`` from frozen context and a manifest.

    If ``composer`` is omitted, every slot's ``source`` is treated as an exact
    dotted JSON path into the frozen context.  The deterministic mode does not
    guess semantic mappings.  A model-backed composer may create narrative
    blocks, but it cannot return file bytes, paths, or renderer commands.
    """

    semantic_bindings = semantic_slot_bindings(binding_manifest)
    deterministic_bindings = tuple(
        binding
        for binding in binding_manifest.slots
        if binding.composition_mode == "deterministic"
    )
    if composer is not None and not semantic_bindings:
        raise AttachmentContractError(
            "a structured composer may only be used for explicit semantic slots"
        )
    if semantic_bindings and composer is None:
        raise AttachmentContractError(
            "semantic slots require the frozen structured payload composer"
        )

    composed_slots: dict[str, Any] = {}
    if deterministic_bindings:
        deterministic_manifest = _manifest_with_slots(
            binding_manifest,
            deterministic_bindings,
        )
        deterministic_payload = _compose_from_context(deterministic_manifest, context)
        composed_slots.update(deterministic_payload.slot_map)
    if semantic_bindings:
        semantic_manifest = _manifest_with_slots(binding_manifest, semantic_bindings)
        raw = composer.compose(  # type: ignore[union-attr]
            binding_manifest=semantic_manifest,
            context=context,
        )
        semantic_payload = (
            raw if isinstance(raw, DocumentPayload) else DocumentPayload.model_validate(raw)
        )
        _validate_semantic_payload(semantic_payload, semantic_manifest, context)
        composed_slots.update(semantic_payload.slot_map)
    payload = DocumentPayload(
        document_code=binding_manifest.document_code,
        slots=[
            composed_slots[binding.slot_id]
            for binding in binding_manifest.slots
            if binding.slot_id in composed_slots
        ],
    )
    issues = validate_payload_contract(payload, binding_manifest)
    if issues:
        raise AttachmentContractError("; ".join(issue.message for issue in issues))
    return payload


class AttachmentPreparationGraph:
    """Deterministic freeze/compose/fact-resolution/validation pipeline."""

    def prepare(
        self,
        binding_manifest: BindingManifest,
        context: GenerationContextSnapshot,
        fact_registry: FactRegistry,
        *,
        composer: StructuredPayloadComposer | None = None,
        payload: DocumentPayload | Mapping[str, Any] | None = None,
    ) -> PreparedAttachment:
        if payload is not None and composer is not None:
            raise ValueError("provide either payload or composer, not both")
        if payload is None:
            document_payload = compose_document_payload(
                binding_manifest,
                context,
                composer=composer,
            )
        else:
            document_payload = (
                payload
                if isinstance(payload, DocumentPayload)
                else DocumentPayload.model_validate(payload)
            )
            issues = validate_payload_contract(document_payload, binding_manifest)
            if issues:
                raise AttachmentContractError("; ".join(issue.message for issue in issues))
            if semantic_slot_bindings(binding_manifest):
                _validate_semantic_payload(
                    document_payload,
                    _manifest_with_slots(
                        binding_manifest,
                        semantic_slot_bindings(binding_manifest),
                    ),
                    context,
                )

        resolved = fact_registry.resolve_document_payload(document_payload, binding_manifest)
        resolved_issues = tuple(validate_payload_contract(resolved.payload, binding_manifest))
        if resolved_issues:
            raise AttachmentContractError(
                "; ".join(issue.message for issue in resolved_issues)
            )
        return PreparedAttachment(
            document_payload=document_payload,
            resolved_payload=resolved.payload,
            context=context,
            context_snapshot_sha256=context.snapshot_sha256,
            fact_uses=resolved.fact_uses,
            quality_issues=resolved_issues,
        )


def prepare_attachment(
    binding_manifest: BindingManifest,
    context: GenerationContextSnapshot,
    fact_registry: FactRegistry,
    *,
    composer: StructuredPayloadComposer | None = None,
    payload: DocumentPayload | Mapping[str, Any] | None = None,
) -> PreparedAttachment:
    return AttachmentPreparationGraph().prepare(
        binding_manifest,
        context,
        fact_registry,
        composer=composer,
        payload=payload,
    )


def fact_registry_from_context(context: GenerationContextSnapshot) -> FactRegistry:
    """Rehydrate the registry projection embedded by ``context_service``."""

    facts: list[FactRecord] = []
    for fact_key, raw in context.entity_facts.items():
        if not isinstance(raw, Mapping):
            continue
        candidates = raw.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                facts.append(
                    FactRecord.model_validate(
                        {
                            **dict(candidate),
                            "fact_key": str(candidate.get("fact_key") or fact_key),
                        }
                    )
                )
            continue
        facts.append(
            FactRecord(
                fact_key=fact_key,
                value=copy.deepcopy(raw.get("value")),
                display_value=str(raw.get("display_value") or ""),
                status=str(raw.get("status") or "confirmed"),
                source_kind=str(raw.get("source_kind") or "manual_review"),
                source_ref=copy.deepcopy(raw.get("source_ref") or {}),
                evidence_refs=copy.deepcopy(raw.get("evidence_refs") or []),
                revision=int(raw.get("revision") or 1),
                is_current=True,
                reviewed_by=raw.get("reviewed_by"),
            )
        )
    return FactRegistry(facts)


def semantic_slot_bindings(manifest: BindingManifest) -> tuple[Any, ...]:
    return tuple(
        binding
        for binding in manifest.slots
        if binding.composition_mode == "semantic"
    )


def validate_semantic_manifest_facts(
    manifest: BindingManifest,
    registry: FactRegistry,
) -> None:
    """Resolve every explicitly allowed semantic fact during job preflight."""

    for binding in semantic_slot_bindings(manifest):
        for fact_ref in binding.allowed_fact_refs:
            registry.resolve(fact_ref)


def frozen_evidence_allowlist(context: GenerationContextSnapshot) -> frozenset[str]:
    tokens: set[str] = set()
    for raw in context.entity_facts.values():
        if not isinstance(raw, Mapping) or raw.get("resolution_status") != "resolved":
            continue
        for reference in raw.get("evidence_refs") or []:
            if token := evidence_token(reference):
                tokens.add(token)
    entries = context.evidence_manifest.get("citation_plan_entries") or []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        citation_id = str(entry.get("citation_id") or "").strip()
        if citation_id:
            tokens.add(f"citation:{citation_id}")
        for reference in entry.get("evidence_snapshot") or []:
            if token := evidence_token(reference):
                tokens.add(token)
    return frozenset(tokens)


def semantic_composition_contract(
    manifest: BindingManifest,
) -> SemanticCompositionContract:
    """Build an anonymous contract that exposes no internal fact or slot IDs."""

    bindings = semantic_slot_bindings(manifest)
    all_fact_refs = sorted(
        {fact_ref for binding in bindings for fact_ref in binding.allowed_fact_refs}
    )
    fact_ref_to_alias = {
        fact_ref: f"fact_{index:03d}"
        for index, fact_ref in enumerate(all_fact_refs, start=1)
    }
    slot_alias_to_id = {
        f"slot_{index:03d}": binding.slot_id
        for index, binding in enumerate(bindings, start=1)
    }
    request_slots: list[dict[str, Any]] = []
    allowed_by_slot: dict[str, frozenset[str]] = {}
    for slot_alias, binding in zip(slot_alias_to_id, bindings, strict=True):
        aliases = frozenset(
            fact_ref_to_alias[fact_ref] for fact_ref in binding.allowed_fact_refs
        )
        allowed_by_slot[slot_alias] = aliases
        request_slots.append(
            {
                "slot_id": slot_alias,
                "value_type": binding.value_type,
                "required": binding.required,
                "missing_policy": binding.missing_policy,
                "semantic_instruction": binding.semantic_instruction,
                "allowed_facts": [
                    {
                        "fact_ref": fact_ref_to_alias[fact_ref],
                        "label": binding.fact_ref_labels[fact_ref],
                    }
                    for fact_ref in binding.allowed_fact_refs
                ],
            }
        )
    return SemanticCompositionContract(
        request={"document_code": "semantic_attachment", "slots": request_slots},
        slot_alias_to_id=slot_alias_to_id,
        fact_alias_to_ref={alias: fact_ref for fact_ref, alias in fact_ref_to_alias.items()},
        allowed_fact_aliases_by_slot=allowed_by_slot,
    )


def _manifest_with_slots(
    manifest: BindingManifest,
    slots: tuple[Any, ...],
) -> BindingManifest:
    return manifest.model_copy(update={"slots": list(slots)})


def _validate_semantic_payload(
    payload: DocumentPayload,
    manifest: BindingManifest,
    context: GenerationContextSnapshot,
) -> None:
    issues = validate_payload_contract(payload, manifest)
    if issues:
        raise AttachmentContractError("; ".join(issue.message for issue in issues))
    evidence_allowlist = frozen_evidence_allowlist(context)
    for binding in manifest.slots:
        slot = payload.slot_map.get(binding.slot_id)
        if slot is None:
            continue
        if not isinstance(slot, NarrativeSlotPayload):
            raise AttachmentContractError(
                f"semantic slot must contain narrative blocks: {binding.slot_id}"
            )
        allowed_facts = set(binding.allowed_fact_refs)
        for block in slot.blocks:
            block_fact_refs: list[str] = []
            for segment in block.segments:
                if isinstance(segment, FactRefSegment):
                    if segment.fact_ref not in allowed_facts:
                        raise AttachmentContractError(
                            f"semantic slot used an unapproved fact_ref: {segment.fact_ref}"
                        )
                    frozen = context.entity_facts.get(segment.fact_ref)
                    if not isinstance(frozen, Mapping) or frozen.get("resolution_status") != "resolved":
                        raise AttachmentContractError(
                            f"semantic slot used a non-resolved frozen fact_ref: {segment.fact_ref}"
                        )
                    block_fact_refs.append(segment.fact_ref)
                elif isinstance(segment, LiteralSegment):
                    raise AttachmentContractError(
                        "semantic model output cannot contain literal segments"
                    )
                elif isinstance(segment, TextSegment) and _MODEL_TEXT_FORBIDDEN.search(
                    segment.text
                ):
                    raise AttachmentContractError(
                        "semantic model output contains a forbidden path, object ref, or command"
                    )
                elif isinstance(segment, TextSegment) and _MODEL_TEXT_QUANTITATIVE.search(
                    segment.text
                ):
                    raise AttachmentContractError(
                        "semantic model text cannot contain quantities, dates, or amounts; "
                        "use an approved fact_ref"
                    )
            if not block_fact_refs:
                raise AttachmentContractError(
                    f"semantic narrative block requires an approved fact_ref: {block.block_id}"
                )
            unknown_evidence = sorted(set(block.evidence_refs) - evidence_allowlist)
            if unknown_evidence:
                raise AttachmentContractError(
                    "semantic narrative block used evidence outside the frozen allowlist: "
                    + ", ".join(unknown_evidence)
                )


def _compose_from_context(
    manifest: BindingManifest,
    context: GenerationContextSnapshot,
) -> DocumentPayload:
    root = context.model_dump(mode="python", by_alias=True)
    slots = []
    for binding in manifest.slots:
        if not binding.source:
            if binding.required:
                raise AttachmentContractError(
                    f"required slot has no deterministic source path: {binding.slot_id}"
                )
            continue
        fact_key = _fact_key_for_source(binding.source, context)
        fact_reference_only = fact_key is not None
        if fact_reference_only:
            found, value = True, None
        else:
            found, value = _resolve_path(root, binding.source)
        if (not found or value is None) and not fact_reference_only:
            if _is_fact_source(binding.source) and (
                binding.required or binding.missing_policy == "block"
            ):
                raise MissingFactError(_candidate_fact_key(binding.source))
            if binding.required or binding.missing_policy == "block":
                raise AttachmentContractError(
                    f"required context source is missing: {binding.source}"
                )
            if binding.missing_policy == "empty":
                value = [] if binding.value_type == "table_rows" else ""
            else:
                continue

        require_fact_refs = bool(binding.options.get("require_fact_refs", fact_key is not None))
        if require_fact_refs and fact_key is None:
            raise AttachmentContractError(
                f"slot requires fact_ref but source is not a frozen fact: {binding.slot_id}"
            )
        if binding.value_type == "scalar":
            context_evidence = [] if fact_key is not None else [_context_source_token(binding.source, context)]
            segment = (
                FactRefSegment(fact_ref=fact_key, render_as="raw")
                if fact_key is not None
                else LiteralSegment(value=value)
            )
            slots.append(
                ScalarSlotPayload(
                    slot_id=binding.slot_id,
                    segments=[segment],
                    evidence_refs=context_evidence,
                )
            )
        elif binding.value_type == "narrative_blocks":
            slots.append(
                NarrativeSlotPayload(
                    slot_id=binding.slot_id,
                    blocks=_narrative_blocks(
                        binding.slot_id,
                        value,
                        fact_key=fact_key,
                        context_evidence=(
                            None
                            if fact_key is not None
                            else _context_source_token(binding.source, context)
                        ),
                    ),
                )
            )
        else:
            if fact_key is not None:
                slots.append(
                    TableSlotPayload(
                        slot_id=binding.slot_id,
                        source_fact_ref=fact_key,
                    )
                )
                continue
            if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
                raise AttachmentContractError(
                    f"table_rows source must be a list of objects: {binding.source}"
                )
            slots.append(
                TableSlotPayload(
                    slot_id=binding.slot_id,
                    rows=[
                        TableRow(
                            cells={
                                str(key): TableCell(segments=[LiteralSegment(value=item)])
                                for key, item in row.items()
                                if key != "__evidence_refs__"
                            },
                            fact_refs=[fact_key] if fact_key is not None else [],
                            evidence_refs=[
                                *(
                                    [str(reference) for reference in row.get("__evidence_refs__") or []]
                                    if isinstance(row.get("__evidence_refs__"), list)
                                    else []
                                ),
                                _context_source_token(binding.source, context),
                            ],
                        )
                        for row in value
                    ],
                )
            )
    return DocumentPayload(document_code=manifest.document_code, slots=slots)


def _narrative_blocks(
    slot_id: str,
    value: Any,
    *,
    fact_key: str | None,
    context_evidence: str | None,
) -> list[NarrativeBlock]:
    if fact_key is not None:
        return [
            NarrativeBlock(
                block_id=f"{slot_id}.value",
                segments=[FactRefSegment(fact_ref=fact_key, render_as="display")],
                requires_evidence=False,
            )
        ]
    raw_blocks = value if isinstance(value, list) else [value]
    blocks: list[NarrativeBlock] = []
    for index, item in enumerate(raw_blocks):
        if isinstance(item, Mapping):
            text = item.get("text")
            if text is None:
                raise AttachmentContractError(
                    f"narrative source object requires text: {slot_id}[{index}]"
                )
            evidence = [str(ref) for ref in item.get("evidence_refs") or []]
        else:
            text = item
            evidence = []
        if context_evidence:
            evidence.append(context_evidence)
        blocks.append(
            NarrativeBlock(
                block_id=f"{slot_id}.{index + 1}",
                segments=[LiteralSegment(value=text)],
                evidence_refs=evidence,
                requires_evidence=True,
            )
        )
    return blocks


def _fact_key_for_source(source: str, context: GenerationContextSnapshot) -> str | None:
    normalized = _document_source(source)
    if normalized.startswith("entity_facts."):
        candidate = normalized.removeprefix("entity_facts.")
        return candidate if candidate in context.entity_facts else None
    if normalized.startswith("entity.") and normalized in context.entity_facts:
        return normalized
    return None


def _resolve_path(root: Any, path: str) -> tuple[bool, Any]:
    path = _document_source(path)
    entity_facts = root.get("entity_facts", {}) if isinstance(root, Mapping) else {}
    if path.startswith("entity_facts."):
        fact_key = path.removeprefix("entity_facts.")
        if fact_key in entity_facts:
            record = entity_facts[fact_key]
            if isinstance(record, Mapping):
                return ("value" in record), record.get("value")
            return True, record
    if path.startswith("entity.") and path in entity_facts:
        record = entity_facts[path]
        if isinstance(record, Mapping):
            return ("value" in record), record.get("value")
        return True, record
    current = root
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _document_source(source: str) -> str:
    normalized = str(source or "").strip()
    return normalized.removeprefix("document.")


def _is_fact_source(source: str) -> bool:
    normalized = _document_source(source)
    return normalized.startswith(("entity.", "entity_facts."))


def _candidate_fact_key(source: str) -> str:
    normalized = _document_source(source)
    return normalized.removeprefix("entity_facts.")


def _context_source_token(source: str, context: GenerationContextSnapshot) -> str:
    return (
        f"context:{source}@{context.snapshot_sha256}:"
        f"report:{context.report.fact_snapshot_sha256}"
    )


__all__ = [
    "AttachmentPreparationGraph",
    "PreparedAttachment",
    "SemanticCompositionContract",
    "StructuredPayloadComposer",
    "compose_document_payload",
    "fact_registry_from_context",
    "frozen_evidence_allowlist",
    "prepare_attachment",
    "semantic_composition_contract",
    "semantic_slot_bindings",
    "validate_semantic_manifest_facts",
]
