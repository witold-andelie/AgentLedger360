from __future__ import annotations

from fastapi.testclient import TestClient

from agentledger.server import create_app


def test_api_round_then_summary():
    client = TestClient(create_app())
    assert client.get("/api/health").json()["status"] == "ok"

    body = client.post("/api/round", json={"symbols": ["AAPL", "NVDA"], "rounds": 1}).json()
    assert len(body["purchases"]) == 2
    assert body["reconciliation"]["ok"] is True
    assert all(r["status"] == "success" for r in body["pipeline"])

    summary = client.get("/api/summary").json()
    assert summary["kpi"]["orders"] == 2
    assert summary["dq"] and all(c["passed"] == 1 for c in summary["dq"])
    assert client.get("/api/events?limit=5").status_code == 200
    # second bootstrap (new process / restart) must not re-fund the buyer (R5)
    balance = summary["kpi"]["buyer_balance_minor"]
    client2 = TestClient(create_app())
    client2.post("/api/round", json={"symbols": [], "rounds": 1})
    assert client2.get("/api/summary").json()["kpi"]["buyer_balance_minor"] == balance


def test_background_agent_round_job_completes():
    import time

    client = TestClient(create_app())
    health = client.get("/api/health").json()
    assert health["agent_mode"] == "rule"  # conftest forces the deterministic agents
    job_id = client.post("/api/agent/rounds", json={"symbols": ["AAPL"], "as_of": "2026-10-07"}).json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/agent/rounds/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.1)
    assert job["status"] == "completed", job["error"]
    assert job["purchases"][0]["symbol"] == "AAPL"
    assert job["result"]["reconciliation"]["ok"] is True
    summary = client.get("/api/summary").json()
    assert {"ai_cost_micro_usd", "llm_calls", "ai_runs"} <= set(summary["kpi"])
    assert client.get("/api/agent/runs").status_code == 200


def test_demo_reset_wipes_and_refills(monkeypatch):
    client = TestClient(create_app())
    client.post("/api/round", json={"symbols": ["AAPL", "NVDA"], "rounds": 2})
    before = client.get("/api/summary").json()["kpi"]
    assert before["orders"] > 0 and before["buyer_balance_minor"] < 3_000

    body = client.post("/api/demo/reset").json()
    assert body["reset"] is True and body["buyer_balance_minor"] == 3_000
    assert body["reconciliation"]["ok"] is True
    after = client.get("/api/summary").json()
    assert after["kpi"]["orders"] == 0 and after["kpi"]["ai_cost_micro_usd"] == 0
    assert after["dq"] and all(c["passed"] == 1 for c in after["dq"])
    assert client.get("/api/agent/runs").json() == []
    # the market works again right after a reset
    assert client.post("/api/round", json={"symbols": ["AAPL"], "rounds": 1}).status_code == 200


def test_demo_reset_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("AL_ADMIN_TOKEN", "s3cret")
    client = TestClient(create_app())
    assert client.get("/api/health").json()["reset_requires_token"] is True
    assert client.post("/api/demo/reset").status_code == 403
    assert client.post("/api/demo/reset", headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.post("/api/demo/reset", headers={"X-Admin-Token": "s3cret"}).status_code == 200
