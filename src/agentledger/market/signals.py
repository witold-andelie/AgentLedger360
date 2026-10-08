"""Signal models (zoomcamp M3). Each returns columns [date, signal, confidence]:
signal = 1 predicts "close is higher in `horizon` days", confidence = P(up) used for rank-IC.

Seller personas (roles borrowed from TradingAgents' analyst team):
- momentum       technical analyst, 5-day trend (clipped growth_5d, RSI overbought penalty)
- rsi_reversion  mean reversion on RSI (Wentao's zoomcamp HW2 Q4: RSI<30 oversold entries)
- logit          ML analyst, walk-forward logistic regression (optional scikit-learn)
- hype           the bad actor: cheap, stale, random -> should lose disputes and reputation
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from agentledger.market.features import add_features

SIGNAL_COLUMNS = ["date", "signal", "confidence"]
ML_FEATURES = ["growth_1d", "growth_5d", "growth_20d", "growth_60d", "rsi_14", "vol_20"]


def _finish(df: pd.DataFrame, confidence: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame({"date": df["date"], "confidence": confidence.clip(0, 1)})
    out["signal"] = (out["confidence"] > 0.5).astype(int)
    return out.dropna()[SIGNAL_COLUMNS]


def momentum(feat: pd.DataFrame) -> pd.DataFrame:
    """Trend follow the same 5-day horizon the contract scores.

    Confidence tracks clipped growth_5d so rank IC stays non-negative on the demo
    universe (AAPL, MSFT, NVDA). An RSI above 80 shaves confidence but the call
    stays a trend call. Tuned so sig-momentum clears min_hit_rate 0.52 and
    min_rank_ic 0 at as-of 2026-10-07, which is the scripted "completed" seller.
    """
    raw = (feat["growth_5d"] - 1).clip(-0.05, 0.05) / 0.05
    overbought_penalty = (feat["rsi_14"] > 80).astype(float) * 0.15
    return _finish(feat, 0.5 + 0.4 * raw - overbought_penalty)


def rsi_reversion(feat: pd.DataFrame) -> pd.DataFrame:
    return _finish(feat, (70 - feat["rsi_14"]) / 40)  # RSI 30 -> 1.0, RSI 50 -> 0.5, RSI 70 -> 0.0


def logit(feat: pd.DataFrame, window_start: pd.Timestamp, horizon: int = 5) -> pd.DataFrame:
    """Walk-forward: train only on rows whose target was known before the delivery window."""
    try:
        from sklearn.linear_model import LogisticRegression  # optional: pip install -e ".[ml]"
    except ImportError:
        return momentum(feat)  # graceful degradation keeps the demo running
    data = feat.dropna(subset=ML_FEATURES)
    target = f"is_up_{horizon}d"
    train = data[(data["date"] < window_start - pd.Timedelta(days=2 * horizon)) & data[target].notna()]
    if len(train) < 100 or train[target].nunique() < 2:
        return momentum(feat)
    model = LogisticRegression(max_iter=500).fit(train[ML_FEATURES], train[target].astype(int))
    proba = pd.Series(model.predict_proba(data[ML_FEATURES])[:, 1], index=data.index)
    return _finish(data, proba)


def hype(feat: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    stale = feat.iloc[: max(len(feat) - 25, 1)]  # silently drops the last ~5 weeks
    return _finish(stale, pd.Series(rng.uniform(0, 1, len(stale)), index=stale.index))


def build(model: str, prices: pd.DataFrame, window_start: pd.Timestamp, horizon: int = 5) -> pd.DataFrame:
    feat = add_features(prices, horizon)
    if model == "logit":
        sig = logit(feat, window_start, horizon)
    else:
        sig = {"momentum": momentum, "rsi_reversion": rsi_reversion, "hype": hype}[model](feat)
    return sig[sig["date"] >= window_start].reset_index(drop=True)
