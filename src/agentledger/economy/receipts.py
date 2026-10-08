"""Ed25519 signatures for payment receipts and delivery hashes.

Keys are derived from AL_PAYMENT_SECRET so both laptops stay in sync without copying a key file.
Verification uses only the public key. A seller that has fetched the receipt public key does not
need the secret to check X-Payment. Delivery keys are per seller (HKDF info = agent id).
"""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentledger.contracts import PaymentReceipt


def _private(secret: str, salt: bytes, info: bytes) -> Ed25519PrivateKey:
    seed = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(secret.encode())
    return Ed25519PrivateKey.from_private_bytes(seed)


def _receipt_key(secret: str) -> Ed25519PrivateKey:
    return _private(secret, b"agentledger-receipt-v1", b"receipt")


def _content_key(secret: str, seller_agent_id: str) -> Ed25519PrivateKey:
    return _private(secret, b"agentledger-delivery-v1", seller_agent_id.encode())


def _public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.urlsafe_b64encode(raw).decode()


def _public_from_b64(value: str) -> Ed25519PublicKey:
    raw = base64.urlsafe_b64decode(value.encode())
    return Ed25519PublicKey.from_public_bytes(raw)


def _message(order_id: str, quote_id: str, buyer: str, seller: str, amount_minor: int) -> bytes:
    return f"{order_id}|{quote_id}|{buyer}|{seller}|{amount_minor}".encode()


def receipt_public_b64(secret: str) -> str:
    return _public_b64(_receipt_key(secret))


def content_public_b64(secret: str, seller_agent_id: str) -> str:
    return _public_b64(_content_key(secret, seller_agent_id))


def sign(secret: str, order_id: str, quote_id: str, buyer: str, seller: str, amount_minor: int) -> str:
    signature = _receipt_key(secret).sign(_message(order_id, quote_id, buyer, seller, amount_minor))
    return base64.urlsafe_b64encode(signature).decode()


def verify(secret: str, receipt: PaymentReceipt) -> bool:
    return verify_public(receipt_public_b64(secret), receipt)


def verify_public(public_b64: str, receipt: PaymentReceipt) -> bool:
    try:
        _public_from_b64(public_b64).verify(
            base64.urlsafe_b64decode(receipt.signature.encode()),
            _message(receipt.order_id, receipt.quote_id, receipt.buyer_agent_id,
                     receipt.seller_agent_id, receipt.amount_minor),
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def sign_content(secret: str, seller_agent_id: str, content_hash: str) -> str:
    signature = _content_key(secret, seller_agent_id).sign(content_hash.encode())
    return base64.urlsafe_b64encode(signature).decode()


def verify_content(secret: str, seller_agent_id: str, content_hash: str, signature: str) -> bool:
    return verify_content_public(content_public_b64(secret, seller_agent_id), content_hash, signature)


def verify_content_public(public_b64: str, content_hash: str, signature: str) -> bool:
    try:
        _public_from_b64(public_b64).verify(base64.urlsafe_b64decode(signature.encode()), content_hash.encode())
    except (InvalidSignature, ValueError):
        return False
    return True


def to_header(receipt: PaymentReceipt) -> str:
    return base64.urlsafe_b64encode(receipt.model_dump_json().encode()).decode()


def from_header(value: str) -> PaymentReceipt:
    return PaymentReceipt.model_validate_json(base64.urlsafe_b64decode(value.encode()))
