"""测试修改后的附件生成功能。"""
import json
import sys
from pathlib import Path

# 设置路径
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from ai_hunter.app.settings import get_settings
from ai_hunter.annual_audit.file_attachment_service import (
    generate_annual_attachment_package,
    _load_trial_balance,
    _context,
)

settings = get_settings()
engagement_id = 1

# 1. 先测试科目余额表加载
print("=== 1. 测试科目余额表加载 ===")
tb = _load_trial_balance(engagement_id, settings)
print(f"科目数: {len(tb['accounts'])}")
print(f"有余额的科目数: {len(tb['by_name'])}")
print("\n有余额的科目（前20个）:")
for name, data in list(tb["by_name"].items())[:20]:
    cd = data.get("closing_debit", 0)
    cc = data.get("closing_credit", 0)
    od = data.get("opening_debit", 0)
    oc = data.get("opening_credit", 0)
    if cd != 0 or cc != 0 or od != 0 or oc != 0:
        print(f"  {name}: 期末借{cd:.2f} 贷{cc:.2f} | 期初借{od:.2f} 贷{oc:.2f}")

# 2. 生成附件包
print("\n=== 2. 生成附件包 ===")
try:
    result = generate_annual_attachment_package(
        engagement_id,
        created_by="test_script",
        settings=settings,
    )
    print(f"包ID: {result['package_id']}")
    print(f"版本: {result['package_version']}")
    print(f"状态: {result['status']}")
    print(f"附件数: {len(result['artifacts'])}")
    print(f"错误: {result.get('errors', [])}")
    print("\n附件列表:")
    for art in result["artifacts"]:
        print(f"  - {art.get('file_name')} | 填充状态: {art.get('template_fill_status')} | 格式: {art.get('output_file_ext')}")
except Exception as e:
    print(f"生成失败: {e}")
    import traceback
    traceback.print_exc()
