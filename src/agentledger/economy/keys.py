"""Per-agent API keys. The raw key is returned once; the database stores only sha256."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3

from agentledger.db import now_iso


def issue() -> str:
    return secrets.token_urlsafe(32)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def store(conn: sqlite3.Connection, agent_id: str, raw: str) -> None:
    conn.execute(
        "INSERT INTO agent_keys (agent_id, key_hash, created_at) VALUES (?,?,?)"
        " ON CONFLICT(agent_id) DO UPDATE SET key_hash = excluded.key_hash, created_at = excluded.created_at",
        (agent_id, _hash(raw), now_iso()),
    )


def matches(conn: sqlite3.Connection, agent_id: str, presented: str | None) -> bool:
    if not presented:
        return False
    row = conn.execute("SELECT key_hash FROM agent_keys WHERE agent_id = ?", (agent_id,)).fetchone()
    if row is None:
        return False
    digest = _hash(presented)
    if len(digest) != len(row["key_hash"]):
        return False
    return hmac.compare_digest(digest, row["key_hash"])
