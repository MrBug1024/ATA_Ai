"""案件权威文字订正服务（Tier 2 决策三）。

把会话内 prompt 叠加升级为案件级权威订正：写库（authoritative）、加载期应用、
跨会话/跨人生效、全程可追溯。表见 sql/case_corrections.sql。

- add_correction：写一条 active 订正；同 (case_id, target) 已有 active 的自动置 superseded
  （最新权威覆盖，apply 端只见一条/标的；旧值保留作历史可追溯）。
- list_corrections：默认只返 active（加载期应用用）；include_history=True 返全部（追溯审计用）。
- revoke_correction：人工撤销 → status='revoked'。

纯数据层，不调 LLM。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from ..settings import get_settings


VALID_STATUSES = ("active", "superseded", "revoked")


class CorrectionService:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    def add_correction(
        self,
        case_id: int,
        *,
        target: str,
        instruction: str,
        source_query: str = "",
        operator_id: str = "",
        operator_name: str = "",
        operator_meta: dict[str, Any] | None = None,
        scope: str = "全案",
        origin: str = "chat",
    ) -> dict[str, Any]:
        """写一条权威订正。同标的已有 active 订正先自动置 superseded（指向新 id）。"""
        meta_json = json.dumps(operator_meta or {}, ensure_ascii=False)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.case_correction "
                "(case_id, target, instruction, source_query, operator_id, operator_name, "
                " operator_meta, scope, origin, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,'active') RETURNING *",
                (case_id, target, instruction, source_query, operator_id, operator_name,
                 meta_json, scope, origin),
            )
            new_row = dict(cur.fetchone())
            # 自动 supersede：同案同标的的其它 active 订正 → superseded，superseded_by=新 id
            if target:
                cur.execute(
                    "UPDATE public.case_correction "
                    "SET status='superseded', superseded_by=%s, updated_at=now() "
                    "WHERE case_id=%s AND target=%s AND status='active' AND id<>%s",
                    (new_row["id"], case_id, target, new_row["id"]),
                )
            conn.commit()
        return new_row

    def list_corrections(self, case_id: int, *, include_history: bool = False) -> list[dict[str, Any]]:
        """默认只返 active（最新优先）；include_history=True 返全部含 superseded/revoked。"""
        sql = (
            "SELECT * FROM public.case_correction WHERE case_id=%s "
            + ("" if include_history else "AND status='active' ")
            + "ORDER BY created_at DESC, id DESC"
        )
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (case_id,))
            return [dict(r) for r in cur.fetchall()]

    def revoke_correction(self, case_id: int, correction_id: int) -> dict[str, Any] | None:
        """人工撤销一条订正（status='revoked'）。不存在返回 None。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE public.case_correction SET status='revoked', updated_at=now() "
                "WHERE id=%s AND case_id=%s RETURNING *",
                (correction_id, case_id),
            )
            row = cur.fetchone()
            conn.commit()
        return dict(row) if row else None


@lru_cache(maxsize=1)
def get_correction_service() -> CorrectionService:
    return CorrectionService(dsn=get_settings().postgres_checkpointer_dsn)


# ── 加载期应用：把 active 订正渲染成 state 用的两种形态 ──────────────────────
def load_corrections_for_state(case_id: int) -> dict[str, Any]:
    """从库加载该案 active 订正 → 返回 {user_corrections, correction_records}。

    供 fetch_full_context 在加载期覆盖写入 state，使任何 full_audit（不止 re_audit）、
    任何会话/人都自动应用已存订正。库不可达时返回空（调用方回退原会话叠加）。
    """
    try:
        rows = get_correction_service().list_corrections(case_id)
    except Exception:
        return {}
    if not rows:
        return {"user_corrections": [], "correction_records": []}
    user_corrections = [f"标的：{r.get('target','')} -> 强制指令：{r.get('instruction','')}" for r in rows]
    correction_records = [
        {
            "target": r.get("target", ""),
            "instruction": r.get("instruction", ""),
            "source_query": r.get("source_query", ""),
        }
        for r in rows
    ]
    return {"user_corrections": user_corrections, "correction_records": correction_records}
