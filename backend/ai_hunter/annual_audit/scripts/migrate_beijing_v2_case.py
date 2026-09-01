"""Migrate only the reviewed safe subset of the supplied Beijing V2 case.

Examples:

    python -m ai_hunter.annual_audit.scripts.migrate_beijing_v2_case
    python -m ai_hunter.annual_audit.scripts.migrate_beijing_v2_case \
      --source-root E:\\case-data\\new_docs --case-id 42 --apply
    python -m ai_hunter.annual_audit.scripts.migrate_beijing_v2_case \
      --metadata case.json --apply

The default command is a dry-run and never writes PostgreSQL, Redis, or MinIO.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ai_hunter.annual_audit.legacy_case_migration import (
    MigrationPlanError,
    build_migration_plan,
    default_source_root,
    execute_migration,
)


def _read_metadata(path: str) -> dict[str, Any]:
    metadata_path = Path(path)
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationPlanError(f"metadata not found: {metadata_path}") from exc
    except json.JSONDecodeError as exc:
        raise MigrationPlanError(f"metadata is not valid JSON: {metadata_path}") from exc
    if not isinstance(data, dict):
        raise MigrationPlanError("metadata root must be an object")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate the reviewed safe subset of the supplied Beijing V2 annual-audit case. "
            "The default is read-only dry-run; unreviewed manifest files are never uploaded."
        ),
    )
    parser.add_argument(
        "--source-root",
        default=str(default_source_root()),
        help="Local new_docs root. No directory-wide scanning is performed.",
    )
    parser.add_argument(
        "--manifest",
        default="",
        help="Optional explicit manifest path; defaults to the reviewed Beijing V2 manifest under source-root.",
    )
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--case-id",
        type=int,
        help="Existing annual-audit engagement ID. Required for apply unless --metadata is supplied.",
    )
    destination.add_argument(
        "--metadata",
        default="",
        help=(
            "JSON metadata used to create or reuse an engagement. Required keys: "
            "case_name, entity_name, company_id, fiscal_year."
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Perform PostgreSQL and MinIO writes for reviewed safe files.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail when a manual-review manifest source cannot be resolved locally.",
    )
    parser.add_argument("--operator-id", default="historical-migration", help="Audit operator ID stored with batches.")
    parser.add_argument("--operator-name", default="historical-migration", help="Audit operator name stored with batches.")
    parser.add_argument("--batch-name", default="", help="Optional readable prefix for stable migration batches.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_migration_plan(
            source_root=Path(args.source_root),
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
        metadata = _read_metadata(args.metadata) if args.metadata else None
        report = execute_migration(
            plan=plan,
            apply=bool(args.apply),
            case_id=args.case_id,
            case_metadata=metadata,
            operator_id=args.operator_id,
            operator_name=args.operator_name,
            batch_name=args.batch_name,
            strict=bool(args.strict),
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str))
        return 1 if report.errors else 0
    except Exception as exc:  # noqa: BLE001 - CLI must not emit a partial stack trace by default
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry_run",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
