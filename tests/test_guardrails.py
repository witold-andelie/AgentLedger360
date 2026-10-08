"""T1 capability switches, T4 audit chain, T21 startup funding, T23 public cost guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from agentledger.contracts import AcceptanceCriteria, BuyerSignup, Capability, HoldRequest, PaymentRequired, TaskSpec
from agentledger.db import connect, emit_event, now_iso, transaction, verify_audit_chain
from agentledger.server import create_app


def _quote(amount: int) -> HoldRequest:
    return HoldRequest(
        buyer_agent_id="pm-alpha",
        idempotency_key=f"k-{amount}",
        quote=PaymentRequired(
            quote_id=f"q-{amount}", seller_agent_id="sig-hype", amount_minor=amount,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            task=TaskSpec(capability=Capability.SIGNAL_5D, symbol="AAPL"),
            acceptance=AcceptanceCriteria(required_columns=["date"]),
        ),
    )


def test_startup_funds_the_buyer_once():
    client = TestClient(create_app())
    assert client.get("/api/summary").json()["kpi"]["buyer_balance_minor"] == 3_000
    again = TestClient(create_app())
    assert again.get("/api/summary").json()["kpi"]["buyer_balance_minor"] == 3_000


def test_open_funding_pause_and_global_cap(monkeypatch):
    monkeypatch.setenv("AL_ADMIN_TOKEN", "s3cret")
    client = TestClient(create_app())
    signup = BuyerSignup(agent_id="stranger", name="S", owner="o", initial_funding_minor=100).model_dump()
    assert client.post("/platform/registry/buyers", json=signup).status_code == 403
    assert client.get("/platform/wallets/stranger").json()["balance_minor"] == 0
    assert client.post("/platform/registry/buyers", json=signup, headers={"X-Admin-Token": "s3cret"}).status_code == 200

    assert client.post("/api/admin/pause").status_code == 403
    assert client.post("/api/admin/pause", headers={"X-Admin-Token": "s3cret"}).json()["market_paused"] is True
    paused = client.post("/platform/escrow/hold", json=_quote(100).model_dump(mode="json"))
    assert paused.status_code == 503
    assert client.post("/api/admin/resume", headers={"X-Admin-Token": "s3cret"}).json()["market_paused"] is False

    capped = client.post("/platform/escrow/hold", json=_quote(600).model_dump(mode="json"))
    assert capped.status_code == 403
    health = client.get("/api/health").json()
    assert health["capabilities"]["max_order_minor"] == 500
    assert health["capabilities"]["open_funding"] is False


def test_audit_chain_detects_a_rewritten_payload(conn):
    with transaction(conn):
        emit_event(conn, "wallet.funded", "b1", {"amount_minor": 10})
        emit_event(conn, "wallet.funded", "b1", {"amount_minor": 20})
    ok, bad = verify_audit_chain(conn)
    assert ok and bad is None
    conn.execute(
        "UPDATE outbox SET payload_json = ? WHERE seq = (SELECT MIN(seq) FROM outbox)",
        ('{"tampered": true}',),
    )
    ok, bad = verify_audit_chain(conn)
    assert not ok and bad == conn.execute("SELECT MIN(seq) FROM outbox").fetchone()[0]


def test_run_token_rate_limit_and_daily_budget(monkeypatch):
    monkeypatch.setenv("AL_RUN_TOKEN", "run-please")
    monkeypatch.setenv("AL_ROUND_MIN_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("AL_DAILY_AI_BUDGET_USD", "0.01")
    client = TestClient(create_app())
    assert client.get("/api/health").json()["run_requires_token"] is True
    assert client.post("/api/round", json={"symbols": [], "rounds": 1}).status_code == 403
    headers = {"X-Run-Token": "run-please"}
    assert client.post("/api/round", json={"symbols": [], "rounds": 1}, headers=headers).status_code == 200
    assert client.post("/api/round", json={"symbols": [], "rounds": 1}, headers=headers).status_code == 429

    conn = connect()
    conn.execute(
        "INSERT INTO agent_runs (run_id, agent_id, role, goal, provider, model, status, started_at, cost_micro_usd)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        ("run_big", "pm-alpha", "buyer", "goal", "mistral", "m", "completed", now_iso(), 20_000),
    )
    conn.close()
    monkeypatch.setenv("AL_ROUND_MIN_INTERVAL_SECONDS", "0")
    client = TestClient(create_app())
    body = client.post("/api/round", json={"symbols": ["AAPL"], "rounds": 1}, headers=headers).json()
    assert body["degraded"] == "daily AI budget reached"
    conn = connect()
    spent = conn.execute("SELECT COALESCE(SUM(cost_micro_usd), 0) FROM agent_runs").fetchone()[0]
    conn.close()
    assert spent == 20_000
