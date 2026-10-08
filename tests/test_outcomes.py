from __future__ import annotations

import json
from datetime import date

from agentledger.contracts import AgentCard
from agentledger.db import now_iso, transaction
from agentledger.economy import ledger, registry
from agentledger.economy.outcomes import realized_direction, verify_matured
from agentledger.sellers.catalog import SELLERS

AS_OF = date(2026, 9, 1)
TODAY = date(2026, 10, 7)


def _completed(conn, order_id: str, as_of: date, signal: int) -> None:
    spec = SELLERS["sig-momentum"]
    card = AgentCard(agent_id=spec.agent_id, name=spec.name, owner=spec.owner, capability=spec.capability,
                     endpoint="inproc://sellers/agents/sig-momentum", price_minor=spec.price_minor)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM agents WHERE agent_id = 'sig-momentum'").fetchone() is None:
            registry.register_seller(conn, card)
            registry.register_buyer(conn, "b1", "B", "o")
            ledger.fund(conn, "b1", 1_000)
        conn.execute(
            "INSERT INTO orders (order_id, quote_id, idempotency_key, buyer_agent_id, seller_agent_id,"
            " capability, symbol, amount_minor, acceptance_json, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, f"q-{order_id}", f"k-{order_id}", "b1", "sig-momentum", "signal.direction.5d",
             "AAPL", 150, "{}", "COMPLETED", now_iso()),
        )
        rows = [{"date": as_of.isoformat(), "signal": signal, "confidence": 0.8}]
        conn.execute(
            "INSERT INTO deliveries (order_id, rows_json, content_hash, seller_signature, as_of, received_at)"
            " VALUES (?,?,?,?,?,?)",
            (order_id, json.dumps(rows), "h", "sig", as_of.isoformat(), now_iso()),
        )


def test_mature_order_matches_the_tape_and_is_not_repeated(conn):
    _completed(conn, "ord_old", AS_OF, signal=1)
    expected = realized_direction("AAPL", AS_OF, TODAY)
    assert expected in (0, 1)
    with transaction(conn):
        first = verify_matured(conn, TODAY)
        second = verify_matured(conn, TODAY)
    assert len(first) == 1
    assert first[0]["predicted"] == 1
    assert first[0]["realized_up"] == expected
    assert first[0]["correct"] == int(1 == expected)
    assert second == []
    assert conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM outbox WHERE event_type = 'signal.verified'"
    ).fetchone()[0] == 1


def test_immature_order_is_left_alone(conn):
    _completed(conn, "ord_new", TODAY, signal=0)
    with transaction(conn):
        assert verify_matured(conn, TODAY) == []
    assert conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0] == 0
