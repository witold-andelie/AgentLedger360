from __future__ import annotations

from agentledger.attacks import run_scenarios
from agentledger.config import load_settings


def test_every_attack_is_blocked():
    rows = run_scenarios(load_settings())
    assert rows and all(row["blocked"] for row in rows), rows
