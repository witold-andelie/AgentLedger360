"""The market loop shared by the CLI demo and the web server: bootstrap (crawl agent cards, open the
buyer wallet) once, then run rounds. With an LLM configured the round is one run of the LangGraph
procurement agent (agents/buyer_agent.py); otherwise the deterministic rule buyer (agents/buyer.py).
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI

from agentledger.agents.buyer import BuyerAgent, Purchase
from agentledger.agents.llm import resolve_mode
from agentledger.config import Settings, load_settings
from agentledger.contracts import AgentRunReport, BuyerSignup, Capability, TaskSpec
from agentledger.transport import Router

BUYER = BuyerSignup(agent_id="pm-alpha", name="PortfolioManagerAlpha", owner="demo-fund",
                    initial_funding_minor=3_000, max_per_order_minor=500, daily_limit_minor=2_500)


class Market:
    def __init__(self, router: Router, platform_url: str, seller_url: str, settings: Settings | None = None) -> None:
        self.router = router
        self.platform_url = platform_url
        self.seller_url = seller_url
        self.settings = settings or load_settings()
        self.mode = resolve_mode(self.settings)  # "llm" | "rule"
        self.model: Any = None  # tests inject a scripted chat model here
        self.buyer = BuyerAgent(BUYER.agent_id, router, platform_url)
        self.last_run: AgentRunReport | None = None
        self.operator_token = ""  # sent only by bootstrap; not returned by any API
        self._lock = threading.Lock()  # one round at a time
        self._ready = False

    @classmethod
    def in_process(cls, settings: Settings, platform: FastAPI | None = None,
                   sellers: FastAPI | None = None, operator_token: str = "",
                   gate: Any = None) -> Market:
        """Platform always in-process; sellers in-process unless AL_SELLER_URL points at a remote service."""
        from agentledger.governance import Capabilities, CapabilityGate
        from agentledger.platform_api import create_app as platform_app
        from agentledger.sellers.app import create_app as seller_app

        token = operator_token or settings.admin_token or secrets.token_urlsafe(24)
        if gate is None:
            gate = CapabilityGate(Capabilities.from_env())
        router = Router()
        # Build the platform after the router so /orders/{id}/fetch can call the sellers in-process.
        built = platform or platform_app(settings, operator_token=token, gate=gate, router=router)
        platform_url = router.mount("platform", built)
        seller_url = settings.seller_url or router.mount("sellers", sellers or seller_app(settings))
        market = cls(router, platform_url, seller_url.rstrip("/"), settings)
        market.operator_token = token
        market.platform = built
        return market

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the round lock without waiting (demo reset); RuntimeError if a round is running."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("a round is running")
        try:
            yield
        finally:
            self._lock.release()

    def forget_bootstrap(self) -> None:
        self._ready = False
        self.last_run = None

    def bootstrap(self) -> int:
        """Idempotent: re-registering cards is an upsert and the buyer is funded only once."""
        cards = self.router.get(f"{self.seller_url}/.well-known/agents.json").json()
        for card in cards:
            self.router.post(f"{self.platform_url}/registry/sellers", json=card).raise_for_status()
        funded = self.router.post(
            f"{self.platform_url}/registry/buyers", json=BUYER.model_dump(),
            headers={"X-Admin-Token": self.operator_token},
        )
        funded.raise_for_status()
        agent_key = funded.json().get("agent_key")
        if agent_key:
            self.buyer.agent_key = agent_key
        self._ready = True
        return len(cards)

    def run_round(self, symbols: list[str], as_of: date | None = None,
                  on_start: Callable[[str], None] | None = None, force_rule: bool = False) -> list[Purchase]:
        with self._lock:
            if not self._ready:
                self.bootstrap()
            expired = self.router.post(f"{self.platform_url}/orders/expire")
            if expired.status_code != 200:
                expired.raise_for_status()
            self._verify_matured()
            self._load_policy()
            if self.mode == "llm" and not force_rule:
                purchases = self._llm_round(symbols, as_of, on_start)
            else:
                purchases = [self.buyer.acquire(TaskSpec(capability=Capability.SIGNAL_5D, symbol=s.strip().upper(),
                                                        as_of=as_of))
                             for s in symbols if s.strip()]
            self._learn()
            return purchases

    def _verify_matured(self) -> None:
        from datetime import date

        from agentledger.db import connect, transaction
        from agentledger.economy.outcomes import verify_matured

        conn = connect(self.settings)
        try:
            with transaction(conn):
                verify_matured(conn, date.today())
        finally:
            conn.close()

    def _load_policy(self) -> None:
        from agentledger.agents.learning import load_buyer_policy
        from agentledger.db import connect

        conn = connect(self.settings)
        try:
            policy = load_buyer_policy(conn, self.buyer.agent_id)
        finally:
            conn.close()
        self.buyer.price_weight = float(policy["price_weight"])

    def _learn(self) -> None:
        from agentledger.agents.learning import update_buyer_policy
        from agentledger.db import connect, transaction

        conn = connect(self.settings)
        try:
            with transaction(conn):
                policy = update_buyer_policy(conn, self.buyer.agent_id)
        finally:
            conn.close()
        self.buyer.price_weight = float(policy["price_weight"])

    def _llm_round(self, symbols: list[str], as_of: date | None,
                   on_start: Callable[[str], None] | None) -> list[Purchase]:
        from agentledger.agents.buyer_agent import run_llm_buyer  # needs the `.[agent]` extra

        purchases, report = run_llm_buyer(
            self.settings, self.router, self.platform_url, BUYER.agent_id, symbols, as_of,
            model=self.model, on_start=on_start, agent_key=self.buyer.agent_key,
        )
        touched = sum(1 for p in purchases if p.order_id)
        self.router.post(f"{self.platform_url}/telemetry/agent-runs", params={"orders_touched": touched},
                         json=report.model_dump(mode="json")).raise_for_status()
        self.last_run = report
        return purchases


def summarize(p: Purchase) -> dict[str, Any]:
    """Flat JSON view of one purchase for the CLI and the web page."""
    return {
        "symbol": p.task.symbol,
        "seller": p.seller.agent_id if p.seller else None,
        "price_minor": p.quote.amount_minor if p.quote else None,
        "status": p.status,
        "order_id": p.order_id,
        "latency_ms": p.latency_ms,
        "hit_rate": p.report.metrics.get("hit_rate") if p.report else None,
        "refund_minor": p.dispute.refund_minor if p.dispute else None,
        "rationale": p.dispute.rationale if p.dispute else None,
        "ruled_by": p.dispute.ruling_source if p.dispute else None,
        "notes": p.notes,
    }


def run_summary(report: AgentRunReport | None) -> dict[str, Any] | None:
    """Totals of one agent run for API responses (cost in integer micro-USD)."""
    if report is None:
        return None
    return report.model_dump(mode="json", exclude={"steps"})
