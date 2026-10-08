"""Tiny Airflow-style DAG runner: ingest -> marts -> data-quality checks, every run logged to
analytics.pipeline_runs. (Topological runner idea as in quant-alpha-foundation's Bruin asset graph.)

    python -m agentledger.analytics.pipeline
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from graphlib import TopologicalSorter

from agentledger.analytics.ingest import ingest
from agentledger.config import SQL_DIR
from agentledger.db import connect, init_db, new_id, now_iso, verify_audit_chain

TaskFn = Callable[[sqlite3.Connection, str], int]


@dataclass(frozen=True)
class Task:
    name: str
    run: TaskFn
    deps: tuple[str, ...] = ()


def sql_task(relative: str, target: str) -> TaskFn:
    """Run a rebuild script atomically; returns the row count of the target table."""

    def run(conn: sqlite3.Connection, run_id: str) -> int:
        sql = (SQL_DIR / relative).read_text(encoding="utf-8")
        try:
            conn.executescript(f"BEGIN IMMEDIATE;\n{sql}\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return conn.execute(f"SELECT COUNT(*) FROM {target}").fetchone()[0]

    return run


def quality_checks(conn: sqlite3.Connection, run_id: str) -> int:
    """Each `-- name: x` block in sql/quality_checks.sql returns a violation count; 0 = pass."""
    text = (SQL_DIR / "quality_checks.sql").read_text(encoding="utf-8")
    failed = 0
    for block in text.split("-- name:")[1:]:
        name, _, sql = block.partition("\n")
        violations = int(conn.execute(sql).fetchone()[0] or 0)
        failed += violations > 0
        conn.execute(
            "INSERT OR REPLACE INTO analytics.dq_results (run_id, check_name, violations, passed, checked_at)"
            " VALUES (?,?,?,?,?)",
            (run_id, name.strip(), violations, int(violations == 0), now_iso()),
        )
    ok, bad = verify_audit_chain(conn)
    violations = 0 if ok else (bad or 1)
    failed += violations > 0
    conn.execute(
        "INSERT OR REPLACE INTO analytics.dq_results (run_id, check_name, violations, passed, checked_at)"
        " VALUES (?,?,?,?,?)",
        (run_id, "audit_chain_intact", violations, int(violations == 0), now_iso()),
    )
    return failed


TASKS = [
    Task("ingest_events", ingest),
    Task("build_dim_agents", sql_task("marts/dim_agents.sql", "analytics.dim_agents"), ("ingest_events",)),
    Task("build_fact_orders", sql_task("marts/fact_orders.sql", "analytics.fact_orders"), ("ingest_events",)),
    Task("build_ai_costs", sql_task("marts/fact_llm_calls.sql", "analytics.fact_llm_calls"), ("ingest_events",)),
    Task("data_quality_checks", quality_checks, ("build_dim_agents", "build_fact_orders", "build_ai_costs")),
]


def run(conn: sqlite3.Connection | None = None) -> list[dict[str, object]]:
    conn = conn or connect()
    init_db(conn)
    by_name = {t.name: t for t in TASKS}
    order = TopologicalSorter({t.name: set(t.deps) for t in TASKS}).static_order()
    run_id, results, failed = new_id("run"), [], set()
    for name in order:
        task = by_name[name]
        started, t0 = now_iso(), time.perf_counter()
        if failed & set(task.deps):
            status, rows, error = "upstream_failed", None, None
        else:
            try:
                status, rows, error = "success", task.run(conn, run_id), None
            except Exception as exc:  # keep running independent branches, record the failure
                status, rows, error = "failed", None, repr(exc)
        if status != "success":
            failed.add(name)
        ms = int((time.perf_counter() - t0) * 1000)
        conn.execute(
            "INSERT INTO analytics.pipeline_runs (run_id, task, status, rows_out, duration_ms, started_at, error)"
            " VALUES (?,?,?,?,?,?,?)",
            (run_id, name, status, rows, ms, started, error),
        )
        results.append({"run_id": run_id, "task": name, "status": status, "rows": rows, "ms": ms, "error": error})
    return results


if __name__ == "__main__":
    for r in run():
        print(f"{r['task']:<22} {r['status']:<16} rows={r['rows']} {r['ms']}ms {r['error'] or ''}")
