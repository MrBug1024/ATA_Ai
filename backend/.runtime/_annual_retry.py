# -*- coding: utf-8 -*-
import json, re, time, zipfile, shutil
from pathlib import Path
from datetime import date, datetime
from xml.etree import ElementTree as ET
import requests
from openpyxl import Workbook
import sys
sys.path.insert(0, r"E:\实验室\NpaLang\backend")
from ai_hunter.annual_audit.import_service import read_tabular_sheets, detect_sheet_schema, normalize_sheet_rows

BASE="http://127.0.0.1:8080"
CASE_ID=2
PASSWORD="Aa1!NOx99Cxen6n5Xv_hQlaCZHAaHKCk4ET1"
CASE_ROOT=Path(r"E:\实验室\NpaLang\new_docs\逻辑资料V1\AI智能体相关法律、准则、底稿、案例、报告模版【20260703】\7、案例\北京有限公司-京创会审字[2024]第3999号-标准无保留意见-4.3.V2")
OUT=CASE_ROOT/"拆分上传材料"
WORK=CASE_ROOT/"北京有限公司2023年年审底稿.xlsx"
PERIOD=date(2023,12,31)
WNS="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
LOG=Path(r"E:\实验室\NpaLang\backend\.runtime\_annual_retry_run.log")

def log(msg):
    s=str(msg)
    print(s, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(s+"\n")

def login():
    r=requests.post(f"{BASE}/auth/login", json={"login_identifier":"superadmin","password":PASSWORD}, timeout=30)
    r.raise_for_status(); return r.json()["access_token"]

def write_xlsx(path, headers, rows, sheet="Sheet1"):
    wb=Workbook(); ws=wb.active; ws.title=sheet[:31]
    ws.append(headers)
    for row in rows: ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)

def docx_to_txt(src: Path, dst: Path) -> int:
    with zipfile.ZipFile(src) as zf:
        xml=zf.read("word/document.xml")
    root=ET.fromstring(xml)
    paras=[]
    for p in root.iter(WNS+"p"):
        texts=[t.text or "" for t in p.iter(WNS+"t")]
        line="".join(texts).strip()
        if line: paras.append(line)
    dst.write_text("\n".join(paras), encoding="utf-8")
    return len(paras)

def as_text(v):
    if v is None: return ""
    if isinstance(v, datetime): return v.strftime("%Y-%m-%d")
    if isinstance(v, date): return v.isoformat()
    return str(v).strip()

def as_num(v):
    if v is None or v=="": return None
    if isinstance(v,(int,float)) and not isinstance(v,bool): return float(v)
    s=str(v).strip().replace(",","").replace("，","")
    try: return float(s)
    except: return None

def find_sheet(sheets, name):
    if name in sheets: return sheets[name]
    for k,v in sheets.items():
        if name.strip() in k or k.strip()==name.strip(): return v
    return None

def reshape_journal(sheet, path, mode):
    header_idx=None
    for i,row in enumerate(sheet.rows[:10]):
        joined="".join(as_text(c) for c in row)
        if "日期" in joined and "凭证" in joined:
            header_idx=i; break
    if header_idx is None:
        return 0
    header=[as_text(c) for c in sheet.rows[header_idx]]
    def col(*cands):
        for c in cands:
            for i,h in enumerate(header):
                if c and (c==h or c in h or h in c):
                    return i
        return None
    c_date=col("日期")
    c_voucher=col("凭证号数","凭证编号","凭证号","凭证字号")
    c_code=col("科目编码","科目代码")
    c_name=col("科目名称")
    c_sum=col("摘要")
    c_debit=col("借方金额","借方发生额","借方")
    c_credit=col("贷方金额","贷方发生额","贷方")
    rows=[]
    for row in sheet.rows[header_idx+1:]:
        d=as_text(row[c_date]) if c_date is not None and c_date < len(row) else ""
        v=as_text(row[c_voucher]) if c_voucher is not None and c_voucher < len(row) else ""
        name=as_text(row[c_name]) if c_name is not None and c_name < len(row) else ""
        if not d or not v or not name: continue
        if "合计" in name: continue
        code=as_text(row[c_code]) if c_code is not None and c_code < len(row) else ""
        summary=as_text(row[c_sum]) if c_sum is not None and c_sum < len(row) else ""
        debit=as_num(row[c_debit]) if c_debit is not None and c_debit < len(row) else None
        credit=as_num(row[c_credit]) if c_credit is not None and c_credit < len(row) else None
        if mode=="credit_only":
            if credit is None:
                for j in range(len(row)-1,-1,-1):
                    n=as_num(row[j]);
                    if n is not None: credit=n; break
            debit=0.0
        elif mode=="debit_only":
            if debit is None:
                for j in range(len(row)-1,-1,-1):
                    n=as_num(row[j]);
                    if n is not None: debit=n; break
            credit=0.0
        else:
            debit=debit or 0.0; credit=credit or 0.0
        if (debit or 0)==0 and (credit or 0)==0: continue
        rows.append([d,v,1,code,name,debit or 0.0, credit or 0.0,"",summary])
    write_xlsx(path,["凭证日期","凭证号","分录号","科目编码","科目名称","借方金额","贷方金额","对方单位","摘要"], rows, "序时账")
    return len(rows)

def upload(token, files, cat, batch_name):
    headers={"Authorization":f"Bearer {token}"}
    opened=[]; multipart=[]
    try:
        for p in files:
            fh=open(p,"rb"); opened.append(fh)
            multipart.append(("files",(p.name, fh)))
        data={"current_case_id":str(CASE_ID),"doc_category":cat,"batch_name":batch_name,"current_entity_name":"北京有限公司"}
        r=requests.post(f"{BASE}/files/upload-and-ingest", headers=headers, data=data, files=multipart, timeout=180)
        log(f"UPLOAD {cat} {r.status_code} {[p.name for p in files]}")
        if not r.ok: log(r.text[:500])
        r.raise_for_status(); return r.json()
    finally:
        for fh in opened: fh.close()

def poll(token, batch_id, timeout=180):
    h={"Authorization":f"Bearer {token}"}
    last={}
    for _ in range(max(1, timeout//3)):
        r=requests.get(f"{BASE}/files/upload-batches/{batch_id}", headers=h, timeout=30)
        if r.ok:
            last=r.json(); st=(last.get("status") or "").lower()
            log(f"  {batch_id[:12]} {st} records={last.get('records_inserted')}")
            if st in {"completed","failed","success","done","error","partial"}:
                return last
        time.sleep(3)
    return last

def retry_batch(token, batch_id):
    h={"Authorization":f"Bearer {token}"}
    r=requests.post(f"{BASE}/files/upload-batches/{batch_id}/retry", headers=h, timeout=60)
    log(f"RETRY {batch_id} {r.status_code} {r.text[:300]}")
    return r.json() if r.ok else {"error": r.text}

LOG.write_text("", encoding="utf-8")
log("start")
sheets={s.name:s for s in read_tabular_sheets(WORK.name, WORK.read_bytes())}
journal_files=[]
for name, mode, fname in [
    ("营业外收入明细表","credit_only","营业外收入明细表-规范化.xlsx"),
    ("营业外支出明细表","debit_only","营业外支出明细表-规范化.xlsx"),
    ("调整明细","normal","调整明细-规范化.xlsx"),
]:
    s=find_sheet(sheets, name)
    p=OUT/fname
    n=reshape_journal(s, p, mode)
    log(f"journal {name} -> {n}")
    if n:
        sh=read_tabular_sheets(p.name, p.read_bytes())[0]
        det=detect_sheet_schema(sh.rows, source_hint=p.name)
        norm=normalize_sheet_rows(sh, source_ref="x", file_name=p.name, default_period_end=PERIOD)
        log(f"  detect={det[0] if det else None} norm={len(norm[1]) if norm else 0}")
        journal_files.append(p)

conv_dir=OUT/"文本化资料"; conv_dir.mkdir(exist_ok=True)
fs_files=[]
src_xls=CASE_ROOT/"报告"/"2、经审计的财务报表-（会计准则）.xls"
if src_xls.exists():
    dst=conv_dir/src_xls.name
    shutil.copy2(src_xls, dst); fs_files.append(dst)
src_docx=CASE_ROOT/"报告"/"1、A1-1审计报告-标准无保留意见（单体、企业会计准则）.docx"
if src_docx.exists():
    dst=conv_dir/(src_docx.stem+".txt")
    n=docx_to_txt(src_docx, dst); log(f"docx->txt {src_docx.name} paras={n}"); fs_files.append(dst)

conf_files=[]
conf_src=Path(r"E:\实验室\NpaLang\new_docs\逻辑资料V1\AI智能体相关法律、准则、底稿、案例、报告模版【20260703】\10、函证模版")
for src in conf_src.glob("*.xls"):
    dst=conv_dir/src.name
    shutil.copy2(src, dst); conf_files.append(dst)
bank_conf=conf_src/"1银行函证.docx"
if bank_conf.exists():
    dst=conv_dir/"1银行函证.txt"
    n=docx_to_txt(bank_conf, dst); log(f"conf docx->txt paras={n}"); conf_files.append(dst)

token=login(); log("logged in")
results=[]
for bid in ["local-b0405da14306","local-5ab5fce89794"]:
    try:
        retry_batch(token, bid)
        d=poll(token, bid, timeout=90)
        results.append({"retry":bid,"status":d.get("status"),"records":d.get("records_inserted"),"meta":d.get("metadata")})
    except Exception as e:
        results.append({"retry":bid,"error":str(e)})

if journal_files:
    resp=upload(token, journal_files, "journal_entries", "补充营业外及调整分录")
    d=poll(token, resp["upload_batch_id"])
    results.append({"cat":"journal_entries","status":d.get("status"),"records":d.get("records_inserted")})

if fs_files:
    resp=upload(token, fs_files, "financial_statements", "财务报表文本化与报表xls")
    d=poll(token, resp["upload_batch_id"])
    results.append({"cat":"financial_statements","status":d.get("status"),"records":d.get("records_inserted"),"meta":d.get("metadata")})

if conf_files:
    resp=upload(token, conf_files[:5], "confirmations", "函证模板xls与文本")
    d=poll(token, resp["upload_batch_id"])
    results.append({"cat":"confirmations","status":d.get("status"),"records":d.get("records_inserted"),"meta":d.get("metadata")})

h={"Authorization":f"Bearer {token}"}
ready=requests.post(f"{BASE}/api/annual-audit/readiness", json={"case_id":CASE_ID}, headers=h, timeout=60).json()
sales=requests.post(f"{BASE}/api/annual-audit/sales-receivables", json={"case_id":CASE_ID,"recompute":True}, headers=h, timeout=120).json()
cash=requests.post(f"{BASE}/api/annual-audit/cash-and-bank", json={"case_id":CASE_ID,"recompute":True}, headers=h, timeout=120).json()
full=requests.post(f"{BASE}/api/audit/get_full_context", json={"case_id":CASE_ID,"recompute":True}, headers=h, timeout=180).json()
cats=requests.get(f"{BASE}/api/case/{CASE_ID}/doc-categories", headers=h, timeout=30).json()
out={
 "results":results,
 "readiness_counts":ready.get("counts"),
 "ready_sales":ready.get("ready_for_sales_receivables"),
 "ready_cash":ready.get("ready_for_cash_and_bank"),
 "missing":ready.get("missing_required_data"),
 "available_data":ready.get("available_data"),
 "doc_categories":cats,
 "sales_status":sales.get("status"),
 "sales_findings":len(sales.get("findings") or []),
 "sales_ar_total": (sales.get("receivables") or {}).get("total_balance"),
 "sales_finding_titles":[f.get("title") for f in (sales.get("findings") or [])][:10],
 "cash_status":cash.get("status"),
 "cash_findings":len(cash.get("findings") or []),
 "cash_finding_titles":[f.get("title") for f in (cash.get("findings") or [])][:10],
 "cash_rule_hits":cash.get("rule_hit_counts"),
 "full_supported": (full.get("engine_results") or {}).get("annual_audit",{}).get("supported_cycles"),
 "full_completeness": (full.get("engine_results") or {}).get("annual_audit",{}).get("data_completeness") or full.get("data_completeness"),
}
Path(r"E:\实验室\NpaLang\backend\.runtime\_annual_e2e_retry.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
log("DONE")
log(json.dumps(out, ensure_ascii=False, indent=2, default=str)[:3500])
