-- fact_orders: one row per order, rebuilt from events only (idempotent full refresh).
DELETE FROM analytics.fact_orders;

INSERT INTO analytics.fact_orders (
    order_id, buyer_agent_id, seller_agent_id, capability, symbol, amount_minor, refunded_minor, fee_minor,
    final_status, disputed, latency_ms, hit_rate, rank_ic, held_at, closed_at
)
WITH held AS (
    SELECT aggregate_id AS order_id, payload_json AS p, occurred_at AS held_at
    FROM analytics.raw_events
    WHERE event_type = 'payment.held'
),
latest_status AS (   -- window function: last known status per order
    SELECT aggregate_id AS order_id,
           json_extract(payload_json, '$.status') AS status,
           ROW_NUMBER() OVER (PARTITION BY aggregate_id ORDER BY seq DESC) AS rn
    FROM analytics.raw_events
    WHERE json_extract(payload_json, '$.status') IS NOT NULL
),
closing AS (
    SELECT aggregate_id AS order_id,
           SUM(COALESCE(json_extract(payload_json, '$.fee_minor'), 0))      AS fee_minor,
           MAX(COALESCE(json_extract(payload_json, '$.refunded_minor'), 0)) AS refunded_minor,
           MAX(json_extract(payload_json, '$.hit_rate'))                    AS hit_rate,
           MAX(json_extract(payload_json, '$.rank_ic'))                     AS rank_ic,
           MAX(occurred_at)                                                 AS closed_at
    FROM analytics.raw_events
    WHERE event_type IN ('payment.settled', 'payment.refunded')
    GROUP BY aggregate_id
),
delivery AS (
    SELECT aggregate_id AS order_id, MAX(json_extract(payload_json, '$.latency_ms')) AS latency_ms
    FROM analytics.raw_events
    WHERE event_type = 'order.delivered'
    GROUP BY aggregate_id
),
disputed AS (
    SELECT DISTINCT aggregate_id AS order_id
    FROM analytics.raw_events
    WHERE event_type = 'dispute.opened'
)
SELECT
    h.order_id,
    json_extract(h.p, '$.buyer_agent_id'),
    json_extract(h.p, '$.seller_agent_id'),
    json_extract(h.p, '$.capability'),
    json_extract(h.p, '$.symbol'),
    json_extract(h.p, '$.amount_minor'),
    COALESCE(c.refunded_minor, 0),
    COALESCE(c.fee_minor, 0),
    s.status,
    d.order_id IS NOT NULL,
    dl.latency_ms,
    c.hit_rate,
    c.rank_ic,
    h.held_at,
    c.closed_at
FROM held h
JOIN latest_status s ON s.order_id = h.order_id AND s.rn = 1
LEFT JOIN closing c   ON c.order_id = h.order_id
LEFT JOIN delivery dl ON dl.order_id = h.order_id
LEFT JOIN disputed d  ON d.order_id = h.order_id;
