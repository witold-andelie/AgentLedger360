from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage  # noqa: E402
from scripted_llm import BuyerBrain, GuardianBrain, ScriptedChatModel  # noqa: E402

from agentledger.agents import accounting, guardian  # noqa: E402
from agentledger.analytics import pipeline  # noqa: E402
from agentledger.config import load_settings  # noqa: E402
from agentledger.contracts import (  # noqa: E402
    AgentCard,
    Capability,
    Deliverable,
    DeliveryNotice,
    DisputeDecision,
    DisputeRequest,
    GuardianRuling,
    HoldRequest,
    PaymentRequired,
    TaskSpec,
    canonical_hash,
)
from agentledger.db import connect, transaction  # noqa: E402
from agentledger.economy import disputes, escrow, ledger, receipts, registry  # noqa: E402
from agentledger.runner import Market  # noqa: E402
from agentledger.sellers.catalog import SELLERS, frame_to_rows  # noqa: E402

AS_OF = date(2026, 10, 7)


def test_price_table_and_micro_usd_cost(monkeypatch):
    assert accounting.price_for("mistral-medium-latest").input_per_m == 1.5
    assert accounting.price_for("claude-opus-5-5").output_per_m == 20.0
    assert accounting.price_for("some-unknown-model") is None
    price = accounting.price_for("claude-haiku-5-5")
    assert accounting.cost_micro_usd(price, 1_000_000, 0) == 100_000  # $0.10 per 1M input tokens
    monkeypatch.setenv("AL_LLM_PRICE_IN", "2")
    monkeypatch.setenv("AL_LLM_PRICE_OUT", "8")
    override = accounting.price_for("anything", load_settings())
    assert accounting.cost_micro_usd(override, 1000, 100) == 2_800
    msg = AIMessage(content="x", usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10})
    assert accounting.usage_from_message(msg) == (7, 3)


def test_llm_buyer_agent_runs_the_protocol_and_meters_every_call():
    market = Market.in_process(load_settings())
    market.mode = "llm"
    market.model = ScriptedChatModel(brain=BuyerBrain(["AAPL", "NVDA"]))
    purchases = market.run_round(["AAPL", "NVDA"], AS_OF)

    trail = [(p.task.symbol, p.seller.agent_id, p.status) for p in purchases]
    assert trail == [  # cheapest first, disputed; retry once; then learns to skip both failed sellers
        ("AAPL", "sig-hype", "REFUND_FULL"),
        ("AAPL", "sig-rsi", "REFUND_PARTIAL"),
        ("NVDA", "sig-momentum", "COMPLETED"),
    ]

    run = market.last_run
    assert run is not None and run.status == "completed" and run.role == "buyer"
    llm_steps = [s for s in run.steps if s.kind == "llm"]
    assert run.llm_calls == len(llm_steps) >= 3
    assert run.cost_micro_usd == sum(s.cost_micro_usd for s in llm_steps) == run.llm_calls * 2_400
    assert any(s.kind == "policy" and s.name == "grounding" for s in run.steps)  # hallucinated id dropped
    assert "ord_deadbeef0000" not in run.summary

    conn = connect()
    stored = conn.execute("SELECT llm_calls, cost_micro_usd FROM agent_runs WHERE run_id = ?",
                          (run.run_id,)).fetchone()
    assert (stored["llm_calls"], stored["cost_micro_usd"]) == (run.llm_calls, run.cost_micro_usd)
    results = pipeline.run(conn)
    assert all(r["status"] == "success" for r in results)
    assert conn.execute("SELECT COUNT(*) FROM analytics.dq_results WHERE passed = 0").fetchone()[0] == 0
    ai = conn.execute("SELECT SUM(cost_micro_usd) FROM analytics.fact_llm_calls").fetchone()[0]
    assert ai == run.cost_micro_usd


def _disputed_rsi_order(conn):
    """A delivered sig-rsi order whose data fails only performance checks (partial-refund band)."""
    spec = SELLERS["sig-rsi"]
    with transaction(conn):
        registry.register_seller(conn, spec_card(spec))
        registry.register_buyer(conn, "b1", "B", "o")
        ledger.fund(conn, "b1", 1_000)
    task = TaskSpec(capability=Capability.SIGNAL_5D, symbol="MSFT", as_of=AS_OF)
    quote = PaymentRequired(quote_id="q-rsi", seller_agent_id="sig-rsi", amount_minor=120,
                            expires_at=datetime.now(UTC) + timedelta(minutes=5), task=task,
                            acceptance=spec.acceptance)
    s = load_settings()
    with transaction(conn):
        receipt = escrow.hold(conn, HoldRequest(buyer_agent_id="b1", quote=quote, idempotency_key="k-rsi"),
                              s.payment_secret)
    rows = frame_to_rows(spec.produce(task))
    h = canonical_hash(rows)
    with transaction(conn):
        escrow.mark_delivered(conn, receipt.order_id, DeliveryNotice(
            content_hash=h, content_signature=receipts.sign_content(s.payment_secret, "sig-rsi", h), latency_ms=3),
            s.payment_secret)
    deliverable = Deliverable(order_id=receipt.order_id, seller_agent_id="sig-rsi", capability=Capability.SIGNAL_5D,
                              symbol="MSFT", as_of=AS_OF, columns=list(rows[0]), rows=rows, content_hash=h)
    return DisputeRequest(order_id=receipt.order_id, reason="hit rate too low", deliverable=deliverable)


def spec_card(spec):
    return AgentCard(agent_id=spec.agent_id, name=spec.name, owner=spec.owner, capability=spec.capability,
                     endpoint=f"inproc://sellers/agents/{spec.agent_id}", price_minor=spec.price_minor)


def test_guardian_agent_ruling_is_validated_then_executed(conn):
    req = _disputed_rsi_order(conn)
    # first proposal (90%) is outside the 25-75% band -> rejected by the tool; second (40%) accepted
    ruling, run = guardian.investigate(load_settings(), req, model=ScriptedChatModel(brain=GuardianBrain([90, 40])))
    assert ruling is not None and ruling.refund_pct == 40 and ruling.source == "guardian-llm"
    assert any(s.name == "submit_ruling" and "rejected by policy" in s.detail["result"] for s in run.steps)
    with transaction(conn):
        outcome = disputes.open_and_resolve(conn, req, 200, ruling, run.run_id)
    assert outcome.decision is DisputeDecision.REFUND_PARTIAL
    assert outcome.refund_minor == 48  # 40% of $1.20
    assert outcome.ruling_source == "guardian-llm"


def test_out_of_band_ruling_falls_back_to_rule_table(conn):
    req = _disputed_rsi_order(conn)
    rogue = GuardianRuling(decision=DisputeDecision.REFUND_FULL, refund_pct=100, rationale="I feel generous",
                           cited_checks=["hit_rate"], source="guardian-llm")
    with transaction(conn):
        outcome = disputes.open_and_resolve(conn, req, 200, rogue, None)
    assert outcome.decision is DisputeDecision.REFUND_PARTIAL
    assert outcome.refund_minor == 60  # rule default 50%
    assert outcome.ruling_source == "rule-table" and "rejected" in outcome.rationale
