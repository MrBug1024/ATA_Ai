import sys
sys.path.insert(0, r"E:\实验室\NpaLang\backend")
from pathlib import Path
from ai_hunter.annual_audit.import_service import (
    read_tabular_sheets, detect_sheet_schema, is_audit_workpaper_workbook, normalize_sheet_rows
)
from datetime import date

xlsx = Path(r"E:\实验室\NpaLang\new_docs\逻辑资料V1\AI智能体相关法律、准则、底稿、案例、报告模版【20260703】\7、案例\北京有限公司-京创会审字[2024]第3999号-标准无保留意见-4.3.V2\北京有限公司2023年年审底稿.xlsx")
data = xlsx.read_bytes()
print("reading...")
sheets = read_tabular_sheets(xlsx.name, data)
print("sheets", len(sheets), "is_workpaper", is_audit_workpaper_workbook(sheets))

hits = []
for sheet in sheets:
    det = detect_sheet_schema(sheet.rows, source_hint=sheet.name)
    if not det:
        continue
    dataset, header_idx, mapping = det
    # try normalize rough count
    try:
        norm = normalize_sheet_rows(sheet, source_ref="x", file_name=xlsx.name, default_period_end=date(2023,12,31))
        row_count = len(norm[1]) if norm else 0
    except Exception as e:
        row_count = f"err:{e}"
    hits.append((dataset, sheet.name, header_idx, sorted(mapping.keys()), row_count))

from collections import Counter
print("HIT_COUNT", len(hits))
print("BY_DATASET", Counter(h[0] for h in hits))
for h in hits:
    print(f"{h[0]}\trows={h[4]}\theader@{h[2]}\t{h[1]}\tfields={h[3]}")
