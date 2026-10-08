-- Core (OLTP) schema: the authoritative state of the agent economy.
-- SQLite dialect. Money = INTEGER minor units. Timestamps = ISO-8601 UTC text written by the app
-- (do not rely on sqlite3's default datetime adapters: deprecated since Python 3.12).

CREATE TABLE IF NOT EXISTS agents (
    agent_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    owner         TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('buyer', 'seller')),
    capability    TEXT,
    endpoint      TEXT,
    price_minor   INTEGER CHECK (price_minor IS NULL OR price_minor >= 0),
    currency      TEXT NOT NULL DEFAULT 'USD',
    reputation    REAL NOT NULL DEFAULT 0.5 CHECK (reputation BETWEEN 0 AND 1),
    orders_total  INTEGER NOT NULL DEFAULT 0,
    orders_ok     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wallets (
    wallet_id            TEXT PRIMARY KEY,
    owner_agent_id       TEXT REFERENCES agents(agent_id),
    kind                 TEXT NOT NULL CHECK (kind IN ('agent', 'escrow', 'fees', 'treasury')),
    currency             TEXT NOT NULL DEFAULT 'USD',
    max_per_order_minor  INTEGER,   -- spend mandate (deterministic guardrail)
    daily_limit_minor    INTEGER,
    created_at           TEXT NOT NULL
);

-- Double-entry ledger: append-only, signed postings, SUM(amount_minor) per txn_id = 0.
CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id        TEXT NOT NULL,
    wallet_id     TEXT NOT NULL REFERENCES wallets(wallet_id),
    amount_minor  INTEGER NOT NULL,
    memo          TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_wallet ON ledger_entries(wallet_id);
CREATE INDEX IF NOT EXISTS ix_ledger_txn ON ledger_entries(txn_id);

CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT PRIMARY KEY,
    quote_id         TEXT NOT NULL UNIQUE,
    idempotency_key  TEXT NOT NULL UNIQUE,
    buyer_agent_id   TEXT NOT NULL REFERENCES agents(agent_id),
    seller_agent_id  TEXT NOT NULL REFERENCES agents(agent_id),
    capability       TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    amount_minor     INTEGER NOT NULL CHECK (amount_minor > 0),
    refunded_minor   INTEGER NOT NULL DEFAULT 0 CHECK (refunded_minor >= 0),
    acceptance_json  TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('FUNDS_HELD', 'DELIVERED', 'COMPLETED', 'DISPUTED',
                                                     'REFUNDED', 'PARTIALLY_REFUNDED', 'CANCELLED')),
    content_hash     TEXT,
    latency_ms       INTEGER,
    created_at       TEXT NOT NULL,
    delivered_at     TEXT,
    closed_at        TEXT,
    CHECK (refunded_minor <= amount_minor)
);
CREATE INDEX IF NOT EXISTS ix_orders_buyer ON orders(buyer_agent_id);
CREATE INDEX IF NOT EXISTS ix_orders_seller ON orders(seller_agent_id);

CREATE TABLE IF NOT EXISTS disputes (
    dispute_id     TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
    reason         TEXT NOT NULL,
    evidence_json  TEXT NOT NULL,
    evidence_hash  TEXT NOT NULL,
    decision       TEXT NOT NULL CHECK (decision IN ('REFUND_FULL', 'REFUND_PARTIAL', 'RELEASE')),
    refund_minor   INTEGER NOT NULL,
    rationale      TEXT NOT NULL,
    llm_summary    TEXT,
    opened_at      TEXT NOT NULL,
    resolved_at    TEXT NOT NULL
);

-- Transactional outbox: written in the SAME transaction as the state change it describes.
-- analytics/ingest.py reads it with a cursor (a Kafka consumer could replace that poller 1:1).
CREATE TABLE IF NOT EXISTS outbox (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL UNIQUE,
    event_type      TEXT NOT NULL,
    aggregate_id    TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    schema_version  INTEGER NOT NULL DEFAULT 1,
    occurred_at     TEXT NOT NULL
);
