from agentledger.contracts import PaymentReceipt
from agentledger.economy import receipts

SECRET = "test-secret"


def test_receipt_verifies_with_the_public_key_only():
    signature = receipts.sign(SECRET, "ord1", "q1", "buyer", "seller", 150)
    receipt = PaymentReceipt(
        order_id="ord1", quote_id="q1", buyer_agent_id="buyer", seller_agent_id="seller",
        amount_minor=150, signature=signature,
    )
    public = receipts.receipt_public_b64(SECRET)
    assert receipts.verify_public(public, receipt)
    forged = receipt.model_copy(update={"amount_minor": 1})
    assert not receipts.verify_public(public, forged)


def test_delivery_signature_is_per_seller():
    signature = receipts.sign_content(SECRET, "sig-rsi", "abc")
    assert receipts.verify_content_public(receipts.content_public_b64(SECRET, "sig-rsi"), "abc", signature)
    assert not receipts.verify_content_public(receipts.content_public_b64(SECRET, "sig-hype"), "abc", signature)
