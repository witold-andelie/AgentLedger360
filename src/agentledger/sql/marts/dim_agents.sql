-- dim_agents: latest registration per agent + latest reputation (both from events).
DELETE FROM analytics.dim_agents;

INSERT INTO analytics.dim_agents (agent_id, name, owner, role, capability, list_price_minor, reputation, registered_at)
WITH reg AS (
    SELECT aggregate_id AS agent_id, payload_json AS p, occurred_at,
           ROW_NUMBER() OVER (PARTITION BY aggregate_id ORDER BY seq DESC) AS rn
    FROM analytics.raw_events
    WHERE event_type = 'agent.registered'
),
rep AS (
    SELECT aggregate_id AS agent_id, json_extract(payload_json, '$.reputation') AS reputation,
           ROW_NUMBER() OVER (PARTITION BY aggregate_id ORDER BY seq DESC) AS rn
    FROM analytics.raw_events
    WHERE event_type = 'reputation.updated'
)
SELECT
    reg.agent_id,
    json_extract(reg.p, '$.name'),
    json_extract(reg.p, '$.owner'),
    json_extract(reg.p, '$.role'),
    json_extract(reg.p, '$.capability'),
    json_extract(reg.p, '$.price_minor'),
    COALESCE(rep.reputation, 0.5),
    reg.occurred_at
FROM reg
LEFT JOIN rep ON rep.agent_id = reg.agent_id AND rep.rn = 1
WHERE reg.rn = 1;
