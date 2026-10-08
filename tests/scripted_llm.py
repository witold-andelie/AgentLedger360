"""Scripted chat model for agent tests: a deterministic 'brain' drives the real LangGraph agents through the
real tools, with realistic token usage, so tests are offline, free and repeatable."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

USAGE = {"input_tokens": 1200, "output_tokens": 80, "total_tokens": 1280}


class ScriptedChatModel(BaseChatModel):
    brain: Any

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.brain(messages))])


def say(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata=dict(USAGE))


def call(name: str, args: dict[str, Any], n: int) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call{n:05d}"}],
                     usage_metadata=dict(USAGE))


class Brain:
    """Phase routing shared by both brains: plan prompt, reflect prompt, otherwise one tool step."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self, messages: list[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, HumanMessage) and "Stopped because" in str(last.content):
            return say(self.report())  # reflect node
        if isinstance(last, HumanMessage) and "Your plan:" not in str(last.content):
            return say("1. look around 2. act 3. report")  # plan node (react starts with 'Your plan:')
        if isinstance(last, ToolMessage):
            self.observe(last.name or "", str(last.content))
        self.n += 1
        action = self.next_action()
        return say("done") if action is None else call(action[0], action[1], self.n)

    def observe(self, tool: str, content: str) -> None: ...

    def next_action(self) -> tuple[str, dict[str, Any]] | None: ...

    def report(self) -> str:
        return "done"


class BuyerBrain(Brain):
    """Buys each symbol from the best-ranked seller it has not seen fail in this run; disputes failures and
    retries a symbol once with another seller."""

    def __init__(self, symbols: list[str]) -> None:
        super().__init__()
        self.todo = list(symbols)
        self.sellers: list[str] = []
        self.failed: set[str] = set()  # sellers that failed in this run, for any symbol
        self.queue: list[tuple[str, dict[str, Any]]] = [("check_wallet", {}), ("search_sellers",
                                                                             {"max_price_usd": 5.0})]
        self.orders: list[str] = []
        self.attempts: dict[str, int] = {}

    def _start(self, symbol: str) -> None:
        seller = next(s for s in self.sellers if s not in self.failed)
        self.current = (symbol, seller)
        self.attempts[symbol] = self.attempts.get(symbol, 0) + 1
        self.queue.append(("request_quote", {"seller_id": seller, "symbol": symbol}))

    def observe(self, tool: str, content: str) -> None:
        data = json.loads(content) if content.startswith(("{", "[")) else {}
        if tool == "search_sellers":
            self.sellers = [s["seller_id"] for s in data]
            if self.todo:
                self._start(self.todo.pop(0))
        elif tool == "request_quote":
            self.queue.append(("buy", {"quote_id": data["quote_id"]}))
        elif tool == "buy":
            self.orders.append(data["order_id"])
            self.queue.append(("verify_delivery", {"order_id": data["order_id"]}))
        elif tool == "verify_delivery":
            if data["passed"]:
                self.queue.append(("accept_delivery", {"order_id": data["order_id"]}))
            else:
                failed = [c["name"] for c in data["checks"] if not c["passed"]]
                self.queue.append(("open_dispute", {"order_id": data["order_id"], "reason": f"failed {failed}"}))
        elif tool in ("accept_delivery", "open_dispute"):
            symbol, seller = self.current
            if tool == "open_dispute":
                self.failed.add(seller)
            if tool == "open_dispute" and self.attempts[symbol] < 2:
                self._start(symbol)
            elif self.todo:
                self._start(self.todo.pop(0))

    def next_action(self) -> tuple[str, dict[str, Any]] | None:
        return self.queue.pop(0) if self.queue else None

    def report(self) -> str:
        lines = [f"order {oid}" for oid in self.orders]
        return "\n".join(lines + ["order ord_deadbeef0000 (hallucinated)", "Lesson: avoid cheap sellers."])


class GullibleBrain(Brain):
    """Trusts a seller blurb and tries to pay before running acceptance checks."""

    def __init__(self) -> None:
        super().__init__()
        self.queue: list[tuple[str, dict[str, Any]]] = [
            ("search_sellers", {"max_price_usd": 5.0}),
        ]
        self.refusal = ""

    def observe(self, tool: str, content: str) -> None:
        data = json.loads(content) if content.startswith(("{", "[")) else {}
        if tool == "search_sellers":
            seller = next(row["seller_id"] for row in data if row["seller_id"] == "sig-injector")
            self.queue.append(("request_quote", {"seller_id": seller, "symbol": "AAPL"}))
        elif tool == "request_quote":
            self.queue.append(("buy", {"quote_id": data["quote_id"]}))
        elif tool == "buy":
            self.queue.append(("accept_delivery", {"order_id": data["order_id"]}))
        elif tool == "accept_delivery":
            self.refusal = content

    def next_action(self) -> tuple[str, dict[str, Any]] | None:
        return self.queue.pop(0) if self.queue else None

    def report(self) -> str:
        return f"Tried to accept early. Tool said: {self.refusal}"


class GuardianBrain(Brain):
    """Reads the bounds, then proposes `pct` citing the failed checks (first proposal can be out of band)."""

    def __init__(self, proposals: list[int]) -> None:
        super().__init__()
        self.proposals = list(proposals)
        self.bounds: dict[str, Any] = {}
        self.queue: list[tuple[str, dict[str, Any]]] = [("get_case", {}), ("rerun_acceptance_checks", {}),
                                                        ("seller_track_record", {}), ("policy_bounds", {})]

    def observe(self, tool: str, content: str) -> None:
        if tool == "policy_bounds":
            self.bounds = json.loads(content)
        if tool in ("policy_bounds", "submit_ruling") and self.proposals and not content.startswith("accepted"):
            self.queue.append(("submit_ruling", {
                "decision": self.bounds["decision"], "refund_pct": self.proposals.pop(0),
                "rationale": "hit rate far below the contract threshold",
                "cited_checks": self.bounds["failed_checks"][:1]}))

    def next_action(self) -> tuple[str, dict[str, Any]] | None:
        return self.queue.pop(0) if self.queue else None

    def report(self) -> str:
        return "Partial refund: performance checks failed."


BrainFactory = Callable[[], Brain]
