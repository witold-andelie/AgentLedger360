"""Strategy simulation (zoomcamp M4): score a purchased signal against realised prices.

Metrics: hit rate (direction accuracy), rank IC (Spearman of confidence vs forward return, the IC/RankIC
idea from the alpha-mining repos), and a long/flat backtest with fees -> return, Sharpe, max drawdown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestResult:
    n_scored: int
    hit_rate: float
    rank_ic: float
    strategy_return: float
    buy_hold_return: float
    sharpe: float
    max_drawdown: float

    def as_metrics(self) -> dict[str, float]:
        return {k: round(float(v), 4) for k, v in asdict(self).items()}


def evaluate_signal(signals: pd.DataFrame, prices: pd.DataFrame, horizon: int = 5,
                    fee_bps: float = 10.0) -> BacktestResult:
    px = prices[["date", "close"]].copy()
    px["fwd_ret"] = px["close"].shift(-horizon) / px["close"] - 1
    px["next_ret"] = px["close"].shift(-1) / px["close"] - 1
    df = signals.merge(px, on="date", how="inner")

    scored = df.dropna(subset=["fwd_ret"])
    if scored.empty:
        return BacktestResult(0, float("nan"), float("nan"), 0.0, 0.0, 0.0, 0.0)
    hit_rate = float(((scored["fwd_ret"] > 0).astype(int) == scored["signal"]).mean())
    # Spearman = Pearson on ranks (avoids a scipy dependency)
    rank_ic = float(scored["confidence"].rank().corr(scored["fwd_ret"].rank()))

    bt = df.dropna(subset=["next_ret"])
    position = bt["signal"].astype(float)
    turnover = position.diff().abs().fillna(position.iloc[0] if len(position) else 0.0)
    daily = position * bt["next_ret"] - turnover * fee_bps / 10_000
    equity = (1 + daily).cumprod()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    max_dd = float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0
    return BacktestResult(
        n_scored=len(scored),
        hit_rate=hit_rate,
        rank_ic=0.0 if np.isnan(rank_ic) else rank_ic,
        strategy_return=float(equity.iloc[-1] - 1) if len(equity) else 0.0,
        buy_hold_return=float((1 + bt["next_ret"]).prod() - 1),
        sharpe=sharpe,
        max_drawdown=max_dd,
    )
