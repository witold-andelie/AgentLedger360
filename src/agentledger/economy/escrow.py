"""Order lifecycle + escrow. Every function expects to run inside db.transaction(conn).

FUNDS_HELD -> DELIVERED -> COMPLETED
                        -> DISPUTED -> COMPLETED | REFUNDED | PARTIALLY_REFUNDED
FUNDS_HELD -> CANCELLED (expire_undelivered refunds orders never delivered)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from agentledger.contracts import (
    DeliveryNotice,
    EventType,
    HoldRequest,
    OrderStatus,
    OrderView,
    PaymentReceipt,
    QualityReport,
)
from agentledger.db import emit_event, new_id, now_iso
from agentledger.economy import DomainError, ledger, receipts, registry
from agentledger.economy.rails import current_rail

S = OrderStatus


def get_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise DomainError(f"unknown order {order_id}", 404)
    return row


def to_view(row: sqlite3.Row) -> OrderView:
    return OrderView(**{k: row[k] for k in OrderView.model_fields})


def _event_base(row: sqlite3.Row) -> dict[str, Any]:
    keys = ("order_id", "buyer_agent_id", "seller_agent_id", "capability", "symbol", "amount_minor")
    return {k: row[k] for k in keys}


def _transition(conn: sqlite3.Connection, order_id: str, allowed_from: set[OrderStatus], to: OrderStatus,
                **extra: Any) -> sqlite3.Row:
    """Compare-and-set on status: a second settle/refund of the same order finds 0 rows and fails."""
    sets = ", ".join(["status = ?"] + [f"{k} = ?" for k in extra])
    placeholders = ",".join("?" * len(allowed_from))
    cur = conn.execute(
        f"UPDATE orders SET {sets} WHERE order_id = ? AND status IN ({placeholders})",
        (str(to), *extra.values(), order_id, *map(str, allowed_from)),
    )
    if cur.rowcount != 1:
        current = get_order(conn, order_id)["status"]
        raise DomainError(f"order {order_id}: illegal transition {current} -> {to}")
    return get_order(conn, order_id)


def hold(conn: sqlite3.Connection, req: HoldRequest, secret: str) -> PaymentReceipt:
    q = req.quote
    existing = conn.execute("SELECT * FROM orders WHERE idempotency_key = ?", (req.idempotency_key,)).fetchone()
    if existing is not None:  # idempotent retry: same receipt, no second debit
        return _receipt(existing, secret)
    if q.expires_at < datetime.now(UTC):
        raise DomainError("quote expired", 410)

    wallet = conn.execute(
        "SELECT * FROM wallets WHERE owner_agent_id = ? AND kind = 'agent'", (req.buyer_agent_id,)
    ).fetchone()
    if wallet is None:
        raise DomainError(f"buyer {req.buyer_agent_id} has no wallet", 404)
    if wallet["max_per_order_minor"] is not None and q.amount_minor > wallet["max_per_order_minor"]:
        raise DomainError("spend mandate: amount exceeds max per order", 403)
    if wallet["daily_limit_minor"] is not None and (
        ledger.spent_today(conn, wallet["wallet_id"]) + q.amount_minor > wallet["daily_limit_minor"]
    ):
        raise DomainError("spend mandate: daily limit reached", 403)

    order_id = new_id("ord")
    conn.execute(
        "INSERT INTO orders (order_id, quote_id, idempotency_key, buyer_agent_id, seller_agent_id, capability,"
        " symbol, amount_minor, acceptance_json, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (order_id, q.quote_id, req.idempotency_key, req.buyer_agent_id, q.seller_agent_id, str(q.task.capability),
         q.task.symbol, q.amount_minor, q.acceptance.model_dump_json(), str(S.FUNDS_HELD), now_iso()),
    )
    current_rail().hold(conn, order_id, wallet["wallet_id"], q.amount_minor)
    row = get_order(conn, order_id)
    emit_event(conn, EventType.PAYMENT_HELD, order_id, {**_event_base(row), "status": str(S.FUNDS_HELD)})
    return _receipt(row, secret)


def _receipt(row: sqlite3.Row, secret: str) -> PaymentReceipt:
    sig = receipts.sign(secret, row["order_id"], row["quote_id"], row["buyer_agent_id"],
                        row["seller_agent_id"], row["amount_minor"])
    return PaymentReceipt(order_id=row["order_id"], quote_id=row["quote_id"], buyer_agent_id=row["buyer_agent_id"],
                          seller_agent_id=row["seller_agent_id"], amount_minor=row["amount_minor"], signature=sig)


def mark_delivered(conn: sqlite3.Connection, order_id: str, notice: DeliveryNotice, secret: str) -> OrderView:
    seller_agent_id = get_order(conn, order_id)["seller_agent_id"]
    if not receipts.verify_content(secret, seller_agent_id, notice.content_hash, notice.content_signature):
        raise DomainError("delivery signature rejected", 403)
    row = _transition(conn, order_id, {S.FUNDS_HELD}, S.DELIVERED, content_hash=notice.content_hash,
                      latency_ms=notice.latency_ms, delivered_at=now_iso())
    emit_event(conn, EventType.ORDER_DELIVERED, order_id,
               {**_event_base(row), "status": str(S.DELIVERED), "latency_ms": notice.latency_ms})
    return to_view(row)


def _pay_seller(conn: sqlite3.Connection, row: sqlite3.Row, amount_minor: int, fee_bps: int) -> int:
    seller_wallet = ledger.wallet_id_for(row["seller_agent_id"])
    return current_rail().capture(conn, row["order_id"], seller_wallet, amount_minor, fee_bps)


def expire_undelivered(conn: sqlite3.Connection, older_than_seconds: int) -> list[OrderView]:
    """Full refund of FUNDS_HELD orders strictly older than the TTL. Not escrow.refund (DISPUTED only)."""
    cutoff = (datetime.now(UTC) - timedelta(seconds=older_than_seconds)).isoformat(timespec="milliseconds")
    pending = conn.execute(
        "SELECT order_id FROM orders WHERE status = ? AND created_at < ?",
        (str(S.FUNDS_HELD), cutoff),
    ).fetchall()
    cancelled: list[OrderView] = []
    for item in pending:
        row = get_order(conn, item["order_id"])
        if row["status"] != str(S.FUNDS_HELD):
            continue
        amount = int(row["amount_minor"])
        row = _transition(conn, row["order_id"], {S.FUNDS_HELD}, S.CANCELLED,
                          refunded_minor=amount, closed_at=now_iso())
        buyer_wallet = ledger.wallet_id_for(row["buyer_agent_id"])
        current_rail().release(conn, row["order_id"], buyer_wallet, amount)
        emit_event(
            conn, EventType.PAYMENT_REFUNDED, row["order_id"],
            {**_event_base(row), "status": str(S.CANCELLED), "refunded_minor": amount, "fee_minor": 0},
        )
        registry.record_outcome(conn, row["seller_agent_id"], success=False)
        cancelled.append(to_view(row))
    return cancelled


def settle(conn: sqlite3.Connection, order_id: str, report: QualityReport | None, fee_bps: int) -> OrderView:
    row = _transition(conn, order_id, {S.DELIVERED, S.DISPUTED}, S.COMPLETED, closed_at=now_iso())
    fee = _pay_seller(conn, row, row["amount_minor"], fee_bps)
    metrics = report.metrics if report else {}
    emit_event(conn, EventType.PAYMENT_SETTLED, order_id,
               {**_event_base(row), "status": str(S.COMPLETED), "settled_minor": row["amount_minor"],
                "fee_minor": fee, **metrics})
    registry.record_outcome(conn, row["seller_agent_id"], success=True)
    return to_view(row)


def refund(conn: sqlite3.Connection, order_id: str, refund_minor: int, fee_bps: int,
           metrics: dict[str, float] | None = None) -> OrderView:
    row = get_order(conn, order_id)
    if not 0 < refund_minor <= row["amount_minor"]:
        raise DomainError("refund must be within (0, amount]", 422)
    full = refund_minor == row["amount_minor"]
    row = _transition(conn, order_id, {S.DISPUTED}, S.REFUNDED if full else S.PARTIALLY_REFUNDED,
                      refunded_minor=refund_minor, closed_at=now_iso())
    buyer_wallet = ledger.wallet_id_for(row["buyer_agent_id"])
    seller_wallet = ledger.wallet_id_for(row["seller_agent_id"])
    fee = current_rail().refund(
        conn, order_id, buyer_wallet, seller_wallet, refund_minor, int(row["amount_minor"]), fee_bps,
    )
    emit_event(conn, EventType.PAYMENT_REFUNDED, order_id,
               {**_event_base(row), "status": row["status"], "refunded_minor": refund_minor, "fee_minor": fee,
                **(metrics or {})})
    registry.record_outcome(conn, row["seller_agent_id"], success=False)
    return to_view(row)
