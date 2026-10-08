-- Data-quality & reconciliation checks. Each block returns ONE number = violations (0 = pass).
-- analytics/pipeline.py splits this file on the name markers; results land in analytics.dq_results.

-- name: ingestion_complete
SELECT COALESCE((SELECT MAX(seq) FROM main.outbox), 0)
     - COALESCE((SELECT last_seq FROM analytics.ingest_cursor WHERE consumer = 'analytics'), 0);

-- name: ledger_txns_balanced
SELECT COUNT(*) FROM (
    SELECT txn_id FROM main.ledger_entries GROUP BY txn_id HAVING SUM(amount_minor) <> 0
);

-- name: no_negative_agent_balance
SELECT COUNT(*) FROM (
    SELECT w.wallet_id
    FROM main.wallets w JOIN main.ledger_entries e ON e.wallet_id = w.wallet_id
    WHERE w.kind = 'agent'
    GROUP BY w.wallet_id HAVING SUM(e.amount_minor) < 0
);

-- name: escrow_reconciles_with_open_orders
SELECT ABS(
    COALESCE((SELECT SUM(amount_minor) FROM main.ledger_entries WHERE wallet_id = 'w_escrow'), 0)
  - COALESCE((SELECT SUM(amount_minor) FROM main.orders
              WHERE status IN ('FUNDS_HELD', 'DELIVERED', 'DISPUTED')), 0)
) > 0;

-- name: oltp_vs_warehouse_order_count
SELECT ABS((SELECT COUNT(*) FROM main.orders) - (SELECT COUNT(*) FROM analytics.fact_orders));

-- name: no_settlement_without_delivery
SELECT COUNT(*) FROM main.orders WHERE status = 'COMPLETED' AND delivered_at IS NULL;

-- name: refund_within_amount
SELECT COUNT(*) FROM analytics.fact_orders WHERE refunded_minor > amount_minor;

-- name: at_most_one_refund_per_order
SELECT COUNT(*) FROM (
    SELECT aggregate_id FROM analytics.raw_events
    WHERE event_type = 'payment.refunded' GROUP BY aggregate_id HAVING COUNT(*) > 1
);

-- name: valid_final_status
SELECT COUNT(*) FROM analytics.fact_orders
WHERE final_status NOT IN ('FUNDS_HELD', 'DELIVERED', 'COMPLETED', 'DISPUTED',
                           'REFUNDED', 'PARTIALLY_REFUNDED', 'CANCELLED');

-- name: llm_tokens_non_negative
SELECT COUNT(*) FROM analytics.fact_llm_calls
WHERE input_tokens < 0 OR output_tokens < 0 OR cost_micro_usd < 0;

-- name: ai_cost_reconciles_calls_vs_runs
SELECT ABS(
    COALESCE((SELECT SUM(cost_micro_usd) FROM analytics.fact_llm_calls), 0)
  - COALESCE((SELECT SUM(cost_micro_usd) FROM analytics.fact_agent_runs), 0)
) > 0;
