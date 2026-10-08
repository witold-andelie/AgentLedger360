from __future__ import annotations

from agentledger import demo
from agentledger.db import connect


def test_demo_runs_and_all_quality_checks_pass(capsys):
    assert demo.main(["--rounds", "3", "--symbols", "AAPL,MSFT,NVDA", "--as-of", "2026-10-07"]) == 0
    out = capsys.readouterr().out
    assert "'ok': True" in out  # ledger reconciliation
    conn = connect()
    statuses = {r[0] for r in conn.execute("SELECT status FROM orders")}
    assert "COMPLETED" in statuses
    assert statuses & {"REFUNDED", "PARTIALLY_REFUNDED"}  # at least one dispute paid out
    failed = conn.execute("SELECT check_name FROM analytics.dq_results WHERE passed = 0").fetchall()
    assert failed == []
