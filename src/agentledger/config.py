"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent / "sql"  # shipped inside the package (works when pip-installed)


@dataclass(frozen=True)
class Settings:
    var_dir: Path
    payment_secret: str
    fee_bps: int
    order_ttl_seconds: int   # cancel FUNDS_HELD orders older than this (AL_ORDER_TTL_SECONDS)
    data_source: str
    role: str                # all | sellers  (what this web process serves, see server.py)
    seller_url: str | None   # remote seller service for the buyer; None = in-process sellers
    seller_public_url: str   # base URL this seller service advertises in its agent cards
    frontend_dist: Path      # Vite build output served at "/" when present
    admin_token: str | None  # if set, POST /api/demo/reset requires header X-Admin-Token (set it on Render)
    daily_ai_budget_usd: float   # past this, a round degrades to the rule agent (AL_DAILY_AI_BUDGET_USD)
    run_token: str | None         # if set, starting a round requires header X-Run-Token
    round_min_interval_seconds: int  # minimum gap between rounds from the same IP; 0 disables the limit
    # ---- AI agents (agents/llm.py, agents/graph.py) ----
    agent_mode: str          # auto (LLM if a key is configured) | llm | rule (deterministic fallback)
    llm_provider: str        # mistral | anthropic | openai_compat (DeepSeek, OpenRouter, vLLM, ...)
    llm_model: str           # empty = provider default (see agents/llm.py DEFAULT_MODELS)
    llm_base_url: str | None
    agent_max_tool_calls: int    # per agent run (revio-style tool budget)
    agent_max_cost_usd: float    # per agent run; the loop stops when the meter crosses it
    llm_price_in: float | None   # USD per 1M input tokens, overrides the built-in price table
    llm_price_out: float | None  # USD per 1M output tokens

    @property
    def core_db(self) -> Path:
        return self.var_dir / "core.db"

    @property
    def analytics_db(self) -> Path:
        return self.var_dir / "analytics.db"

    @property
    def cache_dir(self) -> Path:
        return self.var_dir / "cache"


def load_settings() -> Settings:
    return Settings(
        var_dir=Path(os.getenv("AL_VAR_DIR", "var")).resolve(),
        payment_secret=os.getenv("AL_PAYMENT_SECRET", "dev-secret-change-me"),
        fee_bps=int(os.getenv("AL_FEE_BPS", "200")),
        order_ttl_seconds=int(os.getenv("AL_ORDER_TTL_SECONDS", "300")),
        data_source=os.getenv("AL_DATA_SOURCE", "synthetic"),
        role=os.getenv("AL_ROLE", "all"),
        seller_url=os.getenv("AL_SELLER_URL") or None,
        seller_public_url=os.getenv("AL_SELLER_PUBLIC_URL", "inproc://sellers").rstrip("/"),
        frontend_dist=Path(os.getenv("AL_FRONTEND_DIST", "frontend/dist")).resolve(),
        admin_token=os.getenv("AL_ADMIN_TOKEN") or None,
        daily_ai_budget_usd=float(os.getenv("AL_DAILY_AI_BUDGET_USD", "2.00")),
        run_token=os.getenv("AL_RUN_TOKEN") or None,
        round_min_interval_seconds=int(os.getenv("AL_ROUND_MIN_INTERVAL_SECONDS", "60")),
        agent_mode=os.getenv("AL_AGENT_MODE", "auto"),
        llm_provider=os.getenv("AL_LLM_PROVIDER", "mistral"),
        llm_model=os.getenv("AL_LLM_MODEL", ""),
        llm_base_url=os.getenv("AL_LLM_BASE_URL") or None,
        agent_max_tool_calls=int(os.getenv("AL_AGENT_MAX_TOOL_CALLS", "30")),
        agent_max_cost_usd=float(os.getenv("AL_AGENT_MAX_COST_USD", "0.50")),
        llm_price_in=_optional_float("AL_LLM_PRICE_IN"),
        llm_price_out=_optional_float("AL_LLM_PRICE_OUT"),
    )


def _optional_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None
