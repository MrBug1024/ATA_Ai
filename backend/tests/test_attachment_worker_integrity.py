from __future__ import annotations

from copy import deepcopy
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_hunter.annual_audit.attachments import repository, worker_pipeline
from ai_hunter.annual_audit.attachments.content_schemas import RenderResult
from ai_hunter.annual_audit.attachments.context_service import (
    build_generation_context_snapshot,
)
from ai_hunter.annual_audit.attachments.quality_service import QualityReport
from ai_hunter.annual_audit.attachments.worker_pipeline import (
    AttachmentWorkerError,
    _assert_item_identity,
    _assert_template_snapshot_integrity,
)
from ai_hunter.document_templates.integrity import stable_template_content_hash


def _binding_manifest() -> dict:
    return {
        "document_code": "audit_report",
        "source_template_sha256": "a" * 64,
        "slots": [
            {
                "slot_id": "title",
                "target": "md:variable:title",
                "source": "document.report.title",
                "value_type": "scalar",
                "required": True,
            }
        ],
    }


def _snapshot() -> dict:
    return {
        "business_type": "annual_audit",
        "contract_version": "1.0",
        "manifest": {"locale": "zh-CN"},
        "files": [
            {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "document_code": "audit_report",
                "display_name": "Audit report",
                "extension": ".md",
                "source_sha256": "a" * 64,
                "compiled_sha256": "b" * 64,
                "renderer_profile": "jinja_sandbox",
                "binding_manifest": _binding_manifest(),
                "sort_order": 0,
            }
        ],
    }


def _item() -> dict:
    return {
        "document_code": "audit_report",
        "extension": ".md",
        "source_template_sha256": "a" * 64,
        "compiled_template_sha256": "b" * 64,
        "binding_manifest": _binding_manifest(),
    }


def test_worker_rejects_template_snapshot_whose_activation_hash_changed() -> None:
    snapshot = _snapshot()
    job = {"template_content_sha256": stable_template_content_hash(snapshot)}
    _assert_template_snapshot_integrity(job, snapshot)

    tampered = deepcopy(snapshot)
    tampered["files"][0]["display_name"] = "Tampered"
    with pytest.raises(AttachmentWorkerError) as raised:
        _assert_template_snapshot_integrity(job, tampered)

    assert raised.value.code == "TEMPLATE_SNAPSHOT_SHA_MISMATCH"
    assert raised.value.stage == "freezing_context"


def test_worker_requires_item_manifest_to_match_frozen_snapshot_canonically() -> None:
    snapshot_file = _snapshot()["files"][0]
    item = _item()
    item["binding_manifest"] = {
        key: item["binding_manifest"][key]
        for key in reversed(list(item["binding_manifest"]))
    }
    _assert_item_identity(item, snapshot_file)

    item["binding_manifest"]["slots"][0]["source"] = "document.entity.legal_name"
    with pytest.raises(AttachmentWorkerError) as raised:
        _assert_item_identity(item, snapshot_file)

    assert raised.value.code == "TEMPLATE_BINDING_MANIFEST_MISMATCH"
    assert raised.value.stage == "freezing_context"


def _worker_context():
    return build_generation_context_snapshot(
        engagement={"engagement_id": 7, "project_name": "Audit Project"},
        report={"id": 8, "version": 1, "fact_snapshot": {}},
        generation_policy_version="annual-attachment-v1",
    )


def _process_inputs(*, manifest: dict, source: bytes, compiled: bytes):
    job_id = str(uuid4())
    item_id = str(uuid4())
    template_file_id = str(uuid4())
    return (
        {
            "id": job_id,
            "engagement_id": 7,
            "report_id": 8,
            "template_version_id": str(uuid4()),
            "model_manifest": {"mode": "deterministic"},
            "renderer_manifest": {},
            "delivery_level": "review_draft",
            "requested_by": "tester",
        },
        {
            "id": item_id,
            "template_file_id": template_file_id,
            "document_code": manifest["document_code"],
            "display_name": "Audit output",
            "extension": ".md",
            "source_template_sha256": hashlib.sha256(source).hexdigest(),
            "compiled_template_sha256": hashlib.sha256(compiled).hexdigest(),
            "binding_manifest": manifest,
        },
        {
            "id": template_file_id,
            "source_object_ref": "minio://templates/source",
            "compiled_object_ref": "minio://templates/compiled",
            "renderer_profile": "jinja_sandbox",
        },
    )


def test_worker_uses_frozen_composer_for_semantic_item(monkeypatch) -> None:
    source = b"semantic source"
    compiled = b"semantic compiled"
    manifest = {
        "document_code": "audit_report",
        "source_template_sha256": hashlib.sha256(source).hexdigest(),
        "slots": [
            {
                "slot_id": "overview",
                "target": "md:section:overview",
                "value_type": "narrative_blocks",
                "required": True,
                "missing_policy": "block",
                "options": {
                    "composition_mode": "semantic",
                    "semantic_instruction": "按批准标签编排简短陈述",
                    "allowed_fact_refs": ["entity.legal_name"],
                    "fact_ref_labels": {"entity.legal_name": "企业名称"},
                },
            }
        ],
    }
    job, item, template_file = _process_inputs(
        manifest=manifest,
        source=source,
        compiled=compiled,
    )
    job["model_manifest"] = {
        "mode": "semantic_opt_in",
        "provider": "fake",
        "model": "frozen-model",
    }
    sentinel_composer = object()
    captured = {}

    class _Minio:
        def get_object_bytes(self, ref: str) -> bytes:
            return compiled if ref.endswith("compiled") else source

    class _PreparedReached(RuntimeError):
        pass

    def fake_prepare(_manifest, _context, _registry, *, composer=None, **_kwargs):
        captured["composer"] = composer
        raise _PreparedReached

    monkeypatch.setattr(worker_pipeline, "get_minio_service", lambda: _Minio())
    monkeypatch.setattr(
        worker_pipeline,
        "build_frozen_attachment_composer",
        lambda **_kwargs: sentinel_composer,
    )
    monkeypatch.setattr(worker_pipeline, "prepare_attachment", fake_prepare)

    with pytest.raises(_PreparedReached):
        worker_pipeline._process_item(
            job=job,
            item=item,
            template_file=template_file,
            context=_worker_context(),
            lease_token=str(uuid4()),
            settings=object(),  # type: ignore[arg-type]
        )
    assert captured["composer"] is sentinel_composer


def test_lease_loss_cleans_only_current_lease_uploads(monkeypatch) -> None:
    source = b"markdown source"
    compiled = b"{{ title }}"
    manifest = {
        "document_code": "audit_report",
        "source_template_sha256": hashlib.sha256(source).hexdigest(),
        "slots": [
            {
                "slot_id": "title",
                "target": "md:variable:title",
                "source": "document.engagement.project_name",
                "value_type": "scalar",
                "required": True,
                "missing_policy": "block",
            }
        ],
    }
    job, item, template_file = _process_inputs(
        manifest=manifest,
        source=source,
        compiled=compiled,
    )
    lease_token = str(uuid4())
    uploads: list[tuple[str, str, str]] = []
    deleted: list[str] = []

    class _Minio:
        def get_object_bytes(self, ref: str) -> bytes:
            return compiled if ref.endswith("compiled") else source

        def upload_attachment_blob(self, *, category: str, blob_id: str, **_kwargs):
            ref = f"minio://artifacts/{category}/{blob_id}"
            uploads.append((category, blob_id, ref))
            return SimpleNamespace(storage_ref=ref)

        def upload_derived_blob(self, *, blob_id: str, **_kwargs):
            ref = f"minio://derived/preview/{blob_id}"
            uploads.append(("preview", blob_id, ref))
            return SimpleNamespace(storage_ref=ref)

        def delete_object(self, ref: str) -> None:
            deleted.append(ref)

    minio = _Minio()
    rendered = b"Rendered attachment"
    quality = QualityReport(
        passed=True,
        file_name="audit.md",
        extension=".md",
        artifact_sha256=hashlib.sha256(rendered).hexdigest(),
        extracted_text_sha256=hashlib.sha256(rendered).hexdigest(),
    )

    monkeypatch.setattr(worker_pipeline, "get_minio_service", lambda: minio)
    monkeypatch.setitem(
        worker_pipeline.RENDERERS,
        ".md",
        lambda _bytes, _payload, execution_manifest: RenderResult(
            data=rendered,
            extension=".md",
            content_type="text/markdown; charset=utf-8",
            source_template_sha256=execution_manifest.source_template_sha256,
        ),
    )
    monkeypatch.setattr(
        worker_pipeline,
        "validate_rendered_artifact",
        lambda *_args, **_kwargs: quality,
    )
    monkeypatch.setattr(worker_pipeline, "require_quality", lambda report: report)
    monkeypatch.setattr(
        worker_pipeline,
        "convert_to_pdf",
        lambda **_kwargs: b"%PDF-current-lease",
    )

    def lose_lease(**_kwargs):
        raise repository.AttachmentStateError("lease changed")

    monkeypatch.setattr(worker_pipeline.repository, "complete_item", lose_lease)

    with pytest.raises(repository.AttachmentStateError):
        worker_pipeline._process_item(
            job=job,
            item=item,
            template_file=template_file,
            context=_worker_context(),
            lease_token=lease_token,
            settings=object(),  # type: ignore[arg-type]
        )

    assert [category for category, _blob_id, _ref in uploads] == [
        "payloads",
        "artifacts",
        "preview",
        "manifests",
    ]
    assert all(blob_id.endswith(lease_token) for _category, blob_id, _ref in uploads)
    assert set(deleted) == {ref for _category, _blob_id, ref in uploads}
    assert "minio://artifacts/artifacts/newer-lease-object" not in deleted
