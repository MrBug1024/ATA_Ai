"""查看模板相关表结构。"""
from ai_hunter.annual_audit.storage import mysql_connection
from ai_hunter.app.settings import get_settings

settings = get_settings()
with mysql_connection(settings) as conn:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE 'annual_audit_template%'")
        tables = [list(t.values())[0] for t in cur.fetchall()]
        for t in tables:
            print(f"\n=== {t} ===")
            cur.execute(f"DESCRIBE `{t}`")
            cols = cur.fetchall()
            for c in cols:
                print(f"  {c.get('Field')} ({c.get('Type')})")

        # 查看模板文件表内容
        for t in tables:
            if "file" in t.lower():
                cur.execute(f"SELECT * FROM `{t}` LIMIT 10")
                rows = cur.fetchall()
                print(f"\n=== {t} data ===")
                for r in rows:
                    print(f"  {r}")
