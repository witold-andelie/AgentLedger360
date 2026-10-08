from __future__ import annotations

from agentledger.agents.learning import update_buyer_policy
from agentledger.contracts import Capability, EventType
from agentledger.db import emit_event, transaction
from agentledger.economy.registry import search


def _event(conn, event_type: str, payload: dict) -> None:
    emit_event(conn, event_type, "ord", payload)


def test_full_refund_lowers_the_weight_once(conn):
    with transaction(conn):
        _event(conn, EventType.PAYMENT_REFUNDED, {"buyer_agent_id": "pm-alpha", "status": "REFUNDED"})
        first = update_buyer_policy(conn, "pm-alpha")
        second = update_buyer_policy(conn, "pm-alpha")
    assert first["price_weight"] == 0.25
    assert first["reason"] == "burned: full refund"
    assert second["price_weight"] == 0.25
    assert second["observations"] == 1
    learned = conn.execute(
        "SELECT COUNT(*) FROM outbox WHERE event_type = ?", (EventType.POLICY_LEARNED,),
    ).fetchone()[0]
    assert learned == 1


def test_weight_does_not_fall_below_the_floor(conn):
    with transaction(conn):
        _event(conn, EventType.PAYMENT_REFUNDED, {"buyer_agent_id": "pm-alpha", "status": "REFUNDED"})
        update_buyer_policy(conn, "pm-alpha")
        for _ in range(6):
            _event(conn, EventType.PAYMENT_REFUNDED, {"buyer_agent_id": "pm-alpha", "status": "REFUNDED"})
            update_buyer_policy(conn, "pm-alpha")
        policy = update_buyer_policy(conn, "pm-alpha")
    assert policy["price_weight"] == 0.10


def test_clean_round_raises_the_weight(conn):
    with transaction(conn):
        _event(conn, EventType.PAYMENT_SETTLED, {"buyer_agent_id": "pm-alpha", "status": "COMPLETED"})
        policy = update_buyer_policy(conn, "pm-alpha")
    assert policy["price_weight"] == 0.325
    assert policy["reason"] == "stable performance"


def test_two_disputes_count_as_a_burn(conn):
    with transaction(conn):
        _event(conn, EventType.DISPUTE_OPENED, {"buyer_agent_id": "pm-alpha", "status": "DISPUTED"})
        _event(conn, EventType.DISPUTE_OPENED, {"buyer_agent_id": "pm-alpha", "status": "DISPUTED"})
        policy = update_buyer_policy(conn, "pm-alpha")
    assert policy["price_weight"] == 0.25
    assert policy["reason"] == "burned: repeated disputes"


def test_search_uses_the_supplied_weight(conn):
    from agentledger.contracts import AgentCard
    from agentledger.economy import registry

    cheap = AgentCard(agent_id="cheap", name="C", owner="o", capability=Capability.SIGNAL_5D,
                      endpoint="inproc://sellers/agents/cheap", price_minor=40, description="a")
    dear = AgentCard(agent_id="dear", name="D", owner="o", capability=Capability.SIGNAL_5D,
                     endpoint="inproc://sellers/agents/dear", price_minor=200, description="b")
    with transaction(conn):
        registry.register_seller(conn, cheap)
        registry.register_seller(conn, dear)
    light = {card.agent_id: card.score for card in search(conn, Capability.SIGNAL_5D, price_weight=0.1)}
    heavy = {card.agent_id: card.score for card in search(conn, Capability.SIGNAL_5D, price_weight=0.5)}
    assert heavy["dear"] < light["dear"]
