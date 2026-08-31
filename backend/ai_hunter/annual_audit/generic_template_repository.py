"""Generic template-version and template-file registry.

The registry is deliberately not tied to the annual-audit document types.
Annual-audit generation uses the optional ``template_usage`` value on a file
to select the relevant active file; other business lines can use the same
version/file registry without adding another table family.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.app.settings import Settings, get_settings

from .storage import mysql_connection


SUPPORTED_TEMPLATE_EXTENSIONS = {
    ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".pdf",
    ".md", ".markdown", ".txt", ".csv",
}

ANNUAL_TEMPLATE_USAGE_LABELS = {
    "annual_report": "年度审计报告",
    "financial_statements": "财务报表",
    "notes": "财务报表附注",
    "audit_workpaper": "审计工作底稿（过程资料）",
    "management_letter": "管理建议书",
    "confirmations": "函证模板（过程资料）",
}

CORE_ANNUAL_TEMPLATE_USAGES = (
    "annual_report",
    "financial_statements",
    "notes",
)

# Business-line/template-type keys are intentionally shared by the generic
# registry.  Only annual_audit is wired to the current AI delivery flow; the
# other keys keep the registry ready for later business lines without making
# users type arbitrary values.
TEMPLATE_TYPE_LABELS = {
    "annual_audit": "年度审计",
    "bookkeeping": "代理记账",
    "tax_filing": "税务业务",
}

ANNUAL_TEMPLATE_BUSINESS_LINES = {
    "annual_audit",
    "年度审计",
    "年度财务报表审计",
    "年度财务报表审计业务",
}

_USAGE_ALIASES = {
    **{value: key for key, value in ANNUAL_TEMPLATE_USAGE_LABELS.items()},
    "审计报告": "annual_report",
    "报表": "financial_statements",
    "附注": "notes",
    "工作底稿": "audit_workpaper",
    "管理建议": "management_letter",
    "函证": "confirmations",
    "询证": "confirmations",
}

_TEMPLATE_TYPE_ALIASES = {
    **{label: key for key, label in TEMPLATE_TYPE_LABELS.items()},
    "annual_audit": "annual_audit",
    "年度财务报表审计": "annual_audit",
    "年度财务报表审计业务": "annual_audit",
    "代理记账业务": "bookkeeping",
    "税务申报": "tax_filing",
}


def _json_load(value: Any, default: Any) -> Any:
    """Decode JSON columns while keeping old rows backward compatible."""

    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def normalize_template_usage(value: str) -> str:
    raw = str(value or "").strip()
    return _USAGE_ALIASES.get(raw, raw)


def normalize_template_type(value: str) -> str:
    raw = str(value or "").strip()
    return _TEMPLATE_TYPE_ALIASES.get(raw, raw)


def template_type_label(value: str) -> str:
    normalized = normalize_template_type(value)
    return TEMPLATE_TYPE_LABELS.get(normalized, str(value or ""))


def _template_type_aliases(value: str) -> list[str]:
    normalized = normalize_template_type(value)
    aliases = [normalized]
    aliases.extend(key for key, target in _TEMPLATE_TYPE_ALIASES.items() if target == normalized and key not in aliases)
    return aliases


def is_annual_audit_business_line(value: str) -> bool:
    normalized = normalize_template_type(value).lower()
    return normalized == "annual_audit"


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _safe_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def template_version_ref(version: dict[str, Any]) -> str:
    label = str(version.get("version_label") or "").strip()
    return label or f"{version.get('template_code') or 'template'}-v{int(version.get('version_no') or 0)}"


def _normalize_file(row: dict[str, Any]) -> dict[str, Any]:
    file_name = str(row.get("file_name") or "")
    return {
        "id": int(row.get("file_id") or row.get("id") or 0),
        "template_version_id": int(row.get("template_version_id") or 0),
        "file_name": file_name,
        "file_ext": str(row.get("file_ext") or Path(file_name).suffix.lower()),
        "content_type": str(row.get("content_type") or "application/octet-stream"),
        "storage_ref": str(row.get("storage_ref") or ""),
        "storage_sha256": str(row.get("storage_sha256") or ""),
        "file_size": int(row.get("file_size") or 0),
        "template_usage": str(row.get("template_usage") or ""),
        "template_usage_label": ANNUAL_TEMPLATE_USAGE_LABELS.get(
            normalize_template_usage(str(row.get("template_usage") or "")),
            str(row.get("template_usage") or ""),
        ),
        "remark": str(row.get("remark") or ""),
        "status": str(row.get("file_status") or row.get("status") or "active"),
        "created_by": str(row.get("file_created_by") or row.get("created_by") or ""),
        "created_at": _safe_value(row.get("file_created_at") or row.get("created_at")),
    }


def _template_contract(
    files: list[dict[str, Any]],
    *,
    field_schema: Any = None,
    business_line: str = "",
    version_status: str = "draft",
) -> dict[str, Any]:
    """Expose file, contract and delivery readiness as separate states.

    ``ready_for_core_delivery`` used to mean only that three file usages were
    present.  That was unsafe for annual-audit DOCX templates: a draft could
    look delivery-ready even though it had no executable slot contract.  The
    actual document-byte binding remains an activation-time validation, so a
    draft may be eligible to *request* activation without being described as
    ready for customer delivery.
    """

    usage_counts: dict[str, int] = {}
    for file in files:
        usage = normalize_template_usage(str(file.get("template_usage") or ""))
        if usage:
            usage_counts[usage] = usage_counts.get(usage, 0) + 1
    annual_audit = is_annual_audit_business_line(business_line)
    required_usages = list(CORE_ANNUAL_TEMPLATE_USAGES) if annual_audit else []
    missing = [usage for usage in required_usages if not usage_counts.get(usage)]
    slot_contract_error = (
        _core_docx_slot_contract_error(field_schema, files)
        if annual_audit
        else None
    )
    activation_blockers: list[str] = []
    if annual_audit and missing:
        labels = "、".join(ANNUAL_TEMPLATE_USAGE_LABELS[usage] for usage in missing)
        activation_blockers.append(f"年度审计模板版本缺少核心交付文件：{labels}。")
    legacy_doc_names = [
        Path(str(file.get("file_name") or "")).name
        for file in files
        if normalize_template_usage(str(file.get("template_usage") or ""))
        in ANNUAL_TEMPLATE_USAGE_LABELS
        and str(file.get("file_ext") or Path(str(file.get("file_name") or "")).suffix)
        .lower()
        == ".doc"
    ]
    if annual_audit and legacy_doc_names:
        activation_blockers.append(
            "年度审计客户附件不支持旧版 .doc 模板，请转换为 DOCX 后重新上传："
            f"{'、'.join(legacy_doc_names)}。"
        )
    if slot_contract_error:
        activation_blockers.append(slot_contract_error)

    has_annual_docx = any(
        normalize_template_usage(str(file.get("template_usage") or ""))
        in ANNUAL_TEMPLATE_USAGE_LABELS
        and str(file.get("file_ext") or Path(str(file.get("file_name") or "")).suffix).lower() == ".docx"
        for file in files
    )
    eligible_for_activation_check = (
        not activation_blockers
        and (not annual_audit or bool(files))
    )
    if activation_blockers:
        slot_contract_validation = "blocked"
    elif not has_annual_docx:
        slot_contract_validation = "not_required"
    elif str(version_status or "").lower() == "active":
        slot_contract_validation = "passed_on_activation"
    else:
        slot_contract_validation = "required_on_activation"

    return {
        "required_usages": required_usages,
        "present_usages": sorted(usage_counts),
        "usage_counts": usage_counts,
        "missing_usages": missing,
        "core_files_ready": not missing,
        "declared_docx_slot_contract_ready": annual_audit and not slot_contract_error,
        "activation_blockers": activation_blockers,
        "eligible_for_activation_check": eligible_for_activation_check,
        "slot_contract_validation": slot_contract_validation,
        "ready_for_core_delivery": bool(
            annual_audit
            and str(version_status or "").lower() == "active"
            and not activation_blockers
        ),
    }


def _has_declared_docx_slot_contract(value: Any) -> bool:
    """Check the minimum executable shape before a template is activated.

    The document preflight still validates addresses, source text and SHA-256
    bindings against the actual DOCX.  Activation must at least reject an
    arbitrary nonempty object or an empty slots array, both of which would
    otherwise publish a template that can never be rendered.
    """

    slots = value if isinstance(value, list) else value.get("slots") if isinstance(value, Mapping) else None
    if not isinstance(slots, list) or not slots:
        return False
    return all(
        isinstance(item, Mapping)
        and bool(str(item.get("slot_id") or "").strip())
        and bool(str(item.get("target") or item.get("address") or "").strip())
        for item in slots
    )


def _core_docx_slot_contract_error(
    field_schema: Any,
    files: list[dict[str, Any]],
) -> str | None:
    """Return the activation blocker for any annual-audit DOCX contract gap."""

    docx_files = [
        file
        for file in files
        if normalize_template_usage(str(file.get("template_usage") or ""))
        in ANNUAL_TEMPLATE_USAGE_LABELS
        and str(file.get("file_ext") or Path(str(file.get("file_name") or "")).suffix)
        .lower()
        == ".docx"
    ]
    if not docx_files:
        return None

    docx_schema = (
        field_schema.get("docx")
        if isinstance(field_schema, Mapping)
        else None
    )
    if not isinstance(docx_schema, Mapping):
        docx_schema = field_schema if isinstance(field_schema, Mapping) else {}
    file_names = [Path(str(file.get("file_name") or "")).name for file in docx_files]
    named_contracts = docx_schema.get("slot_contracts") or docx_schema.get("contracts")

    if len(docx_files) == 1:
        has_single_contract = _has_declared_docx_slot_contract(
            docx_schema.get("slot_contract")
        )
        has_named_contract = isinstance(named_contracts, Mapping) and _has_declared_docx_slot_contract(
            named_contracts.get(file_names[0])
        )
        if has_single_contract or has_named_contract:
            return None
        return (
            f"年度审计 DOCX 模板缺少显式槽位契约：{file_names[0]}。"
            "请在 field_schema_json.docx.slot_contract 中配置该文件，"
            "或在 field_schema_json.docx.slot_contracts 中按文件名配置。"
        )

    missing_names = (
        file_names
        if not isinstance(named_contracts, Mapping)
        else [
            file_name
            for file_name in file_names
            if not _has_declared_docx_slot_contract(named_contracts.get(file_name))
        ]
    )
    if not missing_names:
        return None
    return (
        "年度审计 DOCX 模板必须在 "
        "field_schema_json.docx.slot_contracts 中按文件名分别配置："
        f"{'、'.join(missing_names)}。"
    )


def _validate_annual_docx_slot_contracts(
    field_schema: Any,
    files: list[dict[str, Any]],
) -> None:
    """Bind every publishable annual-audit DOCX contract to its exact file.

    A nonempty JSON object is not a usable contract.  Before activation, load
    each final Word template and validate target grammar, source allowlisting,
    original text fingerprints and optional template SHA bindings.  This is a
    read-only check inside the draft-to-active transaction; no invalid version
    can be published and deferred to a customer generation job.
    """

    from .attachment_blueprint_service import bind_docx_slot_contract

    docx_files = [
        file
        for file in files
        if normalize_template_usage(str(file.get("template_usage") or ""))
        in ANNUAL_TEMPLATE_USAGE_LABELS
        and str(file.get("file_ext") or Path(str(file.get("file_name") or "")).suffix)
        .lower()
        == ".docx"
    ]
    if not docx_files:
        return
    minio = get_minio_service()
    for file in docx_files:
        name = Path(str(file.get("file_name") or "")).name
        storage_ref = str(file.get("storage_ref") or "")
        if not storage_ref:
            raise ValueError(f"年度审计 DOCX 模板缺少对象存储引用：{name}")
        try:
            data = minio.get_object_bytes(storage_ref)
        except Exception as exc:
            raise ValueError(f"无法读取年度审计 DOCX 模板：{name}") from exc
        stored_sha = str(file.get("storage_sha256") or "").lower()
        actual_sha = hashlib.sha256(data).hexdigest()
        if stored_sha and stored_sha != actual_sha:
            raise ValueError(f"年度审计 DOCX 模板对象 SHA-256 不一致：{name}")
        try:
            contract = bind_docx_slot_contract(
                data,
                field_schema=field_schema,
                file_name=name,
            )
        except ValueError as exc:
            raise ValueError(f"年度审计 DOCX 槽位契约无效：{name}：{exc}") from exc
        if not contract.get("declared") or not contract.get("slots"):
            raise ValueError(f"年度审计 DOCX 模板缺少可执行槽位契约：{name}")


def _normalize_version(row: dict[str, Any], files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    content = _json_load(row.get("content_json"), {})
    field_schema = _json_load(row.get("field_schema_json"), {})
    normalized_files = list(files or [])
    business_line = normalize_template_type(str(row.get("business_line") or ""))
    version_status = str(row.get("version_status") or row.get("status") or "draft")
    return {
        "id": int(row.get("version_id") or row.get("id") or 0),
        "template_id": int(row.get("template_id") or 0),
        "template_code": str(row.get("template_code") or ""),
        "template_name": str(row.get("template_name") or row.get("name") or ""),
        "business_line": business_line,
        "description": str(row.get("description") or ""),
        "template_status": str(row.get("template_status") or row.get("status") or "active"),
        "active_version_no": int(row.get("active_version_no") or 0),
        "version_no": int(row.get("version_no") or 0),
        "version_label": str(row.get("version_label") or ""),
        "status": version_status,
        "content": content if isinstance(content, dict) else {},
        "field_schema": field_schema if isinstance(field_schema, (dict, list)) else {},
        "content_hash": str(row.get("content_hash") or ""),
        "file_count": int(row.get("file_count") or len(normalized_files)),
        "files": normalized_files,
        "template_contract": _template_contract(
            normalized_files,
            field_schema=field_schema,
            business_line=business_line,
            version_status=version_status,
        ),
        "created_by": str(row.get("version_created_by") or row.get("created_by") or ""),
        "published_by": str(row.get("published_by") or ""),
        "published_at": _safe_value(row.get("published_at")),
        "created_at": _safe_value(row.get("version_created_at") or row.get("created_at")),
    }


def _files_for_version(cursor: Any, version_id: int) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT id AS file_id, template_version_id, file_name, file_ext,
               content_type, storage_ref, storage_sha256, file_size,
               template_usage, remark, status AS file_status,
               created_by AS file_created_by, created_at AS file_created_at
        FROM annual_audit_template_file
        WHERE template_version_id = %s AND status = 'active'
        ORDER BY id
        """,
        (version_id,),
    )
    return [_normalize_file(dict(row)) for row in cursor.fetchall()]


def list_template_versions(*, settings: Settings | None = None) -> dict[str, Any]:
    """Return a flat version list for the generic template-management menu."""

    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id AS template_id, t.template_code, t.name AS template_name,
                       t.business_line, t.description, t.status AS template_status,
                       t.active_version_no, v.id AS version_id, v.version_no,
                       v.version_label, v.status AS version_status,
                       v.content_json, v.field_schema_json, v.content_hash,
                       v.created_by AS version_created_by, v.published_by,
                       v.published_at, v.created_at AS version_created_at,
                       (SELECT COUNT(*) FROM annual_audit_template_file f
                        WHERE f.template_version_id = v.id AND f.status = 'active') AS file_count
                FROM annual_audit_template t
                JOIN annual_audit_template_version v ON v.template_id = t.id
                WHERE t.status <> 'deleted' AND v.status <> 'deleted'
                ORDER BY v.created_at DESC, v.id DESC
                """
            )
            versions = []
            for row in cursor.fetchall():
                normalized = dict(row)
                files = _files_for_version(cursor, int(normalized.get("version_id") or 0))
                versions.append(_normalize_version(normalized, files))
    return {
        "versions": versions,
        "business_lines": sorted({item["business_line"] for item in versions if item["business_line"]}),
        "template_types": TEMPLATE_TYPE_LABELS,
        "template_usage_labels": ANNUAL_TEMPLATE_USAGE_LABELS,
    }


def get_template_version(
    template_code: str,
    version_no: int,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id AS template_id, t.template_code, t.name AS template_name,
                       t.business_line, t.description, t.status AS template_status,
                       t.active_version_no, v.id AS version_id, v.version_no,
                       v.version_label, v.status AS version_status,
                       v.content_json, v.field_schema_json, v.content_hash,
                       v.created_by AS version_created_by, v.published_by,
                       v.published_at, v.created_at AS version_created_at
                FROM annual_audit_template t
                JOIN annual_audit_template_version v ON v.template_id = t.id
                WHERE t.template_code = %s AND v.version_no = %s
                """,
                (template_code.strip(), version_no),
            )
            row = dict(cursor.fetchone() or {})
            if not row:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            return _normalize_version(row, _files_for_version(cursor, int(row["version_id"])))


def create_template_version_record(
    *,
    template_name: str,
    business_line: str,
    version_label: str = "",
    template_code: str = "",
    description: str = "",
    field_schema: dict[str, Any] | list[Any] | None = None,
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    name = template_name.strip()
    if not name:
        raise ValueError("模板名称不能为空")
    line = normalize_template_type(business_line)
    if not line:
        raise ValueError("业务线不能为空")
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            code = template_code.strip()
            if code:
                cursor.execute("SELECT * FROM annual_audit_template WHERE template_code = %s FOR UPDATE", (code,))
                template = dict(cursor.fetchone() or {})
                if not template:
                    cursor.execute(
                        """
                        INSERT INTO annual_audit_template
                          (template_code, template_type, name, business_line, description, status, created_by)
                        VALUES (%s, %s, %s, %s, %s, 'active', %s)
                        """,
                        (code, line, name, line, description.strip(), created_by or "system"),
                    )
                    template = {"id": int(cursor.lastrowid), "template_code": code}
            else:
                aliases = _template_type_aliases(line)
                placeholders = ", ".join(["%s"] * len(aliases))
                cursor.execute(
                    f"""
                    SELECT * FROM annual_audit_template
                    WHERE business_line IN ({placeholders}) AND status <> 'deleted'
                    ORDER BY CASE WHEN active_version_no IS NULL THEN 1 ELSE 0 END, id
                    LIMIT 1 FOR UPDATE
                    """,
                    tuple(aliases),
                )
                template = dict(cursor.fetchone() or {})
                if not template:
                    digest = hashlib.sha1(line.encode()).hexdigest()[:16]
                    code = f"template_{digest}"
                    cursor.execute(
                        """
                        INSERT INTO annual_audit_template
                          (template_code, template_type, name, business_line, description, status, created_by)
                        VALUES (%s, %s, %s, %s, %s, 'active', %s)
                        """,
                        (code, line, name, line, description.strip(), created_by or "system"),
                    )
                    template = {"id": int(cursor.lastrowid), "template_code": code}
                else:
                    code = str(template["template_code"])
            cursor.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS latest FROM annual_audit_template_version WHERE template_id = %s",
                (int(template["id"]),),
            )
            version_no = int((cursor.fetchone() or {}).get("latest") or 0) + 1
            label = version_label.strip() or f"v{version_no}"
            content_hash = hashlib.sha256(b"{}").hexdigest()
            cursor.execute(
                """
                INSERT INTO annual_audit_template_version
                  (template_id, version_no, version_label, status, content_json,
                   field_schema_json, content_hash, created_by)
                VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
                """,
                (
                    int(template["id"]),
                    version_no,
                    label,
                    _json_dump({}),
                    _json_dump(field_schema or {}),
                    content_hash,
                    created_by or "system",
                ),
            )
        connection.commit()
    return {"template_code": code, "template_name": name, "business_line": line, "version_no": version_no, "version_label": label, "status": "draft", "file_count": 0}


def add_template_file(
    template_code: str,
    version_no: int,
    *,
    file_name: str,
    file_ext: str,
    content_type: str,
    storage_ref: str,
    storage_sha256: str,
    file_size: int,
    template_usage: str = "",
    remark: str = "",
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    normalized_name = Path(file_name or "").name.strip()
    normalized_ext = (file_ext or Path(normalized_name).suffix).lower()
    if not normalized_name or normalized_name in {".", ".."}:
        raise ValueError("模板文件名不能为空")
    if normalized_ext not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise ValueError(f"不支持的模板文件格式：{normalized_ext or normalized_name}")
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT v.id, v.status, t.business_line FROM annual_audit_template_version v
                JOIN annual_audit_template t ON t.id = v.template_id
                WHERE t.template_code = %s AND v.version_no = %s FOR UPDATE
                """,
                (template_code.strip(), version_no),
            )
            version = dict(cursor.fetchone() or {})
            if not version:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            if version.get("status") != "draft":
                raise ValueError("已激活或已归档的版本不可修改，请新建版本")
            normalized_usage = normalize_template_usage(template_usage)
            if is_annual_audit_business_line(str(version.get("business_line") or "")) and not normalized_usage:
                raise ValueError("年度审计模板文件必须填写模板用途")
            if (
                is_annual_audit_business_line(str(version.get("business_line") or ""))
                and normalized_ext == ".doc"
            ):
                raise ValueError(
                    "年度审计客户附件不支持旧版 .doc 模板，请转换为 DOCX 后重新上传"
                )
            cursor.execute(
                """
                INSERT INTO annual_audit_template_file
                  (template_version_id, file_name, file_ext, content_type,
                   storage_ref, storage_sha256, file_size, template_usage,
                   remark, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s)
                """,
                (int(version["id"]), normalized_name, normalized_ext, content_type or "application/octet-stream", storage_ref, storage_sha256, int(file_size), normalized_usage, remark.strip(), created_by or "system"),
            )
            file_id = int(cursor.lastrowid)
            _refresh_version_content_hash(cursor, int(version["id"]))
        connection.commit()
    return {"id": file_id, "template_code": template_code, "version_no": version_no, "file_name": normalized_name, "file_ext": normalized_ext, "content_type": content_type or "application/octet-stream", "storage_ref": storage_ref, "storage_sha256": storage_sha256, "file_size": int(file_size), "template_usage": normalize_template_usage(template_usage), "remark": remark.strip(), "status": "active"}


def update_template_version_field_schema(
    template_code: str,
    version_no: int,
    *,
    field_schema: dict[str, Any] | list[Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Replace the declared field schema for one *draft* template version.

    The schema is versioned alongside the uploaded files.  It is deliberately
    editable only before activation so a published template and its explicit
    DOCX slot contract remain immutable.
    """

    if not isinstance(field_schema, (dict, list)):
        raise ValueError("字段配置必须是 JSON 对象或数组")
    try:
        serialized_schema = _json_dump(field_schema)
    except (TypeError, ValueError) as exc:
        raise ValueError("字段配置必须可序列化为 JSON") from exc

    normalized_code = template_code.strip()
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT v.id, v.status
                FROM annual_audit_template_version v
                JOIN annual_audit_template t ON t.id = v.template_id
                WHERE t.template_code = %s AND v.version_no = %s FOR UPDATE
                """,
                (normalized_code, version_no),
            )
            version = dict(cursor.fetchone() or {})
            if not version:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            if version.get("status") != "draft":
                raise ValueError("已激活或已归档的版本不可修改，请新建版本")
            cursor.execute(
                "UPDATE annual_audit_template_version SET field_schema_json = %s WHERE id = %s",
                (serialized_schema, int(version["id"])),
            )
        connection.commit()
    return {
        "template_code": normalized_code,
        "version_no": version_no,
        "status": "draft",
        "field_schema": field_schema,
    }


def delete_template_file(file_id: int, *, deleted_by: str = "system", settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT f.*, v.status AS version_status, t.template_code, v.version_no
                FROM annual_audit_template_file f
                JOIN annual_audit_template_version v ON v.id = f.template_version_id
                JOIN annual_audit_template t ON t.id = v.template_id
                WHERE f.id = %s FOR UPDATE
                """,
                (file_id,),
            )
            row = dict(cursor.fetchone() or {})
            if not row:
                raise ValueError(f"未找到模板文件：{file_id}")
            if row.get("version_status") != "draft":
                raise ValueError("已激活或已归档版本的文件不可删除，请新建版本")
            cursor.execute("DELETE FROM annual_audit_template_file WHERE id = %s", (file_id,))
            _refresh_version_content_hash(cursor, int(row["template_version_id"]))
        connection.commit()
    return {"id": file_id, "template_code": row.get("template_code"), "version_no": int(row.get("version_no") or 0), "storage_ref": row.get("storage_ref"), "status": "deleted", "deleted_by": deleted_by}


def delete_template_version(template_code: str, version_no: int, *, deleted_by: str = "system", settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id AS template_id, t.active_version_no, v.id AS version_id,
                       v.version_label, v.status AS version_status
                FROM annual_audit_template t
                JOIN annual_audit_template_version v ON v.template_id = t.id
                WHERE t.template_code = %s AND v.version_no = %s FOR UPDATE
                """,
                (template_code.strip(), version_no),
            )
            version = dict(cursor.fetchone() or {})
            if not version:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            cursor.execute("SELECT storage_ref FROM annual_audit_template_file WHERE template_version_id = %s", (int(version["version_id"]),))
            refs = [str(row.get("storage_ref") or "") for row in cursor.fetchall() if row.get("storage_ref")]
            cursor.execute("DELETE FROM annual_audit_template_file WHERE template_version_id = %s", (int(version["version_id"]),))
            cursor.execute("DELETE FROM annual_audit_template_version WHERE id = %s", (int(version["version_id"]),))
            if int(version.get("active_version_no") or 0) == version_no:
                cursor.execute("UPDATE annual_audit_template SET active_version_no = NULL WHERE id = %s", (int(version["template_id"]),))
            cursor.execute("SELECT COUNT(*) AS remaining FROM annual_audit_template_version WHERE template_id = %s", (int(version["template_id"]),))
            if int((cursor.fetchone() or {}).get("remaining") or 0) == 0:
                cursor.execute("DELETE FROM annual_audit_template WHERE id = %s", (int(version["template_id"]),))
        connection.commit()
    return {"template_code": template_code, "version_no": version_no, "version_label": version.get("version_label"), "storage_refs": refs, "status": "deleted", "deleted_by": deleted_by}


def activate_template_version(template_code: str, version_no: int, *, published_by: str = "system", settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM annual_audit_template WHERE template_code = %s FOR UPDATE", (template_code.strip(),))
            template = dict(cursor.fetchone() or {})
            if not template:
                raise ValueError(f"未找到模板：{template_code}")
            cursor.execute("SELECT * FROM annual_audit_template_version WHERE template_id = %s AND version_no = %s FOR UPDATE", (int(template["id"]), version_no))
            target = dict(cursor.fetchone() or {})
            if not target:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            cursor.execute("SELECT COUNT(*) AS file_count FROM annual_audit_template_file WHERE template_version_id = %s AND status = 'active'", (int(target["id"]),))
            file_count = int((cursor.fetchone() or {}).get("file_count") or 0)
            if not file_count:
                raise ValueError("版本至少上传一个文件后才能激活")
            if is_annual_audit_business_line(str(template.get("business_line") or "")):
                cursor.execute(
                    """
                    SELECT file_name, file_ext, storage_ref, storage_sha256, template_usage
                    FROM annual_audit_template_file
                    WHERE template_version_id = %s AND status = 'active'
                    """,
                    (int(target["id"]),),
                )
                active_files = [dict(row) for row in cursor.fetchall()]
                legacy_doc_names = [
                    Path(str(row.get("file_name") or "")).name
                    for row in active_files
                    if str(
                        row.get("file_ext")
                        or Path(str(row.get("file_name") or "")).suffix
                    ).lower()
                    == ".doc"
                ]
                if legacy_doc_names:
                    raise ValueError(
                        "年度审计客户附件不支持旧版 .doc 模板，请转换为 DOCX 后重新上传："
                        f"{'、'.join(legacy_doc_names)}。"
                    )
                present = {
                    normalize_template_usage(str(row.get("template_usage") or ""))
                    for row in active_files
                }
                missing = [usage for usage in CORE_ANNUAL_TEMPLATE_USAGES if usage not in present]
                if missing:
                    labels = "、".join(ANNUAL_TEMPLATE_USAGE_LABELS[usage] for usage in missing)
                    raise ValueError(
                        f"年度审计模板版本缺少核心交付文件：{labels}。"
                        "核心交付必须同时配置审计报告、财务报表和财务报表附注。"
                    )
                slot_contract_error = _core_docx_slot_contract_error(
                    _json_load(target.get("field_schema_json"), {}),
                    active_files,
                )
                if slot_contract_error:
                    raise ValueError(slot_contract_error)
                _validate_annual_docx_slot_contracts(
                    _json_load(target.get("field_schema_json"), {}),
                    active_files,
                )
            aliases = _template_type_aliases(str(template.get("business_line") or ""))
            placeholders = ", ".join(["%s"] * len(aliases))
            cursor.execute(
                f"SELECT id FROM annual_audit_template WHERE business_line IN ({placeholders}) AND status <> 'deleted' FOR UPDATE",
                tuple(aliases),
            )
            type_template_ids = [int(row["id"]) for row in cursor.fetchall()]
            id_placeholders = ", ".join(["%s"] * len(type_template_ids))
            cursor.execute(
                f"UPDATE annual_audit_template_version SET status = 'archived' WHERE template_id IN ({id_placeholders}) AND status = 'active'",
                tuple(type_template_ids),
            )
            cursor.execute(
                f"UPDATE annual_audit_template SET active_version_no = NULL WHERE id IN ({id_placeholders})",
                tuple(type_template_ids),
            )
            cursor.execute("UPDATE annual_audit_template_version SET status = 'active', published_by = %s, published_at = UTC_TIMESTAMP(6) WHERE id = %s", (published_by or "system", int(target["id"])))
            cursor.execute("UPDATE annual_audit_template SET active_version_no = %s WHERE id = %s", (version_no, int(template["id"])))
        connection.commit()
    return {"template_code": template_code, "version_no": version_no, "version_label": target.get("version_label"), "status": "active", "file_count": file_count}


def _refresh_version_content_hash(cursor: Any, version_id: int) -> str:
    """Make the version hash describe the uploaded file set, not an empty JSON body."""

    cursor.execute(
        """
        SELECT storage_sha256
        FROM annual_audit_template_file
        WHERE template_version_id = %s AND status = 'active'
        ORDER BY id
        """,
        (version_id,),
    )
    hashes = [str(row.get("storage_sha256") or "") for row in cursor.fetchall()]
    content_hash = hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()
    cursor.execute(
        "UPDATE annual_audit_template_version SET content_hash = %s WHERE id = %s",
        (content_hash, version_id),
    )
    return content_hash


def get_active_template_catalog(
    settings: Settings | None = None,
    *,
    business_line: str | None = "年度审计",
) -> dict[str, dict[str, Any]]:
    """Map active generic template files to annual-audit usages.

    The generic registry is shared by business lines.  Annual-audit
    generation must not accidentally consume a similarly named file from an
    unrelated business line, so the default is intentionally scoped to the
    annual-audit business-line aliases.
    """

    catalog: dict[str, dict[str, Any]] = {}
    versions = list_template_versions(settings=settings).get("versions") or []
    for summary in versions:
        actual_business_line = str(summary.get("business_line") or "")
        if business_line:
            if is_annual_audit_business_line(business_line):
                if not is_annual_audit_business_line(actual_business_line):
                    continue
            elif normalize_template_type(actual_business_line) != normalize_template_type(business_line):
                continue
        if summary.get("status") != "active" or summary.get("active_version_no") != summary.get("version_no"):
            continue
        detail = get_template_version(summary["template_code"], summary["version_no"], settings=settings)
        files_by_usage: dict[str, list[dict[str, Any]]] = {}
        for file in detail.get("files") or []:
            usage = normalize_template_usage(str(file.get("template_usage") or ""))
            # Keep the registry extensible: a future business attachment may
            # declare its own usage key.  The renderer will still require an
            # explicit template slot/data mapping before publication; this
            # catalog layer must not silently discard a valid uploaded file.
            if not usage:
                continue
            files_by_usage.setdefault(usage, []).append(file)
        for usage, files in files_by_usage.items():
            if usage in catalog:
                continue
            catalog[usage] = {
                **detail,
                "template_type": usage,
                "template_type_label": ANNUAL_TEMPLATE_USAGE_LABELS.get(usage, usage),
                "version_label": detail.get("version_label") or template_version_ref(detail),
                "version_no": detail.get("version_no"),
                "files": files,
                "content_hash": detail.get("content_hash") or "",
            }
    return catalog


__all__ = [
    "ANNUAL_TEMPLATE_USAGE_LABELS",
    "ANNUAL_TEMPLATE_BUSINESS_LINES",
    "CORE_ANNUAL_TEMPLATE_USAGES",
    "TEMPLATE_TYPE_LABELS",
    "SUPPORTED_TEMPLATE_EXTENSIONS",
    "activate_template_version",
    "add_template_file",
    "create_template_version_record",
    "delete_template_file",
    "delete_template_version",
    "get_active_template_catalog",
    "get_template_version",
    "is_annual_audit_business_line",
    "list_template_versions",
    "normalize_template_usage",
    "normalize_template_type",
    "template_type_label",
    "template_version_ref",
    "update_template_version_field_schema",
]
