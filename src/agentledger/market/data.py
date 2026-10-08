"""Price oracle (zoomcamp M1). Order of preference: local CSV cache -> yfinance -> synthetic.

Synthetic prices are deterministic per symbol and anchored to a fixed start date, so the path up to any
date never changes (point-in-time stable) and buyer, seller and adjudicator all see the same data.
Note: seeds come from zlib.crc32, never hash(): str hashes are randomised per process.
"""

from __future__ import annotations

import zlib
from datetime import date, timedelta
from functools import cache

import numpy as np
import pandas as pd

from agentledger.config import load_settings

ANCHOR = date(2020, 1, 1)
HORIZON = date(2035, 12, 31)
PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def load_prices(symbol: str, as_of: date | None = None, lookback_days: int | None = None) -> pd.DataFrame:
    as_of = as_of or date.today()
    source = load_settings().data_source
    df = None
    if source == "yfinance":
        df = _from_cache_or_yfinance(symbol, as_of)
    if df is None:
        df = synthetic_prices(symbol, as_of)
    df = df[df["date"] <= pd.Timestamp(as_of)]
    if lookback_days:
        df = df[df["date"] > pd.Timestamp(as_of - timedelta(days=lookback_days))]
    return df.reset_index(drop=True)


def synthetic_prices(symbol: str, as_of: date) -> pd.DataFrame:
    """Geometric random walk whose drift follows a slow AR(1) regime, so trends exist but are noisy."""
    full = _synthetic_full(symbol.upper())
    return full[full["date"] <= pd.Timestamp(as_of)].copy()


@cache
def _synthetic_full(symbol: str) -> pd.DataFrame:
    # Always draw the same fixed-length path, then slice: the RNG stream must not depend on as_of,
    # otherwise history would change as days pass.
    dates = pd.bdate_range(ANCHOR, HORIZON)
    n = len(dates)
    rng = np.random.default_rng(zlib.crc32(symbol.upper().encode()))
    drift = np.zeros(n)
    shocks = rng.normal(0.0, 0.0009, n)
    for t in range(1, n):
        drift[t] = 0.985 * drift[t - 1] + shocks[t]
    returns = drift + rng.normal(0.0, 0.013, n)
    close = 50.0 * (1 + (zlib.crc32(symbol.encode()) % 300) / 100) * np.exp(np.cumsum(returns))
    spread = np.abs(rng.normal(0.0, 0.006, n))
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0.0, 0.003, n)),
        "high": close * (1 + spread),
        "low": close * (1 - spread),
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n),
    })


def _from_cache_or_yfinance(symbol: str, as_of: date) -> pd.DataFrame | None:
    path = load_settings().cache_dir / f"{symbol.upper()}_{as_of.isoformat()}.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["date"])
    try:
        import yfinance as yf  # optional dependency: pip install -e ".[data]"

        raw = yf.download(symbol, start=ANCHOR.isoformat(), end=(as_of + timedelta(days=1)).isoformat(),
                          auto_adjust=True, progress=False)
    except Exception:  # offline, rate-limited, not installed... fall back to synthetic
        return None
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.reset_index().rename(columns=str.lower)[PRICE_COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df
