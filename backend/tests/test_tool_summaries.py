import json

from ai_hunter.app.tools.case_tools import fetch_enterprise
from ai_hunter.app.tools.summary_utils import build_tool_error, build_tool_result


class _FakeEnterpriseClient:
    def fetch_enterprise_sync(self, case_id: int, company_name: str, depth: int):
        return {
            "company_name": company_name,
            "chains": [
                {
                    "name": f"关联公司{i}",
                    "raw_text": "x" * 600,
                }
                for i in range(8)
            ],
            "attachments": ["y" * 500 for _ in range(3)],
        }


def test_build_tool_result_returns_dehydrated_envelope():
    payload = {
        "records": [{"name": f"项目{i}", "detail": "z" * 500} for i in range(7)],
        "meta": {"source": "unit-test"},
    }
    result = json.loads(build_tool_result("demo_tool", payload))

    assert set(result.keys()) == {"summary", "key_facts", "truncated", "next_hint"}
    assert result["truncated"] is True
    assert "demo_tool" in result["summary"]
    assert "records" in result["key_facts"]


def test_build_tool_error_returns_uniform_shape():
    result = json.loads(build_tool_error("demo_tool", RuntimeError("boom")))

    assert result["summary"] == "demo_tool 调用失败。"
    assert result["key_facts"]["error"] == "boom"
    assert result["truncated"] is False


def test_fetch_enterprise_uses_summary_wrapper(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.tools.case_tools.get_enterprise_api_client",
        lambda: _FakeEnterpriseClient(),
    )

    result = json.loads(fetch_enterprise.invoke({"case_id": 116, "company_name": "万海隆", "depth": 3}))

    assert result["truncated"] is True
    assert "fetch_enterprise" in result["summary"]
    assert "chains" in result["key_facts"]
