from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from agentledger.contracts import Capability, HoldRequest, PaymentRequired, TaskSpec
from agentledger.sellers.app import create_app as seller_app
from agentledger.server import create_app


def _quote(client: TestClient) -> dict:
    response = client.post(
        "/agents/sig-momentum/tasks",
        json=TaskSpec(capability=Capability.SIGNAL_5D, symbol="AAPL", as_of=date(2026, 10, 7)).model_dump(mode="json"),
    )
    assert response.status_code == 402
    assert response.json()["amount_minor"] == 150
    return response.json()


def test_seller_walks_down_to_the_floor_and_then_closes():
    client = TestClient(seller_app())
    quote = _quote(client)
    quote_id = quote["quote_id"]
    path = f"/agents/sig-momentum/quotes/{quote_id}/counter"
    first = client.post(path, json={"amount_minor": 100})
    assert first.status_code == 402
    assert first.json()["amount_minor"] == 135  # midpoint of 150 and floor 120
    assert first.json()["negotiation_round"] == 1
    second = client.post(path, json={"amount_minor": 100})
    assert second.status_code == 402 and second.json()["negotiation_round"] == 2
    third = client.post(path, json={"amount_minor": 100})
    assert third.status_code == 402
    assert third.json()["amount_minor"] == 120  # final offer is the floor
    assert third.json()["negotiation_round"] == 3
    closed = client.post(path, json={"amount_minor": 100})
    assert closed.status_code == 409


def test_negotiated_price_is_what_gets_held(monkeypatch):
    monkeypatch.setenv("AL_ADMIN_TOKEN", "s3cret")
    client = TestClient(create_app())
    quoted = client.post(
        "/sellers/agents/sig-momentum/tasks",
        json=TaskSpec(capability=Capability.SIGNAL_5D, symbol="AAPL", as_of=date(2026, 10, 7)).model_dump(mode="json"),
    )
    quote = PaymentRequired.model_validate(quoted.json())
    agreed = client.post(
        f"/sellers/agents/sig-momentum/quotes/{quote.quote_id}/counter",
        json={"amount_minor": 120},
    )
    quote = PaymentRequired.model_validate(agreed.json())
    key = client.post(
        "/platform/registry/buyers",
        headers={"X-Admin-Token": "s3cret"},
        json={"agent_id": "haggler", "name": "H", "owner": "o", "initial_funding_minor": 2000,
              "max_per_order_minor": 500},
    ).json()["agent_key"]
    held = client.post(
        "/platform/escrow/hold",
        headers={"X-Agent-Key": key},
        json=HoldRequest(buyer_agent_id="haggler", quote=quote, idempotency_key=quote.quote_id).model_dump(mode="json"),
    )
    assert held.status_code == 200, held.text
    assert held.json()["amount_minor"] == 120
    fetched = client.post(f"/platform/orders/{held.json()['order_id']}/fetch", headers={"X-Agent-Key": key})
    assert fetched.status_code == 200, fetched.text
