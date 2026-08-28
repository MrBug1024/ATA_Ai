"""查看已激活的模板版本和文件。"""
from ai_hunter.annual_audit.storage import mysql_connection
from ai_hunter.app.settings import get_settings

settings = get_settings()
with mysql_connection(settings) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tv.id, t.template_type, tv.version_no, tv.status, tv.version_label
            FROM annual_audit_template_version tv
            JOIN annual_audit_template t ON tv.template_id = t.id
            WHERE tv.status = 'active'
        """)
        rows = cur.fetchall()
        print("=== 激活的模板版本 ===")
        for r in rows:
            print(f"  {r}")

        cur.execute("""
            SELECT tvf.id, tvf.file_name, tvf.file_ext, tvf.template_version_id,
                   t.template_type
            FROM annual_audit_template_version_file tvf
            JOIN annual_audit_template_version tv ON tvf.template_version_id = tv.id
            JOIN annual_audit_template t ON tv.template_id = t.id
            WHERE tv.status = 'active'
        """)
        files = cur.fetchall()
        print("\n=== 激活的模板文件 ===")
        for f in files:
            print(f"  {f}")
