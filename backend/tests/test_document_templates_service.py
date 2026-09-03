from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from ai_hunter.document_templates.compiler.models import sha256_bytes
from ai_hunter.document_templates.repository import (
    TemplateRevisionConflictError,
    TemplateValidationStateError,
)
from ai_hunter.document_templates.service import (
    DocumentTemplateService,
    TemplateStorageError,
)


class UploadResult:
    def __init__(self, storage_ref: str) -> None:
        self.storage_ref = storage_ref


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.counter = 0

    def upload_template(self, *, variant: str, file_bytes: bytes, **_) -> UploadResult:
        self.counter += 1
        storage_ref = f"minio://templates/{variant}/{self.counter}"
        self.objects[storage_ref] = file_bytes
        return UploadResult(storage_ref)

    def get_object_bytes(self, storage_ref: str) -> bytes:
        return self.objects[storage_ref]

    def delete_object(self, storage_ref: str) -> bool:
        self.deleted.append(storage_ref)
        self.objects.pop(storage_ref, None)
        return True


class MemoryRepository:
    def __init__(self) -> None:
        self.family_id = uuid4()
        self.version_id = uuid4()
        self.version = {
            "id": self.version_id,
            "family_id": self.family_id,
            "business_type": "annual_audit",
            "scope_type": "system",
            "scope_key": "system",
            "version_no": 1,
            "version_label": "v1",
            "name": "Annual audit",
            "description": "",
            "status": "draft",
            "contract_version": "1.0",
            "manifest": {},
            "content_sha256": "",
            "validation_report": {},
            "revision": 1,
            "family_revision": 1,
            "active": False,
            "files": [],
        }
        self.files: dict[object, dict] = {}
        self.fail_add = False
        self.fail_compilation = False
        self.validation_call: dict | None = None
        self.activation_call: dict | None = None
        self.active_snapshot: dict | None = None

    def get_version(self, version_id, *, include_files: bool = True) -> dict:
        assert str(version_id) == str(self.version_id)
        result = deepcopy(self.version)
        result["files"] = [deepcopy(item) for item in self.files.values()] if include_files else []
        return result

    def get_file(self, file_id) -> dict:
        return deepcopy(self.files[file_id])

    def add_file(self, record: dict, *, actor: str) -> dict:
        if self.fail_add:
            raise TemplateRevisionConflictError("simulated conflict")
        stored = {
            **deepcopy(record),
            "revision": 1,
            "compiled_object_ref": "",
            "compiled_sha256": "",
            "renderer_profile": "",
            "binding_manifest": {},
            "preview_object_ref": "",
            "preview_sha256": "",
            "created_by": actor,
            "updated_by": actor,
        }
        self.files[stored["id"]] = stored
        self.version["revision"] += 1
        return deepcopy(stored)

    def record_compilation(self, file_id, *, actor: str, **values) -> dict:
        if self.fail_compilation:
            raise TemplateRevisionConflictError("simulated conflict")
        stored = self.files[file_id]
        stored.update(values)
        stored["status"] = "ready"
        stored["revision"] += 1
        stored["updated_by"] = actor
        self.version["revision"] += 1
        return deepcopy(stored)

    def record_validation(self, version_id, **values) -> dict:
        self.validation_call = deepcopy(values)
        self.version["validation_report"] = deepcopy(values["validation_report"])
        self.version["content_sha256"] = values["content_sha256"] if values["passed"] else ""
        self.version["status"] = "ready" if values["passed"] else "draft"
        self.version["revision"] += 1
        return self.get_version(version_id)

    def set_activation(self, version_id, **values) -> dict:
        self.activation_call = deepcopy(values)
        return self.get_version(version_id)

    def get_active_template_snapshot(self, business_type: str) -> dict | None:
        return deepcopy(self.active_snapshot)


@pytest.fixture
def settings() -> SimpleNamespace:
    return SimpleNamespace(
        attachment_template_max_mb=10,
        attachment_zip_max_entries=2_000,
        attachment_zip_max_uncompressed_mb=100,
        attachment_zip_max_entry_mb=20,
        attachment_zip_max_ratio=100,
        attachment_xml_max_mb=20,
        attachment_clamav_host="",
        attachment_clamav_port=3310,
        attachment_clamav_timeout_seconds=1,
        attachment_clamav_required=False,
        attachment_gotenberg_url="",
        attachment_gotenberg_timeout_seconds=10,
        attachment_preview_required=False,
        attachment_renderer_image_digest="renderer@sha256:test",
        attachment_font_manifest_version="fonts-v1",
    )


def _service(settings):
    repository = MemoryRepository()
    storage = MemoryStorage()
    return DocumentTemplateService(repository, storage, settings), repository, storage


def _manifest() -> dict:
    return {
        "document_code": "audit_report",
        "slots": [
            {
                "slot_id": "title",
                "target": "md:jinja:title",
                "source": "document.title",
                "value_type": "scalar",
                "required": True,
            }
        ],
    }


def _upload_markdown(service, repository) -> dict:
    return service.upload_file(
        repository.version_id,
        file_name="audit.md",
        content_type="text/markdown",
        file_bytes=b"Audit: {{ title }}",
        document_code="audit_report",
        display_name="Audit report",
        sort_order=0,
        actor="superadmin",
    )


def _valid_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    return output.getvalue()


def test_upload_compensates_storage_when_repository_rejects(settings) -> None:
    service, repository, storage = _service(settings)
    repository.fail_add = True
    with pytest.raises(TemplateRevisionConflictError):
        _upload_markdown(service, repository)
    assert storage.deleted == ["minio://templates/source/1"]
    assert not storage.objects


def test_compile_compensates_new_objects_on_revision_conflict(settings) -> None:
    service, repository, storage = _service(settings)
    uploaded = _upload_markdown(service, repository)
    repository.fail_compilation = True
    with pytest.raises(TemplateRevisionConflictError):
        service.compile_file(
            uploaded["id"],
            revision=uploaded["revision"],
            binding_manifest=_manifest(),
            actor="superadmin",
        )
    assert "minio://templates/compiled/2" in storage.deleted
    assert "minio://templates/source/1" in storage.objects


def test_validation_allows_activation_when_optional_previews_are_unavailable(settings) -> None:
    service, repository, storage = _service(settings)
    uploaded = _upload_markdown(service, repository)
    compiled = service.compile_file(
        uploaded["id"],
        revision=uploaded["revision"],
        binding_manifest=_manifest(),
        actor="superadmin",
    )
    validated = service.validate_version(
        repository.version_id,
        revision=repository.version["revision"],
        actor="superadmin",
    )
    report = repository.validation_call["validation_report"]
    assert compiled["preview_object_ref"] == ""
    assert report["passed"] is True
    assert report["files"][0]["passed"] is True
    assert {item["code"] for item in report["warnings"]} >= {
        "PREVIEW_MISSING",
        "PREVIEW_RENDERER_UNAVAILABLE",
    }
    assert report["renderer_image_digest"] == "renderer@sha256:test"
    assert "object_ref" not in str(report)
    assert validated["status"] == "ready"
    assert compiled["binding_manifest"]["binding_sha256"]


def test_validation_passes_with_frozen_and_current_previews(settings, monkeypatch) -> None:
    service, repository, _ = _service(settings)
    preview = _valid_pdf()
    monkeypatch.setattr(service, "_preview_bytes", lambda _record, _compiled: preview)
    uploaded = _upload_markdown(service, repository)
    compiled = service.compile_file(
        uploaded["id"],
        revision=uploaded["revision"],
        binding_manifest=_manifest(),
        actor="superadmin",
    )

    validated = service.validate_version(
        repository.version_id,
        revision=repository.version["revision"],
        actor="superadmin",
    )

    report = repository.validation_call["validation_report"]
    assert compiled["preview_object_ref"]
    assert report["passed"] is True
    assert report["files"][0]["passed"] is True
    assert not {
        item["code"] for item in report["blockers"]
    } & {"PREVIEW_MISSING", "PREVIEW_RENDERER_REQUIRED"}
    assert validated["status"] == "ready"


def test_activation_does_not_require_preview_or_renderer_confirmation(settings) -> None:
    service, repository, _ = _service(settings)
    repository.version.update(
        {
            "status": "ready",
            "revision": 3,
            "content_sha256": "a" * 64,
            "validation_report": {
                "passed": True,
                "content_sha256": "a" * 64,
                "renderer_image_digest": "old-renderer",
                "font_manifest_version": "fonts-v1",
            },
        }
    )
    service.set_activation(
        repository.version_id,
        revision=3,
        active=True,
        actor="superadmin",
    )
    assert repository.activation_call == {
        "revision": 3,
        "active": True,
        "actor": "superadmin",
    }


def test_activation_keeps_content_validation_as_the_gate(settings) -> None:
    service, repository, _ = _service(settings)
    repository.version.update(
        {
            "status": "ready",
            "revision": 3,
            "content_sha256": "a" * 64,
            "validation_report": {
                "passed": False,
                "content_sha256": "a" * 64,
            },
        }
    )

    with pytest.raises(TemplateValidationStateError, match="content validation"):
        service.set_activation(
            repository.version_id,
            revision=3,
            active=True,
            actor="superadmin",
        )
    assert repository.activation_call is None


def test_internal_active_snapshot_has_stable_ids_and_internal_refs(settings) -> None:
    service, repository, _ = _service(settings)
    file_id = uuid4()
    repository.active_snapshot = {
        "family_id": repository.family_id,
        "business_type": "annual_audit",
        "scope_type": "system",
        "scope_key": "system",
        "family_revision": 4,
        "version_id": repository.version_id,
        "version_no": 2,
        "version_label": "v2",
        "version_revision": 8,
        "contract_version": "1.0",
        "content_sha256": "b" * 64,
        "manifest": {},
        "validation_report": {"passed": True},
        "files": [
            {
                "id": file_id,
                "document_code": "audit_report",
                "display_name": "Audit report",
                "source_file_name": "audit.md",
                "extension": ".md",
                "content_type": "text/markdown",
                "size_bytes": 10,
                "source_object_ref": "minio://templates/source/x",
                "source_sha256": "c" * 64,
                "compiled_object_ref": "minio://templates/compiled/x",
                "compiled_sha256": "d" * 64,
                "renderer_profile": "jinja_sandbox",
                "binding_manifest": _manifest(),
                "preview_object_ref": "",
                "preview_sha256": "",
                "sort_order": 0,
                "revision": 2,
            }
        ],
    }
    snapshot = service.get_active_template_snapshot("annual_audit")
    assert snapshot["version_id"] == str(repository.version_id)
    assert snapshot["version_revision"] == 8
    assert snapshot["files"][0]["id"] == str(file_id)
    assert snapshot["files"][0]["compiled_object_ref"].startswith("minio://")


def test_preview_detects_storage_tampering(settings) -> None:
    service, repository, storage = _service(settings)
    file_id = uuid4()
    preview_ref = "minio://templates/preview/x"
    storage.objects[preview_ref] = b"%PDF-tampered"
    repository.files[file_id] = {
        "id": file_id,
        "source_file_name": "audit.docx",
        "preview_object_ref": preview_ref,
        "preview_sha256": sha256_bytes(b"different"),
    }
    with pytest.raises(TemplateStorageError):
        service.get_preview(file_id)
