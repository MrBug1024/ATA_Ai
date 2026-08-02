"""司法时效看板确定性引擎（Tier 2-5）。

把审计引擎的 deadline_scan 产出归一为「倒计时 + 红黄绿四级」的结构化看板。
倒计时（剩余天数）随日期实时变化，红黄绿分级由本模块**确定性重算**（不信上游
出报告那刻的分类），阈值 env 可配。纯函数、不调 LLM、不读库。

deadline_scan 是外部审计 API 产出，单项字段名未在仓库内固定 → 用**别名列表**容错归一；
真实字段确认后只需调 `_FIELD_ALIASES` 一处映射。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..settings import get_settings

# 上游审计引擎 /api/audit/deadline-scan 的数组键（已对齐 NpaDemo deadline_alerts）：
# expired_alerts / red_alerts / yellow_alerts / green_alerts；都没有则把 dict 里所有 list 值摊平兜底。
_LIST_KEYS = ("expired_alerts", "red_alerts", "yellow_alerts", "green_alerts",
              "safe_alerts", "alerts", "items", "deadlines")

# 单项字段别名（首位为上游 deadline_alerts 表真实列名，其余为容错兜底）：
#   deadline_date / alert_type / related_asset / action_required（+ handler 增强的 suggested_action）。
_FIELD_ALIASES = {
    "due_date": ("deadline_date", "due_date", "deadline", "expire_date", "expiry_date", "到期日", "时限"),
    "asset": ("related_asset", "asset", "target", "subject", "关联资产", "资产"),
    "action": ("suggested_action", "action_required", "action", "advice", "recommended_action", "建议动作", "动作"),
    "type": ("alert_type", "type", "category", "node", "预警类型", "节点"),
}


def _pick(item: dict, key: str) -> str:
    for alias in _FIELD_ALIASES[key]:
        val = item.get(alias)
        if val not in (None, ""):
            return str(val)
    return ""


def _as_ordinal(s: str) -> int | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip()[:10]).toordinal()
    except ValueError:
        return None


def _collect_items(deadline_scan: dict) -> list[dict]:
    """从 deadline_scan 摊平所有条目（兼容多种数组键 / 任意 list 值）。"""
    if not isinstance(deadline_scan, dict):
        return []
    items: list[dict] = []
    used = False
    for key in _LIST_KEYS:
        val = deadline_scan.get(key)
        if isinstance(val, list):
            items.extend(x for x in val if isinstance(x, dict))
            used = True
    if not used:  # 没有已知数组键 → 摊平所有 list 值兜底
        for val in deadline_scan.values():
            if isinstance(val, list):
                items.extend(x for x in val if isinstance(x, dict))
    return items


def compute_deadline_board(
    deadline_scan: dict,
    *,
    today: date | None = None,
    red_days: int | None = None,
    yellow_days: int | None = None,
) -> dict[str, Any]:
    """归一 + 倒计时 + 红黄绿四级（确定性重算）。

    分级：已过期(剩余<0) / 🔴红(0≤剩余≤red_days) / 🟡黄(red<剩余≤yellow) /
    🟢安全(剩余>yellow) / 未知(无到期日)。
    """
    today = today or date.today()
    settings = get_settings()
    red = settings.deadline_red_days if red_days is None else red_days
    yellow = settings.deadline_yellow_days if yellow_days is None else yellow_days
    today_ord = today.toordinal()

    groups: dict[str, list[dict]] = {"expired": [], "red": [], "yellow": [], "safe": [], "unknown": []}
    for raw in _collect_items(deadline_scan):
        due = _pick(raw, "due_date")
        o = _as_ordinal(due)
        entry = {
            **raw,  # 透传上游其它字段
            "type": _pick(raw, "type"),
            "due_date": due,
            "related_asset": _pick(raw, "asset"),
            "action": _pick(raw, "action"),
        }
        if o is None:
            entry["remaining_days"] = None
            groups["unknown"].append(entry)
            continue
        remaining = o - today_ord
        entry["remaining_days"] = remaining
        if remaining < 0:
            entry["level"] = "已过期"
            groups["expired"].append(entry)
        elif remaining <= red:
            entry["level"] = "红"
            groups["red"].append(entry)
        elif remaining <= yellow:
            entry["level"] = "黄"
            groups["yellow"].append(entry)
        else:
            entry["level"] = "安全"
            groups["safe"].append(entry)

    # 组内按剩余天数升序（最紧急在前；未知组保持原序）
    for key in ("expired", "red", "yellow", "safe"):
        groups[key].sort(key=lambda e: e["remaining_days"])

    counts = {k: len(v) for k, v in groups.items()}
    counts["total"] = sum(counts.values())
    return {
        "today": today.isoformat(),
        "thresholds": {"red_days": red, "yellow_days": yellow},
        "counts": counts,
        "groups": groups,
    }
