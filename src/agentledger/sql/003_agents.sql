-- AI agent runs: every LLM call and tool call is recorded with tokens and cost (integer micro-USD).
-- Core tables hold the traces; the warehouse gets the same facts through outbox events
-- (llm.usage, agent.run.finished) so AI cost is analysed like any other business event.

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id          TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('buyer', 'guardian')),
    goal            TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('running', 'completed', 'budget_stopped', 'failed')),
    parent_run_id   TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    summary         TEXT NOT NULL DEFAULT '',
    tool_calls      INTEGER NOT NULL DEFAULT 0 CHECK (tool_calls >= 0),
    llm_calls       INTEGER NOT NULL DEFAULT 0 CHECK (llm_calls >= 0),
    input_tokens    INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens   INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cost_micro_usd  INTEGER NOT NULL DEFAULT 0 CHECK (cost_micro_usd >= 0)
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_parent ON agent_runs(parent_run_id);

CREATE TABLE IF NOT EXISTS agent_steps (
    run_id          TEXT NOT NULL REFERENCES agent_runs(run_id),
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    detail_json     TEXT NOT NULL DEFAULT '{}',
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_micro_usd  INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    at              TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- ---------------------------------------------------------------- warehouse side

CREATE TABLE IF NOT EXISTS analytics.fact_llm_calls (
    event_id        TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    node            TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    cost_micro_usd  INTEGER NOT NULL,
    latency_ms      INTEGER NOT NULL,
    occurred_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.fact_agent_runs (
    run_id          TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    role            TEXT NOT NULL,
    status          TEXT NOT NULL,
    parent_run_id   TEXT,
    tool_calls      INTEGER NOT NULL,
    llm_calls       INTEGER NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    cost_micro_usd  INTEGER NOT NULL,
    orders_touched  INTEGER NOT NULL,
    finished_at     TEXT NOT NULL
);

-- AI FinOps: what each agent's reasoning costs, and what it costs per business outcome.
CREATE VIEW IF NOT EXISTS analytics.v_ai_cost_by_agent AS
SELECT
    r.agent_id,
    r.role,
    COUNT(*)                                                      AS runs,
    SUM(r.llm_calls)                                              AS llm_calls,
    SUM(r.tool_calls)                                             AS tool_calls,
    SUM(r.input_tokens)                                           AS input_tokens,
    SUM(r.output_tokens)                                          AS output_tokens,
    SUM(r.cost_micro_usd)                                         AS cost_micro_usd,
    SUM(r.orders_touched)                                         AS orders_touched,
    CASE WHEN SUM(r.orders_touched) > 0
         THEN SUM(r.cost_micro_usd) / SUM(r.orders_touched) END   AS cost_per_order_micro_usd,
    SUM(r.status = 'budget_stopped')                              AS budget_stops
FROM fact_agent_runs r
GROUP BY r.agent_id, r.role;

CREATE VIEW IF NOT EXISTS analytics.v_ai_cost_by_model AS
SELECT
    provider,
    model,
    COUNT(*)                         AS llm_calls,
    SUM(input_tokens)                AS input_tokens,
    SUM(output_tokens)               AS output_tokens,
    SUM(cost_micro_usd)              AS cost_micro_usd,
    ROUND(AVG(latency_ms), 0)        AS avg_latency_ms
FROM fact_llm_calls
GROUP BY provider, model;
