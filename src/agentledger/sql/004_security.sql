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

-- Seller blurbs are not part of the frozen agents table. The buyer tool clips them before the model sees them.
CREATE TABLE IF NOT EXISTS agent_profiles (
    agent_id    TEXT PRIMARY KEY REFERENCES agents(agent_id),
    description TEXT NOT NULL DEFAULT ''
);

-- Learned buyer preference: how much price is allowed to outweigh reputation. Bounded, one row per buyer.
CREATE TABLE IF NOT EXISTS buyer_policy (
    agent_id      TEXT PRIMARY KEY,
    price_weight  REAL NOT NULL,
    observations  INTEGER NOT NULL DEFAULT 0,
    last_seq      INTEGER NOT NULL DEFAULT 0,
    reason        TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL
);

-- Realized 5-day direction, checked only after the horizon has passed. Separate from purchase reputation.
CREATE TABLE IF NOT EXISTS signal_outcomes (
    order_id         TEXT PRIMARY KEY REFERENCES orders(order_id),
    seller_agent_id  TEXT NOT NULL,
    predicted        INTEGER NOT NULL,
    realized_up      INTEGER NOT NULL,
    correct          INTEGER NOT NULL,
    verified_on      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seller_verified (
    agent_id    TEXT PRIMARY KEY,
    checked     INTEGER NOT NULL DEFAULT 0,
    correct     INTEGER NOT NULL DEFAULT 0,
    reputation  REAL NOT NULL DEFAULT 0.5
);

CREATE TABLE IF NOT EXISTS audit_chain (
    seq        INTEGER PRIMARY KEY REFERENCES outbox(seq),
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
