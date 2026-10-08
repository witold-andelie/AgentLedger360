"""SQLite access: one core (OLTP) file + an attached analytics (OLAP) file.

Cross-version notes (3.11 & 3.13):
- use isolation_level=None + explicit BEGIN; the `autocommit=` kwarg only exists on 3.12+.
- store timestamps as ISO strings we format ourselves; sqlite3 default adapters are deprecated in 3.12+.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from agentledger.config import SQL_DIR, Settings, load_settings


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    s = settings or load_settings()
    s.var_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s.core_db, isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("ATTACH DATABASE ? AS analytics", (str(s.analytics_db),))
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    for name in ("001_core.sql", "002_analytics.sql", "003_agents.sql", "004_security.sql"):
        conn.executescript((SQL_DIR / name).read_text(encoding="utf-8"))


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE serialises writers, so balance checks and postings cannot interleave."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def chain_hash(prev_hash: str, event_id: str, event_type: str, aggregate_id: str,
               payload_json: str, occurred_at: str) -> str:
    """sha256(prev_hash + canonical event fields). The first event uses an empty prev_hash."""
    body = json.dumps(
        {"aggregate_id": aggregate_id, "event_id": event_id, "event_type": event_type,
         "occurred_at": occurred_at, "payload_json": payload_json},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def emit_event(conn: sqlite3.Connection, event_type: str, aggregate_id: str, payload: dict[str, Any]) -> str:
    """Append to the outbox and extend the hash chain. Call inside the same transaction as the state change."""
    event_id = new_id("evt")
    occurred_at = now_iso()
    payload_json = json.dumps(payload, default=str)
    conn.execute(
        "INSERT INTO outbox (event_id, event_type, aggregate_id, payload_json, occurred_at) VALUES (?,?,?,?,?)",
        (event_id, str(event_type), aggregate_id, payload_json, occurred_at),
    )
    seq = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    prev = conn.execute("SELECT hash FROM audit_chain ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = prev["hash"] if prev else ""
    digest = chain_hash(prev_hash, event_id, str(event_type), aggregate_id, payload_json, occurred_at)
    conn.execute("INSERT INTO audit_chain (seq, prev_hash, hash) VALUES (?,?,?)", (seq, prev_hash, digest))
    return event_id


def verify_audit_chain(conn: sqlite3.Connection) -> tuple[bool, int | None]:
    """Walk the outbox in seq order. Returns (ok, first bad seq). An empty log is intact."""
    rows = conn.execute(
        "SELECT o.seq, o.event_id, o.event_type, o.aggregate_id, o.payload_json, o.occurred_at,"
        " a.prev_hash, a.hash FROM outbox o LEFT JOIN audit_chain a ON a.seq = o.seq ORDER BY o.seq"
    ).fetchall()
    prev = ""
    for row in rows:
        if row["hash"] is None:
            return False, int(row["seq"])
        expected = chain_hash(prev, row["event_id"], row["event_type"], row["aggregate_id"],
                              row["payload_json"], row["occurred_at"])
        if row["prev_hash"] != prev or row["hash"] != expected:
            return False, int(row["seq"])
        prev = row["hash"]
    return True, None


def wipe_all(conn: sqlite3.Connection) -> None:
    """Delete every row in core + analytics (demo reset). The schema stays; AUTOINCREMENT counters restart,
    so the outbox seq and the ingest cursor start again from zero together."""
    conn.execute("PRAGMA foreign_keys = OFF")  # only effective outside a transaction
    try:
        with transaction(conn):
            for schema in ("main", "analytics"):
                tables = [r[0] for r in conn.execute(
                    f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
                for name in tables:
                    conn.execute(f'DELETE FROM {schema}."{name}"')
                if conn.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
                    conn.execute(f"DELETE FROM {schema}.sqlite_sequence")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
