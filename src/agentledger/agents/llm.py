"""Chat-model factory for the agents (pattern from witold-andelie/revio agent/llm.py).

Providers (AL_LLM_PROVIDER):
- mistral        ChatMistralAI, key MISTRAL_API_KEY                     (default)
- anthropic      ChatAnthropic, key ANTHROPIC_API_KEY
- openai_compat  ChatOpenAI against any OpenAI-compatible endpoint (DeepSeek by default),
                 key AL_LLM_API_KEY or DEEPSEEK_API_KEY, base URL AL_LLM_BASE_URL

Every model exposes .bind_tools() and .invoke() and reports token usage in usage_metadata, so the
graph in agents/graph.py and the meter in agents/accounting.py stay provider-agnostic.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from agentledger.config import Settings

DEFAULT_MODELS = {
    "mistral": "mistral-medium-latest",
    "anthropic": "claude-opus-5-5",
    "openai_compat": "deepseek-v4-flash",
}
KEY_ENVS = {
    "mistral": ("MISTRAL_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai_compat": ("AL_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
}
PACKAGES = {"mistral": "langchain_mistralai", "anthropic": "langchain_anthropic", "openai_compat": "langchain_openai"}
# Anthropic models that accept the server-side refusal fallback (re-runs a declined request on another model)
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")


class LLMUnavailableError(RuntimeError):
    """No usable provider: missing package, missing key, or unknown provider."""


def model_name(s: Settings) -> str:
    return s.llm_model or DEFAULT_MODELS.get(s.llm_provider, "")


def api_key(s: Settings) -> str | None:
    if os.getenv("AL_LLM_API_KEY"):
        return os.getenv("AL_LLM_API_KEY")
    return next((os.environ[k] for k in KEY_ENVS.get(s.llm_provider, ()) if os.getenv(k)), None)


def llm_available(s: Settings) -> bool:
    package = PACKAGES.get(s.llm_provider)
    return bool(package and importlib.util.find_spec(package) and api_key(s))


def resolve_mode(s: Settings) -> str:
    """'llm' or 'rule'. auto = LLM when a provider key is configured, otherwise the deterministic agent."""
    if s.agent_mode == "rule":
        return "rule"
    if s.agent_mode == "llm":
        if not llm_available(s):
            raise LLMUnavailableError(f"AL_AGENT_MODE=llm but provider {s.llm_provider!r} has no key or package")
        return "llm"
    return "llm" if llm_available(s) else "rule"


def make_chat_model(s: Settings, max_tokens: int = 2048) -> Any:
    provider, model, key = s.llm_provider, model_name(s), api_key(s)
    if not llm_available(s) or key is None:
        raise LLMUnavailableError(f"provider {provider!r}: install `.[agent]` and set {KEY_ENVS.get(provider)}")

    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI

        return ChatMistralAI(model=model, api_key=key, temperature=0, max_tokens=max_tokens, max_retries=3,
                             timeout=90)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Current Claude models reject sampling parameters and run adaptive thinking by default,
        # so no temperature / thinking arguments here.
        kwargs: dict[str, Any] = {"model": model, "api_key": key, "max_tokens": max_tokens, "max_retries": 3,
                                  "timeout": 120}
        if s.llm_base_url:
            kwargs["base_url"] = s.llm_base_url
        if any(model.startswith(m) for m in _FALLBACK_MODELS):
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["model_kwargs"] = {"fallbacks": "default"}
        return ChatAnthropic(**kwargs)

    if provider == "openai_compat":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=key, base_url=s.llm_base_url or "https://api.deepseek.com",
                          temperature=0, max_tokens=max_tokens, max_retries=3, timeout=90)

    raise LLMUnavailableError(f"unknown provider {provider!r}")
