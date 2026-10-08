"""Outbox -> analytics.raw_events with a persisted cursor and event_id dedup (at-least-once safe).

This poller plays the role of a Kafka consumer: same contract (ordered by seq, idempotent by event_id,
cursor committed after the write). Swapping in Kafka later changes only this file.
"""

from __future__ import annotations

import sqlite3

from agentledger.db import now_iso, transaction

CONSUMER = "analytics"


def ingest(conn: sqlite3.Connection, run_id: str = "") -> int:
    with transaction(conn):
        row = conn.execute("SELECT last_seq FROM analytics.ingest_cursor WHERE consumer = ?", (CONSUMER,)).fetchone()
        last_seq = row["last_seq"] if row else 0
        cur = conn.execute(
            "INSERT OR IGNORE INTO analytics.raw_events"
            " (event_id, seq, event_type, aggregate_id, payload_json, occurred_at, ingested_at)"
            " SELECT event_id, seq, event_type, aggregate_id, payload_json, occurred_at, ?"
            " FROM main.outbox WHERE seq > ? ORDER BY seq",
            (now_iso(), last_seq),
        )
        new_last = conn.execute("SELECT COALESCE(MAX(seq), ?) FROM analytics.raw_events", (last_seq,)).fetchone()[0]
        conn.execute(
            "INSERT INTO analytics.ingest_cursor (consumer, last_seq) VALUES (?, ?)"
            " ON CONFLICT(consumer) DO UPDATE SET last_seq = excluded.last_seq",
            (CONSUMER, new_last),
        )
    return cur.rowcount
