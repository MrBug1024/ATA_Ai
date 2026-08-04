import xlrd
from pathlib import Path
p = Path(r"E:\实验室\NpaLang\new_docs\逻辑资料V1\AI智能体相关法律、准则、底稿、案例、报告模版【20260703】\7、案例\北京有限公司-京创会审字[2024]第3999号-标准无保留意见-4.3.V2\报告\2、经审计的财务报表-（会计准则）.xls")
wb = xlrd.open_workbook(str(p))
print("sheets", wb.sheet_names())
for name in wb.sheet_names():
    sh = wb.sheet_by_name(name)
    print("---", name, "rows", sh.nrows, "cols", sh.ncols)
    for r in range(min(8, sh.nrows)):
        vals = [str(sh.cell_value(r,c))[:30] for c in range(min(8, sh.ncols))]
        if any(v.strip() for v in vals):
            print(r, vals)
