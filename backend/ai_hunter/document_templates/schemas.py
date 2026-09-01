"""Typed HTTP and service contracts for document template governance."""

from __future__ import annotations

import re
import math
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


BUSINESS_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
DOCUMENT_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,127}$")


def _bounded_text(value: str | None, *, field: str, limit: int, required: bool = False) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > limit:
        raise ValueError(f"{field} must not exceed {limit} characters")
    return normalized


def _bounded_json(value: dict[str, Any], *, field: str) -> dict[str, Any]:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > 50_000 or depth > 24:
            raise ValueError(f"{field} is too deeply nested or contains too many values")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 512:
                    raise ValueError(f"{field} contains an invalid object key")
                string_bytes += len(key.encode("utf-8"))
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            string_bytes += len(item.encode("utf-8"))
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError(f"{field} contains a non-finite number")
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError(f"{field} must contain JSON-compatible values")
        if string_bytes > 2 * 1024 * 1024:
            raise ValueError(f"{field} exceeds the text size limit")
    return value


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateBusinessType(BaseModel):
    code: str
    label: str
    generator_enabled: bool = False
    supported_formats: list[str] = Field(default_factory=list)
    required_profile: list[str] = Field(default_factory=list)


class TemplateBusinessTypeListResponse(BaseModel):
    items: list[TemplateBusinessType] = Field(default_factory=list)


class TemplateVersionCreateRequest(StrictRequest):
    business_type: str
    name: str
    description: str = ""
    scope_type: str = "system"
    scope_key: str = "system"

    @field_validator("business_type")
    @classmethod
    def validate_business_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not BUSINESS_TYPE_PATTERN.fullmatch(normalized):
            raise ValueError("business_type must be a stable lowercase code")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _bounded_text(value, field="name", limit=255, required=True)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _bounded_text(value, field="description", limit=4000)

    @field_validator("scope_type")
    @classmethod
    def validate_scope_type(cls, value: str) -> str:
        normalized = _bounded_text(value, field="scope_type", limit=32, required=True)
        if normalized != "system":
            raise ValueError("only system-scoped templates are enabled")
        return normalized

    @field_validator("scope_key")
    @classmethod
    def validate_scope_key(cls, value: str) -> str:
        normalized = _bounded_text(value, field="scope_key", limit=128, required=True)
        if normalized != "system":
            raise ValueError("only system-scoped templates are enabled")
        return normalized


class TemplateVersionUpdateRequest(StrictRequest):
    revision: int = Field(gt=0)
    name: str | None = None
    description: str | None = None
    manifest: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_text(value, field="name", limit=255, required=True)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_text(value, field="description", limit=4000)

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.description is None and self.manifest is None:
            raise ValueError("at least one mutable field is required")
        return self

    @field_validator("manifest")
    @classmethod
    def validate_manifest(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if value is None else _bounded_json(value, field="manifest")


class TemplateVersionCloneRequest(StrictRequest):
    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_text(value, field="name", limit=255, required=True)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_text(value, field="description", limit=4000)


class RevisionRequest(StrictRequest):
    revision: int = Field(gt=0)


class TemplatePreviewConfirmation(StrictRequest):
    file_id: UUID
    preview_sha256: str

    @field_validator("preview_sha256")
    @classmethod
    def validate_preview_sha256(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("preview_sha256 must contain 64 lowercase hex characters")
        return normalized


class TemplateActivationRequest(RevisionRequest):
    active: bool
    preview_confirmations: list[TemplatePreviewConfirmation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_preview_confirmations(self):
        if self.active and not self.preview_confirmations:
            raise ValueError("preview_confirmations are required when activating a template")
        if not self.active and self.preview_confirmations:
            raise ValueError("preview_confirmations are only accepted when activating a template")
        file_ids = [item.file_id for item in self.preview_confirmations]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("preview_confirmations must contain unique file_id values")
        return self


class TemplateFileUpdateRequest(StrictRequest):
    revision: int = Field(gt=0)
    document_code: str | None = None
    display_name: str | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    binding_manifest: dict[str, Any] | None = None

    @field_validator("document_code")
    @classmethod
    def validate_document_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not DOCUMENT_CODE_PATTERN.fullmatch(normalized):
            raise ValueError("document_code must be a stable lowercase code")
        return normalized

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_text(value, field="display_name", limit=255, required=True)

    @model_validator(mode="after")
    def require_change(self):
        if (
            self.document_code is None
            and self.display_name is None
            and self.sort_order is None
            and self.binding_manifest is None
        ):
            raise ValueError("at least one mutable field is required")
        return self

    @field_validator("binding_manifest")
    @classmethod
    def validate_binding_manifest(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        return None if value is None else _bounded_json(value, field="binding_manifest")


class TemplateCompileRequest(RevisionRequest):
    binding_manifest: dict[str, Any]

    @field_validator("binding_manifest")
    @classmethod
    def validate_binding_manifest(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, field="binding_manifest")


class TemplateFileResponse(BaseModel):
    id: UUID
    template_version_id: UUID
    document_code: str
    display_name: str
    source_file_name: str
    extension: str
    content_type: str
    size_bytes: int
    source_sha256: str
    compiled_sha256: str = ""
    renderer_profile: str = ""
    binding_manifest: dict[str, Any] = Field(default_factory=dict)
    inspection_report: dict[str, Any] = Field(default_factory=dict)
    preview_available: bool = False
    preview_sha256: str = ""
    status: str
    sort_order: int = 0
    revision: int
    created_by: str = ""
    updated_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TemplateVersionResponse(BaseModel):
    id: UUID
    family_id: UUID
    business_type: str
    scope_type: str = "system"
    scope_key: str = "system"
    version_no: int
    version_label: str
    name: str
    description: str = ""
    status: str
    contract_version: str = "1.0"
    manifest: dict[str, Any] = Field(default_factory=dict)
    content_sha256: str = ""
    validation_report: dict[str, Any] = Field(default_factory=dict)
    revision: int
    family_revision: int = 1
    active: bool = False
    file_count: int = 0
    ready_file_count: int = 0
    created_by: str = ""
    updated_by: str = ""
    activated_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    activated_at: datetime | None = None
    archived_at: datetime | None = None
    files: list[TemplateFileResponse] = Field(default_factory=list)


class TemplateVersionListResponse(BaseModel):
    items: list[TemplateVersionResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class TemplateDeleteResponse(BaseModel):
    deleted: bool = True
    id: UUID


__all__ = [
    "BUSINESS_TYPE_PATTERN",
    "DOCUMENT_CODE_PATTERN",
    "RevisionRequest",
    "TemplateActivationRequest",
    "TemplateBusinessType",
    "TemplateBusinessTypeListResponse",
    "TemplateCompileRequest",
    "TemplateDeleteResponse",
    "TemplateFileResponse",
    "TemplateFileUpdateRequest",
    "TemplatePreviewConfirmation",
    "TemplateVersionCloneRequest",
    "TemplateVersionCreateRequest",
    "TemplateVersionListResponse",
    "TemplateVersionResponse",
    "TemplateVersionUpdateRequest",
]
