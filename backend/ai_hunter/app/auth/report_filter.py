"""Filter annual-audit report sections by the role permission catalog."""

from __future__ import annotations

import re

from .permissions import report_section_code_for_id
from .roles import report_sections_from_seed

# Section heading: Markdown heading + numeric section id.
_SECTION_HEADER = re.compile(r"(?m)^#{2,4}\s*([0-9]+)\s*[\.。、．]")


def _audience_of(section_id: str) -> str | None:
    for section in report_sections_from_seed():
        if str(section.get("section_id") or "") == section_id:
            return str(section.get("audience") or "") or None
    return None


def filter_report_text(report: str, visible_audiences: set[str]) -> str:
    """保留可见 audience 段 + 无段号块（导言/溯源附录）。无段头则原样返回。"""
    if not report:
        return report
    matches = list(_SECTION_HEADER.finditer(report))
    if not matches:
        return report

    blocks: list[str] = []
    if matches[0].start() > 0:
        blocks.append(report[: matches[0].start()].rstrip())  # 段头前导言

    for i, m in enumerate(matches):
        sid = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        block = report[m.start():end].rstrip()
        aud = _audience_of(sid)
        # Known annual sections are filtered; unknown appendix blocks are retained.
        if aud is None or aud in visible_audiences:
            blocks.append(block)

    return "\n\n".join(b for b in blocks if b)


def filter_report_text_by_sections(report: str, visible_section_codes: set[str]) -> str:
    """Filter known annual sections by section_code; retain unknown appendices."""
    if not report:
        return report
    matches = list(_SECTION_HEADER.finditer(report))
    if not matches:
        return report

    blocks: list[str] = []
    if matches[0].start() > 0:
        blocks.append(report[: matches[0].start()].rstrip())

    for i, m in enumerate(matches):
        sid = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        block = report[m.start():end].rstrip()
        section_code = report_section_code_for_id(sid)
        if section_code is None or section_code in visible_section_codes:
            blocks.append(block)

    return "\n\n".join(b for b in blocks if b)
