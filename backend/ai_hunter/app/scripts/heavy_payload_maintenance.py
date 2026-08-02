"""CLI helper for inspecting and pruning heavy_payload_store rows."""

from __future__ import annotations

import argparse
import json

from ..services.heavy_payload_admin import get_heavy_payload_stats, prune_heavy_payloads


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Heavy payload maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("stats", help="Show heavy payload storage stats")

    prune_parser = subparsers.add_parser("prune", help="Prune expired heavy payload rows")
    prune_parser.add_argument("--execute", action="store_true", help="Actually delete matching rows")
    prune_parser.add_argument("--payload-type", default="", help="Only prune one payload type")
    prune_parser.add_argument(
        "--older-than-seconds",
        type=int,
        default=0,
        help="Override the age threshold in seconds",
    )
    prune_parser.add_argument("--limit", type=int, default=0, help="Maximum rows to inspect/delete")
    return parser


def main() -> None:
    """Run the heavy payload maintenance command."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "stats":
        stats = get_heavy_payload_stats()
        print(
            json.dumps(
                {
                    "total_rows": stats.total_rows,
                    "type_counts": stats.type_counts,
                    "oldest_updated_at": stats.oldest_updated_at.isoformat()
                    if stats.oldest_updated_at
                    else None,
                    "newest_updated_at": stats.newest_updated_at.isoformat()
                    if stats.newest_updated_at
                    else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    result = prune_heavy_payloads(
        dry_run=not args.execute,
        payload_type=args.payload_type or None,
        older_than_seconds=args.older_than_seconds or None,
        limit=args.limit or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
