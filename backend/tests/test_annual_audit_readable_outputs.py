"""User-facing annual-audit response contracts."""

from ai_hunter.app.graph.nodes.read_only_capabilities import _render_task_list
from ai_hunter.annual_audit.workflow_guide import render_annual_workflow_guide


def test_task_query_is_business_facing_and_not_dehydrated_json():
    output = _render_task_list(
        {
            "case_id": 10,
            "total": 1,
            "tasks": [
                {
                    "task_no": "AUTO-001",
                    "action": "补充应收账款审计证据",
                    "detail": "核对客户主数据并形成处理结论。",
                    "assigned_role": "项目主审",
                    "deadline": "2023-12-31",
                    "deliverable": "复核记录和支持性证据",
                    "priority": "medium",
                    "status": "待执行",
                }
            ],
        }
    )

    assert "AUTO-001" in output
    assert "项目主审" in output
    assert "list_annual_tasks" not in output
    assert "_omitted_keys" not in output
    assert '"tasks"' not in output


def test_workflow_guide_covers_the_complete_delivery_chain():
    output = render_annual_workflow_guide(case_id=10)

    for expected in (
        "风险评估、重要性与审计计划",
        "控制测试与实质性程序",
        "六大循环",
        "三级复核与签发",
        "正式审计报告",
        "管理建议书",
        "证据索引",
        "草稿",
    ):
        assert expected in output
    assert "_omitted_keys" not in output
