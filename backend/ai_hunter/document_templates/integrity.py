"""Canonical integrity helpers shared by template governance and workers."""

from __future__ import annotations

import hashlib
from typing import Any

from .compiler.models import canonical_json


def canonical_json_sha256(value: Any) -> str:
    """Hash one JSON-compatible value using the template contract encoding."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_template_content_hash(version: dict[str, Any]) -> str:
    """Return the activation hash for a complete template version snapshot."""

    files = []
    for item in sorted(
        list(version.get("files") or []),
        key=lambda value: (int(value.get("sort_order") or 0), str(value.get("id") or "")),
    ):
        files.append(
            {
                "id": str(item.get("id") or ""),
                "document_code": item.get("document_code"),
                "display_name": item.get("display_name"),
                "extension": item.get("extension"),
                "source_sha256": item.get("source_sha256"),
                "compiled_sha256": item.get("compiled_sha256"),
                "renderer_profile": item.get("renderer_profile"),
                "binding_manifest": item.get("binding_manifest") or {},
                "sort_order": int(item.get("sort_order") or 0),
            }
        )
    return canonical_json_sha256(
        {
            "contract_version": version.get("contract_version"),
            "business_type": version.get("business_type"),
            "manifest": version.get("manifest") or {},
            "files": files,
        }
    )


__all__ = ["canonical_json_sha256", "stable_template_content_hash"]
