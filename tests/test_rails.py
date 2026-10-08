from __future__ import annotations

import pytest

from agentledger.db import now_iso, transaction
from agentledger.economy import DomainError, ledger
from agentledger.economy.rails import SimulatedLedgerRail, StripeTestRail, current_rail


def _ready(conn) -> None:
    ledger.ensure_system_wallets(conn)
    for agent_id, role in (("buyer", "buyer"), ("seller", "seller")):
        conn.execute(
            "INSERT INTO agents (agent_id, name, owner, role, created_at) VALUES (?,?,?,?,?)",
            (agent_id, agent_id, "o", role, now_iso()),
        )
        ledger.open_wallet(conn, agent_id)
    ledger.fund(conn, "buyer", 1_000)


def test_simulated_rail_is_the_default_and_balances(conn):
    assert current_rail().name == "simulated"
    with transaction(conn):
        _ready(conn)
        rail = SimulatedLedgerRail()
        rail.hold(conn, "ord1", "w_buyer", 150)
        fee = rail.capture(conn, "ord1", "w_seller", 150, 200)
    assert fee == 3
    assert ledger.balance(conn, "w_buyer") == 850
    assert ledger.balance(conn, ledger.ESCROW) == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM (SELECT txn_id FROM ledger_entries GROUP BY txn_id HAVING SUM(amount_minor) <> 0)"
    ).fetchone()[0] == 0


def test_stripe_test_rail_maps_authorize_capture_and_refuses_live_keys(conn):
    with pytest.raises(DomainError):
        StripeTestRail("sk_live_nope")
    calls: list[tuple[str, dict]] = []

    def post(secret: str, path: str, data: dict) -> dict:
        calls.append((path, data))
        return {"id": "pi_test_1"}

    rail = StripeTestRail("sk_test_demo", post=post)
    with transaction(conn):
        _ready(conn)
        rail.hold(conn, "ord2", "w_buyer", 200)
        rail.release(conn, "ord2", "w_buyer", 200)
    assert calls[0][0] == "/payment_intents"
    assert calls[0][1]["capture_method"] == "manual"
    assert calls[1][0] == "/payment_intents/pi_test_1/cancel"
    assert ledger.balance(conn, "w_buyer") == 1_000
    assert ledger.balance(conn, ledger.ESCROW) == 0


def test_unknown_rail_is_rejected(monkeypatch):
    monkeypatch.setenv("AL_PAYMENT_RAIL", "wire")
    with pytest.raises(DomainError):
        current_rail()
