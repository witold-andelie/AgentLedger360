from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from agentledger.contracts import (
    AcceptanceCriteria,
    AgentCard,
    Capability,
    DeliveryNotice,
    HoldRequest,
    OrderStatus,
    PaymentRequired,
    TaskSpec,
)
from agentledger.db import transaction
from agentledger.economy import DomainError, escrow, ledger, receipts, registry

SECRET = "test-secret"


def _setup(conn, funding=1_000, max_per_order=None):
    with transaction(conn):
        registry.register_seller(conn, AgentCard(agent_id="s1", name="S", owner="o", capability=Capability.SIGNAL_5D,
                                                 endpoint="inproc://sellers/agents/s1", price_minor=100))
        registry.register_buyer(conn, "b1", "B", "o", max_per_order_minor=max_per_order)
        ledger.fund(conn, "b1", funding)


def _quote(amount=100, quote_id="q1", ttl=timedelta(minutes=5)):
    return PaymentRequired(quote_id=quote_id, seller_agent_id="s1", amount_minor=amount,
                           expires_at=datetime.now(UTC) + ttl, task=TaskSpec(capability=Capability.SIGNAL_5D,
                                                                               symbol="AAPL"),
                           acceptance=AcceptanceCriteria(required_columns=["date"]))


def _hold(conn, quote, key="k1"):
    with transaction(conn):
        return escrow.hold(conn, HoldRequest(buyer_agent_id="b1", quote=quote, idempotency_key=key), SECRET)


def _notice(content_hash="h", latency_ms=5, seller="s1", secret=SECRET):
    return DeliveryNotice(
        content_hash=content_hash,
        content_signature=receipts.sign_content(secret, seller, content_hash),
        latency_ms=latency_ms,
    )


def test_hold_is_idempotent_and_receipt_verifies(conn):
    _setup(conn)
    r1 = _hold(conn, _quote())
    r2 = _hold(conn, _quote())
    assert r1.order_id == r2.order_id
    assert receipts.verify(SECRET, r1)
    assert ledger.balance(conn, ledger.wallet_id_for("b1")) == 900
    assert ledger.balance(conn, ledger.ESCROW) == 100


def test_settle_pays_seller_minus_fee_and_cannot_repeat(conn):
    _setup(conn)
    r = _hold(conn, _quote())
    with transaction(conn):
        escrow.mark_delivered(conn, r.order_id, _notice(), SECRET)
        escrow.settle(conn, r.order_id, None, fee_bps=200)
    assert ledger.balance(conn, ledger.wallet_id_for("s1")) == 98
    assert ledger.balance(conn, ledger.FEES) == 2
    with pytest.raises(DomainError), transaction(conn):
        escrow.settle(conn, r.order_id, None, fee_bps=200)
    assert ledger.balance(conn, ledger.wallet_id_for("s1")) == 98  # rolled back, no double pay


def test_insufficient_funds_and_mandate_are_enforced(conn):
    _setup(conn, funding=50, max_per_order=80)
    with pytest.raises(DomainError) as exc:
        _hold(conn, _quote(amount=100))
    assert exc.value.status == 403  # mandate checked before balance
    with pytest.raises(DomainError) as exc:
        _hold(conn, _quote(amount=60, quote_id="q2"), key="k2")
    assert exc.value.status == 402
    assert ledger.balance(conn, ledger.wallet_id_for("b1")) == 50


def test_expired_quote_rejected(conn):
    _setup(conn)
    with pytest.raises(DomainError):
        _hold(conn, _quote(ttl=timedelta(seconds=-1)))


def test_reputation_moves_with_outcomes(conn):
    _setup(conn)
    with transaction(conn):
        assert registry.record_outcome(conn, "s1", success=False) == pytest.approx(1 / 3)
        assert registry.record_outcome(conn, "s1", success=True) == pytest.approx(2 / 4)


def test_fresh_funds_held_order_is_not_cancelled(conn):
    _setup(conn)
    receipt = _hold(conn, _quote())
    with transaction(conn):
        cancelled = escrow.expire_undelivered(conn, older_than_seconds=86_400)
    assert cancelled == []
    status = conn.execute("SELECT status FROM orders WHERE order_id = ?", (receipt.order_id,)).fetchone()["status"]
    assert status == "FUNDS_HELD"
    assert ledger.balance(conn, ledger.wallet_id_for("b1")) == 900
    assert ledger.balance(conn, ledger.ESCROW) == 100


def test_expired_undelivered_order_is_refunded_once(conn):
    _setup(conn)
    receipt = _hold(conn, _quote())
    conn.execute(
        "UPDATE orders SET created_at = ? WHERE order_id = ?",
        ("2020-01-01T00:00:00.000+00:00", receipt.order_id),
    )
    with transaction(conn):
        cancelled = escrow.expire_undelivered(conn, older_than_seconds=300)
    assert len(cancelled) == 1
    assert cancelled[0].order_id == receipt.order_id
    assert cancelled[0].status == OrderStatus.CANCELLED
    assert cancelled[0].refunded_minor == 100
    row = conn.execute(
        "SELECT status, refunded_minor, delivered_at, closed_at FROM orders WHERE order_id = ?",
        (receipt.order_id,),
    ).fetchone()
    assert row["status"] == "CANCELLED"
    assert row["refunded_minor"] == 100
    assert row["delivered_at"] is None
    assert row["closed_at"]
    assert ledger.balance(conn, ledger.wallet_id_for("b1")) == 1_000
    assert ledger.balance(conn, ledger.ESCROW) == 0
    assert conn.execute("SELECT COALESCE(SUM(amount_minor), 0) FROM ledger_entries").fetchone()[0] == 0
    payload = json.loads(conn.execute(
        "SELECT payload_json FROM outbox WHERE aggregate_id = ? AND event_type = 'payment.refunded'",
        (receipt.order_id,),
    ).fetchone()["payload_json"])
    assert payload["status"] == "CANCELLED"
    assert payload["refunded_minor"] == 100
    assert payload["fee_minor"] == 0
    assert payload["buyer_agent_id"] == "b1"
    rep = conn.execute("SELECT reputation, orders_ok FROM agents WHERE agent_id = 's1'").fetchone()
    assert rep["orders_ok"] == 0
    assert rep["reputation"] == pytest.approx(1 / 3)
    entries = conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    with transaction(conn):
        again = escrow.expire_undelivered(conn, older_than_seconds=300)
    assert again == []
    assert conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == entries
    assert ledger.balance(conn, ledger.wallet_id_for("b1")) == 1_000
    assert ledger.balance(conn, ledger.ESCROW) == 0
    assert conn.execute("SELECT COALESCE(SUM(amount_minor), 0) FROM ledger_entries").fetchone()[0] == 0


def test_mark_delivered_rejects_bad_signature_and_settle_accepts_good_one(conn):
    _setup(conn)
    receipt = _hold(conn, _quote())
    bad_notices = [
        DeliveryNotice(content_hash="h", latency_ms=5),
        DeliveryNotice(content_hash="h", content_signature=receipts.sign_content(SECRET, "s1", "other"), latency_ms=5),
        DeliveryNotice(content_hash="h", content_signature=receipts.sign_content(SECRET, "other", "h"), latency_ms=5),
    ]
    for notice in bad_notices:
        with pytest.raises(DomainError) as exc, transaction(conn):
            escrow.mark_delivered(conn, receipt.order_id, notice, SECRET)
        assert exc.value.status == 403
        status = conn.execute("SELECT status FROM orders WHERE order_id = ?", (receipt.order_id,)).fetchone()["status"]
        assert status == "FUNDS_HELD"
    assert ledger.balance(conn, ledger.ESCROW) == 100
    with transaction(conn):
        delivered = escrow.mark_delivered(conn, receipt.order_id, _notice(), SECRET)
        settled = escrow.settle(conn, receipt.order_id, None, fee_bps=200)
    assert delivered.status == OrderStatus.DELIVERED
    assert settled.status == OrderStatus.COMPLETED
    assert ledger.balance(conn, ledger.wallet_id_for("s1")) == 98
    assert ledger.balance(conn, ledger.FEES) == 2
    assert ledger.balance(conn, ledger.ESCROW) == 0
