"""Thin factory helpers for model construction inside graph nodes."""

from langchain_openai import ChatOpenAI

from ..settings import get_settings


def _normalize_temperature(provider: str, base_url: str | None, temperature: float) -> float:
    """Keep structured-output temperatures compatible with provider quirks."""
    normalized = max(temperature, 0.0)
    if provider == "minimax" and base_url and "minimaxi.com" in base_url and normalized <= 0:
        return 0.01
    return normalized


def _build_chat_model(role: str, temperature: float, provider_override: str | None = None) -> ChatOpenAI:
    """Construct the shared OpenAI-compatible chat client used by graph nodes.

    provider_override 用于按段分流（核心段走 kimi 等），不影响其它 role。
    """
    settings = get_settings()
    config = settings.get_llm_config(role, provider_override=provider_override)
    kwargs = {}
    if config["provider"] == "minimax" and config["base_url"] and "minimaxi.com" in config["base_url"]:
        # MiniMax can split reasoning from final content on the OpenAI-compatible endpoint.
        kwargs["extra_body"] = {"reasoning_split": True}
    if role == "report_a" and config["provider"] == "kimi" and settings.report_section_max_completion_tokens_kimi > 0:
        # Kimi-compatible reasoning models can spend the default completion budget on reasoning only.
        kwargs["max_completion_tokens"] = settings.report_section_max_completion_tokens_kimi
    return ChatOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        temperature=_normalize_temperature(config["provider"], config["base_url"], temperature),
        **kwargs,
    )


def has_api_key(llm: ChatOpenAI) -> bool:
    """Return True when the model client carries a usable API key.

    ChatOpenAI stores the key on ``openai_api_key`` as a SecretStr, so a plain
    ``llm.api_key`` access raises AttributeError. Resolve the real secret value
    instead of trusting the wrapper object's truthiness.
    """
    secret = getattr(llm, "openai_api_key", None)
    if secret is None:
        return False
    value = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
    return bool(value and str(value).strip())


def build_router_llm() -> ChatOpenAI:
    """Build the low-cost router model with deterministic-ish settings."""
    settings = get_settings()
    return _build_chat_model("router", settings.openai_temperature_router)


def build_zero_temp_router_llm() -> ChatOpenAI:
    """Build a near-zero-temperature small model for structured routing or correction extraction."""
    return _build_chat_model("router", 0)


def build_report_a_llm() -> ChatOpenAI:
    """Build the model used for the first half of the audit report."""
    settings = get_settings()
    return _build_chat_model("report_a", settings.openai_temperature_report)


def build_report_b_llm() -> ChatOpenAI:
    """Build the model used for the second half of the audit report."""
    settings = get_settings()
    return _build_chat_model("report_b", settings.openai_temperature_report)


def build_report_section_llm(provider_override: str | None = None) -> ChatOpenAI:
    """Build the per-section report model（按段分流：核心段可 provider_override='kimi'）。"""
    settings = get_settings()
    return _build_chat_model("report_a", settings.openai_temperature_report, provider_override=provider_override)


def build_agent_llm() -> ChatOpenAI:
    """Build the model used by the drilldown tool-calling agent."""
    settings = get_settings()
    return _build_chat_model("agent", settings.openai_temperature_agent)
