from ai_hunter.app.graph.write_contracts import resolve_case_create_command


def test_structured_create_command_builds_annual_engagement_payload():
    payload, missing = resolve_case_create_command(
        {
            "query": "创建年度审计项目",
            "write_command": {
                "capability": "case.create",
                "case_name": "示例制造有限公司 2025 年度审计",
                "entity_name": "示例制造有限公司",
                "entity_uscc": "91110000123456789A",
                "fiscal_year": 2025,
            },
        }
    )
    assert missing == []
    assert payload == {
        "case_name": "示例制造有限公司 2025 年度审计",
        "entity_name": "示例制造有限公司",
        "case_type": "年度财务报表审计",
        "entity_uscc": "91110000123456789A",
        "fiscal_year": 2025,
    }


def test_create_command_requires_project_entity_and_fiscal_year():
    _, missing = resolve_case_create_command({"write_command": {"capability": "case.create"}})
    assert missing == ["case_name", "entity_name", "fiscal_year"]
