"""Typed deterministic renderers for approved attachment templates."""

from .docx import DOCX_CONTENT_TYPE, render_docx
from .markdown import MARKDOWN_CONTENT_TYPE, render_markdown
from .pdf import PDF_CONTENT_TYPE, render_pdf
from .xlsx import XLSX_CONTENT_TYPE, escape_formula_text, render_xlsx


RENDERERS = {
    ".docx": render_docx,
    ".xlsx": render_xlsx,
    ".md": render_markdown,
    ".pdf": render_pdf,
}


__all__ = [
    "DOCX_CONTENT_TYPE",
    "MARKDOWN_CONTENT_TYPE",
    "PDF_CONTENT_TYPE",
    "RENDERERS",
    "XLSX_CONTENT_TYPE",
    "escape_formula_text",
    "render_docx",
    "render_markdown",
    "render_pdf",
    "render_xlsx",
]
