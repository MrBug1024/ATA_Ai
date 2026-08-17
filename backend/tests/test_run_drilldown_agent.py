import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages.tool import ToolMessage
from langchain_core.runnables import RunnableLambda

from ai_hunter.app.graph.nodes import run_drilldown_agent as drilldown


def _tool_message(name: str, key_facts: dict, *, truncated: bool = False) -> ToolMessage:
    return ToolMessage(
        name=name,
        tool_call_id=f"call-{name}",
        content=json.dumps(
            {
                "summary": f"{name} completed",
                "key_facts": key_facts,
                "truncated": truncated,
            }
        ),
    )


def test_runtime_model_failure_uses_deterministic_annual_fallback(monkeypatch):
    async def fail_at_runtime(_state):
        raise ConnectionError("provider unavailable")

    monkeypatch.setattr(drilldown, "build_agent_llm", lambda: object())
    monkeypatch.setattr(drilldown, "has_api_key", lambda _llm: True)
    monkeypatch.setattr(
        drilldown,
        "_build_scoped_agent",
        lambda *_args, **_kwargs: RunnableLambda(fail_at_runtime),
    )
    monkeypatch.setattr(
        drilldown,
        "_runtime_fallback_domain_agent_output",
        lambda state, capability: {
            "agent_output": f"degraded:{capability}:{state['current_case_id']}",
            "business_line_result": {"degraded": True},
        },
    )

    runnable = drilldown.build_capability_agent_node("audit.drilldown")
    result = asyncio.run(runnable.ainvoke({"current_case_id": 7}))

    assert result["agent_output"] == "degraded:audit.drilldown:7"
    assert result["business_line_result"]["degraded"] is True


def test_extract_agent_output_keeps_only_current_successful_analysis_scope():
    historical_sales = _tool_message(
        "analyze_sales_receivables",
        {"analysis_type": "sales_receivables", "analysis_run_id": 7},
    )
    current_sales = _tool_message(
        "analyze_sales_receivables",
        {"analysis_type": "sales_receivables", "analysis_run_id": 41},
    )
    current_cash = _tool_message(
        "analyze_cash_and_bank",
        {"analysis_type": "cash_and_bank", "analysis_run_id": "42"},
    )
    mismatched_type = _tool_message(
        "analyze_sales_receivables",
        {"analysis_type": "cash_and_bank", "analysis_run_id": 43},
    )
    failed_analysis = _tool_message(
        "analyze_cash_and_bank",
        {"error": "database unavailable"},
    )
    current_evidence = _tool_message(
        "search_annual_evidence",
        {
            "items": [{"chunk_id": "current-chunk", "file_id": 9}],
            "returned_count": 1,
            "total_count": 1,
        },
    )
    failed_evidence = _tool_message(
        "search_annual_evidence",
        {"error": "vector store unavailable"},
    )

    result = drilldown._extract_agent_output(
        {
            "messages": [
                HumanMessage(content="earlier query"),
                historical_sales,
                AIMessage(content="earlier answer"),
                HumanMessage(content="current query"),
                current_sales,
                current_cash,
                mismatched_type,
                failed_analysis,
                current_evidence,
                failed_evidence,
                AIMessage(content="current answer"),
            ]
        }
    )

    assert result["agent_output"] == "current answer"
    assert result["response_analysis_runs"] == [
        {
            "tool_name": "analyze_sales_receivables",
            "analysis_type": "sales_receivables",
            "analysis_run_id": 41,
        },
        {
            "tool_name": "analyze_cash_and_bank",
            "analysis_type": "cash_and_bank",
            "analysis_run_id": 42,
        },
    ]
    assert result["response_evidence_tool_results"] == [
        {
            "tool_name": "search_annual_evidence",
            "key_facts": {
                "items": [{"chunk_id": "current-chunk", "file_id": 9}],
                "returned_count": 1,
                "total_count": 1,
            },
            "truncated": False,
        }
    ]


def test_extract_agent_output_clears_scope_when_no_tool_messages_exist():
    result = drilldown._extract_agent_output({"messages": [AIMessage(content="plain answer")]})

    assert result == {
        "agent_output": "plain answer",
        "response_analysis_runs": [],
        "response_evidence_tool_results": [],
    }


def test_audit_drilldown_rejects_an_answer_when_no_tool_result_succeeded():
    failed_tool = ToolMessage(
        name="get_annual_engagement",
        tool_call_id="call-missing-engagement",
        content=json.dumps(
            {
                "summary": "engagement lookup failed",
                "key_facts": {"error": "engagement not found"},
                "truncated": False,
            }
        ),
    )

    result = drilldown._extract_agent_output(
        {
            "messages": [
                HumanMessage(content="请审计项目 10"),
                failed_tool,
                AIMessage(content="不应输出的虚构审计结论"),
            ]
        },
        capability="audit.drilldown",
    )

    assert result["business_line_result"]["error"] == "no_successful_audit_tool_result"
    assert "不能形成审计事实" in result["agent_output"]
    assert result["response_analysis_runs"] == []
