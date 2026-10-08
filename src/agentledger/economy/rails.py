"""Payment rail between buyer and seller.

hold authorizes (escrow), capture settles, release cancels an authorization, refund returns money.
SimulatedLedgerRail is the default and posts the local double-entry ledger.
StripeTestRail maps the same four calls onto a test-mode PaymentIntent
(capture_method=manual): authorize, capture, cancel, refund. It refuses live secret keys.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Protocol

import httpx

from agentledger.economy import DomainError, ledger

STRIPE_API = "https://api.stripe.com/v1"


class PaymentRail(Protocol):
    name: str

    def hold(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, amount_minor: int) -> None:
        """Authorize `amount_minor` from the buyer into escrow."""

    def capture(self, conn: sqlite3.Connection, order_id: str, seller_wallet: str,
                amount_minor: int, fee_bps: int) -> int:
        """Capture an authorization. Returns the platform fee in minor units."""

    def release(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, amount_minor: int) -> None:
        """Cancel an authorization and return the full amount to the buyer."""

    def refund(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, seller_wallet: str,
               refund_minor: int, amount_minor: int, fee_bps: int) -> int:
        """Return `refund_minor` to the buyer. A partial refund captures the remainder. Returns the fee."""


class SimulatedLedgerRail:
    name = "simulated"

    def hold(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, amount_minor: int) -> None:
        ledger.post(conn, [(buyer_wallet, -amount_minor), (ledger.ESCROW, amount_minor)], memo=f"hold {order_id}")

    def capture(self, conn: sqlite3.Connection, order_id: str, seller_wallet: str,
                amount_minor: int, fee_bps: int) -> int:
        fee = amount_minor * fee_bps // 10_000
        ledger.post(
            conn,
            [(ledger.ESCROW, -amount_minor), (seller_wallet, amount_minor - fee), (ledger.FEES, fee)],
            memo=f"settle {order_id}",
        )
        return fee

    def release(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, amount_minor: int) -> None:
        ledger.post(conn, [(ledger.ESCROW, -amount_minor), (buyer_wallet, amount_minor)], memo=f"cancel {order_id}")

    def refund(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, seller_wallet: str,
               refund_minor: int, amount_minor: int, fee_bps: int) -> int:
        ledger.post(conn, [(ledger.ESCROW, -refund_minor), (buyer_wallet, refund_minor)], memo=f"refund {order_id}")
        if refund_minor == amount_minor:
            return 0
        return self.capture(conn, order_id, seller_wallet, amount_minor - refund_minor, fee_bps)


class StripeTestRail:
    """Test-mode Stripe. Authorization is the escrow hold; capture settles; cancel releases."""

    name = "stripe-test"

    def __init__(self, secret: str, post: Any = None) -> None:
        if not secret.startswith("sk_test_"):
            raise DomainError("STRIPE_TEST_SECRET_KEY must be a Stripe test key (sk_test_)", 503)
        self._secret = secret
        self._post = post or _stripe_post
        self._books = SimulatedLedgerRail()

    def hold(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, amount_minor: int) -> None:
        body = self._post(self._secret, "/payment_intents", {
            "amount": amount_minor, "currency": "usd", "capture_method": "manual", "confirm": "true",
            "payment_method": "pm_card_visa",
            "automatic_payment_methods[enabled]": "true",
            "automatic_payment_methods[allow_redirects]": "never",
            "metadata[order_id]": order_id,
        })
        external_id = str(body.get("id") or "")
        if not external_id:
            raise DomainError("stripe did not return a payment intent", 502)
        conn.execute(
            "INSERT INTO payment_authorizations (order_id, external_id, rail) VALUES (?,?,?)",
            (order_id, external_id, self.name),
        )
        self._books.hold(conn, order_id, buyer_wallet, amount_minor)

    def capture(self, conn: sqlite3.Connection, order_id: str, seller_wallet: str,
                amount_minor: int, fee_bps: int) -> int:
        external_id = _external_id(conn, order_id)
        self._post(self._secret, f"/payment_intents/{external_id}/capture", {"amount_to_capture": amount_minor})
        return self._books.capture(conn, order_id, seller_wallet, amount_minor, fee_bps)

    def release(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, amount_minor: int) -> None:
        external_id = _external_id(conn, order_id)
        self._post(self._secret, f"/payment_intents/{external_id}/cancel", {})
        self._books.release(conn, order_id, buyer_wallet, amount_minor)

    def refund(self, conn: sqlite3.Connection, order_id: str, buyer_wallet: str, seller_wallet: str,
               refund_minor: int, amount_minor: int, fee_bps: int) -> int:
        external_id = _external_id(conn, order_id)
        if refund_minor == amount_minor:
            self._post(self._secret, f"/payment_intents/{external_id}/cancel", {})
        else:
            self._post(self._secret, f"/payment_intents/{external_id}/capture",
                       {"amount_to_capture": amount_minor - refund_minor})
        return self._books.refund(conn, order_id, buyer_wallet, seller_wallet, refund_minor, amount_minor, fee_bps)


def current_rail() -> PaymentRail:
    kind = os.getenv("AL_PAYMENT_RAIL", "simulated")
    if kind == "stripe-test":
        secret = os.getenv("STRIPE_TEST_SECRET_KEY", "")
        return StripeTestRail(secret)
    if kind != "simulated":
        raise DomainError(f"unknown payment rail {kind}", 503)
    return SimulatedLedgerRail()


def rail_name() -> str:
    kind = os.getenv("AL_PAYMENT_RAIL", "simulated")
    return kind if kind in ("simulated", "stripe-test") else "simulated"


def _external_id(conn: sqlite3.Connection, order_id: str) -> str:
    row = conn.execute(
        "SELECT external_id FROM payment_authorizations WHERE order_id = ?", (order_id,),
    ).fetchone()
    if row is None:
        raise DomainError(f"no stripe authorization for {order_id}", 409)
    return str(row["external_id"])


def _stripe_post(secret: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{STRIPE_API}{path}", auth=(secret, ""), data=data, timeout=20.0)
    body = response.json()
    if response.status_code >= 400:
        message = body.get("error", {}).get("message", response.text)
        raise DomainError(f"stripe: {message}", 502)
    return body
