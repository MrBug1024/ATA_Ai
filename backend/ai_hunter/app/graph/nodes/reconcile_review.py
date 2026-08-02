"""复盘报告收尾：拼接 R1/R2/R3 + 金额口径清洗 → final_report_ref（Tier1-3 Phase 2-A）。

复盘报告复用 final_report_ref 字段走现有 finalize_answer → persist_conversation_memory，
因此自动持久化(conversation_messages 全文 + ref)、历史可取回、靠 intent=review 区分。
复盘是只读对账：不抽任务、不种子化预期、不写 case_progress。
"""

from __future__ import annotations

from ..context_loader import resolve_report_section
from ..heavy_state import put_heavy_payload
from ..review_sections import REVIEW_SECTION_BY_ID, REVIEW_SECTION_IDS
from ..state import AuditGraphState
from .reconcile_report import _strip_thousands_separators


def reconcile_review(state: AuditGraphState) -> AuditGraphState:
    case_id = int(state.get("current_case_id", 0) or 0)
    today = ((state.get("review_context") or {}).get("metrics") or {}).get("today", "")

    chunks: list[str] = []
    for sid in REVIEW_SECTION_IDS:
        text = resolve_report_section(state, sid).strip()
        if text:
            chunks.append(_strip_thousands_separators(text))

    header = f"# 案件 {case_id} 回款复盘报告" + (f"（复盘日 {today}）" if today else "")
    final_report = "\n\n".join([header, *chunks]) if chunks else (
        header + "\n\n（暂无可对账的回款数据：未发现预期回款分档或已确认实收，无法生成复盘。）"
    )

    final_report_ref = put_heavy_payload("final_report", {"text": final_report})
    return {
        "final_report_ref": final_report_ref,
        "final_report_summary": final_report[:240],
        "final_report": "",
    }
