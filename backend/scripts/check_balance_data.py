"""检查数据库中的科目余额表和可用数据。"""
from ai_hunter.annual_audit.file_attachment_service import _load_latest_report
from ai_hunter.annual_audit.storage import mysql_connection
from ai_hunter.app.settings import get_settings
import json

settings = get_settings()
latest = _load_latest_report(1, settings)
snapshot = dict(latest.get("snapshot") or {})

readiness = snapshot.get("readiness") or {}
available = readiness.get("available_data") or []
print("=== available_data ===")
for item in available:
    print(f"  {item}")

with mysql_connection(settings) as conn:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        tables = [list(t.values())[0] for t in cur.fetchall()]
        print("\n=== all tables ===")
        for t in tables:
            print(f"  {t}")

        # 查找科目余额相关表
        balance_tables = [t for t in tables if "balance" in t.lower() or "account" in t.lower() or "trial" in t.lower() or "ledger" in t.lower()]
        print(f"\n=== balance/account/trial/ledger tables ===")
        for t in balance_tables:
            print(f"  {t}")
            cur.execute(f"SELECT COUNT(*) AS cnt FROM `{t}`")
            print(f"    rows: {cur.fetchone()}")
            cur.execute(f"DESCRIBE `{t}`")
            cols = cur.fetchall()
            col_names = [c.get("Field") for c in cols]
            print(f"    columns: {col_names}")
