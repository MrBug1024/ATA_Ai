"""八段式报告子 agent（Tier1-2）：注册表 + 节点工厂 + 流式映射。"""

import pytest

from ai_hunter.app.graph.nodes.generate_sections import build_section_node, _slice_context
from ai_hunter.app.graph.report_sections import (
    SECTION_BY_NODE,
    SECTIONS,
    section_id_from_node,
    section_node_name,
)


def test_registry_has_8_sections_with_audience():
    assert [s["id"] for s in SECTIONS] == ["1", "2", "3", "4", "5", "6", "7", "8"]
    # 每段都有标题/prompt/audience；provider 不在注册表硬编码，默认跟随 LLM_PROVIDER_REPORT_A。
    for s in SECTIONS:
        assert s["title"] and s["prompt"].startswith("report_s") and s["audience"] in {"field", "expert", "management"}
        assert "provider" not in s
    # §7 标记 tasks
    assert SECTION_BY_NODE[section_node_name("7")].get("tasks") is True


def test_section_node_name_roundtrip():
    assert section_node_name("3") == "generate_section_3"
    assert section_id_from_node("generate_section_3") == "3"
    assert section_id_from_node("compute_metrics") is None
    assert section_id_from_node("") is None


def test_slice_context_picks_section_keys_plus_common():
    state = {
        "full_context_data": {
            "case_id": 116,
            "real_estate_dehydrated": {"_meta": {"total_count": 6}},
            "mining_dehydrated": {"_meta": {"total_count": 3}},
            "claims": [{"principal": 100.0, "interest": 20.0}],
            "engine_results": {"valuation_squeeze": {"real_estate_valuations": []}},
            "fund_flow": {"x": 1},
        },
    }
    s2 = next(s for s in SECTIONS if s["id"] == "2")
    sliced = _slice_context(state, s2)
    # 公共：case_id + computed_metrics
    assert sliced["case_id"] == 116
    assert "computed_metrics" in sliced
    # §2 data_keys 含 real_estate / mining / valuation_detail / claims
    assert "real_estate" in sliced and "mining" in sliced and "valuation_detail" in sliced
    # 不属于 §2 的 fund_flow 不应切进来
    assert "fund_flow" not in sliced


def test_is_overloaded_classification():
    from ai_hunter.app.graph.nodes.generate_sections import _is_overloaded
    assert _is_overloaded(Exception("Error code: 529 - overloaded_error 服务集群负载较高"))
    assert _is_overloaded(Exception("rate limit exceeded (429)"))
    assert _is_overloaded(TimeoutError("request timeout"))
    assert not _is_overloaded(ValueError("bad input"))
    assert not _is_overloaded(Exception("401 invalid api key"))


def test_report_section_concurrency_settings_accept_inline_comments_and_provider_overrides():
    from ai_hunter.app.settings import Settings

    settings = Settings(
        _env_file=None,
        report_section_concurrency="4 # global",
        report_section_concurrency_kimi="2 # kimi",
        report_section_concurrency_minimax="",
    )

    assert settings.report_section_concurrency_for("kimi") == 2
    assert settings.report_section_concurrency_for("minimax") == 4
    assert settings.report_section_concurrency_for("faker") == 4
    assert Settings(_env_file=None, report_section_concurrency="0").report_section_concurrency == 1
    assert Settings(_env_file=None, report_section_concurrency="bad value").report_section_concurrency == 3


def test_report_section_provider_settings_validate_and_resolve_overrides():
    from pydantic import ValidationError
    from ai_hunter.app.settings import Settings

    settings = Settings(
        _env_file=None,
        report_section_provider_1="KIMI # core section",
        report_section_provider_2="",
    )

    assert settings.report_section_provider_for("1") == "kimi"
    assert settings.report_section_provider_for("2") is None
    assert settings.report_section_provider_for("9") is None
    with pytest.raises(ValidationError, match="不支持的报告段 provider"):
        Settings(_env_file=None, report_section_provider_1="unknown")


def test_report_section_timeout_setting_accepts_inline_comments():
    from ai_hunter.app.settings import Settings

    assert Settings(_env_file=None, report_section_timeout_seconds="120 # seconds").report_section_timeout_seconds == 120
    assert Settings(_env_file=None, report_section_timeout_seconds="0 # too low").report_section_timeout_seconds == 10
    assert Settings(_env_file=None, report_section_timeout_seconds="").report_section_timeout_seconds == 150
    assert Settings(_env_file=None, report_section_timeout_seconds="bad value").report_section_timeout_seconds == 150


def test_section_timeout_seconds_reads_settings(monkeypatch):
    import ai_hunter.app.graph.nodes.generate_sections as gs

    class _S:
        report_section_timeout_seconds = 300

    monkeypatch.setattr(gs, "get_settings", lambda: _S())

    assert gs._section_timeout_seconds() == 300


def test_section_failure_text_uses_section_metadata():
    from ai_hunter.app.graph.nodes.generate_sections import _section_failure_text

    text = _section_failure_text({"id": "6", "title": "猎人行动令"}, "本段 LLM 生成超时")
    assert "第6段占位：猎人行动令" in text
    assert "本段 LLM 生成超时" in text


def test_clean_section_text_strips_reasoning_tags():
    from ai_hunter.app.graph.nodes.generate_sections import _clean_section_text

    assert _clean_section_text("<think></think>") == ""
    assert _clean_section_text("<think>内部推理</think>## 6. 标题") == "## 6. 标题"


def test_section_provider_override_reads_settings(monkeypatch):
    import ai_hunter.app.graph.nodes.generate_sections as gs
    from ai_hunter.app.graph.nodes.generate_sections import _section_provider_override

    class _Settings:
        @staticmethod
        def report_section_provider_for(section_id):
            return "kimi" if section_id == "2" else None

    monkeypatch.setattr(gs, "get_settings", lambda: _Settings())

    assert _section_provider_override({"id": "2"}) == "kimi"
    assert _section_provider_override({"id": "3"}) is None


def test_section_provider_override_is_used_for_node_build(monkeypatch):
    import ai_hunter.app.graph.nodes.generate_sections as gs

    calls = {"configs": [], "llms": []}

    class _S:
        @staticmethod
        def report_section_provider_for(section_id):
            return "kimi" if section_id == "2" else None

        def get_llm_config(self, role, provider_override=None):
            calls["configs"].append((role, provider_override))
            return {"api_key": "key", "provider": provider_override or "minimax"}

    class _LLM:
        def invoke(self, messages):
            return type("R", (), {"content": "ok"})()

    def _fake_build_report_section_llm(provider_override=None):
        calls["llms"].append(provider_override)
        return _LLM()

    monkeypatch.setattr(gs, "get_settings", lambda: _S())
    monkeypatch.setattr(gs, "build_report_section_llm", _fake_build_report_section_llm)

    gs.build_section_node(next(s for s in SECTIONS if s["id"] == "2"))

    assert ("report_a", "kimi") in calls["configs"]
    assert "kimi" in calls["llms"]


def test_kimi_report_section_llm_uses_configured_completion_budget(monkeypatch):
    import ai_hunter.app.graph.llm as llm_mod

    captured = {}

    class _S:
        openai_temperature_report = 0.7
        report_section_max_completion_tokens_kimi = 12288

        def get_llm_config(self, role, provider_override=None):
            return {
                "provider": "kimi",
                "api_key": "key",
                "base_url": "https://faker-model.rhzy.ai/v1",
                "model": "kimi/Kimi-k2.6",
            }

    class _ChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_mod, "get_settings", lambda: _S())
    monkeypatch.setattr(llm_mod, "ChatOpenAI", _ChatOpenAI)

    llm_mod.build_report_section_llm(provider_override="kimi")

    assert captured["max_completion_tokens"] == 12288


def test_astream_section_retries_on_overload():
    import asyncio
    from ai_hunter.app.graph.nodes import generate_sections as gs

    calls = {"n": 0}

    class _FakeLLM:
        async def astream(self, messages):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("Error code: 529 overloaded_error")  # 首次过载
            for piece in ["第一段", "内容"]:
                yield type("C", (), {"content": piece})()

    # 把退避缩短，避免测试慢
    monkeypatch_sleep = gs.asyncio.sleep
    async def _fast_sleep(_): return None
    gs.asyncio.sleep = _fast_sleep
    try:
        text = asyncio.run(gs._astream_section_text(_FakeLLM(), [], section_id="1"))
    finally:
        gs.asyncio.sleep = monkeypatch_sleep
    assert text == "第一段内容"
    assert calls["n"] == 2  # 重试 1 次后成功


def test_section_semaphore_bounds_concurrency(monkeypatch):
    import asyncio
    from ai_hunter.app.graph.nodes import generate_sections as gs

    class _S:
        @staticmethod
        def report_section_concurrency_for(provider):
            assert provider == "minimax"
            return 2

    monkeypatch.setattr(gs, "get_settings", lambda: _S())
    gs._SECTION_SEMS = {}  # 强制按新 limit 重建
    state = {"running": 0, "peak": 0}

    async def worker():
        async with gs._section_semaphore("minimax"):
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
            await asyncio.sleep(0.05)
            state["running"] -= 1

    async def main():
        await asyncio.gather(*[worker() for _ in range(6)])

    asyncio.run(main())
    assert state["peak"] <= 2  # 并发被限到 2


def test_section_node_fallback_writes_ref(monkeypatch):
    # 无 api key → fallback 占位，写 report_section_refs[id]
    import ai_hunter.app.graph.nodes.generate_sections as gs

    class _S:
        @staticmethod
        def report_section_provider_for(section_id):
            return None

        def get_llm_config(self, role, provider_override=None):
            return {"api_key": "", "provider": provider_override or "minimax"}

    monkeypatch.setattr(gs, "get_settings", lambda: _S())
    node = build_section_node(next(s for s in SECTIONS if s["id"] == "1"))
    out = node.invoke({})
    refs = out["report_section_refs"]
    assert "1" in refs and refs["1"]
