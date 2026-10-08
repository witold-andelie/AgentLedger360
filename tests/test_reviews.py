from __future__ import annotations

from fastapi.testclient import TestClient
from test_agents import _disputed_rsi_order

from agentledger.contracts import DisputeDecision, GuardianRuling
from agentledger.db import transaction
from agentledger.economy import DomainError, disputes, escrow, ledger
from agentledger.server import create_app


def _edge_ruling() -> GuardianRuling:
    return GuardianRuling(
        decision=DisputeDecision.REFUND_PARTIAL, refund_pct=25, rationale="at the edge of the band",
        cited_checks=["hit_rate"], source="guardian-llm",
    )


def test_edge_ruling_waits_for_a_person_and_a_bad_ruling_does_not_move_money(conn):
    req = _disputed_rsi_order(conn)
    before = ledger.balance(conn, ledger.wallet_id_for("b1"))
    with transaction(conn):
        outcome = disputes.open_and_resolve(conn, req, 200, _edge_ruling(), None)
    assert outcome.pending_review is True
    assert escrow.get_order(conn, req.order_id)["status"] == "DISPUTED"
    assert ledger.balance(conn, ledger.wallet_id_for("b1")) == before

    rogue = GuardianRuling(
        decision=DisputeDecision.REFUND_FULL, refund_pct=100, rationale="pay them everything",
        cited_checks=["hit_rate"], source="human",
    )
    with transaction(conn):
        try:
            disputes.decide_review(conn, req.order_id, rogue, "ada", "too generous")
            raise AssertionError("out of band ruling was accepted")
        except DomainError as exc:
            assert exc.status == 422
    assert ledger.balance(conn, ledger.wallet_id_for("b1")) == before

    with transaction(conn):
        decided = disputes.decide_review(conn, req.order_id, _edge_ruling(), "ada", "edge case, keep the band")
    assert decided.pending_review is False
    assert decided.decision is DisputeDecision.REFUND_PARTIAL
    assert decided.refund_minor == 30  # 25% of $1.20
    assert conn.execute(
        "SELECT COUNT(*) FROM (SELECT txn_id FROM ledger_entries GROUP BY txn_id HAVING SUM(amount_minor) <> 0)"
    ).fetchone()[0] == 0
    payload = conn.execute(
        "SELECT payload_json FROM outbox WHERE event_type = 'dispute.resolved' AND aggregate_id = ?",
        (req.order_id,),
    ).fetchone()["payload_json"]
    assert "ada" in payload and "edge case, keep the band" in payload


def test_decide_requires_the_operator_token(monkeypatch):
    monkeypatch.setenv("AL_ADMIN_TOKEN", "s3cret")
    client = TestClient(create_app())
    body = {"human_id": "ada", "rationale": "ok", "decision": "REFUND_PARTIAL", "refund_pct": 50,
            "cited_checks": ["hit_rate"]}
    assert client.post("/api/reviews/ord_missing/decide", json=body).status_code == 403
    assert client.post(
        "/api/reviews/ord_missing/decide", json=body, headers={"X-Admin-Token": "s3cret"},
    ).status_code == 404


def test_large_order_and_repeat_rejected_buyer_are_queued(conn, monkeypatch):
    monkeypatch.setenv("AL_CAP_HUMAN_REVIEW_ABOVE_MINOR", "100")
    req = _disputed_rsi_order(conn)
    with transaction(conn):
        outcome = disputes.open_and_resolve(conn, req, 200, None, None)
    assert outcome.pending_review is True
    assert "human-review threshold" in outcome.rationale
