"""File-backed annual-audit template versions.

The logical template tables retain their old JSON columns for migration
compatibility, but actual template files are stored in MinIO and referenced by
``annual_audit_template_file``.  Only those uploaded files are used for
confirmed attachment generation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ai_hunter.app.settings import Settings, get_settings

from .storage import mysql_connection


TEMPLATE_TYPES = (
    "annual_report",
    "financial_statements",
    "notes",
    "audit_workpaper",
    "management_letter",
)

TEMPLATE_TYPE_LABELS = {
    "annual_report": "年度审计报告",
    "financial_statements": "财务报表",
    "notes": "财务报表附注",
    "audit_workpaper": "审计工作底稿",
    "management_letter": "管理建议书",
}

SUPPORTED_TEMPLATE_EXTENSIONS = {
    ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".pdf",
    ".md", ".markdown", ".txt", ".csv",
}


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _safe_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def template_version_ref(template: dict[str, Any]) -> str:
    label = str(template.get("version_label") or "").strip()
    return label or f"{template.get('template_code') or 'template'}-v{int(template.get('version_no') or 0)}"


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
        "status": str(row.get("file_status") or row.get("status") or "active"),
        "created_by": str(row.get("file_created_by") or row.get("created_by") or ""),
        "created_at": _safe_value(row.get("file_created_at") or row.get("created_at")),
    }


def _normalize_template(row: dict[str, Any]) -> dict[str, Any]:
    template_type = str(row.get("template_type") or "")
    return {
        "id": int(row.get("id") or 0),
        "template_code": str(row.get("template_code") or ""),
        "template_type": template_type,
        "template_type_label": TEMPLATE_TYPE_LABELS.get(template_type, template_type),
        "name": str(row.get("name") or ""),
        "description": str(row.get("description") or ""),
        "status": str(row.get("status") or "active"),
        "active_version_no": int(row.get("active_version_no") or 0),
        "created_by": str(row.get("created_by") or ""),
        "created_at": _safe_value(row.get("created_at")),
        "updated_at": _safe_value(row.get("updated_at")),
    }


def _normalize_version(row: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    content = _json_load(row.get("content_json"), {})
    schema = _json_load(row.get("field_schema_json"), {})
    return {
        "id": int(row.get("id") or row.get("version_id") or 0),
        "template_id": int(row.get("template_id") or template.get("id") or 0),
        "template_code": str(row.get("template_code") or template.get("template_code") or ""),
        "template_type": str(row.get("template_type") or template.get("template_type") or ""),
        "version_no": int(row.get("version_no") or 0),
        "version_label": str(row.get("version_label") or ""),
        "status": str(row.get("version_status") or row.get("status") or "draft"),
        "content": content if isinstance(content, dict) else {},
        "field_schema": schema if isinstance(schema, (dict, list)) else {},
        "content_hash": str(row.get("content_hash") or ""),
        "files": [],
        "file_count": 0,
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
               status AS file_status, created_by AS file_created_by,
               created_at AS file_created_at
        FROM annual_audit_template_file
        WHERE template_version_id = %s AND status = 'active'
        ORDER BY id
        """,
        (version_id,),
    )
    return [_normalize_file(dict(row)) for row in cursor.fetchall()]


def _attach_files(cursor: Any, version: dict[str, Any]) -> dict[str, Any]:
    version = dict(version)
    version["files"] = _files_for_version(cursor, int(version["id"]))
    version["file_count"] = len(version["files"])
    return version


def get_active_template_catalog(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Return active template versions that contain uploaded files."""

    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.*, v.id AS version_id, v.template_id, v.version_no,
                       v.version_label, v.status AS version_status,
                       v.content_json, v.field_schema_json, v.content_hash,
                       v.created_by AS version_created_by, v.published_by,
                       v.published_at, v.created_at AS version_created_at
                FROM annual_audit_template t
                JOIN annual_audit_template_version v
                  ON v.template_id = t.id AND v.version_no = t.active_version_no
                WHERE t.status = 'active' AND v.status = 'active'
                  AND EXISTS (
                    SELECT 1 FROM annual_audit_template_file f
                    WHERE f.template_version_id = v.id AND f.status = 'active'
                  )
                ORDER BY t.template_type, t.template_code
                """
            )
            catalog: dict[str, dict[str, Any]] = {}
            for raw in cursor.fetchall():
                row = dict(raw)
                template = _normalize_template(row)
                version = _attach_files(cursor, _normalize_version(row, template))
                template.update(
                    {
                        "active_version": version,
                        "version_no": version["version_no"],
                        "version_label": version["version_label"],
                        "content": version["content"],
                        "field_schema": version["field_schema"],
                        "content_hash": version["content_hash"],
                        "files": version["files"],
                    }
                )
                catalog[template["template_type"]] = template
    return catalog


def list_templates(
    *,
    template_type: str | None = None,
    include_versions: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            where = "WHERE 1=1"
            params: list[Any] = []
            if template_type:
                where += " AND t.template_type = %s"
                params.append(template_type)
            cursor.execute(f"SELECT t.* FROM annual_audit_template t {where} ORDER BY t.template_type, t.template_code", params)
            result: list[dict[str, Any]] = []
            for raw in cursor.fetchall():
                template = _normalize_template(dict(raw))
                cursor.execute(
                    """
                    SELECT v.*, t.template_code, t.template_type
                    FROM annual_audit_template_version v
                    JOIN annual_audit_template t ON t.id = v.template_id
                    WHERE v.template_id = %s ORDER BY v.version_no DESC
                    """,
                    (template["id"],),
                )
                versions = [
                    _attach_files(cursor, _normalize_version(dict(row), template))
                    for row in cursor.fetchall()
                ]
                active = next((v for v in versions if v["version_no"] == template["active_version_no"]), None)
                if active:
                    template.update(
                        {
                            "active_version": active,
                            "version_no": active["version_no"],
                            "version_label": active["version_label"],
                            "content": active["content"],
                            "files": active["files"],
                        }
                    )
                if include_versions:
                    template["versions"] = versions
                result.append(template)
    return {"templates": result, "template_types": TEMPLATE_TYPE_LABELS}


def create_template(
    *,
    template_code: str,
    template_type: str,
    name: str,
    description: str = "",
    content: dict[str, Any] | None = None,
    field_schema: dict[str, Any] | list[Any] | None = None,
    version_label: str = "v1",
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if template_type not in TEMPLATE_TYPES:
        raise ValueError(f"template_type 必须为：{', '.join(TEMPLATE_TYPES)}")
    code = template_code.strip()
    if not code:
        raise ValueError("template_code 不能为空")
    body = content if isinstance(content, dict) else {}
    schema = field_schema if isinstance(field_schema, (dict, list)) else {}
    content_hash = hashlib.sha256(_json_dump(body).encode("utf-8")).hexdigest()
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM annual_audit_template WHERE template_code = %s", (code,))
            if cursor.fetchone():
                raise ValueError(f"模板编码已存在：{code}")
            cursor.execute("SELECT template_code FROM annual_audit_template WHERE template_type = %s", (template_type,))
            existing = cursor.fetchone()
            if existing:
                raise ValueError(f"模板类型 {template_type} 已由 {existing.get('template_code')} 管理，请通过新增版本维护")
            cursor.execute(
                """
                INSERT INTO annual_audit_template
                  (template_code, template_type, name, description, status, created_by)
                VALUES (%s, %s, %s, %s, 'active', %s)
                """,
                (code, template_type, name.strip(), description.strip(), created_by or "system"),
            )
            template_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO annual_audit_template_version
                  (template_id, version_no, version_label, status, content_json,
                   field_schema_json, content_hash, created_by)
                VALUES (%s, 1, %s, 'draft', %s, %s, %s, %s)
                """,
                (template_id, version_label.strip() or "v1", _json_dump(body), _json_dump(schema), content_hash, created_by or "system"),
            )
        connection.commit()
    return {"template_code": code, "version_no": 1, "status": "draft", "template_id": template_id, "file_count": 0}


def create_template_version(
    template_code: str,
    *,
    content: dict[str, Any] | None = None,
    field_schema: dict[str, Any] | list[Any] | None = None,
    version_label: str = "",
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    body = content if isinstance(content, dict) else {}
    resolved = settings or get_settings()
    content_hash = hashlib.sha256(_json_dump(body).encode("utf-8")).hexdigest()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM annual_audit_template WHERE template_code = %s FOR UPDATE", (template_code.strip(),))
            template = dict(cursor.fetchone() or {})
            if not template:
                raise ValueError(f"未找到模板：{template_code}")
            cursor.execute("SELECT COALESCE(MAX(version_no), 0) AS latest FROM annual_audit_template_version WHERE template_id = %s", (int(template["id"]),))
            version_no = int((cursor.fetchone() or {}).get("latest") or 0) + 1
            label = version_label.strip() or f"{template_code}-v{version_no}"
            cursor.execute(
                """
                INSERT INTO annual_audit_template_version
                  (template_id, version_no, version_label, status, content_json,
                   field_schema_json, content_hash, created_by)
                VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
                """,
                (int(template["id"]), version_no, label, _json_dump(body), _json_dump(field_schema if isinstance(field_schema, (dict, list)) else {}), content_hash, created_by or "system"),
            )
        connection.commit()
    return {"template_code": template_code, "template_type": str(template.get("template_type") or ""), "version_no": version_no, "version_label": label, "status": "draft", "content_hash": content_hash, "file_count": 0}


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
    created_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    normalized_name = Path(file_name or "").name.strip()
    normalized_ext = (file_ext or Path(normalized_name).suffix).lower()
    if not normalized_name or normalized_name in {".", ".."}:
        raise ValueError("模板文件名不能为空")
    if normalized_ext not in SUPPORTED_TEMPLATE_EXTENSIONS:
        raise ValueError(f"不支持的模板文件格式：{normalized_ext or normalized_name}")
    if not storage_ref or not storage_sha256 or file_size < 0:
        raise ValueError("模板文件存储信息不完整")
    resolved = settings or get_settings()
    with mysql_connection(resolved) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT v.id, v.status, t.template_code
                FROM annual_audit_template_version v
                JOIN annual_audit_template t ON t.id = v.template_id
                WHERE t.template_code = %s AND v.version_no = %s FOR UPDATE
                """,
                (template_code.strip(), version_no),
            )
            version = dict(cursor.fetchone() or {})
            if not version:
                raise ValueError(f"未找到模板版本：{template_code} v{version_no}")
            if version.get("status") != "draft":
                raise ValueError("已激活或已归档的模板版本不可继续上传文件，请新建版本")
            cursor.execute(
                """
                INSERT INTO annual_audit_template_file
                  (template_version_id, file_name, file_ext, content_type,
                   storage_ref, storage_sha256, file_size, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s)
                """,
                (int(version["id"]), normalized_name, normalized_ext, content_type or "application/octet-stream", storage_ref, storage_sha256, int(file_size), created_by or "system"),
            )
            file_id = int(cursor.lastrowid)
        connection.commit()
    return {"id": file_id, "template_code": template_code, "version_no": version_no, "file_name": normalized_name, "file_ext": normalized_ext, "content_type": content_type or "application/octet-stream", "storage_ref": storage_ref, "storage_sha256": storage_sha256, "file_size": int(file_size), "status": "active"}


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
            cursor.execute("UPDATE annual_audit_template_file SET status = 'deleted' WHERE id = %s", (file_id,))
        connection.commit()
    return {"id": file_id, "template_code": row.get("template_code"), "version_no": int(row.get("version_no") or 0), "storage_ref": row.get("storage_ref"), "status": "deleted", "deleted_by": deleted_by}


def activate_template_version(
    template_code: str,
    version_no: int,
    *,
    published_by: str = "system",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if version_no <= 0:
        raise ValueError("version_no 必须大于 0")
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
            if file_count == 0:
                raise ValueError("模板版本至少上传一个实际模板文件后才能激活")
            cursor.execute("UPDATE annual_audit_template_version SET status = 'archived' WHERE template_id = %s AND status = 'active'", (int(template["id"]),))
            cursor.execute("UPDATE annual_audit_template_version SET status = 'active', published_by = %s, published_at = UTC_TIMESTAMP(6) WHERE id = %s", (published_by or "system", int(target["id"])))
            cursor.execute("UPDATE annual_audit_template SET active_version_no = %s WHERE id = %s", (version_no, int(template["id"])))
        connection.commit()
    return {"template_code": template_code, "template_type": str(template.get("template_type") or ""), "version_no": version_no, "version_label": str(target.get("version_label") or ""), "status": "active", "file_count": file_count}


__all__ = [
    "SUPPORTED_TEMPLATE_EXTENSIONS",
    "TEMPLATE_TYPES",
    "TEMPLATE_TYPE_LABELS",
    "activate_template_version",
    "add_template_file",
    "create_template",
    "create_template_version",
    "delete_template_file",
    "get_active_template_catalog",
    "list_templates",
    "template_version_ref",
]
