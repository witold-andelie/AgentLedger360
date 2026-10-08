"""Seller service: hosts every agent in the catalog behind an HTTP 402 paywall.

Run on laptop B:  uvicorn agentledger.sellers.app:create_app --factory --host 0.0.0.0 --port 8002
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from agentledger.config import Settings, load_settings
from agentledger.contracts import AgentCard, Deliverable, PaymentRequired, TaskSpec, canonical_hash
from agentledger.db import new_id
from agentledger.economy import receipts
from agentledger.sellers.catalog import SELLERS, frame_to_rows

QUOTE_TTL = timedelta(minutes=5)
MAX_COUNTERS = 3


class CounterOffer(BaseModel):
    amount_minor: int = Field(gt=0)


def floor_minor(list_price: int) -> int:
    """Seller will not go below 80% of the list price."""
    return max(1, list_price * 80 // 100)

SKILL_MD = """# Selling agents - onboarding for buyer agents
1. GET /.well-known/agents.json -> agent cards (capability, price, endpoint)
2. POST {endpoint}/tasks with a TaskSpec -> HTTP 402 + PaymentRequired quote
3. Optional: POST {endpoint}/quotes/{quote_id}/counter with an offer, at most 3 rounds
4. Hold the quoted amount at the clearing house: POST /escrow/hold -> PaymentReceipt
5. Repeat step 2 with header X-Payment: base64(PaymentReceipt JSON) -> Deliverable
6. Verify against quote.acceptance; accept or dispute at the clearing house.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or load_settings()
    app = FastAPI(title="AgentLedger sellers")
    quotes: dict[str, PaymentRequired] = {}
    floors: dict[str, int] = {}
    redeemed: set[str] = set()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/SKILL.md", response_class=PlainTextResponse)
    def skill() -> str:
        return SKILL_MD

    @app.get("/.well-known/agents.json")
    def agent_cards() -> list[AgentCard]:
        return [
            AgentCard(agent_id=sp.agent_id, name=sp.name, owner=sp.owner, capability=sp.capability,
                      endpoint=f"{s.seller_public_url}/agents/{sp.agent_id}", price_minor=sp.price_minor,
                      description=sp.description)
            for sp in SELLERS.values()
        ]

    @app.post("/agents/{agent_id}/tasks", response_model=None)
    def task(agent_id: str, spec: TaskSpec, x_payment: str | None = Header(default=None)) -> JSONResponse | Deliverable:
        seller = SELLERS.get(agent_id)
        if seller is None:
            raise HTTPException(404, f"unknown agent {agent_id}")
        if spec.capability != seller.capability:
            raise HTTPException(422, f"{agent_id} sells {seller.capability}, not {spec.capability}")

        if x_payment is None:  # step 1: quote
            spec = spec.model_copy(update={"as_of": spec.as_of or date.today()})
            quote = PaymentRequired(quote_id=new_id("q"), seller_agent_id=agent_id, amount_minor=seller.price_minor,
                                    expires_at=datetime.now(UTC) + QUOTE_TTL, task=spec, acceptance=seller.acceptance)
            quotes[quote.quote_id] = quote
            floors[quote.quote_id] = floor_minor(seller.price_minor)
            return JSONResponse(status_code=402, content=quote.model_dump(mode="json"))

        # step 2: paid request
        try:
            receipt = receipts.from_header(x_payment)
        except Exception as exc:
            raise HTTPException(400, "malformed X-Payment header") from exc
        quote = quotes.get(receipt.quote_id)
        if not receipts.verify(s.payment_secret, receipt):
            raise HTTPException(402, "invalid payment signature")
        if quote is None or quote.seller_agent_id != agent_id or receipt.amount_minor != quote.amount_minor:
            raise HTTPException(402, "receipt does not match a quote issued by this agent")
        if receipt.quote_id in redeemed:
            raise HTTPException(409, "receipt already redeemed")
        redeemed.add(receipt.quote_id)

        task_spec = quote.task  # execute what was quoted, not what the body says now
        rows = frame_to_rows(seller.produce(task_spec))
        content_hash = canonical_hash(rows)
        return Deliverable(
            order_id=receipt.order_id, seller_agent_id=agent_id, capability=seller.capability,
            symbol=task_spec.symbol, as_of=task_spec.as_of or date.today(),
            columns=list(rows[0].keys()) if rows else [], rows=rows, content_hash=content_hash,
            content_signature=receipts.sign_content(s.payment_secret, agent_id, content_hash),
            meta={"seller": seller.name, "model": seller.description},
        )

    @app.post("/agents/{agent_id}/quotes/{quote_id}/counter", response_model=None)
    def counter(agent_id: str, quote_id: str, offer: CounterOffer) -> JSONResponse:
        """Buyer counter-offer. At most 3 rounds. The seller never goes below its floor."""
        quote = quotes.get(quote_id)
        if quote is None or quote.seller_agent_id != agent_id:
            raise HTTPException(404, "unknown quote")
        if quote_id in redeemed:
            raise HTTPException(409, "quote already redeemed")
        if quote.negotiation_round >= MAX_COUNTERS:
            raise HTTPException(409, "negotiation closed after 3 rounds")
        floor = floors[quote_id]
        quote.negotiation_round += 1
        if offer.amount_minor >= quote.amount_minor or offer.amount_minor >= floor:
            if offer.amount_minor < quote.amount_minor:
                quote.amount_minor = offer.amount_minor
            quotes[quote_id] = quote
            return JSONResponse(status_code=200, content=quote.model_dump(mode="json"))
        if quote.negotiation_round == MAX_COUNTERS:
            quote.amount_minor = floor
        else:
            quote.amount_minor = max(floor, (quote.amount_minor + floor) // 2)
        quotes[quote_id] = quote
        return JSONResponse(status_code=402, content=quote.model_dump(mode="json"))

    return app
