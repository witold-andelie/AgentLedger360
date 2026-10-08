"""A1-A4: the clearing house does not trust either party. See progress.md section 2.3."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from agentledger.contracts import BuyerSignup, Capability, HoldRequest, PaymentRequired, TaskSpec
from agentledger.server import create_app


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AL_ADMIN_TOKEN", "s3cret")
    return TestClient(create_app())


def _buyer(client: TestClient) -> str:
    body = BuyerSignup(agent_id="attacker", name="A", owner="o", initial_funding_minor=2_000,
                       max_per_order_minor=500).model_dump()
    response = client.post("/platform/registry/buyers", json=body, headers={"X-Admin-Token": "s3cret"})
    assert response.status_code == 200, response.text
    return response.json()["agent_key"]


def _hold_and_fetch(client: TestClient, key: str, seller: str) -> str:
    quoted = client.post(
        f"/sellers/agents/{seller}/tasks",
        json=TaskSpec(capability=Capability.SIGNAL_5D, symbol="AAPL", as_of=date(2026, 10, 7)).model_dump(mode="json"),
    )
    assert quoted.status_code == 402, quoted.text
    quote = PaymentRequired.model_validate(quoted.json())
    held = client.post(
        "/platform/escrow/hold",
        headers={"X-Agent-Key": key},
        json=HoldRequest(
            buyer_agent_id="attacker", quote=quote, idempotency_key=quote.quote_id,
        ).model_dump(mode="json"),
    )
    assert held.status_code == 200, held.text
    order_id = held.json()["order_id"]
    fetched = client.post(f"/platform/orders/{order_id}/fetch", headers={"X-Agent-Key": key})
    assert fetched.status_code == 200, fetched.text
    return order_id


def test_a1_accept_and_dispute_require_the_buyer_key(monkeypatch):
    client = _client(monkeypatch)
    key = _buyer(client)
    order_id = _hold_and_fetch(client, key, "sig-momentum")
    report = {"passed": True, "score": 1, "checks": [], "metrics": {}}
    assert client.post(f"/platform/orders/{order_id}/accept", json=report).status_code == 403
    assert client.post(
        f"/platform/orders/{order_id}/accept", json=report, headers={"X-Agent-Key": "not-the-buyer"},
    ).status_code == 403
    assert client.post("/platform/disputes", json={"order_id": order_id, "reason": "nope"}).status_code == 403


def test_a2_dispute_uses_the_archive_not_the_buyers_story(monkeypatch):
    client = _client(monkeypatch)
    key = _buyer(client)
    order_id = _hold_and_fetch(client, key, "sig-hype")
    fake = {
        "order_id": order_id, "seller_agent_id": "sig-hype", "capability": "signal.direction.5d",
        "symbol": "AAPL", "as_of": "2026-10-07", "columns": ["date"], "rows": [{"date": "2026-10-07"}],
        "content_hash": "forged",
    }
    opened = client.post(
        "/platform/disputes",
        headers={"X-Agent-Key": key},
        json={"order_id": order_id, "reason": "seller shipped garbage", "deliverable": fake},
    )
    assert opened.status_code == 200, opened.text
    # The forged fresh row is ignored. The archived hype series is stale, so the buyer is refunded in full.
    assert opened.json()["decision"] == "REFUND_FULL"


def test_a3_fetch_archives_delivery_without_a_buyer_report(monkeypatch):
    client = _client(monkeypatch)
    key = _buyer(client)
    order_id = _hold_and_fetch(client, key, "sig-momentum")
    orders = client.get("/platform/orders").json()
    status = next(row["status"] for row in orders if row["order_id"] == order_id)
    assert status == "DELIVERED"
    missing = client.post(
        f"/platform/orders/{order_id}/delivered", json={"content_hash": "x", "latency_ms": 1},
    )
    assert missing.status_code == 404


def test_a4_public_signup_cannot_mint_money(monkeypatch):
    client = _client(monkeypatch)
    body = BuyerSignup(agent_id="mint", name="M", owner="o", initial_funding_minor=10_000).model_dump()
    assert client.post("/platform/registry/buyers", json=body).status_code == 403
    assert client.get("/platform/wallets/mint").json()["balance_minor"] == 0


def test_ledger_stays_balanced_after_the_blocked_attacks(monkeypatch):
    client = _client(monkeypatch)
    key = _buyer(client)
    _hold_and_fetch(client, key, "sig-hype")
    assert client.get("/platform/ledger/check").json()["ok"] is True
