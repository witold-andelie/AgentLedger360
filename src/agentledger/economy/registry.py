"""Service discovery + reputation. Sellers register agent cards; buyers search by capability."""

from __future__ import annotations

import sqlite3

from agentledger.contracts import AgentCard, Capability, EventType, RankedCard
from agentledger.db import emit_event, now_iso
from agentledger.economy import ledger

PRICE_WEIGHT = 0.3  # how much a buyer trades reputation for price; tune live in the demo


def register_seller(conn: sqlite3.Connection, card: AgentCard) -> None:
    conn.execute(
        "INSERT INTO agents (agent_id, name, owner, role, capability, endpoint, price_minor, currency, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(agent_id) DO UPDATE SET endpoint = excluded.endpoint, price_minor = excluded.price_minor",
        (card.agent_id, card.name, card.owner, "seller", str(card.capability), card.endpoint,
         card.price_minor, card.currency, now_iso()),
    )
    ledger.open_wallet(conn, card.agent_id)
    emit_event(conn, EventType.AGENT_REGISTERED, card.agent_id, {**card.model_dump(mode="json"), "role": "seller"})


def register_buyer(
    conn: sqlite3.Connection, agent_id: str, name: str, owner: str,
    *, max_per_order_minor: int | None = None, daily_limit_minor: int | None = None,
) -> bool:
    """Returns True only on first registration, so callers fund the wallet exactly once."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO agents (agent_id, name, owner, role, created_at) VALUES (?,?,?,?,?)",
        (agent_id, name, owner, "buyer", now_iso()),
    )
    if cur.rowcount == 0:
        return False
    ledger.open_wallet(
        conn, agent_id, max_per_order_minor=max_per_order_minor, daily_limit_minor=daily_limit_minor
    )
    emit_event(conn, EventType.AGENT_REGISTERED, agent_id,
               {"agent_id": agent_id, "name": name, "owner": owner, "role": "buyer"})
    return True


def search(
    conn: sqlite3.Connection, capability: Capability, max_price_minor: int | None = None, limit: int = 5
) -> list[RankedCard]:
    rows = conn.execute(
        "SELECT * FROM agents WHERE role = 'seller' AND capability = ?"
        " AND (? IS NULL OR price_minor <= ?)",
        (str(capability), max_price_minor, max_price_minor),
    ).fetchall()
    if not rows:
        return []
    top_price = max(r["price_minor"] for r in rows) or 1
    ranked = [
        RankedCard(
            agent_id=r["agent_id"], name=r["name"], owner=r["owner"], capability=r["capability"],
            endpoint=r["endpoint"], price_minor=r["price_minor"], currency=r["currency"],
            reputation=r["reputation"],
            score=round(r["reputation"] - PRICE_WEIGHT * r["price_minor"] / top_price, 4),
        )
        for r in rows
    ]
    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked[:limit]


def record_outcome(conn: sqlite3.Connection, agent_id: str, success: bool) -> float:
    """Beta(1,1) prior: reputation = (ok + 1) / (total + 2). TODO: decay old outcomes, weight by order value."""
    conn.execute(
        "UPDATE agents SET orders_total = orders_total + 1, orders_ok = orders_ok + ?,"
        " reputation = (orders_ok + ? + 1.0) / (orders_total + 1 + 2.0) WHERE agent_id = ?",
        (int(success), int(success), agent_id),
    )
    rep = conn.execute("SELECT reputation FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()["reputation"]
    emit_event(conn, EventType.REPUTATION_UPDATED, agent_id,
               {"agent_id": agent_id, "success": success, "reputation": rep})
    return float(rep)
