"""Stable identity helpers for entities, relations, and graph status defaults."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation


DEFAULT_GRAPH_STATUS = "active"

# 图谱的 entity_type 是实体本体类型，不是业务角色。模型经常把“客户、供应商、
# 被审计单位”等角色直接当成类型输出，因此在进入稳定 key 和数据库前统一一次。
# 这里保留 legacy alias，避免历史数据在前端继续显示为未分类。
ENTITY_TYPE_ALIASES = {
    "audited_entity": "company",
    "audited_company": "company",
    "enterprise": "company",
    "企业": "company",
    "被审计单位": "company",
    "related_party": "organization",
    "关联方": "organization",
    "customer": "organization",
    "客户": "organization",
    "supplier": "organization",
    "供应商": "organization",
    "bank_account": "account",
    "bankaccount": "account",
    "银行账户": "account",
    "ledger": "ledger_account",
    "会计科目": "ledger_account",
    "unknown": "other",
    "未分类": "other",
    "其他": "other",
}

RELATION_TYPE_ALIASES = {
    "": "related_to",
    "related": "related_to",
    "关联": "related_to",
    "相关": "related_to",
}


def normalize_entity_name(name: str) -> str:
    """Normalize entity names so trivial OCR punctuation and spacing noise does not churn keys."""
    cleaned = unicodedata.normalize("NFKC", str(name or ""))
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    return cleaned.strip()


def normalize_entity_type(entity_type: str | None) -> str:
    """Return the canonical entity taxonomy used by extraction, persistence, and UI."""
    normalized = unicodedata.normalize("NFKC", str(entity_type or "")).strip().lower()
    normalized = re.sub(r"[\s-]+", "_", normalized)
    return ENTITY_TYPE_ALIASES.get(normalized, normalized or "other")


def normalize_relation_type(relation_type: str | None) -> str:
    """Return a non-empty relation code while preserving domain-specific relation types."""
    normalized = unicodedata.normalize("NFKC", str(relation_type or "")).strip().lower()
    normalized = re.sub(r"[\s-]+", "_", normalized)
    return RELATION_TYPE_ALIASES.get(normalized, normalized or "related_to")


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
