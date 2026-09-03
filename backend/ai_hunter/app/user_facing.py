"""Formatting helpers for annual-audit text shown to auditors.

Storage keys and schema fields are useful inside the service boundary, but
they do not make a useful audit narrative.  Keep the conversion here so
reports, chat replies, and historical replies use the same vocabulary.
"""

from __future__ import annotations

import re
from email.header import decode_header, make_header
from pathlib import PurePath
from typing import Any


AUDIT_DATASET_LABELS = {
    "trial_balance": "科目余额表",
    "trial_balance_source": "科目余额表源数据",
    "journal_entries": "序时账及凭证明细",
    "journal_entries_source": "序时账及凭证明细源数据",
    "journal_entries_salary_v2": "工资薪酬序时账（版本 2）",
    "receivables": "应收账款及往来明细",
    "receivables_source": "应收账款及往来明细源数据",
    "bank_statements": "银行流水及对账单",
    "bank_statements_source": "银行流水及对账单源数据",
    "financial_statements": "财务报表",
    "financial_statement_notes": "财务报表附注",
    "audit_report": "审计报告",
    "general_ledger": "总账及明细账",
    "accounts_payable": "应付账款及采购往来明细",
    "revenue_support": "收入支持性资料",
    "confirmations": "函证及回函",
    "tax_materials": "纳税申报及税务资料",
    "audit_workpapers": "历史审计底稿",
    "case_materials_readme_ocr": "项目资料说明（识别稿）",
    "bank_confirmation_ocr": "银行函证（识别稿）",
    "tax_gap_ocr": "税务资料缺口说明（识别稿）",
}

PROFILE_FIELD_LABELS = {
    "entity_type": "被审计单位类型",
    "audit_purpose": "审计目的",
    "accounting_framework": "适用会计准则",
    "firm_name": "会计师事务所",
    "engagement_partner": "项目合伙人",
    "signing_cpa_primary": "主签字注册会计师",
    "signing_cpa_secondary": "第二签字注册会计师",
    "data_classification": "数据分级",
    "data_residency": "数据存储地区",
    "model_data_policy": "模型数据使用规则",
}

INTERNAL_FIELD_LABELS = {
    **PROFILE_FIELD_LABELS,
    "case_id": "项目编号",
    "entity_id": "被审计单位编号",
    "file_id": "文件编号",
    "source_file": "来源文件",
    "source_file_id": "来源文件",
    "source_page": "来源页",
    "source_page_id": "页码",
    "source_chunk": "证据位置",
    "source_chunk_id": "证据位置",
    "storage_ref": "文件引用",
    "storage_key": "文件引用",
    "upload_batch_id": "上传批次",
    "document_code": "文档类别",
}

ATTACHMENT_FAILURE_MESSAGES = {
    "FINANCIAL_STATEMENTS_BLOCKED": (
        "用于生成附件的财务报表及附注尚未满足条件。"
        "请先补齐并确认财务报表资料后重新生成附件。"
    ),
    "FINANCIAL_STATEMENTS_MISSING": "尚未提供可用于生成附件的完整财务报表及附注。",
    "FINANCIAL_STATEMENTS_INVALID": "财务报表及附注尚未通过完整性或勾稽校验。",
    "TEMPLATE_VALIDATION_FAILED": "当前启用的模板尚未完成校验，请在模板管理中处理后重新生成附件。",
    "NO_ACTIVE_TEMPLATE": "当前没有可用于生成附件的已激活模板，请先在模板管理中启用合适版本。",
    "REQUIRED_FACT_MISSING": "生成附件所需的项目资料尚未齐备，请补齐后重新生成。",
    "FACT_CONFLICTED": "生成附件所需的项目资料存在待确认差异，请复核后重新生成。",
    "GENERATION_CONTEXT_BLOCKED": "当前项目资料尚未满足附件生成条件，请检查资料和模板配置后重试。",
    "REPORT_NOT_FOUND": "未找到可用于生成附件的已保存审计报告。",
}

_RFC2047_WORD_RE = re.compile(r"=\?[^?\s]+\?[bqBQ]\?[^?]*\?=")
_FILENAME_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_./:-])"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9_. -]*\.(?:xlsx|xlsm|xls|csv|pdf|docx|doc|txt|md|png|jpe?g))"
    r"(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)
_INTERNAL_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    + r"(?:"
    + "|".join(re.escape(key) for key in sorted(AUDIT_DATASET_LABELS, key=len, reverse=True))
    + r")"
    + r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_INTERNAL_FIELD_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    + r"(?:"
    + "|".join(re.escape(key) for key in sorted(INTERNAL_FIELD_LABELS, key=len, reverse=True))
    + r")"
    + r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_ERROR_CODE_PARENS_RE = re.compile(
    r"\s*[（(]\s*(?:错误码|error\s*code)\s*[:：]\s*`?[A-Z][A-Z0-9_]{2,}`?\s*[）)]",
    re.IGNORECASE,
)
_ERROR_CODE_RE = re.compile(r"(?<![A-Z0-9_])(?P<code>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![A-Z0-9_])")
_EVIDENCE_LOCATOR_WITH_QUOTE_RE = re.compile(
    r"证据锚点\s*[：:]\s*"
    r"(?:source_file_id|file_id|文件编号|来源文件)\s*=\s*\d+"
    r"(?:[\s,，;；]+)(?:source_page_id|page|页码|来源页)\s*=\s*\d+"
    r"(?:[\s,，;；]+)(?:source_chunk_id|chunk|证据位置|证据片段)\s*=\s*[^|\n]+\|\s*",
    re.IGNORECASE,
)
_EVIDENCE_LOCATOR_ONLY_RE = re.compile(
    r"证据锚点\s*[：:]\s*"
    r"(?:source_file_id|file_id|文件编号|来源文件)\s*=\s*\d+"
    r"(?:[\s,，;；]+)(?:source_page_id|page|页码|来源页)\s*=\s*\d+"
    r"(?:[\s,，;；]+)(?:source_chunk_id|chunk|证据位置|证据片段)\s*=\s*[^\n]+",
    re.IGNORECASE,
)


def decode_rfc2047_text(value: object) -> str:
    """Decode RFC-2047 words without failing a visible reply on bad metadata."""

    text = str(value or "")

    def replace(match: re.Match[str]) -> str:
        encoded = match.group(0)
        try:
            return str(make_header(decode_header(encoded)))
        except (LookupError, UnicodeError, ValueError):
            return encoded

    return _RFC2047_WORD_RE.sub(replace, text)


def audit_dataset_label(value: object, *, fallback: str = "") -> str:
    """Return a Chinese business label for a known audit dataset or preserve text."""

    raw = decode_rfc2047_text(value).strip()
    if not raw:
        return fallback
    return AUDIT_DATASET_LABELS.get(raw.lower(), raw)


def profile_field_label(value: object) -> str:
    """Return a human-readable project-profile field name."""

    raw = str(value or "").strip()
    return PROFILE_FIELD_LABELS.get(raw.lower(), raw or "项目资料")


def display_file_name(value: object, *, fallback: str = "未命名文件") -> str:
    """Return a decoded, user-facing file name without exposing a path or key."""

    raw = decode_rfc2047_text(value).strip()
    if not raw:
        return fallback
    name = re.split(r"[\\/]", raw)[-1].strip()
    if not name:
        return fallback
    path = PurePath(name)
    label = AUDIT_DATASET_LABELS.get(path.stem.lower())
    return f"{label}{path.suffix}" if label else name


def attachment_failure_message(code: object) -> str:
    """Explain attachment rejection without exposing internal error codes."""

    normalized = str(code or "").strip().upper()
    return ATTACHMENT_FAILURE_MESSAGES.get(
        normalized,
        "附件暂未生成，请检查项目资料完整性和模板配置后重新生成。",
    )


def humanize_audit_text(value: Any) -> str:
    """Normalize machine-oriented audit prose before it reaches a chat bubble.

    This is deliberately a presentation safeguard, not a storage migration:
    raw keys remain usable for evidence resolution while every user-visible
    answer consistently uses decoded names and business labels.
    """

    if not isinstance(value, str):
        return ""
    text = decode_rfc2047_text(value)
    text = _FILENAME_TOKEN_RE.sub(lambda match: display_file_name(match.group("name")), text)
    # A citation marker remains in the claim line for the UI to resolve. The
    # visible appendix only needs the evidence quotation, never storage IDs.
    text = _EVIDENCE_LOCATOR_WITH_QUOTE_RE.sub("证据摘录：", text)
    text = _EVIDENCE_LOCATOR_ONLY_RE.sub("证据摘录：已关联可回溯证据", text)
    text = _INTERNAL_IDENTIFIER_RE.sub(lambda match: audit_dataset_label(match.group(0)), text)
    text = _INTERNAL_FIELD_RE.sub(
        lambda match: INTERNAL_FIELD_LABELS.get(match.group(0).lower(), match.group(0)),
        text,
    )
    text = _ERROR_CODE_PARENS_RE.sub("", text)
    text = _ERROR_CODE_RE.sub(
        lambda match: ATTACHMENT_FAILURE_MESSAGES.get(match.group("code"), "系统处理限制"),
        text,
    )
    return re.sub(r"[ \t]{2,}", " ", text).strip()


__all__ = [
    "ATTACHMENT_FAILURE_MESSAGES",
    "AUDIT_DATASET_LABELS",
    "INTERNAL_FIELD_LABELS",
    "PROFILE_FIELD_LABELS",
    "attachment_failure_message",
    "audit_dataset_label",
    "decode_rfc2047_text",
    "display_file_name",
    "humanize_audit_text",
    "profile_field_label",
]
