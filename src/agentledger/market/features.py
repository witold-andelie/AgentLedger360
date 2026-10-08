"""Feature engineering (zoomcamp M2): growth_Nd, moving averages, RSI, volatility, calendar dummies,
and the forward-looking target. Hand-rolled in pandas: TA-Lib's C build is painful on Windows/3.13.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GROWTH_WINDOWS = (1, 5, 20, 60)
FEATURE_COLUMNS = ["date", *[f"growth_{n}d" for n in GROWTH_WINDOWS], "sma_10", "sma_50", "rsi_14", "vol_20",
                   "weekday", "month"]


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def add_features(prices: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:
    df = prices.copy()
    for n in GROWTH_WINDOWS:
        df[f"growth_{n}d"] = df["close"] / df["close"].shift(n)
    df["sma_10"] = df["close"].rolling(10).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df["rsi_14"] = rsi(df["close"])
    df["vol_20"] = df["close"].pct_change().rolling(20).std() * np.sqrt(252)
    df["weekday"] = df["date"].dt.weekday
    df["month"] = df["date"].dt.month
    # Target - never ship these columns to a buyer (that would be look-ahead).
    df[f"future_growth_{horizon}d"] = df["close"].shift(-horizon) / df["close"]
    df[f"is_up_{horizon}d"] = (df[f"future_growth_{horizon}d"] > 1).astype(float)
    df.loc[df[f"future_growth_{horizon}d"].isna(), f"is_up_{horizon}d"] = np.nan
    return df
