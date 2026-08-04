"""Reusable platform contracts and isolation helpers.

This module contains no annual-audit or NPA business rules.  Business domains
may depend on it; it must never import a business domain.  The physical Redis,
MinIO and database services may be shared, but every key/object/reference is
scoped by the active business domain and project.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal


_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def validate_domain(value: str, *, expected: str | None = None) -> str:
    domain = str(value or "").strip().lower()
    if not _DOMAIN_RE.fullmatch(domain):
        raise ValueError(f"invalid business domain: {value!r}")
    if expected and domain != expected:
        raise ValueError(f"business domain {domain!r} is not {expected!r}")
    return domain


def _namespace(settings: Any) -> str:
    domain = validate_domain(getattr(settings, "business_domain", ""))
    raw = str(getattr(settings, "annual_redis_namespace", "") or "").strip()
    if not raw.startswith("ata:") or not raw.endswith(":"):
        raise ValueError("Redis namespace must start with ata: and end with :")
    # Existing environments may have ata:online:. Add the active domain at
    # the code boundary so legacy keys cannot collide with the new project.
    base = raw.rstrip(":")
    if base.endswith(f":{domain}"):
        return base
    return f"{base}:{domain}"


def scoped_redis_key(settings: Any, area: str, *parts: object) -> str:
    """Return a Redis key scoped by namespace and business domain."""

    normalized_area = str(area or "").strip(":/")
    if not normalized_area:
        raise ValueError("Redis key area is required")
    normalized_parts = [str(part).strip(":/") for part in parts if str(part).strip(":/")]
    return ":".join([_namespace(settings), normalized_area, *normalized_parts])


def scoped_object_key(
    settings: Any,
    *,
    project_id: int,
    category: str,
    parts: tuple[object, ...] = (),
) -> str:
    """Return a MinIO object key scoped by domain and project."""

    domain = validate_domain(getattr(settings, "business_domain", ""))
    prefix = str(getattr(settings, "annual_minio_prefix", "") or "").strip("/") or domain
    if domain not in {segment.strip() for segment in prefix.split("/") if segment.strip()}:
        prefix = f"{domain}/{prefix}"
    normalized = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return str(PurePosixPath(prefix, f"project-{max(int(project_id), 0)}", category, *normalized))


@dataclass(frozen=True)
class DomainContext:
    """Request/project scope carried through storage and agent operations."""

    domain_code: str
    project_id: int
    tenant_id: str = ""
    user_id: str = ""
    thread_id: str = ""
    request_id: str = ""


@dataclass(frozen=True)
class EvidenceRef:
    """Stable source locator; business rows must reference this contract."""

    domain_code: str
    project_id: int
    source_file_id: int
    source_page_id: int = 0
    source_chunk_id: str = ""
    locator_kind: Literal[
        "sheet_row",
        "cell_range",
        "csv_row",
        "pdf_page",
        "image_region",
        "text_span",
        "unknown",
    ] = "unknown"
    page_no: int = 0
    sheet_name: str = ""
    row_start: int = 0
    row_end: int = 0
    cell_range: str = ""
    quote_text: str = ""
    bbox_list: list[dict[str, float]] = field(default_factory=list)
    page_image_ref: str = ""
    source_file_ref: str = ""
    content_type: str = ""
    preview_ref: str = ""

    @property
    def is_bound(self) -> bool:
        return self.source_file_id > 0 and bool(self.source_chunk_id or self.source_page_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_code": self.domain_code,
            "project_id": self.project_id,
            "source_file_id": self.source_file_id,
            "source_page_id": self.source_page_id,
            "source_chunk_id": self.source_chunk_id,
            "locator_kind": self.locator_kind,
            "page_no": self.page_no,
            "sheet_name": self.sheet_name,
            "row_start": self.row_start,
            "row_end": self.row_end,
            "cell_range": self.cell_range,
            "quote_text": self.quote_text,
            "bbox_list": list(self.bbox_list),
            "page_image_ref": self.page_image_ref,
            "source_file_ref": self.source_file_ref,
            "content_type": self.content_type,
            "preview_ref": self.preview_ref,
        }


@dataclass(frozen=True)
class ArtifactRef:
    """Versioned generated artifact metadata, independent of a domain."""

    artifact_type: str
    template_version: str
    version: int
    storage_ref: str = ""
    content_type: str = ""
    file_name: str = ""
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "template_version": self.template_version,
            "version": self.version,
            "storage_ref": self.storage_ref,
            "content_type": self.content_type,
            "file_name": self.file_name,
            "status": self.status,
        }
