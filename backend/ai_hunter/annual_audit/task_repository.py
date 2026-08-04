"""Annual engagement task repository backed by isolated MySQL."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .engagement_repository import get_engagement
from .storage import mysql_connection


def _serializable(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in row.items()
    }


def create_task_batch(
    engagement_id: int,
    tasks: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    get_engagement(engagement_id, settings=resolved)
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            for task in tasks:
                action = str(task.get("action") or "").strip()
                if not action:
                    skipped.append({"reason": "action为空", "task": task})
                    continue
                try:
                    cursor.execute(
                        """
                        SELECT id AS task_id, status FROM annual_task
                        WHERE engagement_id = %s AND action = %s
                          AND status != '已取消' AND deleted_at IS NULL
                        LIMIT 1
                        """,
                        (engagement_id, action),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        skipped.append(
                            {
                                "reason": "任务已存在",
                                "task_id": int(existing["task_id"]),
                                "action": action,
                                "status": existing["status"],
                            }
                        )
                        continue
                    cursor.execute(
                        """
                        INSERT INTO annual_task (
                          engagement_id, task_no, action, detail, assigned_role,
                          deadline, deliverable, priority, source_engine, status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '待执行')
                        """,
                        (
                            engagement_id,
                            task.get("task_no"),
                            action,
                            task.get("detail"),
                            task.get("assigned_role") or task.get("role"),
                            task.get("deadline") or None,
                            task.get("deliverable") or task.get("delivery"),
                            task.get("priority") or "中",
                            task.get("source_engine") or task.get("engine") or "annual_audit",
                        ),
                    )
                    created.append(
                        {
                            "task_id": int(cursor.lastrowid),
                            "task_no": task.get("task_no"),
                            "action": action,
                        }
                    )
                except Exception as exc:
                    failed.append({"action": action, "error": str(exc)[:500]})
            connection.commit()
    return {
        "case_id": engagement_id,
        "tasks_created": len(created),
        "tasks_skipped": len(skipped),
        "tasks_failed": len(failed),
        "tasks": created,
        "skipped": skipped,
        "failed": failed,
    }


def manage_tasks(
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    engagement_id = int(payload.get("case_id") or 0)
    get_engagement(engagement_id, settings=resolved)
    action = str(payload.get("action") or "").strip().lower()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            if action == "list":
                sql = """
                    SELECT id AS task_id, task_no, action, detail, assigned_role,
                           assigned_to, deadline, deliverable, priority, source_engine,
                           status, completion_note, started_at, completed_at,
                           created_at, updated_at
                    FROM annual_task
                    WHERE engagement_id=%s AND deleted_at IS NULL
                """
                params: list[Any] = [engagement_id]
                if payload.get("filter_status"):
                    sql += " AND status=%s"
                    params.append(payload["filter_status"])
                sql += " ORDER BY FIELD(priority,'紧急','高','中','低'), deadline, id"
                cursor.execute(sql, tuple(params))
                tasks = [_serializable(dict(row)) for row in cursor.fetchall()]
                return {"case_id": engagement_id, "total": len(tasks), "tasks": tasks}
            if action == "summary":
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total,
                      SUM(status='待执行') AS pending,
                      SUM(status='进行中') AS in_progress,
                      SUM(status='已完成') AS completed,
                      SUM(status='逾期') AS overdue,
                      SUM(priority='紧急') AS urgent,
                      MIN(CASE WHEN status IN ('待执行','进行中') THEN deadline END) AS nearest_deadline
                    FROM annual_task
                    WHERE engagement_id=%s AND deleted_at IS NULL
                    """,
                    (engagement_id,),
                )
                return _serializable(dict(cursor.fetchone()))
            task_id = int(payload.get("task_id") or 0)
            cursor.execute(
                "SELECT id FROM annual_task WHERE id=%s AND engagement_id=%s AND deleted_at IS NULL",
                (task_id, engagement_id),
            )
            if not cursor.fetchone():
                raise ValueError(f"年审项目 {engagement_id} 下不存在任务 {task_id}")
            if action == "update":
                new_status = str(payload.get("new_status") or "").strip()
                if not new_status:
                    raise ValueError("update需要new_status")
                cursor.execute(
                    """
                    UPDATE annual_task
                    SET status=%s,
                        started_at=CASE WHEN %s='进行中' THEN COALESCE(started_at,NOW(6)) ELSE started_at END,
                        completed_at=CASE WHEN %s='已完成' THEN NOW(6) ELSE completed_at END,
                        completion_note=CASE WHEN %s='已完成' THEN %s ELSE completion_note END
                    WHERE id=%s AND engagement_id=%s
                    """,
                    (
                        new_status,
                        new_status,
                        new_status,
                        new_status,
                        payload.get("completion_note") or "",
                        task_id,
                        engagement_id,
                    ),
                )
                connection.commit()
                return {"task_id": task_id, "new_status": new_status, "message": "任务状态已更新"}
            if action == "assign":
                assigned_to = str(payload.get("assigned_to") or "").strip()
                if not assigned_to:
                    raise ValueError("assign需要assigned_to")
                cursor.execute(
                    "UPDATE annual_task SET assigned_to=%s WHERE id=%s AND engagement_id=%s",
                    (assigned_to, task_id, engagement_id),
                )
                connection.commit()
                return {"task_id": task_id, "assigned_to": assigned_to, "message": "任务已指派"}
    raise ValueError(f"不支持的action: {action}")


__all__ = ["create_task_batch", "manage_tasks"]
