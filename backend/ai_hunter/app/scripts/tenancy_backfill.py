"""Dry-run-first backfill for auth v2-B thread metadata."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ..settings import get_settings


DEFAULT_COMPANY_ID = "co_f1824b82e2116701"


@dataclass(frozen=True)
class ThreadCandidate:
    thread_id: str
    message_case_ids: tuple[int, ...] = ()
    checkpoint_case_ids: tuple[int, ...] = ()
    message_created_at: datetime | None = None
    message_updated_at: datetime | None = None
    checkpoint_created_at: datetime | None = None
    checkpoint_updated_at: datetime | None = None
    message_all_deleted: bool | None = None
    checkpoint_all_deleted: bool | None = None
    last_intent: str = ""


@dataclass(frozen=True)
class BackfillRow:
    thread_id: str
    case_id: int | None
    company_id: str
    created_by: str
    last_intent: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    classification: str
    candidate_case_ids: tuple[int, ...]


def classify_candidate(
    candidate: ThreadCandidate,
    case_companies: dict[int, str],
    *,
    default_company_id: str = DEFAULT_COMPANY_ID,
    conflict_policy: str = "abort",
) -> BackfillRow:
    """Resolve only provable ownership; ambiguous legacy rows stay admin-only."""
    candidate_case_ids = tuple(sorted(set(candidate.message_case_ids + candidate.checkpoint_case_ids)))
    valid_case_ids = tuple(case_id for case_id in candidate_case_ids if case_id in case_companies)
    if len(candidate_case_ids) > 1:
        if conflict_policy == "abort":
            classification = "conflict"
        else:
            classification = "conflict_to_null"
        case_id = None
    elif candidate_case_ids and not valid_case_ids:
        classification = "missing_case_to_null"
        case_id = None
    elif valid_case_ids:
        classification = "case_resolved"
        case_id = valid_case_ids[0]
    else:
        classification = "no_case"
        case_id = None

    source_deleted = [
        value
        for value in (candidate.message_all_deleted, candidate.checkpoint_all_deleted)
        if value is not None
    ]
    is_deleted = bool(source_deleted) and all(source_deleted)
    created_values = [
        value
        for value in (candidate.message_created_at, candidate.checkpoint_created_at)
        if value is not None
    ]
    updated_values = [
        value
        for value in (candidate.message_updated_at, candidate.checkpoint_updated_at)
        if value is not None
    ]
    if not created_values or not updated_values:
        raise ValueError(f"thread 缺少可用时间戳: {candidate.thread_id}")
    created_at = min(created_values)
    updated_at = max(updated_values)
    return BackfillRow(
        thread_id=candidate.thread_id,
        case_id=case_id,
        company_id=case_companies.get(case_id, default_company_id),
        created_by="",
        last_intent=candidate.last_intent,
        title="",
        status="deleted" if is_deleted else "active",
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=updated_at if is_deleted else None,
        classification=classification,
        candidate_case_ids=candidate_case_ids,
    )


def _load_candidates(conn: psycopg.Connection) -> list[ThreadCandidate]:
    query = """
    WITH message_threads AS (
        SELECT
            thread_id,
            array_agg(DISTINCT NULLIF(case_id, 0))
                FILTER (WHERE NULLIF(case_id, 0) IS NOT NULL) AS case_ids,
            min(created_at) AS created_at,
            max(created_at) AS updated_at,
            bool_and(deleted_at IS NOT NULL) AS all_deleted
        FROM public.conversation_messages
        GROUP BY thread_id
    ),
    latest_intents AS (
        SELECT DISTINCT ON (thread_id) thread_id, COALESCE(intent, '') AS last_intent
        FROM public.conversation_messages
        WHERE COALESCE(intent, '') <> ''
        ORDER BY thread_id, created_at DESC, id DESC
    ),
    checkpoint_values AS (
        SELECT
            thread_id,
            CASE
                WHEN checkpoint->'channel_values'->>'current_case_id' ~ '^[0-9]+$'
                THEN NULLIF((checkpoint->'channel_values'->>'current_case_id')::bigint, 0)
            END AS case_id,
            (checkpoint->>'ts')::timestamptz AS checkpoint_ts,
            deleted_at
        FROM public.checkpoints
        WHERE checkpoint_ns = ''
    ),
    checkpoint_threads AS (
        SELECT
            thread_id,
            array_agg(DISTINCT case_id) FILTER (WHERE case_id IS NOT NULL) AS case_ids,
            min(checkpoint_ts) AS created_at,
            max(checkpoint_ts) AS updated_at,
            bool_and(deleted_at IS NOT NULL) AS all_deleted
        FROM checkpoint_values
        GROUP BY thread_id
    )
    SELECT
        COALESCE(m.thread_id, cp.thread_id) AS thread_id,
        COALESCE(m.case_ids, '{}'::bigint[]) AS message_case_ids,
        COALESCE(cp.case_ids, '{}'::bigint[]) AS checkpoint_case_ids,
        m.created_at AS message_created_at,
        m.updated_at AS message_updated_at,
        cp.created_at AS checkpoint_created_at,
        cp.updated_at AS checkpoint_updated_at,
        m.all_deleted AS message_all_deleted,
        cp.all_deleted AS checkpoint_all_deleted,
        COALESCE(li.last_intent, '') AS last_intent
    FROM message_threads m
    FULL JOIN checkpoint_threads cp USING (thread_id)
    LEFT JOIN latest_intents li ON li.thread_id = COALESCE(m.thread_id, cp.thread_id)
    ORDER BY thread_id
    """
    rows = conn.execute(query).fetchall()
    return [
        ThreadCandidate(
            thread_id=str(row["thread_id"]),
            message_case_ids=tuple(int(value) for value in row["message_case_ids"]),
            checkpoint_case_ids=tuple(int(value) for value in row["checkpoint_case_ids"]),
            message_created_at=row["message_created_at"],
            message_updated_at=row["message_updated_at"],
            checkpoint_created_at=row["checkpoint_created_at"],
            checkpoint_updated_at=row["checkpoint_updated_at"],
            message_all_deleted=row["message_all_deleted"],
            checkpoint_all_deleted=row["checkpoint_all_deleted"],
            last_intent=str(row["last_intent"] or ""),
        )
        for row in rows
    ]


def run_backfill(
    *,
    execute: bool = False,
    conflict_policy: str = "abort",
    default_company_id: str = DEFAULT_COMPANY_ID,
) -> dict[str, Any]:
    """Inspect or backfill thread_metadata without overwriting existing rows."""
    settings = get_settings()
    with psycopg.connect(settings.postgres_checkpointer_dsn, row_factory=dict_row) as conn:
        if not execute:
            conn.execute("SET TRANSACTION READ ONLY")
        case_companies = {
            int(row["case_id"]): str(row["company_id"] or default_company_id)
            for row in conn.execute("SELECT case_id, company_id FROM public.cases").fetchall()
        }
        existing_ids = {
            str(row["thread_id"])
            for row in conn.execute("SELECT thread_id FROM public.thread_metadata").fetchall()
        }
        candidates = _load_candidates(conn)
        rows = [
            classify_candidate(
                candidate,
                case_companies,
                default_company_id=default_company_id,
                conflict_policy=conflict_policy,
            )
            for candidate in candidates
            if candidate.thread_id not in existing_ids
        ]
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.classification] = counts.get(row.classification, 0) + 1
        status_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1
        conflicts = [row for row in rows if row.classification == "conflict"]
        result = {
            "mode": "execute" if execute else "dry_run",
            "candidate_threads": len(candidates),
            "existing_metadata": len(existing_ids),
            "pending_rows": len(rows),
            "classification_counts": counts,
            "status_counts": status_counts,
            "admin_only_rows": sum(1 for row in rows if row.case_id is None),
            "conflicts": [
                {"thread_id": row.thread_id, "candidate_case_ids": list(row.candidate_case_ids)}
                for row in conflicts
            ],
            "inserted_rows": 0,
        }
        if execute and conflicts:
            raise RuntimeError("存在跨案件 thread 冲突；请人工确认或显式使用 --conflict-policy null")
        if execute and rows:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO public.thread_metadata (
                        thread_id, case_id, company_id, created_by, last_intent, title,
                        status, created_at, updated_at, deleted_at
                    ) VALUES (
                        %(thread_id)s, %(case_id)s, %(company_id)s, %(created_by)s,
                        %(last_intent)s, %(title)s, %(status)s, %(created_at)s,
                        %(updated_at)s, %(deleted_at)s
                    )
                    ON CONFLICT (thread_id) DO NOTHING
                    """,
                    [
                        {
                            key: value
                            for key, value in asdict(row).items()
                            if key not in {"classification", "candidate_case_ids"}
                        }
                        for row in rows
                    ],
                )
                inserted_rows = max(cur.rowcount, 0)
            conn.commit()
            result["inserted_rows"] = inserted_rows
        else:
            conn.rollback()
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill auth v2-B thread metadata")
    parser.add_argument("--execute", action="store_true", help="Actually insert pending metadata rows")
    parser.add_argument(
        "--conflict-policy",
        choices=("abort", "null"),
        default="abort",
        help="abort blocks execution; null migrates ambiguous threads as admin-only case_id=NULL",
    )
    parser.add_argument("--default-company-id", default=DEFAULT_COMPANY_ID)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_backfill(
        execute=args.execute,
        conflict_policy=args.conflict_policy,
        default_company_id=args.default_company_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
