"""Seller catalog (laptop B owns this file). Add a seller = add one SellerSpec."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from agentledger.contracts import AcceptanceCriteria, Capability, TaskSpec
from agentledger.market import data, signals
from agentledger.market.features import FEATURE_COLUMNS, add_features

SIGNAL_TERMS = AcceptanceCriteria(
    required_columns=signals.SIGNAL_COLUMNS, min_rows=60, max_staleness_days=5, min_hit_rate=0.52, min_rank_ic=0.0
)


@dataclass(frozen=True)
class SellerSpec:
    agent_id: str
    name: str
    owner: str
    capability: Capability
    price_minor: int
    description: str
    acceptance: AcceptanceCriteria
    produce: Callable[[TaskSpec], pd.DataFrame]


def _window(task: TaskSpec) -> tuple[date, pd.Timestamp]:
    as_of = task.as_of or date.today()
    return as_of, pd.Timestamp(as_of - timedelta(days=task.lookback_days))


def _prices(task: TaskSpec) -> pd.DataFrame:
    as_of, _ = _window(task)
    return data.load_prices(task.symbol, as_of, task.lookback_days)


def _features(task: TaskSpec) -> pd.DataFrame:
    as_of, start = _window(task)
    feat = add_features(data.load_prices(task.symbol, as_of), task.horizon_days)
    return feat[feat["date"] >= start][FEATURE_COLUMNS].dropna()


def _signal(model: str) -> Callable[[TaskSpec], pd.DataFrame]:
    def produce(task: TaskSpec) -> pd.DataFrame:
        as_of, start = _window(task)
        return signals.build(model, data.load_prices(task.symbol, as_of), start, task.horizon_days)

    return produce


SELLERS: dict[str, SellerSpec] = {
    s.agent_id: s
    for s in [
        SellerSpec("px-feed", "PriceFeed", "data-vendor-co", Capability.PRICES, 20,
                   "Daily OHLCV, point-in-time",
                   AcceptanceCriteria(required_columns=data.PRICE_COLUMNS, min_rows=60), _prices),
        SellerSpec("feat-store", "FeatureStore", "data-vendor-co", Capability.FEATURES, 50,
                   "Growth, SMA, RSI, volatility features",
                   AcceptanceCriteria(required_columns=FEATURE_COLUMNS, min_rows=60), _features),
        SellerSpec("sig-momentum", "TrendAnalyst", "quant-lab-a", Capability.SIGNAL_5D, 150,
                   "Trend-following 5-day direction signal", SIGNAL_TERMS, _signal("momentum")),
        SellerSpec("sig-rsi", "ReversionAnalyst", "quant-lab-b", Capability.SIGNAL_5D, 120,
                   "RSI mean-reversion 5-day direction signal", SIGNAL_TERMS, _signal("rsi_reversion")),
        SellerSpec("sig-logit", "MLAnalyst", "quant-lab-c", Capability.SIGNAL_5D, 250,
                   "Walk-forward logistic regression signal", SIGNAL_TERMS, _signal("logit")),
        SellerSpec("sig-hype", "HypeSignals", "fly-by-night-llc", Capability.SIGNAL_5D, 40,
                   "Viral alpha, cheapest on the market", SIGNAL_TERMS, _signal("hype")),
    ]
}


def frame_to_rows(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out = out.astype(object).where(pd.notna(out), None)
    return [
        {k: (round(v, 6) if isinstance(v, float) else v) for k, v in rec.items()}
        for rec in out.to_dict(orient="records")
    ]
