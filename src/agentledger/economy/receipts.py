"""Signed payment receipts (the X-Payment header of the HTTP 402 flow).

The clearing house signs; sellers verify offline with the shared secret. Stretch goal: swap HMAC for
an asymmetric signature (Ed25519) so sellers need only the public key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from agentledger.contracts import PaymentReceipt


def _message(order_id: str, quote_id: str, buyer: str, seller: str, amount_minor: int) -> bytes:
    return f"{order_id}|{quote_id}|{buyer}|{seller}|{amount_minor}".encode()


def sign(secret: str, order_id: str, quote_id: str, buyer: str, seller: str, amount_minor: int) -> str:
    mac = hmac.new(secret.encode(), _message(order_id, quote_id, buyer, seller, amount_minor), hashlib.sha256)
    return mac.hexdigest()


def verify(secret: str, receipt: PaymentReceipt) -> bool:
    expected = sign(
        secret, receipt.order_id, receipt.quote_id, receipt.buyer_agent_id,
        receipt.seller_agent_id, receipt.amount_minor,
    )
    return hmac.compare_digest(expected, receipt.signature)


def sign_content(secret: str, seller_agent_id: str, content_hash: str) -> str:
    """HMAC-SHA256 of the raw content_hash. Key is HMAC(secret, 'delivery|{seller}') as hex."""
    key = hmac.new(secret.encode(), f"delivery|{seller_agent_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.new(key.encode(), content_hash.encode(), hashlib.sha256).hexdigest()


def verify_content(secret: str, seller_agent_id: str, content_hash: str, signature: str) -> bool:
    expected = sign_content(secret, seller_agent_id, content_hash)
    return hmac.compare_digest(expected, signature)


def to_header(receipt: PaymentReceipt) -> str:
    return base64.urlsafe_b64encode(receipt.model_dump_json().encode()).decode()


def from_header(value: str) -> PaymentReceipt:
    return PaymentReceipt.model_validate_json(base64.urlsafe_b64decode(value.encode()))
