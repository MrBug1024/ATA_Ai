"""Shared value objects for deterministic template compilers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class TemplateSecurityLimits:
    max_file_bytes: int = 50 * 1024 * 1024
    max_zip_entries: int = 2_000
    max_uncompressed_bytes: int = 250 * 1024 * 1024
    max_entry_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: int = 100
    max_xml_bytes: int = 20 * 1024 * 1024

    @classmethod
    def from_settings(cls, settings: Any) -> "TemplateSecurityLimits":
        return cls(
            max_file_bytes=max(1, int(getattr(settings, "attachment_template_max_mb", 50)))
            * 1024
            * 1024,
            max_zip_entries=max(1, int(getattr(settings, "attachment_zip_max_entries", 2_000))),
            max_uncompressed_bytes=max(
                1, int(getattr(settings, "attachment_zip_max_uncompressed_mb", 250))
            )
            * 1024
            * 1024,
            max_entry_bytes=max(1, int(getattr(settings, "attachment_zip_max_entry_mb", 50)))
            * 1024
            * 1024,
            max_compression_ratio=max(
                1, int(getattr(settings, "attachment_zip_max_ratio", 100))
            ),
            max_xml_bytes=max(1, int(getattr(settings, "attachment_xml_max_mb", 20)))
            * 1024
            * 1024,
        )


@dataclass
class TemplateInspection:
    extension: str
    content_type: str
    size_bytes: int
    source_sha256: str
    signature: str = ""
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    threats: list[str] = field(default_factory=list)
    format_details: dict[str, Any] = field(default_factory=dict)
    suggested_mapping: dict[str, Any] = field(default_factory=dict)
    antivirus: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.threats

    def add_error(self, code: str, message: str) -> None:
        if not any(item.get("code") == code for item in self.errors):
            self.errors.append({"code": code, "message": message})

    def add_warning(self, code: str, message: str) -> None:
        if not any(item.get("code") == code for item in self.warnings):
            self.warnings.append({"code": code, "message": message})

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection_version": "document-template-inspection-v1",
            "ok": self.ok,
            "extension": self.extension,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "source_sha256": self.source_sha256,
            "signature": self.signature,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "threats": list(self.threats),
            "format_details": self.format_details,
            "suggested_mapping": self.suggested_mapping,
            "antivirus": self.antivirus,
        }


@dataclass(frozen=True)
class CompiledTemplate:
    content: bytes
    renderer_profile: str
    binding_manifest: dict[str, Any]
    compilation_report: dict[str, Any]
    synthetic_content: bytes = b""

    @property
    def compiled_sha256(self) -> str:
        return sha256_bytes(self.content)

    def to_summary(self) -> dict[str, Any]:
        return {
            "renderer_profile": self.renderer_profile,
            "compiled_sha256": self.compiled_sha256,
            "binding_manifest": self.binding_manifest,
            "compilation_report": self.compilation_report,
        }


class TemplateCompilationError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


__all__ = [
    "CompiledTemplate",
    "TemplateCompilationError",
    "TemplateInspection",
    "TemplateSecurityLimits",
    "canonical_json",
    "sha256_bytes",
]
