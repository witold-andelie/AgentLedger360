"""Token accounting for AI agents (pattern from witold-andelie/revio output/cost.py).

Prices are USD per 1M tokens, which is numerically micro-USD per token, so
cost_micro_usd = input_tokens * in_rate + output_tokens * out_rate  (rounded to an int).
Unknown models are reported as unpriced instead of a misleading $0.00.
Override any price with AL_LLM_PRICE_IN / AL_LLM_PRICE_OUT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentledger.config import Settings

PRICES_AS_OF = "2026-10-08"

# model-id fragment -> (USD per 1M input, USD per 1M output, source)
PRICING: dict[str, tuple[float, float, str]] = {
    # Anthropic list prices
    "claude-fable-5-1": (10.0, 50.0, "anthropic list price"),
    "claude-opus-5-5": (4.0, 20.0, "anthropic list price"),
    "claude-opus-5": (5.0, 25.0, "anthropic list price"),
    "claude-sonnet-5-5": (2.0, 10.0, "anthropic list price"),
    "claude-sonnet-5": (2.0, 10.0, "anthropic list price"),
    "claude-haiku-5-5": (0.10, 0.50, "anthropic list price (prompts <= 100K tokens)"),
    "claude-opus-4-8": (5.0, 25.0, "anthropic list price"),
    "claude-haiku-4-5": (1.0, 5.0, "anthropic list price"),
    # Mistral: only Large is on mistral.ai/pricing; the others are third-party trackers - verify on billing
    "mistral-large": (0.5, 1.5, "mistral.ai/pricing"),
    "mistral-medium": (1.5, 7.5, "third-party tracker, verify on Mistral billing"),
    "mistral-small": (0.10, 0.30, "third-party tracker, verify on Mistral billing"),
    # DeepSeek (OpenAI-compatible), as tabulated in revio 2026-05
    "deepseek-v4-flash": (0.14, 0.55, "revio price table 2026-05"),
    "deepseek-v4-pro": (0.27, 1.10, "revio price table 2026-05"),
    "deepseek-chat": (0.27, 1.10, "revio price table 2026-05"),
}


@dataclass(frozen=True)
class Price:
    input_per_m: float
    output_per_m: float
    source: str


def price_for(model: str, settings: Settings | None = None) -> Price | None:
    if settings and settings.llm_price_in is not None and settings.llm_price_out is not None:
        return Price(settings.llm_price_in, settings.llm_price_out, "AL_LLM_PRICE_IN/OUT override")
    m = (model or "").lower()
    best = max((key for key in PRICING if key in m), key=len, default="")
    if not best:
        return None
    rate_in, rate_out, source = PRICING[best]
    return Price(rate_in, rate_out, f"{source}, as of {PRICES_AS_OF}")


def cost_micro_usd(price: Price | None, input_tokens: int, output_tokens: int) -> int:
    if price is None:
        return 0
    return round(input_tokens * price.input_per_m + output_tokens * price.output_per_m)


def usage_from_message(message: Any) -> tuple[int, int]:
    """(input_tokens, output_tokens) from a LangChain AIMessage, whatever the provider."""
    usage = getattr(message, "usage_metadata", None) or {}
    if usage:
        return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
    meta = getattr(message, "response_metadata", None) or {}
    raw = meta.get("token_usage") or meta.get("usage") or {}
    return (int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0),
            int(raw.get("completion_tokens") or raw.get("output_tokens") or 0))


def format_usd(micro_usd: int) -> str:
    usd = micro_usd / 1_000_000
    if usd == 0:
        return "$0.00"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}" if usd < 1 else f"${usd:.2f}"
