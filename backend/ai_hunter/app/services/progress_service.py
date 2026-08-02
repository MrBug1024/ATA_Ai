"""回款闭环与进度看板服务（Tier1-3 Phase 1）。

三表：case_progress / recovery_record / recovery_forecast（见 sql/recovery_progress.sql）。
提供 CRUD + 看板聚合（催收/利润提醒，规则可 env 配）+ 预期回款种子化。
纯数据层，不调 LLM。金额内部存元。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from ..settings import get_settings

VALID_STAGES = (
    "资料录入", "智能初选", "实地尽调", "投委会决策", "资产确权", "执行处置", "审计复盘", "已归档",
)
VALID_STATUSES = ("进行中", "暂停", "已结案", "已归档")


def _overdue_days() -> int:
    return max(0, int(get_settings().recovery_overdue_days))


def _profit_threshold_pct() -> float:
    return float(get_settings().profit_distribution_threshold_pct)


def _num(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def build_board_view(
    case_id: int,
    progress: dict[str, Any],
    forecasts: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    today: date | None = None,
    overdue_days: int | None = None,
    profit_threshold_pct: float | None = None,
) -> dict[str, Any]:
    """纯函数：把进度/预期/收款聚合成看板视图 + 催收/利润提醒（规则可注入，默认读 env）。"""
    from ..graph.metrics_engine import format_amount

    def wan(v) -> str:
        return format_amount(v, "report")  # 万元 / 4 位 / 无千分位

    today = today or date.today()
    overdue_days = _overdue_days() if overdue_days is None else overdue_days
    threshold = _profit_threshold_pct() if profit_threshold_pct is None else profit_threshold_pct
    expected_total = _num(progress.get("expected_recovery_total"))
    actual_total = _num(progress.get("actual_recovery_total"))
    profit_distributable = _num(progress.get("profit_distributable"))
    profit_distributed = _num(progress.get("profit_distributed"))

    overdue_cut = today.toordinal() - overdue_days
    overdue_expected = sum(
        _num(f.get("expected_amount"))
        for f in forecasts
        if f.get("expected_date") and f["expected_date"].toordinal() <= overdue_cut
    )
    alerts: list[dict[str, Any]] = []
    collection_gap = round(overdue_expected - actual_total, 2)
    if collection_gap > 0:
        alerts.append({"type": "催收", "level": "warn",
                       "message": f"已到期预期回款 {wan(overdue_expected)} 万元，实收 {wan(actual_total)} 万元，待催收约 {wan(collection_gap)} 万元"})
    ratio_pct = round(actual_total / expected_total * 100, 2) if expected_total > 0 else 0.0
    if expected_total > 0 and ratio_pct >= threshold:
        alerts.append({"type": "利润分配", "level": "info",
                       "message": f"实收已达预期的 {ratio_pct}%（阈值 {threshold}%），可启动利润分配"})
    # 待确认收款（自动抽取，未计入实收总额，需人工确认）
    pending = [r for r in records if r.get("status") == "pending"]
    if pending:
        pending_sum = round(sum(_num(r.get("amount")) for r in pending), 2)
        alerts.append({"type": "待确认收款", "level": "warn",
                       "message": f"有 {len(pending)} 笔自动抽取的收款（合计 {wan(pending_sum)} 万元）待人工确认，确认后才计入实收"})

    # 金额万元伴生字段（看板展示用 _wan 字符串：万元/4位/无千分位；原值仍为元，供计算）
    forecasts_view = [{**f, "expected_amount_wan": wan(f.get("expected_amount"))} for f in forecasts]
    records_view = [{**r, "amount_wan": wan(r.get("amount"))} for r in records]

    return {
        "case_id": case_id,
        "stage": progress.get("stage"),
        "status": progress.get("status"),
        "risk_alerts": progress.get("risk_alerts") or [],
        "expected_recovery_total": expected_total,
        "expected_recovery_total_wan": wan(expected_total),
        "actual_recovery_total": actual_total,
        "actual_recovery_total_wan": wan(actual_total),
        "recovery_ratio_pct": ratio_pct,
        "profit_distributable": profit_distributable,
        "profit_distributable_wan": wan(profit_distributable),
        "profit_distributed": profit_distributed,
        "profit_distributed_wan": wan(profit_distributed),
        "report_ref": progress.get("report_ref", ""),
        "forecasts": forecasts_view,
        "records": records_view,
        "reminders": alerts,
        "params": {"overdue_days": overdue_days, "profit_threshold_pct": threshold},
    }


class ProgressService:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    # ── 进度 ────────────────────────────────────────────────────────────
    def get_progress(self, case_id: int) -> dict[str, Any]:
        """返回案件进度行；不存在则返回带默认值的空进度（不自动建行）。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM public.case_progress WHERE case_id=%s", (case_id,))
            row = cur.fetchone()
        if row:
            return dict(row)
        return {
            "case_id": case_id, "stage": "资料录入", "status": "进行中", "risk_alerts": [],
            "expected_recovery_total": 0, "actual_recovery_total": 0,
            "profit_distributable": 0, "profit_distributed": 0, "report_ref": "",
        }

    def upsert_progress(self, case_id: int, **fields) -> dict[str, Any]:
        """更新阶段/状态/风险/利润等（只更新传入字段）。"""
        allowed = {"stage", "status", "risk_alerts", "expected_recovery_total",
                   "profit_distributable", "profit_distributed", "report_ref"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "stage" in sets and sets["stage"] not in VALID_STAGES:
            raise ValueError(f"invalid stage: {sets['stage']}")
        if "status" in sets and sets["status"] not in VALID_STATUSES:
            raise ValueError(f"invalid status: {sets['status']}")
        if "risk_alerts" in sets:
            sets["risk_alerts"] = json.dumps(sets["risk_alerts"], ensure_ascii=False)
        cols = ["case_id"] + list(sets.keys())
        vals = [case_id] + list(sets.values())
        placeholders = ", ".join(["%s"] * len(cols))
        update_clause = ", ".join(
            f"{k} = EXCLUDED.{k}" for k in sets
        ) + (", " if sets else "") + "updated_at = now()"
        jsonb_cast = lambda c: "%s::jsonb" if c == "risk_alerts" else "%s"
        ph = ", ".join(jsonb_cast(c) for c in cols)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO public.case_progress ({', '.join(cols)}) VALUES ({ph}) "
                f"ON CONFLICT (case_id) DO UPDATE SET {update_clause} RETURNING *",
                vals,
            )
            row = cur.fetchone()
            conn.commit()
        return dict(row)

    # ── 实际收款 ─────────────────────────────────────────────────────────
    # 实收汇总只计 confirmed（待确认 pending 不计入）
    _ACTUAL_SUM = "(SELECT COALESCE(SUM(amount),0) FROM public.recovery_record WHERE case_id=%s AND status='confirmed')"

    def _refresh_actual_total(self, cur, case_id: int) -> None:
        cur.execute(
            "INSERT INTO public.case_progress (case_id, actual_recovery_total) "
            f"VALUES (%s, {self._ACTUAL_SUM}) "
            "ON CONFLICT (case_id) DO UPDATE SET "
            f"actual_recovery_total = {self._ACTUAL_SUM}, updated_at = now()",
            (case_id, case_id, case_id),
        )

    def add_recovery(self, case_id: int, *, amount: float, recovered_at,
                     disposal_path: str = "", related_task_id: str = "",
                     source_desc: str = "", operator: str = "", note: str = "",
                     status: str = "confirmed", origin: str = "manual") -> dict[str, Any]:
        """记一笔实收。人工录入默认 confirmed 计入；自动抽取传 status='pending'（待确认不计入）。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.recovery_record "
                "(case_id, amount, recovered_at, disposal_path, related_task_id, source_desc, operator, note, status, origin) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (case_id, amount, recovered_at, disposal_path, related_task_id, source_desc, operator, note, status, origin),
            )
            rec = dict(cur.fetchone())
            self._refresh_actual_total(cur, case_id)
            conn.commit()
        return rec

    def confirm_recovery(self, case_id: int, record_id: int) -> dict[str, Any] | None:
        """把一笔待确认收款标记为已确认，并刷新实收汇总。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE public.recovery_record SET status='confirmed' "
                "WHERE id=%s AND case_id=%s RETURNING *",
                (record_id, case_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            self._refresh_actual_total(cur, case_id)
            conn.commit()
        return dict(row)

    def list_recovery(self, case_id: int, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM public.recovery_record WHERE case_id=%s ORDER BY recovered_at DESC, id DESC LIMIT %s",
                (case_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    # ── 预期回款 ─────────────────────────────────────────────────────────
    def seed_forecast(self, case_id: int, *, report_ref: str, tranches: list[dict[str, Any]]) -> int:
        """种子化预期回款（报告出完后调用）：清掉同案旧预期，写入本次三档，并回填进度总额。"""
        total = sum(_num(t.get("expected_amount")) for t in tranches)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM public.recovery_forecast WHERE case_id=%s AND basis='报告NPV'", (case_id,))
            for t in tranches:
                cur.execute(
                    "INSERT INTO public.recovery_forecast "
                    "(case_id, tranche, expected_amount, expected_date, basis, report_ref) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (case_id, str(t.get("tranche", "")), _num(t.get("expected_amount")),
                     t.get("expected_date"), t.get("basis", "报告NPV"), report_ref),
                )
            cur.execute(
                "INSERT INTO public.case_progress (case_id, expected_recovery_total, report_ref) "
                "VALUES (%s,%s,%s) ON CONFLICT (case_id) DO UPDATE SET "
                "expected_recovery_total=EXCLUDED.expected_recovery_total, report_ref=EXCLUDED.report_ref, updated_at=now()",
                (case_id, total, report_ref),
            )
            conn.commit()
        return len(tranches)

    def list_forecast(self, case_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM public.recovery_forecast WHERE case_id=%s ORDER BY created_at DESC, id DESC",
                (case_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    # ── 看板聚合（催收/利润提醒，规则可配）────────────────────────────────
    def build_board(self, case_id: int) -> dict[str, Any]:
        return build_board_view(
            case_id,
            self.get_progress(case_id),
            self.list_forecast(case_id),
            self.list_recovery(case_id),
        )


@lru_cache(maxsize=1)
def get_progress_service() -> ProgressService:
    return ProgressService(dsn=get_settings().postgres_checkpointer_dsn)
