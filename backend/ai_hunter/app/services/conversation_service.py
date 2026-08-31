"""Conversation thread management service."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from ..settings import get_settings
from ..repositories import ConversationMessageRepository


LOGGER = logging.getLogger(__name__)


def _flatten_graph_context(graph_context: Any) -> dict[str, Any]:
    """Unpack the stored graph_context JSONB into flat MessageItem fields.

    Historical assistant rows (persisted before issue #8) and all user rows
    have an empty/absent graph_context → every field falls back to an empty
    list/dict so the API contract stays stable.
    """
    gc = graph_context if isinstance(graph_context, dict) else {}
    coverage = gc.get("citation_coverage")
    route_decision = gc.get("route_decision")
    return {
        "route_decision": route_decision if isinstance(route_decision, dict) and route_decision.get("capability") else None,
        "trace_items": gc.get("trace_items") or [],
        "citation_coverage": coverage if isinstance(coverage, dict) else {},
        "unresolved_relations": gc.get("unresolved_relations") or [],
        "unresolved_claims": gc.get("unresolved_claims") or [],
    }


class ConversationService:
    """Service for managing conversation threads and history."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._msg_repo = ConversationMessageRepository(dsn)

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """Yield a psycopg connection with dict rows."""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    def list_threads(
        self,
        *,
        case_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
        allowed_thread_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """List threads from both the checkpointer and the display history table.

        ``conversation_messages`` is the durable, display-oriented history.  A
        completed graph run can successfully write that table before a
        checkpointer row is visible (and legacy deployments may contain only
        checkpoints), so using either table as the sole source makes threads
        disappear from the sidebar after a refresh.  The CTE below merges both
        sources and lets checkpoint values win when they are available.
        """
        if allowed_thread_ids == []:
            return {"threads": [], "total": 0, "limit": limit, "offset": offset}

        with self.connect() as conn:
            with conn.cursor() as cur:
                query = """
                    WITH latest_checkpoints AS (
                        SELECT DISTINCT ON (thread_id)
                            thread_id,
                            checkpoint,
                            metadata,
                            checkpoint_id,
                            parent_checkpoint_id
                        FROM public.checkpoints
                        WHERE checkpoint_ns = ''
                          AND deleted_at IS NULL
                        ORDER BY thread_id,
                                 (checkpoint->>'ts') DESC NULLS LAST,
                                 checkpoint_id DESC
                    ),
                    message_rollup AS (
                        SELECT
                            thread_id,
                            MAX(created_at) AS updated_at,
                            (array_agg(content ORDER BY created_at DESC, id DESC)
                                FILTER (WHERE role = 'user'))[1] AS last_query,
                            (array_agg(case_id ORDER BY created_at DESC, id DESC)
                                FILTER (WHERE role = 'assistant' AND case_id > 0))[1] AS case_id,
                            (array_agg(intent ORDER BY created_at DESC, id DESC)
                                FILTER (WHERE role = 'assistant' AND COALESCE(intent, '') <> ''))[1] AS last_intent,
                            (array_agg(final_report_ref ORDER BY created_at DESC, id DESC)
                                FILTER (WHERE role = 'assistant' AND COALESCE(final_report_ref, '') <> ''))[1] AS final_report_ref
                        FROM public.conversation_messages
                        WHERE deleted_at IS NULL
                        GROUP BY thread_id
                    ),
                    all_threads AS (
                        SELECT thread_id FROM latest_checkpoints
                        UNION
                        SELECT thread_id FROM message_rollup
                    ),
                    thread_rows AS (
                        SELECT
                            all_threads.thread_id,
                            COALESCE(cp.checkpoint_id, '') AS checkpoint_id,
                            cp.checkpoint,
                            cp.metadata,
                            COALESCE(
                                NULLIF(cp.checkpoint->'channel_values'->>'current_case_id', '')::int,
                                NULLIF(mr.case_id, 0),
                                tm.case_id,
                                0
                            ) AS case_id,
                            COALESCE(
                                NULLIF(cp.checkpoint->'channel_values'->>'current_entity_id', '')::int,
                                0
                            ) AS entity_id,
                            COALESCE(
                                NULLIF(cp.checkpoint->'channel_values'->>'current_entity_name', ''),
                                ''
                            ) AS entity_name,
                            COALESCE(
                                NULLIF(cp.checkpoint->'channel_values'->>'query', ''),
                                mr.last_query,
                                ''
                            ) AS last_query,
                            COALESCE(
                                NULLIF(cp.checkpoint->'channel_values'->>'intent', ''),
                                mr.last_intent,
                                tm.last_intent,
                                ''
                            ) AS last_intent,
                            COALESCE(
                                NULLIF(cp.checkpoint->'channel_values'->>'final_report_ref', ''),
                                mr.final_report_ref,
                                ''
                            ) AS final_report_ref,
                            COALESCE(
                                mr.updated_at,
                                NULLIF(cp.checkpoint->>'ts', '')::timestamptz,
                                tm.updated_at
                            ) AS updated_at,
                            COALESCE(tm.title, '') AS stored_title,
                            COALESCE(cp.metadata->>'step', '0') AS step
                        FROM all_threads
                        LEFT JOIN latest_checkpoints cp ON cp.thread_id = all_threads.thread_id
                        LEFT JOIN message_rollup mr ON mr.thread_id = all_threads.thread_id
                        LEFT JOIN public.thread_metadata tm ON tm.thread_id = all_threads.thread_id
                    )
                    SELECT *, COUNT(*) OVER() AS total_count
                    FROM thread_rows
                """
                where_clauses: list[str] = []
                params: dict[str, Any] = {"limit": limit, "offset": offset}

                if case_id is not None:
                    where_clauses.append("case_id = %(case_id)s")
                    params["case_id"] = case_id
                if allowed_thread_ids is not None:
                    where_clauses.append("thread_id = ANY(%(allowed_thread_ids)s)")
                    params["allowed_thread_ids"] = allowed_thread_ids

                if where_clauses:
                    query += " WHERE " + " AND ".join(where_clauses)
                query += """
                    ORDER BY updated_at DESC NULLS LAST, thread_id
                    LIMIT %(limit)s OFFSET %(offset)s
                """

                cur.execute(query, params)
                rows = cur.fetchall()

                total = int(rows[0]["total_count"]) if rows else 0
                threads = []
                for row in rows:
                    checkpoint = row["checkpoint"] or {}
                    metadata = row["metadata"] or {}
                    channel_values = checkpoint.get("channel_values", {})

                    thread_data = {
                        "thread_id": row["thread_id"],
                        "checkpoint_id": row["checkpoint_id"],
                        "case_id": self._safe_int(row["case_id"]),
                        "entity_id": self._safe_int(row["entity_id"]),
                        "entity_name": str(row["entity_name"] or channel_values.get("current_entity_name") or ""),
                        "last_query": str(row["last_query"] or ""),
                        "last_intent": str(row["last_intent"] or ""),
                        "final_report_ref": str(row["final_report_ref"] or ""),
                        "memory_context": str(channel_values.get("memory_context") or "")[:200],
                        "step": self._safe_int(row["step"] or metadata.get("step", 0)),
                        "updated_at": self._format_timestamp(row["updated_at"]),
                    }

                    title = str(row["stored_title"] or "") or self._generate_thread_title(thread_data)
                    thread_data["title"] = title
                    threads.append(thread_data)

                return {
                    "threads": threads,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }

    def get_thread_detail(self, thread_id: str) -> dict[str, Any] | None:
        """
        Get detailed information about a specific thread.
        
        Args:
            thread_id: The thread ID to query
            
        Returns:
            Thread detail dictionary or None if not found
        """
        with self.connect() as conn:
            with conn.cursor() as cur:
                # Get the latest checkpoint for this thread
                cur.execute(
                    """
                    SELECT 
                        thread_id,
                        checkpoint,
                        metadata,
                        checkpoint_id,
                        parent_checkpoint_id
                    FROM public.checkpoints
                    WHERE thread_id = %(thread_id)s
                      AND checkpoint_ns = ''
                      AND deleted_at IS NULL
                    ORDER BY (checkpoint->>'ts') DESC NULLS LAST, checkpoint_id DESC
                    LIMIT 1
                    """,
                    {"thread_id": thread_id},
                )
                row = cur.fetchone()
                
                if not row:
                    return self._get_thread_detail_from_messages(thread_id)
                
                checkpoint = row["checkpoint"] or {}
                metadata = row["metadata"] or {}
                channel_values = checkpoint.get("channel_values", {})
                
                # Get the first checkpoint to determine created_at
                cur.execute(
                    """
                    SELECT checkpoint
                    FROM public.checkpoints
                    WHERE thread_id = %(thread_id)s
                      AND checkpoint_ns = ''
                      AND deleted_at IS NULL
                    ORDER BY (checkpoint->>'ts') ASC NULLS LAST, checkpoint_id ASC
                    LIMIT 1
                    """,
                    {"thread_id": thread_id},
                )
                first_row = cur.fetchone()
                created_at = None
                if first_row and first_row["checkpoint"]:
                    created_at = first_row["checkpoint"].get("ts")
                
                thread_data = {
                    "thread_id": row["thread_id"],
                    "checkpoint_id": row["checkpoint_id"],
                    "case_id": self._safe_int(channel_values.get("current_case_id")),
                    "entity_id": self._safe_int(channel_values.get("current_entity_id")),
                    "entity_name": str(channel_values.get("current_entity_name") or ""),
                    "last_query": str(channel_values.get("query") or ""),
                    "last_intent": str(channel_values.get("intent") or ""),
                    "final_report_ref": str(channel_values.get("final_report_ref") or ""),
                    "memory_context": str(channel_values.get("memory_context") or ""),
                    "step": metadata.get("step", 0),
                    "created_at": created_at,
                    "updated_at": checkpoint.get("ts"),
                    # 添加文件上传相关信息
                    "upload_batch_id": str(channel_values.get("upload_batch_id") or ""),
                    "doc_category": str(channel_values.get("doc_category") or ""),
                    "batch_name": str(channel_values.get("batch_name") or ""),
                }

                # The dedicated history table is authoritative for display
                # fields. Fill holes in older/stale checkpoints so a refreshed
                # conversation still has its report reference and title.
                try:
                    history_rows = self._msg_repo.get_messages(thread_id)
                except Exception as exc:
                    LOGGER.warning("repo_get_thread_detail_enrichment_failed thread_id=%s error=%s", thread_id, exc)
                    history_rows = []
                latest_user = next(
                    (item for item in reversed(history_rows) if item.get("role") == "user"),
                    None,
                )
                latest_assistant = next(
                    (item for item in reversed(history_rows) if item.get("role") == "assistant"),
                    None,
                )
                if latest_user and not thread_data["last_query"]:
                    thread_data["last_query"] = str(latest_user.get("content") or "")
                if latest_assistant:
                    if not thread_data["final_report_ref"]:
                        thread_data["final_report_ref"] = str(latest_assistant.get("final_report_ref") or "")
                    if not thread_data["last_intent"]:
                        thread_data["last_intent"] = str(latest_assistant.get("intent") or "")
                    if thread_data["case_id"] <= 0:
                        thread_data["case_id"] = self._safe_int(latest_assistant.get("case_id"))
                
                title = self._generate_thread_title(thread_data)
                thread_data["title"] = title
                
                return thread_data

    def _get_thread_detail_from_messages(self, thread_id: str) -> dict[str, Any] | None:
        """Build detail metadata for a thread that has no checkpoint row yet."""
        try:
            rows = self._msg_repo.get_messages(thread_id)
        except Exception as exc:
            LOGGER.warning("repo_get_thread_detail_failed thread_id=%s error=%s", thread_id, exc)
            return None
        if not rows:
            return None

        latest_user = next((row for row in reversed(rows) if row.get("role") == "user"), None)
        latest_assistant = next(
            (row for row in reversed(rows) if row.get("role") == "assistant"),
            None,
        )
        case_id = self._safe_int((latest_assistant or {}).get("case_id"))
        last_query = str((latest_user or {}).get("content") or "")
        last_intent = str((latest_assistant or {}).get("intent") or "")
        thread_data = {
            "thread_id": thread_id,
            "checkpoint_id": "",
            "case_id": case_id,
            "entity_id": 0,
            "entity_name": "",
            "last_query": last_query,
            "last_intent": last_intent,
            "final_report_ref": str((latest_assistant or {}).get("final_report_ref") or ""),
            "memory_context": "",
            "step": 0,
            "upload_batch_id": "",
            "doc_category": "",
            "batch_name": "",
            "created_at": self._format_timestamp(rows[0].get("created_at")),
            "updated_at": self._format_timestamp(rows[-1].get("created_at")),
        }
        thread_data["title"] = self._generate_thread_title(thread_data)
        return thread_data

    def get_thread_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """
        Get all messages from a conversation thread.

        Reads from the dedicated ``conversation_messages`` table first (fast SQL).
        Falls back to deserialising the LangGraph checkpointer for legacy threads
        created before the unified message table existed.
        """
        if self._is_thread_deleted(thread_id):
            return []

        # 1. Fast path: unified message table
        try:
            rows = self._msg_repo.get_messages(thread_id)
        except Exception as exc:
            LOGGER.warning("repo_get_messages_failed thread_id=%s error=%s", thread_id, exc)
            rows = []

        if rows:
            role_to_type = {"user": "human", "assistant": "ai", "system": "system"}
            return [
                {
                    "role": row["role"],
                    "content": row["content"],
                    "type": role_to_type.get(row["role"], row["role"]),
                    "id": row["turn_id"],
                    "name": "",
                    "intent": row.get("intent", "") or "",
                    "final_report_ref": row.get("final_report_ref", "") or "",
                    "uploaded_files": row.get("uploaded_files") or [],
                    **_flatten_graph_context(row.get("graph_context")),
                }
                for row in rows
            ]

        # 2. Fallback: legacy threads stored only in checkpointer blobs
        from ..graph.checkpointer import get_checkpointer

        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        try:
            tuple_ = get_checkpointer().get_tuple(config)
        except Exception as exc:  # pragma: no cover - depends on live checkpointer
            LOGGER.warning("get_thread_messages_failed thread_id=%s error=%s", thread_id, exc)
            return []

        if not tuple_ or not tuple_.checkpoint:
            return []

        channel_values = tuple_.checkpoint.get("channel_values", {})

        conversation_log = channel_values.get("conversation_log") or []
        if conversation_log:
            role_to_type = {"user": "human", "assistant": "ai", "system": "system"}
            return [
                {
                    "role": str(entry.get("role", "") or ""),
                    "content": str(entry.get("content", "") or ""),
                    "type": role_to_type.get(entry.get("role", ""), str(entry.get("role", "") or "")),
                    "id": str(entry.get("id", "") or ""),
                    "name": "",
                    "intent": str(entry.get("intent", "") or ""),
                    "final_report_ref": str(entry.get("final_report_ref", "") or ""),
                    "uploaded_files": entry.get("uploaded_files") or [],
                    **_flatten_graph_context(entry.get("graph_context")),
                }
                for entry in conversation_log
                if isinstance(entry, dict)
            ]

        messages = channel_values.get("messages") or []

        formatted_messages = []
        for msg in messages:
            msg_type, content, msg_id, name = self._extract_message_fields(msg)
            if msg_type == "human":
                role = "user"
            elif msg_type == "ai":
                role = "assistant"
            elif msg_type == "system":
                role = "system"
            else:
                role = msg_type or "unknown"

            formatted_messages.append({
                "role": role,
                "content": str(content),
                "type": msg_type,
                "id": msg_id,
                "name": name,
            })

        return formatted_messages

    def _is_thread_deleted(self, thread_id: str) -> bool:
        """Return True when the thread has no live (non-soft-deleted) records.

        A thread is considered live when EITHER its checkpoint row is live
        (legacy LangGraph checkpointer) OR its conversation_messages rows
        are live (unified table written by persist_conversation_memory).
        Both checks are required so that threads persisted via the new
        table — before any checkpoint exists — are still queryable.
        """
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM public.checkpoints
                    WHERE thread_id = %(thread_id)s
                      AND checkpoint_ns = ''
                      AND deleted_at IS NULL
                    LIMIT 1
                    """,
                    {"thread_id": thread_id},
                )
                if cur.fetchone() is not None:
                    return False
                cur.execute(
                    """
                    SELECT 1
                    FROM public.conversation_messages
                    WHERE thread_id = %(thread_id)s
                      AND deleted_at IS NULL
                    LIMIT 1
                    """,
                    {"thread_id": thread_id},
                )
                return cur.fetchone() is None

    @staticmethod
    def _extract_message_fields(msg: Any) -> tuple[str, Any, str, str]:
        """Pull (type, content, id, name) from a LangChain message object or dict."""
        if isinstance(msg, dict):
            return (
                str(msg.get("type", "")),
                msg.get("content", ""),
                str(msg.get("id", "") or ""),
                str(msg.get("name", "") or ""),
            )
        return (
            str(getattr(msg, "type", "") or ""),
            getattr(msg, "content", ""),
            str(getattr(msg, "id", "") or ""),
            str(getattr(msg, "name", "") or ""),
        )

    def delete_thread(self, thread_id: str) -> bool:
        """
        Soft delete a conversation thread by setting deleted_at timestamp.
        Also soft-deletes the corresponding rows in ``conversation_messages``.
        
        Args:
            thread_id: The thread ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        with self.connect() as conn:
            with conn.cursor() as cur:
                # A thread may have display-history rows before its checkpoint
                # becomes visible.  Treat either persistence source as proof
                # that the thread exists.
                cur.execute(
                    """
                    SELECT 1
                    FROM public.checkpoints
                    WHERE thread_id = %(thread_id)s
                      AND checkpoint_ns = ''
                      AND deleted_at IS NULL
                    LIMIT 1
                    """,
                    {"thread_id": thread_id},
                )
                checkpoint_exists = cur.fetchone() is not None
                cur.execute(
                    """
                    SELECT 1
                    FROM public.conversation_messages
                    WHERE thread_id = %(thread_id)s
                      AND deleted_at IS NULL
                    LIMIT 1
                    """,
                    {"thread_id": thread_id},
                )
                message_exists = cur.fetchone() is not None
                if not checkpoint_exists and not message_exists:
                    return False

                # Soft delete checkpoints
                cur.execute(
                    """
                    UPDATE public.checkpoints
                    SET deleted_at = NOW()
                    WHERE thread_id = %(thread_id)s
                      AND deleted_at IS NULL
                    """,
                    {"thread_id": thread_id},
                )
                
                deleted = cur.rowcount > 0 or message_exists
                cur.execute(
                    """
                    UPDATE public.thread_metadata
                    SET status = 'deleted', deleted_at = NOW(), updated_at = NOW()
                    WHERE thread_id = %(thread_id)s AND status = 'active'
                    """,
                    {"thread_id": thread_id},
                )
                conn.commit()
                
                # Soft delete unified message table (best-effort)
                try:
                    self._msg_repo.soft_delete_by_thread(thread_id)
                except Exception as exc:
                    LOGGER.warning("delete_thread_msg_repo_failed thread_id=%s error=%s", thread_id, exc)
                
                return deleted

    def _safe_int(self, value: Any) -> int:
        """Safely convert value to int."""
        try:
            return int(value) if value is not None else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _format_timestamp(value: Any) -> str | None:
        """Return timestamps in the string shape exposed by the HTTP API."""
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _generate_thread_title(self, thread_data: dict[str, Any]) -> str:
        """Generate a readable title for a thread based on its data."""
        case_id = thread_data.get("case_id", 0)
        entity_name = thread_data.get("entity_name", "")
        last_query = thread_data.get("last_query", "")
        last_intent = thread_data.get("last_intent", "")
        
        # Priority 1: Use last_query if meaningful
        if last_query and len(last_query.strip()) > 0:
            # Truncate long queries
            if len(last_query) > 50:
                return last_query[:47] + "..."
            return last_query
        
        # Priority 2: Generate from the annual engagement and audited entity.
        if case_id > 0:
            if entity_name:
                return f"年审项目{case_id} - {entity_name}"
            return f"案件{case_id}"
        
        # Priority 3: Use intent
        intent_labels = {
            "full_audit": "完整审计",
            "drilldown": "下钻追问",
            "re_audit": "修正重审",
        }
        if last_intent in intent_labels:
            return intent_labels[last_intent]
        
        # Fallback
        return "新对话"


@lru_cache(maxsize=1)
def get_conversation_service() -> ConversationService:
    """Get the singleton conversation service instance."""
    settings = get_settings()
    return ConversationService(dsn=settings.postgres_checkpointer_dsn)
