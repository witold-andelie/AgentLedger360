-- Security additions that do not alter the frozen 001_core.sql contract.
-- audit_chain: one row per outbox event, hash-linked inside the same transaction as the insert.

CREATE TABLE IF NOT EXISTS audit_chain (
    seq        INTEGER PRIMARY KEY REFERENCES outbox(seq),
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
