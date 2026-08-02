"""Stable identity helpers for entities, relations, and graph status defaults."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation


DEFAULT_GRAPH_STATUS = "active"


def normalize_entity_name(name: str) -> str:
    """Normalize entity names so trivial OCR punctuation and spacing noise does not churn keys."""
    cleaned = re.sub(r"\s+", "", name or "")
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    return cleaned.strip()


def build_entity_key(*, case_id: int, entity_type: str, normalized_name: str) -> str:
    """Build a stable entity key scoped to one case."""
    raw = f"{case_id}|{(entity_type or 'unknown').strip().lower()}|{normalized_name}"
    return _sha256(raw)


def build_relation_key(
    *,
    case_id: int,
    relation_type: str,
    from_entity_key: str,
    to_entity_key: str,
    relation_label: str = "",
    event_date: str | None = None,
    amount: float | int | str | None = None,
    amount_currency: str = "CNY",
) -> str:
    """Build a stable relation key from normalized semantic identity fields."""
    label = normalize_relation_label(relation_label)
    normalized_amount = normalize_amount_value(amount)
    raw = "|".join(
        [
            str(case_id),
            (relation_type or "").strip().lower(),
            from_entity_key.strip(),
            to_entity_key.strip(),
            label,
            (event_date or "").strip(),
            normalized_amount,
            (amount_currency or "CNY").strip().upper(),
        ]
    )
    return _sha256(raw)


def normalize_relation_label(label: str) -> str:
    """Normalize relation labels for stable-key use."""
    cleaned = re.sub(r"\s+", "", label or "")
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    return cleaned.strip()


def normalize_amount_value(amount: float | int | str | None) -> str:
    """Normalize relation amounts into a stable string form."""
    if amount in (None, ""):
        return ""
    try:
        decimal_value = Decimal(str(amount)).normalize()
    except (InvalidOperation, ValueError):
        return str(amount).strip()
    text = format(decimal_value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def normalize_graph_status(status: str) -> str:
    """Keep graph object status within the currently supported code-level set."""
    normalized = (status or "").strip().lower()
    if normalized in {"active", "superseded", "invalid"}:
        return normalized
    return DEFAULT_GRAPH_STATUS


def map_graph_status_to_claim_review_status(status: str, current_review_status: str = "pending") -> str:
    """Map graph fact status to the closest legacy claim review status when claim.status is unavailable."""
    normalized_status = normalize_graph_status(status)
    normalized_review_status = (current_review_status or "").strip().lower() or "pending"
    if normalized_status == "invalid":
        return "rejected"
    if normalized_status == "superseded":
        return "corrected"
    if normalized_review_status in {"pending", "approved", "rejected", "corrected"}:
        return normalized_review_status
    return "pending"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
