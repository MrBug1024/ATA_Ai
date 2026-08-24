"""Render confirmed annual-audit attachments from uploaded template files."""

from __future__ import annotations

import json
import mimetypes
import re
import tempfile
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from ai_hunter.app.services.minio_service import get_minio_service
from ai_hunter.app.settings import Settings, get_settings
from ai_hunter.platform_core import ArtifactRef

from .storage import mysql_connection
from .generic_template_repository import get_active_template_catalog, template_version_ref


DEFAULT_ATTACHMENT_TYPES = (
    "annual_report",
    "financial_statements",
    "notes",
    "management_letter",
)
OPTIONAL_ATTACHMENT_TYPES = ("confirmations",)

_TOKEN_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}|\[\[\s*([\w.-]+)\s*\]\]|\$\{\s*([\w.-]+)\s*\}")
_YEAR_MARKER_RE = re.compile(r"20\d{2}年(?:12月31日|\s*月\s*日)")
_BRACKET_PLACEHOLDER_RE = re.compile(r"[\[【](?:被审计单位名称|项目合伙人姓名|注册会计师签名|日期|日期|XXXX|XX)[\]】]")
_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_ATTACHMENT_NAME_LABELS = {
    "annual_report": "财务报表审计报告",
    "financial_statements": "财务报表",
    "notes": "财务报表附注",
    "management_letter": "管理建议书",
    "confirmations": "函证",
    "audit_workpaper": "审计工作底稿",
}

_CONTENT_TYPES_BY_SUFFIX = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _load_latest_report(engagement_id: int, settings: Settings) -> dict[str, Any]:
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, report_version, template_version, status, fact_snapshot_json
                FROM audit_report
                WHERE engagement_id = %s AND report_type = 'annual_audit_draft'
                ORDER BY report_version DESC LIMIT 1
                """,
                (engagement_id,),
            )
            row = dict(cursor.fetchone() or {})
    if not row:
        raise ValueError("当前项目尚未生成审计结果，不能生成附件")
    snapshot = row.get("fact_snapshot_json")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError:
            snapshot = {}
    row["snapshot"] = snapshot if isinstance(snapshot, dict) else {}
    return row


def _next_package_version(engagement_id: int, settings: Settings) -> int:
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(MAX(package_version), 0) AS latest FROM annual_audit_attachment_package WHERE engagement_id = %s",
                (engagement_id,),
            )
            return int((cursor.fetchone() or {}).get("latest") or 0) + 1


def _persist_package(
    *,
    engagement_id: int,
    package_version: int,
    status: str,
    template_snapshot: dict[str, Any],
    artifacts: list[dict[str, Any]],
    created_by: str,
    settings: Settings,
) -> int:
    with mysql_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO annual_audit_attachment_package
                  (engagement_id, package_version, status, template_snapshot_json,
                   artifact_refs_json, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    engagement_id,
                    package_version,
                    status,
                    json.dumps(template_snapshot, ensure_ascii=False, default=_json_default),
                    json.dumps(artifacts, ensure_ascii=False, default=_json_default),
                    created_by or "ai_agent",
                ),
            )
            package_id = int(cursor.lastrowid)
        connection.commit()
    return package_id


def _replace_tokens(value: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = next((item for item in match.groups() if item), "")
        if key not in context:
            return match.group(0)
        value = context[key]
        return "" if value is None else str(value)

    return _TOKEN_RE.sub(replace, value)


def _chinese_year(year: int) -> str:
    digits = "〇一二三四五六七八九"
    return "".join(digits[int(char)] for char in str(year))


def _replace_template_markers(value: str, context: dict[str, Any]) -> str:
    """Fill both explicit tokens and the literal markers used by supplied templates.

    The reference documents in ``new_docs`` predate tokenized templates: they
    use phrases such as ``一般企业模板`` and ``【被审计单位名称】``.  Treating
    those phrases as first-class markers is what makes the uploaded customer
    templates useful without mutating the original file.
    """

    result = _replace_tokens(value, context)
    entity_name = str(context.get("entity_name") or "待补充被审计单位")
    fiscal_year = int(context.get("fiscal_year") or 0)
    issue_year = int(context.get("issue_year") or (fiscal_year + 1 if fiscal_year else 0))
    period_end = str(context.get("period_end") or "待补充日期")
    if fiscal_year:
        result = result.replace("二〇二五", _chinese_year(fiscal_year))
        result = result.replace("二○二五", _chinese_year(fiscal_year))
        result = result.replace("2025", str(fiscal_year))
    if issue_year:
        result = result.replace("2026", str(issue_year))
    result = result.replace("一般企业模板", entity_name)
    result = result.replace("XXX公司", entity_name)
    result = result.replace("一般企业", entity_name)
    result = result.replace("【被审计单位名称】", entity_name)
    result = result.replace("[被审计单位名称]", entity_name)
    result = result.replace("【年度】", f"{fiscal_year}年度" if fiscal_year else "待补充年度")
    result = result.replace("【20XX年度】", f"{fiscal_year}年度" if fiscal_year else "待补充年度")
    result = result.replace("20XX年度", f"{fiscal_year}年度" if fiscal_year else "待补充年度")
    result = result.replace("【日期】", period_end)
    result = result.replace("[日期]", period_end)
    result = result.replace("[注册会计师签名]", "待项目组签字")
    result = result.replace("[项目合伙人姓名]", str(context.get("engagement_partner") or "待补充项目合伙人"))
    result = result.replace("[北京今创会计师事务所（普通合伙）盖章]", "待事务所盖章")
    result = result.replace("[在此处报告与业务经营、税务、管理实务相关的建议和说明。]", "详见当前审计结果摘要及后续复核任务。")
    result = _YEAR_MARKER_RE.sub(lambda _: period_end, result)
    result = _BRACKET_PLACEHOLDER_RE.sub("待补充", result)
    # Make unresolved reference-template placeholders explicit instead of
    # leaving the user with misleadingly blank-looking generated content.
    result = re.sub(r"\bXXX\b", "待补充", result)
    result = re.sub(r"\[(?:填入[^\]]+|如适用，[^\]]+|XX+)\]", "待补充", result)
    return result


def _replace_docx_paragraph(paragraph: Any, context: dict[str, Any]) -> bool:
    original = "".join(run.text or "" for run in paragraph.runs)
    if not original:
        return False
    replaced = _replace_template_markers(original, context)
    if replaced == original:
        return False
    if paragraph.runs:
        paragraph.runs[0].text = replaced
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.text = replaced
    return True


def _replace_docx_container(container: Any, context: dict[str, Any]) -> int:
    changed = sum(_replace_docx_paragraph(item, context) for item in container.paragraphs)
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                changed += _replace_docx_container(cell, context)
    return changed


def _set_docx_cell_text(cell: Any, value: Any) -> None:
    text = "" if value is None else str(value)
    if cell.paragraphs:
        paragraph = cell.paragraphs[0]
        if paragraph.runs:
            paragraph.runs[0].text = text
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.text = text
        for paragraph in cell.paragraphs[1:]:
            paragraph.text = ""
    else:
        cell.text = text


def _set_docx_paragraph_text(paragraph: Any, value: str) -> None:
    """Replace paragraph text without replacing its paragraph/style object."""

    if paragraph.runs:
        # Keep the first run (and therefore its character formatting) as the
        # carrier for the replacement. Clearing only run text preserves the
        # paragraph style, numbering, borders and surrounding layout.
        paragraph.runs[0].text = value
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.text = value


def _fill_docx_tables(document: Any, context: dict[str, Any]) -> int:
    """Fill only values that are actually present in the deterministic snapshot."""

    values = context.get("__table_values__") or {}
    if not isinstance(values, dict):
        return 0
    changed = 0
    for table in document.tables:
        for row in table.rows:
            if not row.cells:
                continue
            label = "".join(cell.text or "" for cell in row.cells[:1]).strip()
            key = next((candidate for candidate in values if candidate and candidate in label), "")
            if not key:
                continue
            value = values[key]
            target_index = 2 if len(row.cells) >= 4 else len(row.cells) - 1
            if target_index <= 0:
                continue
            _set_docx_cell_text(row.cells[target_index], value)
            changed += 1
    return changed


def _downgrade_formal_report_opinion(document: Any) -> int:
    """Prevent a reference unmodified-opinion template from becoming a false opinion."""

    changed = 0
    for paragraph in document.paragraphs:
        text = paragraph.text or ""
        if "审计意见" in text and text.strip() in {"一、审计意见", "审计意见"}:
            _set_docx_paragraph_text(paragraph, "一、审计意见（待项目组复核）")
            changed += 1
        elif "我们认为，后附的财务报表在所有重大方面" in text:
            _set_docx_paragraph_text(
                paragraph,
                "本文件为基于当前已导入资料形成的审计报告格式草稿，尚未完成全部审计程序，未形成正式审计意见。",
            )
            changed += 1
    return changed


def _render_docx(data: bytes, context: dict[str, Any]) -> tuple[bytes, str]:
    from docx import Document

    document = Document(BytesIO(data))
    changed = _replace_docx_container(document, context)
    changed += _fill_docx_tables(document, context)
    if context.get("__template_type__") == "annual_report":
        changed += _downgrade_formal_report_opinion(document)
    for section in document.sections:
        changed += _replace_docx_container(section.header, context)
        changed += _replace_docx_container(section.footer, context)
    output = BytesIO()
    document.save(output)
    return output.getvalue(), "filled" if changed else "copied_no_matching_placeholders"


def _render_xlsx(data: bytes, extension: str, context: dict[str, Any]) -> tuple[bytes, str]:
    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(data), keep_vba=extension == ".xlsm")
    changed = 0
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    replaced = _replace_template_markers(cell.value, context)
                    if replaced != cell.value:
                        cell.value = replaced
                        changed += 1
    output = BytesIO()
    workbook.save(output)
    return output.getvalue(), "filled" if changed else "copied_no_matching_placeholders"


def _render_xls(data: bytes, context: dict[str, Any]) -> tuple[bytes, str]:
    """Fill BIFF8 through Excel while keeping the original ``.xls`` format.

    ``xlrd`` is read-only and rebuilding the workbook with ``openpyxl`` turns
    BIFF8 into OOXML, which changes both the extension and the workbook's
    structure.  On Windows deployments with Excel automation available, use
    Excel's own SaveAs(FileFormat=56) path so formulas, styles, merged cells,
    print settings and sheet order remain under the original file format. If
    automation is unavailable, return the original bytes unchanged rather than
    silently delivering a falsely converted workbook.
    """

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return data, "copied_legacy_unmodified"

    changed = 0
    excel = None
    workbook = None
    pythoncom.CoInitialize()
    try:
        with tempfile.TemporaryDirectory(prefix="annual-audit-xls-") as temp_dir:
            source_path = Path(temp_dir) / "source.xls"
            output_path = Path(temp_dir) / "rendered.xls"
            source_path.write_bytes(data)

            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            excel.ScreenUpdating = False
            try:
                # 3 = msoAutomationSecurityForceDisable; templates must never
                # execute embedded macros during server-side rendering.
                excel.AutomationSecurity = 3
            except Exception:
                pass
            workbook = excel.Workbooks.Open(
                str(source_path),
                UpdateLinks=0,
                ReadOnly=False,
                AddToMru=False,
            )
            for worksheet in workbook.Worksheets:
                used_range = worksheet.UsedRange
                row_count = int(used_range.Rows.Count)
                column_count = int(used_range.Columns.Count)
                for row_index in range(1, row_count + 1):
                    for column_index in range(1, column_count + 1):
                        cell = used_range.Cells(row_index, column_index)
                        value = cell.Value
                        if not isinstance(value, str):
                            continue
                        replaced = _replace_template_markers(value, context)
                        if replaced != value:
                            cell.Value = replaced
                            changed += 1

            # 56 is Excel's native Excel 97-2003 Workbook format (.xls).
            workbook.SaveAs(str(output_path), FileFormat=56)
            workbook.Close(SaveChanges=False)
            workbook = None
            excel.Quit()
            excel = None
            return output_path.read_bytes(), (
                "filled" if changed else "copied_no_matching_placeholders"
            )
    except Exception:
        # A headless/service account may not be allowed to automate Excel. Keep
        # the source format intact and let package validation report the
        # limitation; never fall back to an .xlsx reconstruction.
        return data, "copied_legacy_unmodified"
    finally:
        if workbook is not None:
            try:
                workbook.Close(SaveChanges=False)
            except Exception:
                pass
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _legacy_word_replacement_pairs(context: dict[str, Any]) -> dict[str, str]:
    """Return literal pairs safe to apply through Word's Find/Replace API."""

    entity_name = str(context.get("entity_name") or "待补充被审计单位")
    fiscal_year = int(context.get("fiscal_year") or 0)
    issue_year = int(context.get("issue_year") or (fiscal_year + 1 if fiscal_year else 0))
    period_end = str(context.get("period_end") or "待补充日期")
    pairs: dict[str, str] = {}
    for key, value in context.items():
        if key.startswith("__") or isinstance(value, (dict, list, tuple)):
            continue
        replacement = "" if value is None else str(value)
        pairs.update(
            {
                f"{{{{{key}}}}}": replacement,
                f"[[{key}]]": replacement,
                f"${{{key}}}": replacement,
            }
        )
    if fiscal_year:
        pairs.update(
            {
                "二〇二五": _chinese_year(fiscal_year),
                "二○二五": _chinese_year(fiscal_year),
                "2025": str(fiscal_year),
            }
        )
    if issue_year:
        pairs["2026"] = str(issue_year)
    pairs.update(
        {
            "一般企业模板": entity_name,
            "一般企业": entity_name,
            "XXX公司": entity_name,
            "【被审计单位名称】": entity_name,
            "[被审计单位名称]": entity_name,
            "【年度】": f"{fiscal_year}年度" if fiscal_year else "待补充年度",
            "【20XX年度】": f"{fiscal_year}年度" if fiscal_year else "待补充年度",
            "20XX年度": f"{fiscal_year}年度" if fiscal_year else "待补充年度",
            "【日期】": period_end,
            "[日期]": period_end,
        }
    )
    return {needle: replacement for needle, replacement in pairs.items() if needle and needle != replacement}


def _render_doc(data: bytes, context: dict[str, Any]) -> tuple[bytes, str]:
    """Fill legacy binary Word documents without converting them to DOCX."""

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return data, "copied_legacy_unmodified"

    word = None
    document = None
    pythoncom.CoInitialize()
    try:
        with tempfile.TemporaryDirectory(prefix="annual-audit-doc-") as temp_dir:
            source_path = Path(temp_dir) / "source.doc"
            output_path = Path(temp_dir) / "rendered.doc"
            source_path.write_bytes(data)
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            document = word.Documents.Open(
                str(source_path),
                ConfirmConversions=False,
                ReadOnly=False,
                AddToRecentFiles=False,
            )
            changed = 0
            for needle, replacement in _legacy_word_replacement_pairs(context).items():
                for story in document.StoryRanges:
                    current = story
                    while current is not None:
                        find = current.Find
                        find.ClearFormatting()
                        find.Replacement.ClearFormatting()
                        find.Text = needle
                        find.Replacement.Text = replacement
                        find.Forward = True
                        find.Wrap = 1  # wdFindContinue
                        find.Format = False
                        find.MatchCase = False
                        find.MatchWholeWord = False
                        if find.Execute(Replace=2):  # wdReplaceAll
                            changed += 1
                        try:
                            current = current.NextStoryRange
                        except Exception:
                            current = None
            document.SaveAs(str(output_path), FileFormat=0)  # wdFormatDocument
            document.Close(SaveChanges=False)
            document = None
            word.Quit()
            word = None
            return output_path.read_bytes(), "filled" if changed else "copied_no_matching_placeholders"
    except Exception:
        return data, "copied_legacy_unmodified"
    finally:
        if document is not None:
            try:
                document.Close(SaveChanges=False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _render_pdf(data: bytes, context: dict[str, Any]) -> tuple[bytes, str]:
    """Fill matching AcroForm fields when present; otherwise preserve the PDF."""

    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(BytesIO(data))
        fields = reader.get_fields() or {}
        updates: dict[str, str] = {}
        for field_name in fields:
            key = str(field_name).strip()
            if key in context:
                updates[key] = "" if context[key] is None else str(context[key])
        if not updates:
            return data, "copied_no_matching_form_fields"
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        for page in writer.pages:
            writer.update_page_form_field_values(page, updates, auto_regenerate=False)
        output = BytesIO()
        writer.write(output)
        return output.getvalue(), "filled_acroform"
    except Exception:
        return data, "copied_pdf"


def render_template_file(data: bytes, file_name: str, context: dict[str, Any]) -> tuple[bytes, str]:
    """Render a template without changing its original file format."""

    extension = Path(file_name).suffix.lower()
    if extension == ".docx":
        return _render_docx(data, context)
    if extension in {".xlsx", ".xlsm"}:
        return _render_xlsx(data, extension, context)
    if extension == ".xls":
        return _render_xls(data, context)
    if extension == ".doc":
        return _render_doc(data, context)
    if extension in {".md", ".markdown", ".txt", ".csv"}:
        text = data.decode("utf-8-sig")
        replaced = _replace_template_markers(text, context)
        return replaced.encode("utf-8"), "filled" if replaced != text else "copied_no_matching_placeholders"
    if extension == ".pdf":
        return _render_pdf(data, context)
    # Legacy .doc is a binary format that cannot be safely rewritten with the
    # available libraries. It is retained and reported as a partial artifact.
    return data, "copied_legacy_or_unknown_format"


def _context(snapshot: dict[str, Any], report_text: str, package_version: int, template: dict[str, Any], workpaper: dict[str, Any] | None = None, *, template_type: str = "") -> dict[str, Any]:
    engagement = snapshot.get("engagement") or {}
    fiscal_year = engagement.get("fiscal_year") or snapshot.get("fiscal_year") or ""
    period_end = engagement.get("period_end") or snapshot.get("period_end") or ""
    if not period_end and fiscal_year:
        period_end = f"{fiscal_year}-12-31"
    period_end_display = str(period_end)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_end_display):
        period_end_display = f"{period_end_display[0:4]}年{int(period_end_display[5:7])}月{int(period_end_display[8:10])}日"
    issue_year = int(fiscal_year or 0) + 1 if str(fiscal_year).isdigit() else ""
    sales = snapshot.get("sales_receivables") or {}
    revenue = sales.get("revenue") or {}
    receivables = sales.get("receivables") or {}
    table_values = {
        "应收账款": receivables.get("total_balance"),
        "营业收入": revenue.get("net_revenue"),
    }
    values: dict[str, Any] = {
        "entity_name": engagement.get("entity_name") or snapshot.get("entity_name") or "",
        "entity_uscc": engagement.get("entity_uscc") or snapshot.get("entity_uscc") or "",
        "audit_period": f"{fiscal_year}年度" if fiscal_year else "",
        "fiscal_year": fiscal_year,
        "period_end": period_end_display,
        "issue_year": issue_year,
        "engagement_code": engagement.get("engagement_code") or snapshot.get("engagement_code") or "",
        "engagement_partner": engagement.get("engagement_partner") or "",
        "report_text": report_text,
        "audit_result": report_text,
        "report_version": snapshot.get("report_version") or "",
        "template_version": template_version_ref(template),
        "package_version": package_version,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "__template_type__": template_type,
        "__table_values__": table_values,
    }
    if workpaper:
        values.update(
            {
                "workpaper_code": workpaper.get("code") or "",
                "workpaper_name": workpaper.get("name") or "",
            }
        )
    return values


def _safe_filename_part(value: Any, fallback: str) -> str:
    """Return a readable filename segment that is safe on Windows and POSIX."""

    text = _INVALID_FILENAME_CHARS_RE.sub("", str(value or "")).strip().strip(".")
    return text or fallback


def _content_type_for_file_name(file_name: str, fallback: str = "") -> str:
    """Derive content type from the output extension, not the upload hint."""

    suffix = Path(file_name).suffix.lower()
    return _CONTENT_TYPES_BY_SUFFIX.get(
        suffix,
        mimetypes.guess_type(file_name)[0] or fallback or "application/octet-stream",
    )


def _output_name(
    template_type: str,
    engagement_id: int,
    package_version: int,
    source_name: str,
    workpaper_code: str = "",
    output_suffix: str | None = None,
    *,
    context: dict[str, Any] | None = None,
    duplicate_index: int = 0,
    duplicate_count: int = 1,
) -> str:
    """Build a user-facing name while retaining the source file format.

    The old name exposed internal implementation details such as the numeric
    case id and package version.  Those values are useful in metadata, but a
    downloaded attachment must tell the reviewer what it is.  The extension
    always comes from the actual source template, so an ``.xls`` template
    remains an ``.xls`` deliverable and is never renamed to ``.xlsx``.
    """

    suffix = output_suffix or Path(source_name).suffix.lower()
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    source_stem = _safe_filename_part(Path(source_name).stem, "模板文件")
    context = context or {}
    entity_name = _safe_filename_part(context.get("entity_name"), f"项目{engagement_id}")
    year_match = re.search(r"20\d{2}", str(context.get("fiscal_year") or ""))
    fiscal_year = year_match.group(0) if year_match else ""
    year_part = f"{fiscal_year}年度" if fiscal_year else "年度"
    label = _ATTACHMENT_NAME_LABELS.get(template_type, _safe_filename_part(template_type, "审计附件"))

    if template_type == "audit_workpaper":
        base = f"{entity_name}{year_part}{label}"
        if workpaper_code:
            normalized_code = _safe_filename_part(workpaper_code, "底稿")
            # Most supplied workpaper names already start with the code, e.g.
            # ``4101 货币资金.xls``.  Keep that descriptive source stem once
            # instead of producing ``...-4101-4101 货币资金.xls``.
            base += f"-{source_stem if source_stem.lower().startswith(normalized_code.lower()) else normalized_code}"
        elif duplicate_count > 1:
            base += f"-{source_stem}"
    elif template_type == "confirmations":
        base = f"{entity_name}{year_part}{label}"
        if duplicate_count > 1 or source_stem not in {"模板", "函证模板"}:
            base += f"-{source_stem}"
    else:
        base = f"{entity_name}{year_part}{label}"
        if duplicate_count > 1:
            base += f"-{source_stem}"

    if duplicate_index > 0 and duplicate_count <= 1:
        base += f"-{duplicate_index + 1}"
    return f"{_safe_filename_part(base, '审计附件')}{suffix}"


def _infer_workpaper_code(file_name: str) -> str:
    match = re.search(r"(?<![A-Za-z0-9])((?:[A-Z]\d{1,4}|\d{3,4})(?:-\d+)?)(?![A-Za-z0-9])", Path(file_name).stem, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def generate_annual_attachment_package(
    engagement_id: int,
    *,
    created_by: str = "ai_agent",
    requested_types: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Generate attachments from the exact files in active template versions."""

    resolved = settings or get_settings()
    selected_types = tuple(requested_types or DEFAULT_ATTACHMENT_TYPES)
    unknown = [item for item in selected_types if item not in (*DEFAULT_ATTACHMENT_TYPES, *OPTIONAL_ATTACHMENT_TYPES)]
    if unknown:
        raise ValueError(f"不支持的附件类型：{', '.join(unknown)}")

    from .report_service import generate_annual_report_draft

    generated = generate_annual_report_draft(
        engagement_id,
        recompute=False,
        created_by=created_by or "ai_agent",
        settings=resolved,
    )
    report_text = str(generated.get("report_text") or "")
    latest_report = _load_latest_report(engagement_id, resolved)
    snapshot = dict(latest_report.get("snapshot") or {})
    catalog = get_active_template_catalog(settings=resolved)
    # Workpapers and confirmations are process materials, not standard
    # annual-audit delivery attachments.  They remain selectable through an
    # explicit future request, but are never appended implicitly.
    missing = [item for item in selected_types if item not in catalog or not catalog[item].get("files")]
    if missing:
        labels = ", ".join(missing)
        raise ValueError(f"以下附件类型没有已激活且包含实际文件的模板版本：{labels}，请先上传并激活模板文件")

    package_version = _next_package_version(engagement_id, resolved)
    template_snapshot = {
        template_type: {
            "template_code": template.get("template_code"),
            "template_type": template_type,
            "version_no": int(template.get("version_no") or 0),
            "version_label": template_version_ref(template),
            "content_hash": template.get("content_hash") or "",
            "files": [
                {
                    "id": item.get("id"),
                    "file_name": item.get("file_name"),
                    "file_ext": item.get("file_ext"),
                    "content_type": item.get("content_type"),
                    "storage_ref": item.get("storage_ref"),
                    "storage_sha256": item.get("storage_sha256"),
                    "file_size": item.get("file_size"),
                    "template_usage": item.get("template_usage"),
                    "remark": item.get("remark"),
                }
                for item in template.get("files", [])
            ],
        }
        for template_type, template in catalog.items()
        if template_type in selected_types
    }

    service = get_minio_service()
    published: list[dict[str, Any]] = []
    errors: list[str] = []
    for template_type in selected_types:
        template = catalog[template_type]
        source_files = list(template.get("files", []))
        for source_index, source_file in enumerate(source_files):
            source_name = str(source_file.get("file_name") or "template")
            code = _infer_workpaper_code(source_name) if template_type == "audit_workpaper" else ""
            workpaper = {"code": code, "name": source_name} if code else None
            render_context = _context(
                snapshot,
                report_text,
                package_version,
                template,
                workpaper,
                template_type=template_type,
            )
            output_name = _output_name(
                template_type,
                engagement_id,
                package_version,
                source_name,
                code,
                context=render_context,
                duplicate_index=source_index,
                duplicate_count=len(source_files),
            )
            try:
                source_bytes = service.get_object_bytes(str(source_file.get("storage_ref") or ""))
                rendered_bytes, fill_status = render_template_file(
                    source_bytes,
                    source_name,
                    render_context,
                )
                content_type = _content_type_for_file_name(
                    output_name,
                    str(source_file.get("content_type") or ""),
                )
                uploaded = service.upload_artifact(
                    project_id=engagement_id,
                    file_name=output_name,
                    content_type=content_type,
                    file_bytes=rendered_bytes,
                    # The visible name is intentionally stable and readable;
                    # the package version belongs in the storage key so a
                    # later package does not overwrite an earlier one.
                    storage_file_name=f"package-v{package_version}-{output_name}",
                )
                reference = ArtifactRef(
                    artifact_type=template_type if not code else f"{template_type}_{code}",
                    template_version=template_version_ref(template),
                    version=package_version,
                    storage_ref=uploaded.storage_ref,
                    content_type=content_type,
                    file_name=output_name,
                    status="draft",
                ).to_dict()
                reference.update(
                    {
                        "template_file_id": source_file.get("id"),
                        "source_template_file_name": source_name,
                        "source_template_file_ext": Path(source_name).suffix.lower(),
                        "output_file_ext": Path(output_name).suffix.lower(),
                        "template_fill_status": fill_status,
                    }
                )
                published.append(reference)
                if fill_status in {"copied_legacy_or_unknown_format", "copied_legacy_unmodified", "copied_pdf", "copied_no_matching_form_fields", "copied_no_matching_placeholders", "converted_legacy_no_matching_placeholders"}:
                    errors.append(f"{output_name}: 模板未完成字段填充，已保留原始文件格式和版式；如需自动回填，请提供字段标记，或在部署机启用 Word/Excel 自动化")
            except Exception as exc:
                errors.append(f"{output_name}: {str(exc)[:240]}")

    status = "draft_saved" if not errors else ("partial" if published else "failed")
    package_id = _persist_package(
        engagement_id=engagement_id,
        package_version=package_version,
        status=status,
        template_snapshot=template_snapshot,
        artifacts=published,
        created_by=created_by,
        settings=resolved,
    )
    for index, artifact in enumerate(published):
        artifact["download_url"] = (
            f"/api/annual-audit/{engagement_id}/attachment-packages/"
            f"{package_id}/files/{index}"
        )
        artifact["preview_url"] = (
            f"/api/annual-audit/{engagement_id}/attachment-packages/"
            f"{package_id}/files/{index}/preview"
        )
    return {
        "package_id": package_id,
        "package_version": package_version,
        "status": status,
        "template_snapshot": template_snapshot,
        "artifacts": published,
        "errors": errors,
    }


__all__ = ["DEFAULT_ATTACHMENT_TYPES", "OPTIONAL_ATTACHMENT_TYPES", "generate_annual_attachment_package", "render_template_file"]
