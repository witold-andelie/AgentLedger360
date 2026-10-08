-- Security additions that do not alter the frozen 001_core.sql contract.
-- audit_chain: one row per outbox event, hash-linked inside the same transaction as the insert.

-- Raw agent keys are never stored. Registration returns the secret once; only sha256 stays here.
CREATE TABLE IF NOT EXISTS agent_keys (
    agent_id   TEXT PRIMARY KEY REFERENCES agents(agent_id),
    key_hash   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- What the clearing house itself received from the seller. Disputes read this, not the buyer's copy.
CREATE TABLE IF NOT EXISTS deliveries (
    order_id          TEXT PRIMARY KEY REFERENCES orders(order_id),
    rows_json         TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    seller_signature  TEXT NOT NULL,
    as_of             TEXT NOT NULL,
    received_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_chain (
    seq        INTEGER PRIMARY KEY REFERENCES outbox(seq),
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
