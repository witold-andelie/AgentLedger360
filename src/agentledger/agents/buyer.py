"""Rule-based buyer (deterministic fallback when no LLM is configured; the LLM agent is buyer_agent.py):
discover -> quote (402) -> escrow -> fetch -> verify -> accept | dispute.

Survival tiers (idea from Conway-Research/automaton): the agent's balance decides how much it may
spend per purchase, so a low wallet makes it frugal and an empty one makes it stop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agentledger.contracts import (
    Deliverable,
    DisputeOutcome,
    DisputeRequest,
    HoldRequest,
    PaymentReceipt,
    PaymentRequired,
    QualityReport,
    RankedCard,
    TaskSpec,
)
from agentledger.market import quality
from agentledger.transport import Router

TIERS = (  # (min balance, tier, max price per purchase) in minor units
    (2_000, "normal", 500),
    (500, "low_compute", 150),
    (1, "critical", 50),
    (0, "dead", 0),
)


@dataclass
class Purchase:
    task: TaskSpec
    seller: RankedCard | None = None
    quote: PaymentRequired | None = None
    order_id: str | None = None
    report: QualityReport | None = None
    dispute: DisputeOutcome | None = None
    status: str = "SKIPPED"
    latency_ms: int = 0
    notes: list[str] = field(default_factory=list)


class BuyerAgent:
    def __init__(self, agent_id: str, router: Router, platform_url: str,
                 log: Callable[[str], None] = print) -> None:
        self.agent_id = agent_id
        self.http = router
        self.platform = platform_url
        self.log = log
        self.agent_key = ""
        self.price_weight = 0.3

    def _auth(self) -> dict[str, str]:
        return {"X-Agent-Key": self.agent_key}

    def balance(self) -> int:
        return int(self.http.get(f"{self.platform}/wallets/{self.agent_id}").json()["balance_minor"])

    def tier(self) -> tuple[str, int]:
        bal = self.balance()
        for floor, name, max_price in TIERS:
            if bal >= floor:
                return name, max_price
        return "dead", 0

    def acquire(self, task: TaskSpec) -> Purchase:
        p = Purchase(task=task)
        tier, max_price = self.tier()
        if max_price == 0:
            p.notes.append("wallet empty: agent stops")
            return p

        # 1. discovery
        r = self.http.get(f"{self.platform}/registry/search",
                          params={"capability": str(task.capability), "max_price_minor": max_price,
                                  "price_weight": self.price_weight})
        cards = [RankedCard.model_validate(c) for c in r.json()]
        if not cards:
            p.notes.append(f"no seller under {max_price} (tier {tier})")
            return p
        p.seller = cards[0]
        p.notes.append(f"policy pick: best score {p.seller.score} (tier {tier})")

        # 2. quote via HTTP 402
        r = self.http.post(f"{p.seller.endpoint}/tasks", json=task.model_dump(mode="json"))
        if r.status_code != 402:
            p.status = "SELLER_ERROR"
            p.notes.append(f"expected 402, got {r.status_code}")
            return p
        p.quote = PaymentRequired.model_validate(r.json())

        # 3. escrow hold at the clearing house (idempotent per quote)
        r = self.http.post(f"{self.platform}/escrow/hold", headers=self._auth(), json=HoldRequest(
            buyer_agent_id=self.agent_id, quote=p.quote, idempotency_key=f"{self.agent_id}:{p.quote.quote_id}",
        ).model_dump(mode="json"))
        if r.status_code != 200:
            p.status = "PAYMENT_REJECTED"
            p.notes.append(r.json().get("detail", r.text))
            return p
        receipt = PaymentReceipt.model_validate(r.json())
        p.order_id = receipt.order_id

        # 4. the clearing house fetches and archives the delivery itself
        recorded = self.http.post(f"{self.platform}/orders/{p.order_id}/fetch", headers=self._auth())
        if recorded.status_code != 200:
            p.status = "SELLER_ERROR"
            detail = recorded.json().get("detail", recorded.text) if recorded.content else recorded.text
            p.notes.append(f"clearing house did not archive delivery ({detail}); funds stay held until expiry")
            return p
        deliverable = Deliverable.model_validate(recorded.json())
        p.latency_ms = 0

        # 5. verify against the contract, then accept or dispute
        p.report = quality.evaluate(deliverable, p.quote.acceptance)
        if p.report.passed:
            self.http.post(f"{self.platform}/orders/{p.order_id}/accept", headers=self._auth(),
                           json=p.report.model_dump(mode="json"))
            p.status = "COMPLETED"
        else:
            failed = ", ".join(c.name for c in p.report.checks if not c.passed)
            r = self.http.post(f"{self.platform}/disputes", headers=self._auth(), json=DisputeRequest(
                order_id=p.order_id, reason=f"acceptance checks failed: {failed}", deliverable=deliverable,
            ).model_dump(mode="json"))
            p.dispute = DisputeOutcome.model_validate(r.json())
            p.status = p.dispute.decision.value
        return p
