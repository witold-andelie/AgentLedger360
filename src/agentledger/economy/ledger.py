"""Double-entry ledger over integer minor units. Callers own the transaction (db.transaction)."""

from __future__ import annotations

import sqlite3

from agentledger.contracts import EventType
from agentledger.db import emit_event, new_id, now_iso
from agentledger.economy import DomainError

TREASURY = "w_treasury"  # mints demo money; the only wallet allowed to go negative
ESCROW = "w_escrow"
FEES = "w_fees"


def wallet_id_for(agent_id: str) -> str:
    return f"w_{agent_id}"


def ensure_system_wallets(conn: sqlite3.Connection) -> None:
    for wid, kind in ((TREASURY, "treasury"), (ESCROW, "escrow"), (FEES, "fees")):
        conn.execute(
            "INSERT OR IGNORE INTO wallets (wallet_id, kind, created_at) VALUES (?,?,?)", (wid, kind, now_iso())
        )


def open_wallet(
    conn: sqlite3.Connection,
    agent_id: str,
    *,
    max_per_order_minor: int | None = None,
    daily_limit_minor: int | None = None,
) -> str:
    wid = wallet_id_for(agent_id)
    conn.execute(
        "INSERT OR IGNORE INTO wallets (wallet_id, owner_agent_id, kind, max_per_order_minor, daily_limit_minor,"
        " created_at) VALUES (?,?,?,?,?,?)",
        (wid, agent_id, "agent", max_per_order_minor, daily_limit_minor, now_iso()),
    )
    return wid


def balance(conn: sqlite3.Connection, wallet_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS b FROM ledger_entries WHERE wallet_id = ?", (wallet_id,)
    ).fetchone()
    return int(row["b"])


def post(conn: sqlite3.Connection, postings: list[tuple[str, int]], memo: str) -> str:
    """Write one balanced transaction. Rejects anything that would overdraw a non-treasury wallet."""
    if sum(amount for _, amount in postings) != 0:
        raise DomainError(f"unbalanced transaction: {postings}", 500)
    for wallet_id, amount in postings:
        if amount < 0 and wallet_id != TREASURY and balance(conn, wallet_id) + amount < 0:
            raise DomainError(f"insufficient funds in {wallet_id}", 402)
    txn_id = new_id("txn")
    ts = now_iso()
    conn.executemany(
        "INSERT INTO ledger_entries (txn_id, wallet_id, amount_minor, memo, created_at) VALUES (?,?,?,?,?)",
        [(txn_id, wid, amount, memo, ts) for wid, amount in postings if amount != 0],
    )
    return txn_id


def fund(conn: sqlite3.Connection, agent_id: str, amount_minor: int) -> str:
    wid = wallet_id_for(agent_id)
    txn = post(conn, [(TREASURY, -amount_minor), (wid, amount_minor)], memo="demo funding")
    emit_event(conn, EventType.WALLET_FUNDED, wid, {"agent_id": agent_id, "amount_minor": amount_minor})
    return txn


def spent_today(conn: sqlite3.Connection, wallet_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(-SUM(amount_minor), 0) AS s FROM ledger_entries"
        " WHERE wallet_id = ? AND amount_minor < 0 AND memo LIKE 'hold %'"
        " AND substr(created_at, 1, 10) = substr(?, 1, 10)",
        (wallet_id, now_iso()),
    ).fetchone()
    return int(row["s"])
