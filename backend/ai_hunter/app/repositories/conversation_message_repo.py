"""Conversation message repository — decoupled from LangGraph checkpointer internals.

Design principles
-----------------
1. **Single-writer**: ``persist_conversation_memory`` writes here first, then returns
   state updates to LangGraph. If this write fails the node raises, LangGraph never
   merges the new state → checkpoint stays consistent.
2. **Idempotent inserts**: ``ON CONFLICT DO NOTHING`` avoids duplicates on retries.
3. **Connection pass-through**: callers may pass an existing ``psycopg.Connection`` so
   the repo participates in a broader transaction when needed.
4. **Soft-delete aligned**: ``deleted_at`` is set in tandem with ``checkpoints`` soft
   deletes (see ``ConversationService.delete_thread``).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from ..settings import get_settings


class ConversationMessageRepository:
    """CRUD for conversation messages stored in a dedicated SQL table."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def _connect(self, conn: psycopg.Connection | None = None) -> Iterator[psycopg.Connection]:
        """Yield *conn* if provided, otherwise open a fresh connection."""
        if conn is not None:
            yield conn
            return
        with psycopg.connect(self.dsn, row_factory=dict_row) as fresh:
            yield fresh

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append_messages(
        self,
        thread_id: str,
        messages: list[dict[str, Any]],
        *,
        conn: psycopg.Connection | None = None,
    ) -> int:
        """Insert messages idempotently.  Returns number of rows inserted.

        Each *message* dict is expected to carry at least:
        ``role``, ``content``, ``id`` (used as ``turn_id``), plus optional
        ``intent``, ``case_id``, ``final_report_ref``, ``version``.
        """
        if not messages:
            return 0

        with self._connect(conn) as c:
            with c.cursor() as cur:
                rows = [
                    {
                        "thread_id": thread_id,
                        "turn_id": msg.get("id", ""),
                        "role": msg.get("role", ""),
                        "content": str(msg.get("content", "")),
                        "intent": msg.get("intent") or None,
                        "case_id": msg.get("case_id", 0) or 0,
                        "final_report_ref": msg.get("final_report_ref", "") or "",
                        "uploaded_files": json.dumps(
                            msg.get("uploaded_files") or [],
                            ensure_ascii=False,
                        ),
                        "graph_context": json.dumps(
                            msg.get("graph_context") or {},
                            ensure_ascii=False,
                        ),
                        "version": msg.get("version", 1) or 1,
                    }
                    for msg in messages
                ]
                cur.executemany(
                    """
                    INSERT INTO conversation_messages
                        (thread_id, turn_id, role, content, intent, case_id,
                         final_report_ref, uploaded_files, graph_context, version)
                    VALUES
                        (%(thread_id)s, %(turn_id)s, %(role)s, %(content)s,
                         %(intent)s, %(case_id)s, %(final_report_ref)s,
                         %(uploaded_files)s, %(graph_context)s, %(version)s)
                    ON CONFLICT DO NOTHING
                    """,
                    rows,
                )
                if conn is None:
                    c.commit()
                return cur.rowcount

    def soft_delete_by_thread(
        self,
        thread_id: str,
        *,
        conn: psycopg.Connection | None = None,
    ) -> int:
        """Soft-delete all messages for a thread.  Returns row count."""
        with self._connect(conn) as c:
            with c.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversation_messages
                    SET deleted_at = NOW()
                    WHERE thread_id = %(thread_id)s
                      AND deleted_at IS NULL
                    """,
                    {"thread_id": thread_id},
                )
                if conn is None:
                    c.commit()
                return cur.rowcount

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_messages(
        self,
        thread_id: str,
        *,
        conn: psycopg.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """Return live (non-deleted) messages for a thread, ordered by creation time."""
        with self._connect(conn) as c:
            with c.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        thread_id,
                        turn_id,
                        role,
                        content,
                        intent,
                        case_id,
                        final_report_ref,
                        uploaded_files,
                        graph_context,
                        version,
                        created_at
                    FROM conversation_messages
                    WHERE thread_id = %(thread_id)s
                      AND deleted_at IS NULL
                    ORDER BY created_at ASC, id ASC
                    """,
                    {"thread_id": thread_id},
                )
                rows = cur.fetchall()
                for row in rows:
                    raw = row.get("uploaded_files")
                    if isinstance(raw, str):
                        try:
                            row["uploaded_files"] = json.loads(raw)
                        except (TypeError, ValueError):
                            row["uploaded_files"] = []
                    elif raw is None:
                        row["uploaded_files"] = []
                    gc = row.get("graph_context")
                    if isinstance(gc, str):
                        try:
                            row["graph_context"] = json.loads(gc)
                        except (TypeError, ValueError):
                            row["graph_context"] = {}
                    elif gc is None:
                        row["graph_context"] = {}
                return rows

    def has_messages(
        self,
        thread_id: str,
        *,
        conn: psycopg.Connection | None = None,
    ) -> bool:
        """Return True when the thread has at least one live message."""
        with self._connect(conn) as c:
            with c.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM conversation_messages
                    WHERE thread_id = %(thread_id)s
                      AND deleted_at IS NULL
                    LIMIT 1
                    """,
                    {"thread_id": thread_id},
                )
                return cur.fetchone() is not None

    def get_max_assistant_version(
        self,
        thread_id: str,
        turn_id: str,
        *,
        conn: psycopg.Connection | None = None,
    ) -> int:
        """Return the current max version for assistant records of a turn."""
        with self._connect(conn) as c:
            with c.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(MAX(version), 0)
                    FROM conversation_messages
                    WHERE thread_id = %(thread_id)s
                      AND turn_id = %(turn_id)s
                      AND role = 'assistant'
                      AND deleted_at IS NULL
                    """,
                    {"thread_id": thread_id, "turn_id": turn_id},
                )
                row = cur.fetchone()
                return int(row["coalesce"]) if row else 0

    def get_turns(
        self,
        thread_id: str,
        *,
        conn: psycopg.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """Return messages grouped by turn.

        Each turn contains one ``user`` message and a list of ``assistants``
        sorted by ``version`` ascending.
        The turn_id prefix is derived by stripping the ``_user`` / ``_assistant``
        suffix from the stored ``turn_id``.
        """
        rows = self.get_messages(thread_id, conn=conn)
        turns: list[dict[str, Any]] = []
        current_turn: dict[str, Any] | None = None

        for row in rows:
            # turn_id stored as "{hash}_user" or "{hash}_assistant"
            turn_prefix = row["turn_id"].rsplit("_", 1)[0]

            if row["role"] == "user":
                if current_turn is not None:
                    turns.append(current_turn)
                current_turn = {
                    "turn_id": turn_prefix,
                    "user": {
                        "role": "user",
                        "content": row["content"],
                        "created_at": row["created_at"],
                        "uploaded_files": row.get("uploaded_files") or [],
                    },
                    "assistants": [],
                }
            elif row["role"] == "assistant":
                if current_turn is None:
                    current_turn = {
                        "turn_id": turn_prefix,
                        "user": None,
                        "assistants": [],
                    }
                current_turn["assistants"].append({
                    "role": "assistant",
                    "content": row["content"],
                    "id": row["turn_id"],
                    "created_at": row["created_at"],
                    "intent": row.get("intent"),
                    "case_id": row.get("case_id"),
                    "final_report_ref": row.get("final_report_ref"),
                    # ``graph_context`` is a response-scoped snapshot.  Keep it
                    # with this exact assistant version so the /turns endpoint
                    # never borrows citations or unresolved items from a later
                    # reply in the same thread.
                    "graph_context": row.get("graph_context")
                    if isinstance(row.get("graph_context"), dict)
                    else {},
                    "version": row.get("version", 1),
                })

        if current_turn is not None:
            turns.append(current_turn)

        # Sort assistants by version within each turn
        for turn in turns:
            turn["assistants"].sort(key=lambda a: a.get("version", 1))

        return turns


# Singleton factory -------------------------------------------------------
_repo_instance: ConversationMessageRepository | None = None


def get_conversation_message_repo() -> ConversationMessageRepository:
    """Return the process-level singleton repository instance."""
    global _repo_instance
    if _repo_instance is None:
        settings = get_settings()
        _repo_instance = ConversationMessageRepository(dsn=settings.postgres_checkpointer_dsn)
    return _repo_instance
