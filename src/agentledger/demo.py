"""End-to-end CLI demo: sellers publish agent cards, a buyer agent discovers, pays, verifies, disputes;
then the analytics pipeline builds the marts and runs the data-quality checks.

Single laptop (in-process, no ports):
    python -m agentledger.demo --reset
Against a remote seller service (other laptop or Render):
    AL_SELLER_URL=https://<sellers-host> python -m agentledger.demo
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import date

from agentledger.agents.accounting import format_usd
from agentledger.analytics import pipeline
from agentledger.config import load_settings
from agentledger.db import connect
from agentledger.runner import BUYER, Market, summarize


def print_table(conn: sqlite3.Connection, title: str, sql: str, params: tuple[str, ...] = ()) -> None:
    cur = conn.execute(sql, params)
    print(f"\n== {title}\n  " + " | ".join(d[0] for d in cur.description))
    for row in cur.fetchall():
        print("  " + " | ".join(str(v) for v in row))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="delete var/ databases first")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA")
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="point-in-time cutoff, default today")
    args = ap.parse_args(argv)

    settings = load_settings()
    if args.reset and settings.var_dir.exists():
        shutil.rmtree(settings.var_dir)

    market = Market.in_process(settings)
    print(f"registered {market.bootstrap()} seller agents from {market.seller_url}; "
          f"buyer {BUYER.agent_id} wallet ${market.buyer.balance() / 100:.2f}; agent mode: {market.mode}")

    for rnd in range(1, args.rounds + 1):
        print(f"\n-- round {rnd}: buyer needs 5-day direction signals")
        for p in market.run_round(args.symbols.split(","), args.as_of):
            s = summarize(p)
            price = f"${s['price_minor'] / 100:.2f}" if s["price_minor"] else "-"
            extra = f"hit={s['hit_rate']:.2f}" if s["hit_rate"] is not None else ""
            if s["refund_minor"] is not None:
                extra += f" refund=${s['refund_minor'] / 100:.2f} ({s['rationale']})"
            print(f"  {s['symbol']:<5} {s['seller'] or '-':<13} {price:>6}  {s['status']:<18} {extra}")
            for note in s["notes"]:
                print(f"        - {note}")
        print(f"  wallet ${market.buyer.balance() / 100:.2f}")
        run = market.last_run if market.mode == "llm" else None
        if run is not None:
            print(f"  agent {run.run_id}: {run.status}, {run.llm_calls} LLM calls, {run.tool_calls} tool calls, "
                  f"{run.input_tokens}+{run.output_tokens} tokens, AI cost {format_usd(run.cost_micro_usd)}")

    print(f"\nreconciliation: {market.router.get(f'{market.platform_url}/ledger/check').json()}")
    conn = connect(settings)
    results = pipeline.run(conn)
    for r in results:
        print(f"pipeline {r['task']:<22} {r['status']:<10} rows={r['rows']} {r['error'] or ''}")
    print_table(conn, "Agent reliability (analytics.v_agent_performance)",
                "SELECT seller_agent_id, orders_total, success_rate, dispute_rate, seller_revenue_minor, avg_hit_rate,"
                " reputation FROM analytics.v_agent_performance ORDER BY reputation DESC")
    print_table(conn, "Customer 360 (analytics.v_customer_360)",
                "SELECT buyer_agent_id, orders_total, orders_completed, orders_disputed, gross_spend_minor,"
                " net_spend_minor, avg_signal_hit_rate FROM analytics.v_customer_360")
    print_table(conn, "AI cost by agent (analytics.v_ai_cost_by_agent, micro-USD)",
                "SELECT agent_id, role, runs, llm_calls, tool_calls, input_tokens, output_tokens, cost_micro_usd"
                " FROM analytics.v_ai_cost_by_agent ORDER BY cost_micro_usd DESC")
    print_table(conn, "Data quality (this run)",
                "SELECT check_name, violations, CASE passed WHEN 1 THEN 'PASS' ELSE 'FAIL' END AS result"
                " FROM analytics.dq_results WHERE run_id = ?", (str(results[0]["run_id"]),))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
