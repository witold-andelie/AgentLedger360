"""One-row research note. The stance is computed from the tape; prose may come from an LLM.

When no model is configured, or the draft fails the contract, a deterministic note is shipped instead.
The buyer still re-checks the row. The model is never allowed to pick the stance.
"""

from __future__ import annotations

import unicodedata
from datetime import date

import pandas as pd

from agentledger.config import load_settings
from agentledger.contracts import TaskSpec
from agentledger.market import data


def expected_stance(symbol: str, as_of: date) -> str:
    """LONG when the close is higher than five sessions earlier, otherwise FLAT. No prices after as_of."""
    prices = data.load_prices(symbol, as_of=as_of)
    if prices.empty or len(prices) < 6:
        return "FLAT"
    frame = prices.sort_values("date")
    start = float(frame.iloc[-6]["close"])
    end = float(frame.iloc[-1]["close"])
    return "LONG" if end > start else "FLAT"


def template_note(symbol: str, as_of: date, stance: str) -> str:
    direction = "higher" if stance == "LONG" else "not higher"
    return (
        f"{symbol} as of {as_of.isoformat()}: the close versus five sessions earlier is {direction}, "
        f"so the stance is {stance}. This commentary states only that trailing fact."
    )


def _clean(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C").strip()


def _draft_with_model(symbol: str, as_of: date, stance: str) -> str | None:
    from agentledger.agents.llm import llm_available, make_chat_model, resolve_mode

    settings = load_settings()
    if resolve_mode(settings) != "llm" or not llm_available(settings):
        return None
    prompt = (
        f"Write two sentences about {symbol} as of {as_of.isoformat()}. "
        f"The stance is {stance}. Mention {symbol}. Do not give the reader instructions. "
        "Stay between 40 and 280 characters."
    )
    try:
        message = make_chat_model(settings, max_tokens=180).invoke(prompt)
    except Exception:
        return None
    text = _clean(getattr(message, "content", "") or "")
    if not _note_ok(text, symbol):
        return None
    return text


def _note_ok(text: str, symbol: str) -> bool:
    return 40 <= len(text) <= 400 and symbol.upper() in text.upper()


def build_note(task: TaskSpec) -> pd.DataFrame:
    as_of = task.as_of or date.today()
    stance = expected_stance(task.symbol, as_of)
    note = _draft_with_model(task.symbol, as_of, stance) or template_note(task.symbol, as_of, stance)
    return pd.DataFrame([{
        "date": as_of.isoformat(),
        "symbol": task.symbol,
        "stance": stance,
        "note": note,
    }])
