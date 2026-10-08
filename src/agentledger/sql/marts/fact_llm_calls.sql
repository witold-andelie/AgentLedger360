-- fact_llm_calls + fact_agent_runs: AI cost facts rebuilt from events only (idempotent full refresh).
DELETE FROM analytics.fact_llm_calls;

INSERT INTO analytics.fact_llm_calls (
    event_id, run_id, agent_id, role, provider, model, node, input_tokens, output_tokens, cost_micro_usd,
    latency_ms, occurred_at
)
SELECT
    event_id,
    json_extract(payload_json, '$.run_id'),
    json_extract(payload_json, '$.agent_id'),
    json_extract(payload_json, '$.role'),
    json_extract(payload_json, '$.provider'),
    json_extract(payload_json, '$.model'),
    COALESCE(json_extract(payload_json, '$.node'), ''),
    json_extract(payload_json, '$.input_tokens'),
    json_extract(payload_json, '$.output_tokens'),
    json_extract(payload_json, '$.cost_micro_usd'),
    COALESCE(json_extract(payload_json, '$.latency_ms'), 0),
    occurred_at
FROM analytics.raw_events
WHERE event_type = 'llm.usage';

DELETE FROM analytics.fact_agent_runs;

INSERT INTO analytics.fact_agent_runs (
    run_id, agent_id, role, status, parent_run_id, tool_calls, llm_calls, input_tokens, output_tokens,
    cost_micro_usd, orders_touched, finished_at
)
SELECT
    aggregate_id,
    json_extract(payload_json, '$.agent_id'),
    json_extract(payload_json, '$.role'),
    json_extract(payload_json, '$.status'),
    json_extract(payload_json, '$.parent_run_id'),
    json_extract(payload_json, '$.tool_calls'),
    json_extract(payload_json, '$.llm_calls'),
    json_extract(payload_json, '$.input_tokens'),
    json_extract(payload_json, '$.output_tokens'),
    json_extract(payload_json, '$.cost_micro_usd'),
    COALESCE(json_extract(payload_json, '$.orders_touched'), 0),
    occurred_at
FROM analytics.raw_events
WHERE event_type = 'agent.run.finished';
