-- Realized signal outcomes, rebuilt only from signal.verified events.
DELETE FROM analytics.fact_signal_outcomes;

INSERT INTO analytics.fact_signal_outcomes (
    order_id, seller_agent_id, symbol, predicted, realized_up, correct, verified_at
)
SELECT
    aggregate_id,
    json_extract(payload_json, '$.seller'),
    json_extract(payload_json, '$.symbol'),
    json_extract(payload_json, '$.predicted'),
    json_extract(payload_json, '$.realized_up'),
    json_extract(payload_json, '$.correct'),
    occurred_at
FROM analytics.raw_events
WHERE event_type = 'signal.verified';
