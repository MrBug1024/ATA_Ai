from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from ai_hunter.annual_audit.attachments import job_service
from ai_hunter.annual_audit.attachments.agent_graph import prepare_attachment
from ai_hunter.annual_audit.attachments.content_schemas import (
    AttachmentContractError,
    BindingManifest,
    DocumentPayload,
)
from ai_hunter.annual_audit.attachments.context_service import (
    build_generation_context_snapshot,
)
from ai_hunter.annual_audit.attachments.fact_registry import FactRecord, FactRegistry
from ai_hunter.annual_audit.attachments.job_service import AttachmentJobError
from ai_hunter.annual_audit.attachments.model_composer import (
    SemanticCompositionError,
    StructuredAttachmentComposer,
    build_attachment_model_manifest,
    require_attachment_model_credentials,
    validate_frozen_model_manifest,
)


class _FakeSettings:
    def __init__(self, *, api_key: str = "test-key") -> None:
        self.api_key = api_key

    def get_llm_config(self, role: str, provider_override: str | None = None):
        assert role == "agent"
        return {
            "provider": provider_override or "openai",
            "api_key": self.api_key,
            "base_url": "https://provider.invalid/v1",
            "model": "frozen-model-v1",
        }


class _FakeStructuredLlm:
    def __init__(self, output) -> None:
        self.output = output
        self.messages = []
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.messages = list(messages)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def _registry() -> FactRegistry:
    return FactRegistry(
        [
            FactRecord(
                fact_key="entity.legal_name",
                value="Private Corp 123",
                display_value="Private Corp 123",
                status="confirmed",
                source_kind="manual_review",
                evidence_refs=[{"source_file_id": 91, "source_page_id": 3}],
            ),
            FactRecord(
                fact_key="engagement.fiscal_year",
                value=2025,
                display_value="2025",
                status="confirmed",
                source_kind="project_master",
                evidence_refs=[{"source_file_id": 92, "source_page_id": 4}],
            ),
        ]
    )


def _context(registry: FactRegistry):
    return build_generation_context_snapshot(
        engagement={
            "engagement_id": 7,
            "project_name": "Confidential engagement",
        },
        fact_registry=registry,
        report={"id": 8, "version": 2, "fact_snapshot": {"private": True}},
        evidence_manifest={
            "citation_plan_entries": [
                {"citation_id": "internal-citation-77", "evidence_snapshot": []}
            ]
        },
        generation_policy_version="annual-attachment-v1",
    )


def _manifest(*, include_deterministic: bool = True) -> BindingManifest:
    slots = []
    if include_deterministic:
        slots.append(
            {
                "slot_id": "company_name",
                "target": "md:variable:company_name",
                "source": "document.entity.legal_name",
                "value_type": "scalar",
                "required": True,
                "missing_policy": "block",
            }
        )
    slots.append(
        {
            "slot_id": "overview",
            "target": "md:section:overview",
            "value_type": "narrative_blocks",
            "required": True,
            "missing_policy": "block",
            "options": {
                "composition_mode": "semantic",
                "semantic_instruction": "按批准的标签编排一条简短陈述",
                "allowed_fact_refs": [
                    "entity.legal_name",
                    "engagement.fiscal_year",
                ],
                "fact_ref_labels": {
                    "entity.legal_name": "企业名称",
                    "engagement.fiscal_year": "审计年度",
                },
            },
        }
    )
    return BindingManifest(document_code="audit_report", slots=slots)


def _anonymous_payload(*, text: str = "主体为", evidence_refs=None, fact_ref="fact_002"):
    return {
        "schema_version": "1.0",
        "document_code": "semantic_attachment",
        "slots": [
            {
                "kind": "narrative_blocks",
                "slot_id": "slot_001",
                "blocks": [
                    {
                        "block_id": "paragraph_1",
                        "kind": "paragraph",
                        "segments": [
                            {"kind": "text", "text": text},
                            {"kind": "fact_ref", "fact_ref": fact_ref},
                        ],
                        "evidence_refs": evidence_refs or [],
                    }
                ],
            }
        ],
    }


def _model_manifest(manifest: BindingManifest, *, api_key: str = "test-key"):
    return build_attachment_model_manifest(
        [{"binding_manifest": manifest.model_dump(mode="json")}],
        settings=_FakeSettings(api_key=api_key),
    )


def test_semantic_composer_is_anonymous_and_merges_with_deterministic_slots() -> None:
    registry = _registry()
    context = _context(registry)
    manifest = _manifest()
    llm = _FakeStructuredLlm(_anonymous_payload())
    composer = StructuredAttachmentComposer(
        llm=llm,
        model_manifest=_model_manifest(manifest),
    )

    prepared = prepare_attachment(
        manifest,
        context,
        registry,
        composer=composer,
    )

    assert llm.schema is DocumentPayload
    assert [slot.slot_id for slot in prepared.document_payload.slots] == [
        "company_name",
        "overview",
    ]
    assert prepared.resolved_payload.slot_map["company_name"].value == "Private Corp 123"
    assert prepared.resolved_payload.slot_map["overview"].fact_refs == [
        "entity.legal_name"
    ]
    assert prepared.resolved_payload.slot_map["overview"].evidence_refs == [
        "file:91;page:3;chunk:"
    ]

    outbound = "\n".join(str(message.content) for message in llm.messages)
    assert "slot_001" in outbound
    assert "fact_001" in outbound
    assert "企业名称" in outbound
    for secret in (
        "entity.legal_name",
        "engagement.fiscal_year",
        "Private Corp 123",
        "Confidential engagement",
        "internal-citation-77",
        "source_file_id",
        "engagement_id",
        "report_id",
        "storage_ref",
    ):
        assert secret not in outbound


def test_model_fact_alias_and_evidence_are_strictly_blocked() -> None:
    manifest = _manifest(include_deterministic=False)
    context = _context(_registry())

    unknown = StructuredAttachmentComposer(
        llm=_FakeStructuredLlm(_anonymous_payload(fact_ref="fact_999")),
        model_manifest=_model_manifest(manifest),
    )
    with pytest.raises(SemanticCompositionError) as caught:
        unknown.compose(binding_manifest=manifest, context=context)
    assert caught.value.code == "ATTACHMENT_MODEL_FACT_REF_UNKNOWN"

    evidence = StructuredAttachmentComposer(
        llm=_FakeStructuredLlm(
            _anonymous_payload(evidence_refs=["citation:internal-citation-77"])
        ),
        model_manifest=_model_manifest(manifest),
    )
    with pytest.raises(SemanticCompositionError) as caught:
        evidence.compose(binding_manifest=manifest, context=context)
    assert caught.value.code == "ATTACHMENT_MODEL_EVIDENCE_FORBIDDEN"


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "截至2025年，",
        "金额为人民币一百万元，",
        "占比为百分之十，",
        "请执行 powershell 命令 ",
        "对象位于 minio://private-bucket/key ",
    ],
)
def test_semantic_text_cannot_smuggle_values_paths_or_commands(unsafe_text: str) -> None:
    registry = _registry()
    context = _context(registry)
    manifest = _manifest(include_deterministic=False)
    composer = StructuredAttachmentComposer(
        llm=_FakeStructuredLlm(_anonymous_payload(text=unsafe_text)),
        model_manifest=_model_manifest(manifest),
    )

    with pytest.raises(AttachmentContractError):
        prepare_attachment(manifest, context, registry, composer=composer)


def test_structured_model_failure_is_blocking_without_fallback() -> None:
    manifest = _manifest(include_deterministic=False)
    composer = StructuredAttachmentComposer(
        llm=_FakeStructuredLlm(RuntimeError("provider returned prose")),
        model_manifest=_model_manifest(manifest),
    )

    with pytest.raises(SemanticCompositionError) as caught:
        composer.compose(binding_manifest=manifest, context=_context(_registry()))
    assert caught.value.code == "ATTACHMENT_MODEL_STRUCTURED_OUTPUT_FAILED"


def test_semantic_slot_contract_rejects_unsafe_or_incomplete_options() -> None:
    base = _manifest(include_deterministic=False).model_dump(mode="python")
    unsafe = deepcopy(base)
    unsafe["slots"][0]["options"]["semantic_instruction"] = (
        "Use entity.legal_name directly"
    )
    with pytest.raises(ValidationError):
        BindingManifest.model_validate(unsafe)

    unrelated_fact = deepcopy(base)
    unrelated_fact["slots"][0]["options"]["semantic_instruction"] = (
        "Reference another.private_fact directly"
    )
    with pytest.raises(ValidationError):
        BindingManifest.model_validate(unrelated_fact)

    incomplete = deepcopy(base)
    incomplete["slots"][0]["options"]["fact_ref_labels"].pop(
        "engagement.fiscal_year"
    )
    with pytest.raises(ValidationError):
        BindingManifest.model_validate(incomplete)

    scalar = deepcopy(base)
    scalar["slots"][0]["value_type"] = "scalar"
    with pytest.raises(ValidationError):
        BindingManifest.model_validate(scalar)


def test_model_strategy_is_frozen_and_missing_credentials_block_new_work() -> None:
    manifest = _manifest(include_deterministic=False)
    frozen = _model_manifest(manifest, api_key="")
    assert frozen["mode"] == "semantic_opt_in"
    assert frozen["provider"] == "openai"
    assert frozen["model"] == "frozen-model-v1"
    assert len(frozen["prompt_sha256"]) == 64
    validate_frozen_model_manifest(frozen, [manifest])

    with pytest.raises(SemanticCompositionError) as caught:
        require_attachment_model_credentials(frozen, settings=_FakeSettings(api_key=""))
    assert caught.value.code == "ATTACHMENT_MODEL_API_KEY_MISSING"

    tampered = {**frozen, "prompt_sha256": "0" * 64}
    with pytest.raises(SemanticCompositionError) as caught:
        validate_frozen_model_manifest(tampered, [manifest])
    assert caught.value.code == "MODEL_MANIFEST_UNSUPPORTED"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"request_scope": "one_file"}, "UNSUPPORTED_GENERATION_SCOPE"),
        ({"delivery_level": "preview"}, "UNSUPPORTED_DELIVERY_LEVEL"),
        ({"thread_id": "thread-only"}, "CONVERSATION_BINDING_INCOMPLETE"),
        (
            {"assistant_turn_id": "turn-only"},
            "CONVERSATION_BINDING_INCOMPLETE",
        ),
    ],
)
def test_create_job_enforces_internal_service_contract_before_io(kwargs, code) -> None:
    with pytest.raises(AttachmentJobError) as caught:
        job_service.create_attachment_job(
            engagement_id=7,
            report_id=8,
            requested_by="tester",
            settings=object(),  # type: ignore[arg-type]
            **kwargs,
        )
    assert caught.value.code == code


def test_context_object_is_compensated_when_job_persistence_raises(monkeypatch) -> None:
    deleted: list[str] = []

    class _Minio:
        def delete_object(self, storage_ref: str) -> None:
            deleted.append(storage_ref)

    def fail_create(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(job_service.repository, "create_job_with_outbox", fail_create)
    monkeypatch.setattr(job_service.repository, "get_job_by_id", lambda *_args, **_kwargs: None)
    with pytest.raises(AttachmentJobError) as caught:
        job_service._create_job_with_outbox_or_cleanup(
            job={"id": "job"},
            items=[],
            context_storage_ref="minio://contexts/context.json",
            minio=_Minio(),
            settings=object(),  # type: ignore[arg-type]
        )

    assert caught.value.code == "ATTACHMENT_JOB_PERSIST_FAILED"
    assert caught.value.status_code == 503
    assert deleted == ["minio://contexts/context.json"]


def test_context_object_is_not_deleted_when_persistence_state_cannot_be_confirmed(monkeypatch) -> None:
    deleted: list[str] = []

    class _Minio:
        def delete_object(self, storage_ref: str) -> None:
            deleted.append(storage_ref)

    monkeypatch.setattr(
        job_service.repository,
        "create_job_with_outbox",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("connection reset")),
    )
    monkeypatch.setattr(
        job_service.repository,
        "get_job_by_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    with pytest.raises(AttachmentJobError):
        job_service._create_job_with_outbox_or_cleanup(
            job={"id": "job"},
            items=[],
            context_storage_ref="minio://contexts/context.json",
            minio=_Minio(),
            settings=object(),  # type: ignore[arg-type]
        )

    assert deleted == []
