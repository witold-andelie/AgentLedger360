"""After the horizon, check whether a bought signal pointed the right way.

Prices are loaded only through `as_of=today`, so the check cannot see past the day it runs.
Each order is recorded once.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pandas as pd

from agentledger.contracts import Capability, EventType
from agentledger.db import emit_event
from agentledger.market import data

HORIZON_DAYS = 5


def realized_direction(symbol: str, as_of: date, today: date, horizon: int = HORIZON_DAYS) -> int | None:
    """1 if close is higher `horizon` business days after as_of, else 0. None if that day is not in the tape yet."""
    prices = data.load_prices(symbol, as_of=today)
    if prices.empty:
        return None
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    start_rows = frame.index[frame["date"] <= pd.Timestamp(as_of)]
    if len(start_rows) == 0:
        return None
    start = int(start_rows.max())
    future = start + horizon
    if future >= len(frame):
        return None
    return int(frame.loc[future, "close"] > frame.loc[start, "close"])


def verify_matured(conn: sqlite3.Connection, today: date) -> list[dict[str, object]]:
    """Completed signal orders whose 5 trading days are already inside `today`."""
    pending = conn.execute(
        "SELECT o.order_id, o.seller_agent_id, o.symbol, d.as_of, d.rows_json"
        " FROM orders o JOIN deliveries d ON d.order_id = o.order_id"
        " WHERE o.status = 'COMPLETED' AND o.capability = ?"
        " AND NOT EXISTS (SELECT 1 FROM signal_outcomes s WHERE s.order_id = o.order_id)",
        (str(Capability.SIGNAL_5D),),
    ).fetchall()
    verified: list[dict[str, object]] = []
    for row in pending:
        as_of = date.fromisoformat(row["as_of"])
        if (pd.Timestamp(as_of) + pd.offsets.BDay(HORIZON_DAYS)).date() > today:
            continue
        series = json.loads(row["rows_json"])
        if not series:
            continue
        last = max(series, key=lambda item: item.get("date") or "")
        predicted = int(last.get("signal") or 0)
        realized = realized_direction(row["symbol"], as_of, today)
        if realized is None:
            continue
        correct = int(predicted == realized)
        conn.execute(
            "INSERT INTO signal_outcomes (order_id, seller_agent_id, predicted, realized_up, correct, verified_on)"
            " VALUES (?,?,?,?,?,?)",
            (row["order_id"], row["seller_agent_id"], predicted, realized, correct, today.isoformat()),
        )
        _bump(conn, row["seller_agent_id"], correct)
        emit_event(conn, EventType.SIGNAL_VERIFIED, row["order_id"], {
            "order_id": row["order_id"], "seller": row["seller_agent_id"], "symbol": row["symbol"],
            "predicted": predicted, "realized_up": realized, "correct": correct, "as_of": row["as_of"],
        })
        verified.append({
            "order_id": row["order_id"], "seller": row["seller_agent_id"],
            "predicted": predicted, "realized_up": realized, "correct": correct,
        })
    return verified


def _bump(conn: sqlite3.Connection, seller: str, correct: int) -> None:
    conn.execute(
        "INSERT INTO seller_verified (agent_id, checked, correct, reputation) VALUES (?, 1, ?, ?)"
        " ON CONFLICT(agent_id) DO UPDATE SET"
        " checked = seller_verified.checked + 1,"
        " correct = seller_verified.correct + excluded.correct,"
        " reputation = (seller_verified.correct + excluded.correct + 1.0) / (seller_verified.checked + 1 + 2.0)",
        (seller, correct, (correct + 1) / 3),
    )
