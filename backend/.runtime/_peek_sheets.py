import sys
sys.path.insert(0, r"E:\实验室\NpaLang\backend")
from pathlib import Path
from ai_hunter.annual_audit.import_service import read_tabular_sheets

xlsx = Path(r"E:\实验室\NpaLang\new_docs\逻辑资料V1\AI智能体相关法律、准则、底稿、案例、报告模版【20260703】\7、案例\北京有限公司-京创会审字[2024]第3999号-标准无保留意见-4.3.V2\北京有限公司2023年年审底稿.xlsx")
sheets = {s.name: s for s in read_tabular_sheets(xlsx.name, xlsx.read_bytes())}

targets = [
"C1-2货币资金审定","C1-6银行存款大额收入抽查表 ","C1-4现金大额收入抽查表","C1-8银行未达帐项",
"C1-10银行收支截止性测试","资产表(年末数)","负债及权益表(年末数)","利润表(本年数)",
"C5-2应收帐款审定表","工资","调整明细","营业外收入明细表","营业外支出明细表",
"咨询费合同抽查表","F1-2主营业务收入审定表","F1-3主营业务收入检查表","基础信息",
"C5-5应收账款抽查表","预收替代","D6-2预收帐款审定表"
]
for name in targets:
    s = sheets.get(name)
    if not s:
        # fuzzy
        cands = [k for k in sheets if name.strip() in k or k in name]
        print("MISSING", name, "cands", cands[:5])
        if not cands:
            continue
        s = sheets[cands[0]]
        name = cands[0]
    print("\n====", name, "rows", len(s.rows), "====")
    shown=0
    for i,row in enumerate(s.rows):
        vals=[("" if c is None else str(c)[:35]) for c in row[:12]]
        if any(v.strip() for v in vals):
            print(f"{i:03d}| " + " || ".join(vals))
            shown += 1
        if shown >= 18:
            print("...")
            break
