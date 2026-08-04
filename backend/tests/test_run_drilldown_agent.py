import asyncio

from langchain_core.runnables import RunnableLambda

from ai_hunter.app.graph.nodes import run_drilldown_agent as drilldown


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
