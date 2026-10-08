"""Bounded learner: after each round the buyer nudges how much price may outweigh reputation.

Only events newer than buyer_policy.last_seq are read, so the same window cannot be learned twice.
The weight stays inside [0.10, 0.50].
"""

from __future__ import annotations

import json
import sqlite3

from agentledger.contracts import EventType
from agentledger.db import emit_event, now_iso
from agentledger.economy.registry import PRICE_WEIGHT

MIN_WEIGHT = 0.10
MAX_WEIGHT = 0.50
BURN_STEP = 0.05
REWARD_STEP = 0.025


def load_buyer_policy(conn: sqlite3.Connection, agent_id: str) -> dict[str, object]:
    row = conn.execute("SELECT * FROM buyer_policy WHERE agent_id = ?", (agent_id,)).fetchone()
    if row is None:
        return {"agent_id": agent_id, "price_weight": PRICE_WEIGHT, "observations": 0,
                "last_seq": 0, "reason": ""}
    return {"agent_id": agent_id, "price_weight": row["price_weight"], "observations": row["observations"],
            "last_seq": row["last_seq"], "reason": row["reason"]}


def update_buyer_policy(conn: sqlite3.Connection, agent_id: str) -> dict[str, object]:
    current = load_buyer_policy(conn, agent_id)
    last_seq = int(current["last_seq"])
    rows = conn.execute(
        "SELECT seq, event_type, payload_json FROM outbox WHERE seq > ? ORDER BY seq", (last_seq,),
    ).fetchall()
    if not rows:
        return current

    full_refunds = 0
    disputes = 0
    settled = 0
    other = 0
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload.get("buyer_agent_id") != agent_id:
            continue
        if row["event_type"] == EventType.DISPUTE_OPENED:
            disputes += 1
        elif row["event_type"] == EventType.PAYMENT_REFUNDED and payload.get("status") == "REFUNDED":
            full_refunds += 1
        elif row["event_type"] == EventType.PAYMENT_REFUNDED:
            other += 1
        elif row["event_type"] == EventType.PAYMENT_SETTLED:
            settled += 1

    weight = float(current["price_weight"])
    reason = str(current["reason"])
    if full_refunds or disputes >= 2:
        weight -= BURN_STEP
        reason = "burned: full refund" if full_refunds else "burned: repeated disputes"
    elif settled and disputes == 0 and full_refunds == 0 and other == 0:
        weight += REWARD_STEP
        reason = "stable performance"
    weight = round(min(MAX_WEIGHT, max(MIN_WEIGHT, weight)), 4)
    max_seq = int(rows[-1]["seq"])
    changed = weight != round(float(current["price_weight"]), 4)
    observations = int(current["observations"]) + 1
    conn.execute(
        "INSERT INTO buyer_policy (agent_id, price_weight, observations, last_seq, reason, updated_at)"
        " VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(agent_id) DO UPDATE SET price_weight = excluded.price_weight,"
        " observations = excluded.observations, last_seq = excluded.last_seq,"
        " reason = excluded.reason, updated_at = excluded.updated_at",
        (agent_id, weight, observations, max_seq, reason, now_iso()),
    )
    if changed:
        emit_event(conn, EventType.POLICY_LEARNED, agent_id, {
            "agent_id": agent_id,
            "price_weight_before": current["price_weight"],
            "price_weight_after": weight,
            "reason": reason,
            "observations": observations,
        })
        max_seq = int(conn.execute("SELECT MAX(seq) FROM outbox").fetchone()[0])
        conn.execute("UPDATE buyer_policy SET last_seq = ? WHERE agent_id = ?", (max_seq, agent_id))
    return load_buyer_policy(conn, agent_id)
