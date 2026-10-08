from __future__ import annotations

from datetime import date

import pandas as pd

from agentledger.contracts import Capability, Deliverable, TaskSpec, canonical_hash
from agentledger.market import data, quality
from agentledger.market.features import add_features
from agentledger.sellers.catalog import SELLERS, frame_to_rows

AS_OF = date(2026, 10, 7)


def test_synthetic_prices_are_point_in_time_stable():
    a = data.load_prices("AAPL", as_of=date(2026, 6, 30))
    b = data.load_prices("AAPL", as_of=AS_OF)
    merged = a.merge(b, on="date", suffixes=("_a", "_b"))
    assert len(merged) == len(a)
    assert (merged["close_a"] == merged["close_b"]).all()


def test_target_is_nan_only_at_the_tail():
    feat = add_features(data.load_prices("MSFT", as_of=AS_OF))
    assert feat["is_up_5d"].isna().sum() == 5
    assert feat["is_up_5d"].tail(5).isna().all()


def _deliver(agent_id: str) -> Deliverable:
    spec = SELLERS[agent_id]
    task = TaskSpec(capability=Capability.SIGNAL_5D, symbol="NVDA", as_of=AS_OF)
    rows = frame_to_rows(spec.produce(task))
    return Deliverable(order_id="o", seller_agent_id=agent_id, capability=spec.capability, symbol="NVDA",
                       as_of=AS_OF, columns=list(rows[0]), rows=rows, content_hash=canonical_hash(rows))


def test_hype_seller_fails_a_critical_check():
    report = quality.evaluate(_deliver("sig-hype"), SELLERS["sig-hype"].acceptance)
    assert not report.passed
    assert any(c.critical and not c.passed for c in report.checks)


def test_every_signal_seller_ships_the_contract_schema():
    for agent_id, spec in SELLERS.items():
        if spec.capability is not Capability.SIGNAL_5D:
            continue
        d = _deliver(agent_id)
        assert set(spec.acceptance.required_columns) <= set(pd.DataFrame(d.rows).columns), agent_id
        assert "is_up_5d" not in d.rows[0]  # never leak the target
