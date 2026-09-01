"""Plan conservative attachment-storage reclamation without touching object storage."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
import json
import re
from typing import Any

from ai_hunter.annual_audit.attachments import repository as attachment_repository
from ai_hunter.document_templates.repository import DocumentTemplateRepository


DEFAULT_LIMIT = 100
MAX_LIMIT = 1_000
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_KINDS = frozenset(
    {"source", "compiled", "preview", "context", "payload", "artifact", "provenance"}
)


def _bounded_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def _retention_time(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        normalized = value.strip()
        try:
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("planner returned an invalid retention timestamp") from exc
        return normalized
    raise RuntimeError("planner returned an invalid retention timestamp")


def _public_candidate(item: Mapping[str, Any]) -> dict[str, Any]:
    storage_ref_hash = str(item.get("storage_ref_hash") or "").strip().lower()
    if not _HASH_RE.fullmatch(storage_ref_hash):
        raise RuntimeError("planner returned an invalid storage reference hash")
    object_kind = str(item.get("object_kind") or "").strip().lower()
    if object_kind not in _OBJECT_KINDS:
        raise RuntimeError("planner returned an invalid object kind")
    retention_state = str(item.get("retention_state") or "").strip().lower()
    if retention_state != "reclaim_candidate":
        raise RuntimeError("planner returned an invalid retention state")
    return {
        "object_kind": object_kind,
        "storage_ref_hash": storage_ref_hash,
        "retention_state": retention_state,
        "unreferenced_at": _retention_time(item.get("unreferenced_at")),
        "retention_until": _retention_time(item.get("retention_until")),
    }


def _store_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates = [_public_candidate(item) for item in items]
    return {"count": len(candidates), "items": candidates}


def plan_reclamation(
    *,
    limit: int,
    template_repository: DocumentTemplateRepository | None = None,
    attachment_planner: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if not 1 <= int(limit) <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    template_repo = template_repository or DocumentTemplateRepository()
    attachment_postgres_planner = attachment_planner or attachment_repository.plan_storage_reclamation
    template_candidates = template_repo.plan_storage_reclamation(limit=int(limit))
    attachment_candidates = attachment_postgres_planner(limit=int(limit))
    return {
        "template_postgres": _store_summary(template_candidates),
        "attachment_postgres": _store_summary(attachment_candidates),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mark and list conservative annual-attachment storage reclamation candidates."
    )
    parser.add_argument(
        "--limit",
        type=_bounded_limit,
        default=DEFAULT_LIMIT,
        help=f"maximum candidates per store (1-{MAX_LIMIT})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    print(json.dumps(plan_reclamation(limit=args.limit), ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
