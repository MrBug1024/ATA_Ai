"""Frozen, opt-in structured model composition for semantic narrative slots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from ai_hunter.app.graph.llm import build_frozen_attachment_llm
from ai_hunter.app.graph.prompting import load_prompt
from ai_hunter.app.settings import Settings

from .agent_graph import semantic_composition_contract, semantic_slot_bindings
from .content_schemas import (
    AttachmentContractError,
    BindingManifest,
    DocumentPayload,
    FactRefSegment,
    LiteralSegment,
    NarrativeBlock,
    NarrativeSlotPayload,
    TextSegment,
)
from .context_service import GenerationContextSnapshot, canonical_json_bytes


ATTACHMENT_COMPOSER_PROMPT = "annual_audit_attachment_composer.txt"
ATTACHMENT_COMPOSER_PROMPT_VERSION = "annual-attachment-semantic-v1"
ATTACHMENT_COMPOSITION_POLICY_VERSION = "semantic-slot-opt-in-v1"


class SemanticCompositionError(AttachmentContractError):
    """Focused failure from semantic model configuration or invocation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _prompt_sha256() -> str:
    prompt = load_prompt(ATTACHMENT_COMPOSER_PROMPT)
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _semantic_slot_ids(manifests: list[BindingManifest]) -> list[str]:
    return sorted(
        f"{manifest.document_code}:{binding.slot_id}"
        for manifest in manifests
        for binding in semantic_slot_bindings(manifest)
    )


def build_attachment_model_manifest(
    files: list[dict[str, Any]],
    *,
    settings: Settings,
) -> dict[str, Any]:
    """Freeze the exact composition strategy before a durable job is created."""

    manifests = [
        BindingManifest.model_validate(item.get("binding_manifest") or {})
        for item in files
    ]
    semantic_slots = _semantic_slot_ids(manifests)
    if not semantic_slots:
        return {
            "mode": "deterministic",
            "provider": "deterministic",
            "model": "structured-payload-composer",
            "prompt_version": "annual-attachment-v1",
            "prompt_sha256": "",
            "composition_policy_version": ATTACHMENT_COMPOSITION_POLICY_VERSION,
            "semantic_slots": [],
        }

    try:
        config = settings.get_llm_config("agent")
    except Exception as exc:
        raise SemanticCompositionError(
            "ATTACHMENT_MODEL_CONFIG_INVALID",
            "语义附件编制模型配置无效",
        ) from exc
    provider = str(config.get("provider") or "").strip().lower()
    model = str(config.get("model") or "").strip()
    if not provider or not model:
        raise SemanticCompositionError(
            "ATTACHMENT_MODEL_CONFIG_INVALID",
            "语义附件编制需要明确的 provider 和 model",
        )
    return {
        "mode": "semantic_opt_in",
        "provider": provider,
        "model": model,
        "prompt_version": ATTACHMENT_COMPOSER_PROMPT_VERSION,
        "prompt_sha256": _prompt_sha256(),
        "composition_policy_version": ATTACHMENT_COMPOSITION_POLICY_VERSION,
        "semantic_slots": semantic_slots,
    }


def validate_frozen_model_manifest(
    model_manifest: Mapping[str, Any],
    manifests: list[BindingManifest],
) -> None:
    """Bind worker execution to the model strategy frozen on the job row."""

    semantic_slots = _semantic_slot_ids(manifests)
    mode = str(model_manifest.get("mode") or "")
    if not semantic_slots:
        if mode != "deterministic" or model_manifest.get("semantic_slots") not in ([], ()):
            raise SemanticCompositionError(
                "MODEL_MANIFEST_MISMATCH",
                "确定性模板与冻结模型策略不一致",
            )
        return
    if mode != "semantic_opt_in":
        raise SemanticCompositionError(
            "MODEL_MANIFEST_MISMATCH",
            "语义模板缺少 opt-in 冻结模型策略",
        )
    if list(model_manifest.get("semantic_slots") or []) != semantic_slots:
        raise SemanticCompositionError(
            "MODEL_MANIFEST_MISMATCH",
            "冻结模型策略的语义槽位集合与模板不一致",
        )
    if (
        str(model_manifest.get("prompt_version") or "")
        != ATTACHMENT_COMPOSER_PROMPT_VERSION
        or str(model_manifest.get("composition_policy_version") or "")
        != ATTACHMENT_COMPOSITION_POLICY_VERSION
        or str(model_manifest.get("prompt_sha256") or "") != _prompt_sha256()
        or not str(model_manifest.get("provider") or "").strip()
        or not str(model_manifest.get("model") or "").strip()
    ):
        raise SemanticCompositionError(
            "MODEL_MANIFEST_UNSUPPORTED",
            "冻结模型或 prompt 策略不受当前 worker 支持",
        )


@dataclass(frozen=True)
class StructuredAttachmentComposer:
    """Invoke one structured LLM using only anonymous, value-free aliases."""

    llm: Any
    model_manifest: Mapping[str, Any]

    def compose(
        self,
        *,
        binding_manifest: BindingManifest,
        context: GenerationContextSnapshot,
    ) -> DocumentPayload:
        del context  # The external provider never receives frozen context or values.
        if not semantic_slot_bindings(binding_manifest):
            raise SemanticCompositionError(
                "SEMANTIC_SLOT_NOT_DECLARED",
                "结构化模型只能编制显式 semantic 槽位",
            )
        if (
            str(self.model_manifest.get("prompt_version") or "")
            != ATTACHMENT_COMPOSER_PROMPT_VERSION
            or str(self.model_manifest.get("prompt_sha256") or "") != _prompt_sha256()
        ):
            raise SemanticCompositionError(
                "MODEL_MANIFEST_UNSUPPORTED",
                "冻结 prompt 策略不受当前 worker 支持",
            )
        contract = semantic_composition_contract(binding_manifest)
        messages = [
            SystemMessage(content=load_prompt(ATTACHMENT_COMPOSER_PROMPT)),
            HumanMessage(content=canonical_json_bytes(contract.request).decode("utf-8")),
        ]
        try:
            structured_llm = self.llm.with_structured_output(DocumentPayload)
            raw = structured_llm.invoke(messages)
            if not isinstance(raw, DocumentPayload):
                if hasattr(raw, "model_dump"):
                    raw = raw.model_dump(mode="python")
                raw = DocumentPayload.model_validate(raw)
            return _restore_internal_references(raw, binding_manifest, contract)
        except SemanticCompositionError:
            raise
        except (ValidationError, TypeError, ValueError, RuntimeError) as exc:
            raise SemanticCompositionError(
                "ATTACHMENT_MODEL_STRUCTURED_OUTPUT_FAILED",
                "语义附件编制模型未返回合法 DocumentPayload",
            ) from exc
        except Exception as exc:
            raise SemanticCompositionError(
                "ATTACHMENT_MODEL_INVOCATION_FAILED",
                "语义附件编制模型调用失败",
            ) from exc


def _restore_internal_references(
    payload: DocumentPayload,
    manifest: BindingManifest,
    contract,
) -> DocumentPayload:
    if payload.document_code != "semantic_attachment":
        raise SemanticCompositionError(
            "ATTACHMENT_MODEL_OUTPUT_SCOPE_INVALID",
            "模型返回了未声明的 document_code",
        )
    restored_slots: list[NarrativeSlotPayload] = []
    for slot in payload.slots:
        actual_slot_id = contract.slot_alias_to_id.get(slot.slot_id)
        if actual_slot_id is None or not isinstance(slot, NarrativeSlotPayload):
            raise SemanticCompositionError(
                "ATTACHMENT_MODEL_OUTPUT_SCOPE_INVALID",
                "模型返回了未声明的槽位或槽位类型",
            )
        allowed_aliases = contract.allowed_fact_aliases_by_slot[slot.slot_id]
        restored_blocks: list[NarrativeBlock] = []
        for block in slot.blocks:
            if block.evidence_refs:
                raise SemanticCompositionError(
                    "ATTACHMENT_MODEL_EVIDENCE_FORBIDDEN",
                    "模型不得直接提交 evidence_refs",
                )
            restored_segments = []
            for segment in block.segments:
                if isinstance(segment, FactRefSegment):
                    if segment.fact_ref not in allowed_aliases:
                        raise SemanticCompositionError(
                            "ATTACHMENT_MODEL_FACT_REF_UNKNOWN",
                            "模型使用了未授权的匿名 fact_ref",
                        )
                    restored_segments.append(
                        FactRefSegment(
                            fact_ref=contract.fact_alias_to_ref[segment.fact_ref],
                            render_as=segment.render_as,
                        )
                    )
                elif isinstance(segment, TextSegment):
                    restored_segments.append(segment)
                elif isinstance(segment, LiteralSegment):
                    raise SemanticCompositionError(
                        "ATTACHMENT_MODEL_LITERAL_FORBIDDEN",
                        "模型不得提交 literal segment",
                    )
            restored_blocks.append(
                NarrativeBlock(
                    block_id=block.block_id,
                    kind=block.kind,
                    segments=restored_segments,
                    evidence_refs=[],
                    requires_evidence=block.requires_evidence,
                )
            )
        restored_slots.append(
            NarrativeSlotPayload(
                slot_id=actual_slot_id,
                blocks=restored_blocks,
            )
        )
    return DocumentPayload(document_code=manifest.document_code, slots=restored_slots)


def build_frozen_attachment_composer(
    *,
    model_manifest: Mapping[str, Any],
    settings: Settings,
) -> StructuredAttachmentComposer:
    provider = str(model_manifest.get("provider") or "").strip().lower()
    model = str(model_manifest.get("model") or "").strip()
    try:
        config = settings.get_llm_config("agent", provider_override=provider)
    except Exception as exc:
        raise SemanticCompositionError(
            "ATTACHMENT_MODEL_CONFIG_INVALID",
            "冻结 provider 在当前 worker 上不可用",
        ) from exc
    if not str(config.get("api_key") or "").strip():
        raise SemanticCompositionError(
            "ATTACHMENT_MODEL_API_KEY_MISSING",
            "冻结 provider 的 API key 当前不可用",
        )
    if not model:
        raise SemanticCompositionError(
            "MODEL_MANIFEST_UNSUPPORTED",
            "冻结模型名称为空",
        )
    llm = build_frozen_attachment_llm(
        provider=provider,
        model=model,
        settings=settings,
    )
    return StructuredAttachmentComposer(llm=llm, model_manifest=model_manifest)


def require_attachment_model_credentials(
    model_manifest: Mapping[str, Any],
    *,
    settings: Settings,
) -> None:
    if str(model_manifest.get("mode") or "") != "semantic_opt_in":
        return
    provider = str(model_manifest.get("provider") or "").strip().lower()
    try:
        config = settings.get_llm_config("agent", provider_override=provider)
    except Exception as exc:
        raise SemanticCompositionError(
            "ATTACHMENT_MODEL_CONFIG_INVALID",
            "冻结 provider 在当前服务上不可用",
        ) from exc
    if not str(config.get("api_key") or "").strip():
        raise SemanticCompositionError(
            "ATTACHMENT_MODEL_API_KEY_MISSING",
            "语义附件编制已启用，但当前 provider 未配置 API key",
        )


__all__ = [
    "ATTACHMENT_COMPOSER_PROMPT_VERSION",
    "ATTACHMENT_COMPOSITION_POLICY_VERSION",
    "SemanticCompositionError",
    "StructuredAttachmentComposer",
    "build_attachment_model_manifest",
    "build_frozen_attachment_composer",
    "require_attachment_model_credentials",
    "validate_frozen_model_manifest",
]
