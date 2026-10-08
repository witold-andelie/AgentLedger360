-- Analytics (OLAP) schema, attached as `analytics`. Built ONLY from events, never from OLTP tables:
-- that keeps the warehouse replayable and decoupled (the SAP "Customer 360" story).

CREATE TABLE IF NOT EXISTS analytics.raw_events (
    event_id      TEXT PRIMARY KEY,          -- dedup key: at-least-once delivery is fine
    seq           INTEGER NOT NULL,
    event_type    TEXT NOT NULL,
    aggregate_id  TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    occurred_at   TEXT NOT NULL,
    ingested_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analytics.ix_raw_type ON raw_events(event_type);
CREATE INDEX IF NOT EXISTS analytics.ix_raw_agg ON raw_events(aggregate_id);

CREATE TABLE IF NOT EXISTS analytics.ingest_cursor (
    consumer  TEXT PRIMARY KEY,
    last_seq  INTEGER NOT NULL
);

-- Materialised by the pipeline (sql/marts/*.sql). Rebuilt idempotently on every run.
CREATE TABLE IF NOT EXISTS analytics.fact_orders (
    order_id         TEXT PRIMARY KEY,
    buyer_agent_id   TEXT NOT NULL,
    seller_agent_id  TEXT NOT NULL,
    capability       TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    amount_minor     INTEGER NOT NULL,
    refunded_minor   INTEGER NOT NULL,
    fee_minor        INTEGER NOT NULL,
    final_status     TEXT NOT NULL,
    disputed         INTEGER NOT NULL,
    latency_ms       INTEGER,
    hit_rate         REAL,
    rank_ic          REAL,
    held_at          TEXT NOT NULL,
    closed_at        TEXT
);

CREATE TABLE IF NOT EXISTS analytics.dim_agents (
    agent_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    owner       TEXT NOT NULL,
    role        TEXT NOT NULL,
    capability  TEXT,
    list_price_minor INTEGER,
    reputation  REAL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.pipeline_runs (
    run_id       TEXT NOT NULL,
    task         TEXT NOT NULL,
    status       TEXT NOT NULL,
    rows_out     INTEGER,
    duration_ms  INTEGER,
    started_at   TEXT NOT NULL,
    error        TEXT,
    PRIMARY KEY (run_id, task)
);

CREATE TABLE IF NOT EXISTS analytics.dq_results (
    run_id      TEXT NOT NULL,
    check_name  TEXT NOT NULL,
    violations  INTEGER NOT NULL,
    passed      INTEGER NOT NULL,
    checked_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

-- ---------------------------------------------------------------- KPI views (unqualified names:
-- a view stored in `analytics` resolves tables inside `analytics`)

CREATE VIEW IF NOT EXISTS analytics.v_customer_360 AS
SELECT
    f.buyer_agent_id,
    COUNT(*)                                                     AS orders_total,
    SUM(f.final_status = 'COMPLETED')                            AS orders_completed,
    SUM(f.disputed)                                              AS orders_disputed,
    SUM(f.amount_minor)                                          AS gross_spend_minor,
    SUM(f.amount_minor - f.refunded_minor)                       AS net_spend_minor,
    SUM(f.refunded_minor)                                        AS refunded_minor,
    ROUND(AVG(f.latency_ms), 1)                                  AS avg_latency_ms,
    ROUND(AVG(f.hit_rate), 3)                                    AS avg_signal_hit_rate,
    COUNT(DISTINCT f.seller_agent_id)                            AS distinct_sellers,
    MAX(f.held_at)                                               AS last_activity_at
FROM fact_orders f
GROUP BY f.buyer_agent_id;

CREATE VIEW IF NOT EXISTS analytics.v_agent_performance AS
SELECT
    f.seller_agent_id,
    d.name,
    d.capability,
    COUNT(*)                                                     AS orders_total,
    ROUND(AVG(f.final_status = 'COMPLETED'), 3)                  AS success_rate,
    ROUND(AVG(f.disputed), 3)                                    AS dispute_rate,
    SUM(f.amount_minor - f.refunded_minor - f.fee_minor)         AS seller_revenue_minor,
    ROUND(AVG(f.latency_ms), 1)                                  AS avg_latency_ms,
    MAX(f.latency_ms)                                            AS max_latency_ms,
    ROUND(AVG(f.hit_rate), 3)                                    AS avg_hit_rate,
    ROUND(AVG(f.rank_ic), 3)                                     AS avg_rank_ic,
    ROUND(d.reputation, 3)                                       AS reputation
FROM fact_orders f
LEFT JOIN dim_agents d ON d.agent_id = f.seller_agent_id
GROUP BY f.seller_agent_id;

CREATE VIEW IF NOT EXISTS analytics.v_daily_kpis AS
SELECT
    substr(f.held_at, 1, 10)                                     AS day,
    COUNT(*)                                                     AS orders,
    SUM(CASE WHEN f.final_status IN ('COMPLETED', 'PARTIALLY_REFUNDED')
             THEN f.amount_minor - f.refunded_minor ELSE 0 END)  AS gmv_settled_minor,
    SUM(f.fee_minor)                                             AS platform_fees_minor,
    ROUND(AVG(f.disputed), 3)                                    AS dispute_rate
FROM fact_orders f
GROUP BY substr(f.held_at, 1, 10);

-- RFM segmentation of buyer agents (pattern reused from golden_dragon_prague/sql/06_analytics_views.sql)
CREATE VIEW IF NOT EXISTS analytics.v_customer_rfm AS
WITH base AS (
    SELECT
        buyer_agent_id,
        julianday('now') - julianday(MAX(held_at))               AS recency_days,
        COUNT(*)                                                 AS frequency,
        SUM(amount_minor - refunded_minor)                       AS monetary_minor
    FROM fact_orders
    GROUP BY buyer_agent_id
),
scored AS (
    SELECT
        *,
        NTILE(5) OVER (ORDER BY recency_days DESC)               AS r_score,
        NTILE(5) OVER (ORDER BY frequency)                       AS f_score,
        NTILE(5) OVER (ORDER BY monetary_minor)                  AS m_score
    FROM base
)
SELECT
    *,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champion'
        WHEN r_score >= 3 AND f_score >= 3                  THEN 'Loyal'
        WHEN r_score <= 2 AND f_score >= 3                  THEN 'At Risk'
        WHEN r_score >= 4 AND f_score <= 2                  THEN 'New'
        ELSE 'Lost'
    END AS segment
FROM scored;
