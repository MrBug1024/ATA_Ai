"""报告段落分权（Tier 3）：按可见 audience 过滤报告正文。

报告由各段子 agent 产出，每段以 "### N. 【…】" 段头开头，reconcile 拼接成 final_report
（末尾附角标溯源）。交付/历史回显时，按查看者可见的 audience 集合**过滤掉不可见段**。
段头之前的导言与段落之外的溯源附录恒保留（非敏感正文）。

AUTH_ENABLED=false 时查看者为 admin（可见全部 audience），此过滤为恒等，不影响现状。
"""

from __future__ import annotations

import re

from ..graph.report_sections import SECTION_BY_ID
from ..graph.review_sections import REVIEW_SECTION_BY_ID
from .permissions import report_section_code_for_id

# 段头：行首 2~4 个 # + 段号(1..8 或 R1..)，后接 . 。 、 ．
_SECTION_HEADER = re.compile(r"(?m)^#{2,4}\s*([0-9]+|R[0-9]+)\s*[\.。、．]")


def _audience_of(section_id: str) -> str | None:
    sec = SECTION_BY_ID.get(section_id) or REVIEW_SECTION_BY_ID.get(section_id)
    return sec.get("audience") if sec else None


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
        # 审计段按 audience 筛；复盘段(无 audience)及无法识别段一律保留（模块级已管控复盘）
        if aud is None or aud in visible_audiences:
            blocks.append(block)

    return "\n\n".join(b for b in blocks if b)


def filter_report_text_by_sections(report: str, visible_section_codes: set[str]) -> str:
    """按审计报告 section_code 精确过滤；复盘段/未知段保留。"""
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
