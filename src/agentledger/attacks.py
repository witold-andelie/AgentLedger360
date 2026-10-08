"""Attack-lab scenarios. Each one runs against a throwaway database, never the demo ledger.

A scenario is blocked when the attacker does not get the money, the forged evidence, or the extra order.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from agentledger.config import Settings, load_settings
from agentledger.contracts import (
    BuyerSignup,
    Capability,
    DisputeDecision,
    GuardianRuling,
    HoldRequest,
    PaymentReceipt,
    PaymentRequired,
    TaskSpec,
)
from agentledger.economy import disputes, receipts

AS_OF = date(2026, 10, 7)


@dataclass
class Outcome:
    id: str
    title: str
    blocked: bool
    rule: str
    http_status: int
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "title": self.title, "blocked": self.blocked, "rule": self.rule,
            "http_status": self.http_status, "detail": self.detail,
        }


def _buyer(client: TestClient, agent_id: str) -> str:
    body = BuyerSignup(
        agent_id=agent_id, name=agent_id, owner="lab", initial_funding_minor=2_000, max_per_order_minor=500,
    ).model_dump()
    response = client.post("/platform/registry/buyers", json=body, headers={"X-Admin-Token": "lab-token"})
    response.raise_for_status()
    return response.json()["agent_key"]


def _quote(client: TestClient, seller: str) -> PaymentRequired:
    response = client.post(
        f"/sellers/agents/{seller}/tasks",
        json=TaskSpec(capability=Capability.SIGNAL_5D, symbol="AAPL", as_of=AS_OF).model_dump(mode="json"),
    )
    if response.status_code != 402:
        raise RuntimeError(response.text)
    return PaymentRequired.model_validate(response.json())


def _hold(client: TestClient, key: str, buyer: str, quote: PaymentRequired):
    return client.post(
        "/platform/escrow/hold",
        headers={"X-Agent-Key": key},
        json=HoldRequest(buyer_agent_id=buyer, quote=quote, idempotency_key=quote.quote_id).model_dump(mode="json"),
    )


def run_scenarios(settings: Settings | None = None) -> list[dict[str, object]]:
    base = settings or load_settings()
    scratch = base.var_dir.parent / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="attack-", dir=scratch))
    try:
        from agentledger.server import create_app

        lab = replace(base, var_dir=work, agent_mode="rule", admin_token="lab-token", seller_url=None)
        client = TestClient(create_app(lab))
        return [item.as_dict() for item in _all(client)]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _all(client: TestClient) -> list[Outcome]:
    return [
        _a1(client), _a2(client), _a3(client), _a4(client),
        _replay(client), _double_settle(client), _mandate(client), _tamper_price(client), _out_of_band(),
    ]


def _a1(client: TestClient) -> Outcome:
    key = _buyer(client, "a1")
    quote = _quote(client, "sig-momentum")
    order_id = _hold(client, key, "a1", quote).json()["order_id"]
    client.post(f"/platform/orders/{order_id}/fetch", headers={"X-Agent-Key": key})
    response = client.post(
        f"/platform/orders/{order_id}/accept", json={"passed": True, "score": 1, "checks": [], "metrics": {}},
    )
    return Outcome("A1", "Seller accepts an order without the buyer key", response.status_code == 403,
                   "R19", response.status_code, response.json().get("detail", ""))


def _a2(client: TestClient) -> Outcome:
    key = _buyer(client, "a2")
    quote = _quote(client, "sig-hype")
    order_id = _hold(client, key, "a2", quote).json()["order_id"]
    client.post(f"/platform/orders/{order_id}/fetch", headers={"X-Agent-Key": key})
    forged = {
        "order_id": order_id, "seller_agent_id": "sig-hype", "capability": "signal.direction.5d",
        "symbol": "AAPL", "as_of": "2026-10-07", "columns": ["date"], "rows": [{"date": "2026-10-07"}],
        "content_hash": "forged",
    }
    response = client.post(
        "/platform/disputes", headers={"X-Agent-Key": key},
        json={"order_id": order_id, "reason": "forged evidence", "deliverable": forged},
    )
    decision = response.json().get("decision")
    return Outcome("A2", "Buyer submits forged rows so a bad seller still gets paid",
                   response.status_code == 200 and decision == "REFUND_FULL",
                   "R8", response.status_code, f"decision={decision}")


def _a3(client: TestClient) -> Outcome:
    key = _buyer(client, "a3")
    quote = _quote(client, "sig-momentum")
    order_id = _hold(client, key, "a3", quote).json()["order_id"]
    fetched = client.post(f"/platform/orders/{order_id}/fetch", headers={"X-Agent-Key": key})
    gone = client.post(f"/platform/orders/{order_id}/delivered", json={"content_hash": "x", "latency_ms": 1})
    status = next(row["status"] for row in client.get("/platform/orders").json() if row["order_id"] == order_id)
    blocked = fetched.status_code == 200 and status == "DELIVERED" and gone.status_code == 404
    return Outcome("A3", "Buyer keeps the data and never records delivery", blocked, "R7", gone.status_code,
                   f"order status after fetch is {status}")


def _a4(client: TestClient) -> Outcome:
    body = BuyerSignup(agent_id="mint", name="M", owner="o", initial_funding_minor=50_000).model_dump()
    response = client.post("/platform/registry/buyers", json=body)
    return Outcome("A4", "Signup mints an arbitrary wallet balance", response.status_code == 403,
                   "R19", response.status_code, response.json().get("detail", ""))


def _replay(client: TestClient) -> Outcome:
    key = _buyer(client, "replay")
    quote = _quote(client, "sig-rsi")
    held = _hold(client, key, "replay", quote)
    receipt = PaymentReceipt.model_validate(held.json())
    client.post(f"/platform/orders/{receipt.order_id}/fetch", headers={"X-Agent-Key": key})
    again = client.post(
        "/sellers/agents/sig-rsi/tasks",
        json=TaskSpec(capability=Capability.SIGNAL_5D, symbol="AAPL", as_of=AS_OF).model_dump(mode="json"),
        headers={"X-Payment": receipts.to_header(receipt)},
    )
    return Outcome("R5", "Redeem the same payment receipt twice", again.status_code in (402, 409),
                   "R5", again.status_code, again.json().get("detail", again.text)[:180])


def _double_settle(client: TestClient) -> Outcome:
    key = _buyer(client, "twice")
    quote = _quote(client, "sig-momentum")
    order_id = _hold(client, key, "twice", quote).json()["order_id"]
    client.post(f"/platform/orders/{order_id}/fetch", headers={"X-Agent-Key": key})
    report = {"passed": True, "score": 1, "checks": [], "metrics": {}}
    headers = {"X-Agent-Key": key}
    first = client.post(f"/platform/orders/{order_id}/accept", json=report, headers=headers)
    second = client.post(f"/platform/orders/{order_id}/accept", json=report, headers=headers)
    return Outcome("R4", "Settle the same order twice", first.status_code == 200 and second.status_code != 200,
                   "R4", second.status_code, second.json().get("detail", "")[:180])


def _mandate(client: TestClient) -> Outcome:
    key = _buyer(client, "mandate")
    quote = _quote(client, "sig-momentum").model_copy(update={"amount_minor": 10_000, "quote_id": "over-cap"})
    response = _hold(client, key, "mandate", quote)
    return Outcome("R6", "Hold more than the global order cap", response.status_code == 403,
                   "R6", response.status_code, response.json().get("detail", ""))


def _tamper_price(client: TestClient) -> Outcome:
    key = _buyer(client, "tamper")
    quote = _quote(client, "sig-logit").model_copy(update={"amount_minor": 1})
    held = _hold(client, key, "tamper", quote)
    if held.status_code != 200:
        return Outcome("R7", "Pay a different amount than the seller quoted", True, "R7", held.status_code,
                       held.json().get("detail", ""))
    fetched = client.post(f"/platform/orders/{held.json()['order_id']}/fetch", headers={"X-Agent-Key": key})
    return Outcome("R7", "Pay a different amount than the seller quoted", fetched.status_code != 200,
                   "R7", fetched.status_code, fetched.json().get("detail", "")[:180])


def _out_of_band() -> Outcome:
    band = disputes.PolicyBand(DisputeDecision.REFUND_PARTIAL, 25, 75, 50, "performance", ("hit_rate",))
    ruling = GuardianRuling(decision=DisputeDecision.REFUND_FULL, refund_pct=100, rationale="pay them anyway",
                            cited_checks=["hit_rate"], source="guardian-llm")
    problem = disputes.validate(ruling, band)
    return Outcome("R1", "Guardian ruling outside the policy band", problem is not None, "R1", 0, problem or "accepted")
