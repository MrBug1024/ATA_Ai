# -*- coding: utf-8 -*-
"""Prepare split/transformed annual-audit materials and upload to case 2."""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from openpyxl import Workbook

sys.path.insert(0, r"E:\实验室\NpaLang\backend")
from ai_hunter.annual_audit.import_service import (  # noqa: E402
    detect_sheet_schema,
    normalize_sheet_rows,
    read_tabular_sheets,
)

BASE = "http://127.0.0.1:8080"
CASE_ID = 2
PASSWORD = "Aa1!NOx99Cxen6n5Xv_hQlaCZHAaHKCk4ET1"
CASE_ROOT = Path(
    r"E:\实验室\NpaLang\new_docs\逻辑资料V1\AI智能体相关法律、准则、底稿、案例、报告模版【20260703】\7、案例"
    r"\北京有限公司-京创会审字[2024]第3999号-标准无保留意见-4.3.V2"
)
WORKPAPY = CASE_ROOT / "北京有限公司2023年年审底稿.xlsx"
REPORT_DIR = CASE_ROOT / "报告"
DOCS_ROOT = Path(
    r"E:\实验室\NpaLang\new_docs\逻辑资料V1\AI智能体相关法律、准则、底稿、案例、报告模版【20260703】"
)
OUT_DIR = CASE_ROOT / "拆分上传材料"
RESULT_PATH = Path(r"E:\实验室\NpaLang\backend\.runtime\_annual_e2e_result.json")
PERIOD_END = date(2023, 12, 31)


def hk(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s_\-—–‐‑‒–—―（）()【】\[\]/\\.:：·,，。；;]+", "", text)


def cell(row: list[Any], idx: int) -> Any:
    return row[idx] if idx < len(row) else None


def as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text or text in {"-", "—", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def write_xlsx(path: Path, headers: list[str], rows: list[list[Any]], sheet_name: str = "Sheet1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31] or "Sheet1"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def export_raw_sheet(sheet, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet.name or "Sheet1")[:31]
    for row in sheet.rows:
        ws.append([("" if c is None else c) for c in row])
    wb.save(path)


def find_sheet(sheets: dict[str, Any], name: str):
    if name in sheets:
        return sheets[name]
    key = name.strip()
    for k, v in sheets.items():
        if k.strip() == key or key in k or k in key:
            return v
    return None


def build_trial_balance(sheets: dict[str, Any], out_path: Path) -> int:
    """Reshape 试算平衡资产/负债 sheets into importer-friendly 科目余额表."""
    assets = find_sheet(sheets, "资产表(年末数)")
    liabilities = find_sheet(sheets, "负债及权益表(年末数)")
    rows_out: list[list[Any]] = []

    def parse_section(sheet, side: str) -> None:
        if sheet is None:
            return
        # Find header row containing 未审 / 审定
        start = 0
        for i, row in enumerate(sheet.rows[:20]):
            joined = "".join(as_text(c) for c in row)
            if "未审" in joined or "审定" in joined:
                start = i + 1
                # skip sub-header if present
                nxt = sheet.rows[i + 1] if i + 1 < len(sheet.rows) else []
                if any("借方" in as_text(c) or "贷方" in as_text(c) for c in nxt):
                    start = i + 2
                break
        for row in sheet.rows[start:]:
            name = as_text(cell(row, 0))
            if not name:
                continue
            clean = name.strip()
            # skip section headers / totals
            if clean in {"流动资产", "非流动资产", "资产总计", "流动负债", "非流动负债", "负债合计", "所有者权益", "负债和所有者权益总计", "负债及所有者权益总计"}:
                continue
            if "合计" in clean and len(clean) <= 8:
                continue
            # line no in col1, unaudited col2, total col3, audited usually last numeric among cols
            audited = None
            # Prefer last column with number (审定数)
            for idx in range(len(row) - 1, 1, -1):
                n = as_number(cell(row, idx))
                if n is not None:
                    audited = n
                    break
            if audited is None:
                continue
            # Skip pure zero empty accounts? keep non-zero and small structure
            code = ""
            line_no = as_text(cell(row, 1))
            if re.fullmatch(r"\d+", line_no or ""):
                code = f"TB{side[0].upper()}{int(line_no):03d}"
            # Assets normally debit balance; liabilities/equity credit.
            # Negative asset (e.g. AR credit balance) flips sides.
            if side == "asset":
                if audited >= 0:
                    cd, cc = audited, 0.0
                else:
                    cd, cc = 0.0, abs(audited)
            else:
                if audited >= 0:
                    cd, cc = 0.0, audited
                else:
                    cd, cc = abs(audited), 0.0
            # period amounts unknown from TB snapshot
            rows_out.append(
                [
                    "2023-12-31",
                    code,
                    clean,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    cd,
                    cc,
                    "CNY",
                ]
            )

    parse_section(assets, "asset")
    parse_section(liabilities, "liability")

    headers = [
        "截止日期",
        "科目编码",
        "科目名称",
        "期初借方",
        "期初贷方",
        "本期借方发生额",
        "本期贷方发生额",
        "期末借方余额",
        "期末贷方余额",
        "币种",
    ]
    write_xlsx(out_path, headers, rows_out, sheet_name="科目余额表")
    return len(rows_out)


def build_bank_transactions(sheets: dict[str, Any], out_path: Path) -> int:
    rows_out: list[list[Any]] = []

    # C1-6 银行存款大额收入抽查表: month, day, voucher, summary, amount, counterparty_account
    s6 = find_sheet(sheets, "C1-6银行存款大额收入抽查表")
    if s6:
        for row in s6.rows:
            month = as_number(cell(row, 0))
            day = as_number(cell(row, 1))
            voucher = as_text(cell(row, 2))
            summary = as_text(cell(row, 3))
            # amount may be col5 (empty col4)
            amount = as_number(cell(row, 5))
            if amount is None:
                amount = as_number(cell(row, 4))
            counterparty = as_text(cell(row, 6)) if as_text(cell(row, 6)) else as_text(cell(row, 5))
            # if amount was in col4, counterparty col5
            if as_number(cell(row, 5)) is not None and as_number(cell(row, 4)) is None:
                counterparty = as_text(cell(row, 6))
            if month is None or day is None or amount is None:
                continue
            if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
                continue
            if "合计" in summary or "合计" in voucher:
                continue
            try:
                tx_date = date(2023, int(month), int(day)).isoformat()
            except ValueError:
                continue
            rows_out.append(
                [
                    "基本户-派生抽查",
                    tx_date,
                    amount,
                    amount,  # inflow (大额收入)
                    0.0,
                    "收入",
                    counterparty or "",
                    voucher,
                    summary or "银行存款大额收入抽查",
                    None,
                ]
            )

    # C1-10 银行收支截止性测试: year, month, day, voucher, summary, debit, credit, statement_date
    s10 = find_sheet(sheets, "C1-10银行收支截止性测试")
    if s10:
        for row in s10.rows:
            year = as_number(cell(row, 0))
            month = as_number(cell(row, 1))
            day = as_number(cell(row, 2))
            voucher = as_text(cell(row, 3))
            summary = as_text(cell(row, 4))
            debit = as_number(cell(row, 6))
            credit = as_number(cell(row, 7))
            if year is None or month is None or day is None:
                continue
            if not (2000 <= int(year) <= 2100 and 1 <= int(month) <= 12 and 1 <= int(day) <= 31):
                continue
            if "合计" in summary or voucher == "合计":
                continue
            try:
                tx_date = date(int(year), int(month), int(day)).isoformat()
            except ValueError:
                continue
            debit = debit or 0.0
            credit = credit or 0.0
            if debit == 0 and credit == 0:
                continue
            amount = debit if debit else -credit
            rows_out.append(
                [
                    "基本户-截止性测试派生",
                    tx_date,
                    amount,
                    debit,
                    credit,
                    "收入" if debit else "支出",
                    "",
                    voucher,
                    summary or "银行收支截止性测试",
                    None,
                ]
            )

    headers = [
        "银行账号",
        "交易日期",
        "交易金额",
        "收入金额",
        "支出金额",
        "收支方向",
        "对方单位",
        "流水号",
        "摘要",
        "账户余额",
    ]
    write_xlsx(out_path, headers, rows_out, sheet_name="银行流水")
    return len(rows_out)


def reshape_journal_simple(sheet, out_path: Path, mode: str) -> int:
    """Normalize simple journal-like sheets into canonical headers."""
    # Find header
    header_idx = None
    for i, row in enumerate(sheet.rows[:10]):
        joined = "".join(as_text(c) for c in row)
        if "日期" in joined and ("凭证" in joined or "科目" in joined):
            header_idx = i
            break
    if header_idx is None:
        export_raw_sheet(sheet, out_path)
        return 0

    header = [as_text(c) for c in sheet.rows[header_idx]]
    idx = {hk(h): n for n, h in enumerate(header) if h}

    def col(*names: str) -> int | None:
        for n in names:
            if hk(n) in idx:
                return idx[hk(n)]
        return None

    c_date = col("日期", "凭证日期", "记账日期")
    c_voucher = col("凭证编号", "凭证号", "凭证字号")
    c_code = col("科目编码", "科目代码")
    c_name = col("科目名称", "会计科目", "科目")
    c_summary = col("摘要", "说明")
    c_debit = col("借方金额", "借方发生额", "借方")
    c_credit = col("贷方金额", "贷方发生额", "贷方")

    rows_out: list[list[Any]] = []
    for row in sheet.rows[header_idx + 1 :]:
        d = as_text(cell(row, c_date)) if c_date is not None else ""
        v = as_text(cell(row, c_voucher)) if c_voucher is not None else ""
        name = as_text(cell(row, c_name)) if c_name is not None else ""
        if not d or not v or not name:
            continue
        if "合计" in name or "合计" in d:
            continue
        code = as_text(cell(row, c_code)) if c_code is not None else ""
        summary = as_text(cell(row, c_summary)) if c_summary is not None else ""
        debit = as_number(cell(row, c_debit)) if c_debit is not None else None
        credit = as_number(cell(row, c_credit)) if c_credit is not None else None
        if mode == "credit_only":
            credit = credit if credit is not None else as_number(cell(row, c_debit if c_debit is not None else 0))
            # 营业外收入明细 only has 贷方金额 column sometimes labeled 贷方金额
            if credit is None:
                # last numeric
                for j in range(len(row) - 1, -1, -1):
                    n = as_number(cell(row, j))
                    if n is not None:
                        credit = n
                        break
            debit = 0.0
        elif mode == "debit_only":
            if debit is None:
                for j in range(len(row) - 1, -1, -1):
                    n = as_number(cell(row, j))
                    if n is not None:
                        debit = n
                        break
            credit = 0.0
        else:
            debit = debit or 0.0
            credit = credit or 0.0
        if (debit or 0) == 0 and (credit or 0) == 0:
            continue
        # normalize date
        if isinstance(cell(row, c_date), datetime):
            d = cell(row, c_date).strftime("%Y-%m-%d")
        elif isinstance(cell(row, c_date), date):
            d = cell(row, c_date).isoformat()
        rows_out.append([d, v, 1, code, name, debit or 0.0, credit or 0.0, "", summary])

    headers = [
        "凭证日期",
        "凭证号",
        "分录号",
        "科目编码",
        "科目名称",
        "借方金额",
        "贷方金额",
        "对方单位",
        "摘要",
    ]
    write_xlsx(out_path, headers, rows_out, sheet_name="序时账")
    return len(rows_out)


def login() -> str:
    r = requests.post(
        f"{BASE}/auth/login",
        json={"login_identifier": "superadmin", "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def upload_files(token: str, files: list[Path], doc_category: str, batch_name: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    opened = []
    try:
        multipart = []
        for p in files:
            fh = open(p, "rb")
            opened.append(fh)
            multipart.append(("files", (p.name, fh)))
        data = {
            "current_case_id": str(CASE_ID),
            "doc_category": doc_category,
            "batch_name": batch_name,
            "current_entity_name": "北京有限公司",
        }
        r = requests.post(
            f"{BASE}/files/upload-and-ingest",
            headers=headers,
            data=data,
            files=multipart,
            timeout=180,
        )
        print(f"UPLOAD {doc_category}: {r.status_code} {[p.name for p in files]}")
        if not r.ok:
            print(r.text[:1000])
            r.raise_for_status()
        return r.json()
    finally:
        for fh in opened:
            fh.close()


def poll_batch(token: str, batch_id: str, timeout_sec: int = 300) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    path = f"{BASE}/files/upload-batches/{batch_id}"
    deadline = time.time() + timeout_sec
    last = {}
    while time.time() < deadline:
        r = requests.get(path, headers=headers, timeout=30)
        if r.ok:
            last = r.json()
            status = (last.get("status") or last.get("batch_status") or "").lower()
            stage = last.get("stage") or ""
            print(f"  batch {batch_id[:8]}... status={status} stage={stage}")
            if status in {"completed", "success", "done", "failed", "error", "partial"}:
                return last
            # also check nested
            if last.get("failed_file_count") is not None and last.get("processing_file_count") == 0:
                if (last.get("completed_file_count") or 0) + (last.get("failed_file_count") or 0) >= (
                    last.get("total_file_count") or 0
                ) > 0:
                    return last
        time.sleep(3)
    return last


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"out_dir": str(OUT_DIR), "prepared": {}, "uploads": [], "analyses": {}}

    print("Reading workpaper...", flush=True)
    data = WORKPAPY.read_bytes()
    sheet_list = read_tabular_sheets(WORKPAPY.name, data)
    sheets = {s.name: s for s in sheet_list}
    print(f"sheets={len(sheets)}", flush=True)

    # 1) Export already-useful direct sheets
    direct_exports = {
        "receivables": ["C5-2应收帐款审定表"],
        "journal": ["工资", "调整明细"],
        "revenue_support_raw": ["咨询费合同抽查表", "F1-2主营业务收入审定表", "F1-3主营业务收入检查表"],
        "other_raw": ["预收替代", "基础信息"],
    }
    prepared_paths: dict[str, list[Path]] = {
        "trial_balance": [],
        "bank_statements": [],
        "journal_entries": [],
        "receivables": [],
        "financial_statements": [],
        "revenue_support": [],
        "confirmations": [],
        "tax_materials": [],
        "other": [],
    }

    # receivables / journal direct
    for name in direct_exports["receivables"]:
        s = find_sheet(sheets, name)
        if not s:
            print("MISSING sheet", name)
            continue
        p = OUT_DIR / f"{s.name.strip()}.xlsx"
        export_raw_sheet(s, p)
        prepared_paths["receivables"].append(p)
        # validate detect
        det = detect_sheet_schema(s.rows, source_hint=s.name)
        print("export receivable", s.name, "detect", det[0] if det else None)

    for name in direct_exports["journal"]:
        s = find_sheet(sheets, name)
        if not s:
            print("MISSING sheet", name)
            continue
        p = OUT_DIR / f"{s.name.strip()}.xlsx"
        export_raw_sheet(s, p)
        prepared_paths["journal_entries"].append(p)
        det = detect_sheet_schema(s.rows, source_hint=s.name)
        print("export journal", s.name, "detect", det[0] if det else None)

    # reshaped journals
    for name, mode, fname in [
        ("营业外收入明细表", "credit_only", "营业外收入明细表-规范化.xlsx"),
        ("营业外支出明细表", "debit_only", "营业外支出明细表-规范化.xlsx"),
        ("调整明细", "normal", "调整明细-规范化.xlsx"),
    ]:
        s = find_sheet(sheets, name)
        if not s:
            continue
        p = OUT_DIR / fname
        n = reshape_journal_simple(s, p, mode=mode)
        print(f"reshape journal {name} -> {n} rows")
        if n > 0:
            prepared_paths["journal_entries"].append(p)
            # validate
            sh = read_tabular_sheets(p.name, p.read_bytes())[0]
            det = detect_sheet_schema(sh.rows, source_hint=p.name)
            norm = normalize_sheet_rows(sh, source_ref="x", file_name=p.name, default_period_end=PERIOD_END)
            print("  detect", det[0] if det else None, "norm_rows", len(norm[1]) if norm else 0)

    # trial balance
    tb_path = OUT_DIR / "科目余额表-试算平衡派生.xlsx"
    tb_n = build_trial_balance(sheets, tb_path)
    print("trial balance rows", tb_n)
    if tb_n:
        prepared_paths["trial_balance"].append(tb_path)
        sh = read_tabular_sheets(tb_path.name, tb_path.read_bytes())[0]
        det = detect_sheet_schema(sh.rows, source_hint=tb_path.name)
        norm = normalize_sheet_rows(sh, source_ref="x", file_name=tb_path.name, default_period_end=PERIOD_END)
        print("  detect", det[0] if det else None, "fields", sorted(det[2].keys()) if det else None, "norm", len(norm[1]) if norm else 0)

    # bank
    bank_path = OUT_DIR / "银行流水-底稿抽查派生.xlsx"
    bank_n = build_bank_transactions(sheets, bank_path)
    print("bank rows", bank_n)
    if bank_n:
        prepared_paths["bank_statements"].append(bank_path)
        sh = read_tabular_sheets(bank_path.name, bank_path.read_bytes())[0]
        det = detect_sheet_schema(sh.rows, source_hint=bank_path.name)
        norm = normalize_sheet_rows(sh, source_ref="x", file_name=bank_path.name, default_period_end=PERIOD_END)
        print("  detect", det[0] if det else None, "fields", sorted(det[2].keys()) if det else None, "norm", len(norm[1]) if norm else 0)

    # revenue support raw exports
    for name in direct_exports["revenue_support_raw"]:
        s = find_sheet(sheets, name)
        if not s:
            continue
        p = OUT_DIR / f"{s.name.strip()}.xlsx"
        export_raw_sheet(s, p)
        prepared_paths["revenue_support"].append(p)

    for name in direct_exports["other_raw"]:
        s = find_sheet(sheets, name)
        if not s:
            continue
        p = OUT_DIR / f"{s.name.strip()}.xlsx"
        export_raw_sheet(s, p)
        prepared_paths["other"].append(p)

    # financial statements from report folder
    if REPORT_DIR.exists():
        fs_dir = OUT_DIR / "财务报表"
        fs_dir.mkdir(exist_ok=True)
        for src in REPORT_DIR.iterdir():
            if src.is_file():
                dst = fs_dir / src.name
                shutil.copy2(src, dst)
                prepared_paths["financial_statements"].append(dst)

    # confirmations templates (not entity-specific, for category coverage)
    conf_src = DOCS_ROOT / "10、函证模版"
    conf_dir = OUT_DIR / "函证模版"
    conf_dir.mkdir(exist_ok=True)
    if conf_src.exists():
        for src in conf_src.iterdir():
            if src.is_file() and src.suffix.lower() in {".doc", ".docx", ".xls", ".xlsx"}:
                dst = conf_dir / src.name
                shutil.copy2(src, dst)
                prepared_paths["confirmations"].append(dst)

    # tax templates sample if present
    tax_src = DOCS_ROOT / "12、税审模版"
    tax_dir = OUT_DIR / "税审模版"
    tax_dir.mkdir(exist_ok=True)
    if tax_src.exists():
        count = 0
        for src in tax_src.rglob("*"):
            if src.is_file() and src.suffix.lower() in {".doc", ".docx", ".xls", ".xlsx", ".pdf"}:
                dst = tax_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                prepared_paths["tax_materials"].append(dst)
                count += 1
                if count >= 3:
                    break

    result["prepared"] = {k: [str(p) for p in v] for k, v in prepared_paths.items()}
    manifest = OUT_DIR / "manifest.json"
    manifest.write_text(json.dumps(result["prepared"], ensure_ascii=False, indent=2), encoding="utf-8")
    print("Prepared manifest ->", manifest)

    # Upload missing categories (skip already completed structured if desired; still ok to re-upload)
    token = login()
    print("logged in")

    # Upload plan: prioritize structured missing first
    upload_plan = [
        ("trial_balance", prepared_paths["trial_balance"], "试算平衡派生科目余额表"),
        ("bank_statements", prepared_paths["bank_statements"], "底稿派生银行流水"),
        ("journal_entries", [p for p in prepared_paths["journal_entries"] if "规范化" in p.name], "补充序时账明细"),
        ("financial_statements", prepared_paths["financial_statements"], "经审计财务报表及附注"),
        ("revenue_support", prepared_paths["revenue_support"], "收入支持性资料"),
        ("confirmations", prepared_paths["confirmations"][:3], "函证模板资料"),
        ("tax_materials", prepared_paths["tax_materials"][:3], "税审模板资料"),
        ("other", prepared_paths["other"], "其他底稿拆分资料"),
    ]

    for cat, files, batch_name in upload_plan:
        files = [p for p in files if p.exists()]
        if not files:
            print("SKIP empty category", cat)
            continue
        try:
            resp = upload_files(token, files, cat, batch_name)
            batch_id = resp.get("upload_batch_id") or ""
            detail = poll_batch(token, batch_id) if batch_id else {}
            result["uploads"].append({"category": cat, "response": resp, "batch_detail": detail})
        except Exception as exc:
            print("UPLOAD FAIL", cat, exc)
            result["uploads"].append({"category": cat, "error": str(exc)})

    headers = {"Authorization": f"Bearer {token}"}

    # Readiness
    r = requests.post(f"{BASE}/api/annual-audit/readiness", json={"case_id": CASE_ID}, headers=headers, timeout=60)
    result["analyses"]["readiness"] = r.json() if r.ok else {"status": r.status_code, "text": r.text[:1000]}
    print("READINESS", json.dumps(result["analyses"]["readiness"], ensure_ascii=False)[:1500])

    # Sales receivables
    r = requests.post(
        f"{BASE}/api/annual-audit/sales-receivables",
        json={"case_id": CASE_ID, "recompute": True},
        headers=headers,
        timeout=120,
    )
    result["analyses"]["sales_receivables"] = r.json() if r.ok else {"status": r.status_code, "text": r.text[:2000]}
    print("SALES", r.status_code, json.dumps(result["analyses"]["sales_receivables"], ensure_ascii=False)[:1500])

    # Cash and bank
    r = requests.post(
        f"{BASE}/api/annual-audit/cash-and-bank",
        json={"case_id": CASE_ID, "recompute": True},
        headers=headers,
        timeout=120,
    )
    result["analyses"]["cash_and_bank"] = r.json() if r.ok else {"status": r.status_code, "text": r.text[:2000]}
    print("CASH", r.status_code, json.dumps(result["analyses"]["cash_and_bank"], ensure_ascii=False)[:1500])

    # Full context
    r = requests.post(
        f"{BASE}/api/audit/get_full_context",
        json={"case_id": CASE_ID, "recompute": True},
        headers=headers,
        timeout=180,
    )
    result["analyses"]["full_context"] = r.json() if r.ok else {"status": r.status_code, "text": r.text[:2000]}
    print("FULL_CTX", r.status_code, json.dumps(result["analyses"]["full_context"], ensure_ascii=False)[:1500])

    # categories
    r = requests.get(f"{BASE}/api/case/{CASE_ID}/doc-categories", headers=headers, timeout=30)
    result["doc_categories"] = r.json() if r.ok else {"status": r.status_code, "text": r.text[:500]}

    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("RESULT ->", RESULT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

