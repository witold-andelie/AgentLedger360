"""Dispute resolution: evidence is re-derived by the adjudicator (re-hash + re-run checks), nobody's claims
are trusted. The guardian agent (agents/guardian.py) may PROPOSE a ruling; policy_band() says what is
allowed and validate() rejects anything outside it, falling back to the rule table. Money moves only
through escrow.settle / escrow.refund (rule R1).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from agentledger.contracts import (
    AcceptanceCriteria,
    Capability,
    Deliverable,
    DisputeDecision,
    DisputeOutcome,
    DisputeRequest,
    EventType,
    GuardianRuling,
    OrderStatus,
    QualityReport,
    canonical_hash,
)
from agentledger.db import emit_event, new_id, now_iso
from agentledger.economy import DomainError, escrow
from agentledger.market import quality

PARTIAL_MIN_PCT, PARTIAL_DEFAULT_PCT, PARTIAL_MAX_PCT = 25, 50, 75


@dataclass(frozen=True)
class PolicyBand:
    """The only rulings policy allows for this evidence. Fixed bands have min_pct == max_pct."""

    decision: DisputeDecision
    min_pct: int
    max_pct: int
    default_pct: int
    reason: str
    failed_checks: tuple[str, ...]


def archive(conn: sqlite3.Connection, deliverable: Deliverable) -> None:
    """Store the rows the clearing house actually received. Disputes read only this row."""
    conn.execute(
        "INSERT INTO deliveries (order_id, rows_json, content_hash, seller_signature, as_of, received_at)"
        " VALUES (?,?,?,?,?,?)",
        (deliverable.order_id, json.dumps(deliverable.rows), deliverable.content_hash,
         deliverable.content_signature, deliverable.as_of.isoformat(), now_iso()),
    )


def archived_deliverable(conn: sqlite3.Connection, order: sqlite3.Row) -> Deliverable | None:
    """The rows the clearing house fetched itself. The buyer's copy is never the evidence."""
    row = conn.execute("SELECT * FROM deliveries WHERE order_id = ?", (order["order_id"],)).fetchone()
    if row is None:
        return None
    rows = json.loads(row["rows_json"])
    return Deliverable(
        order_id=order["order_id"], seller_agent_id=order["seller_agent_id"],
        capability=Capability(order["capability"]), symbol=order["symbol"],
        as_of=date.fromisoformat(row["as_of"]),
        columns=list(rows[0].keys()) if rows else [], rows=rows,
        content_hash=row["content_hash"], content_signature=row["seller_signature"],
    )


def evidence(conn: sqlite3.Connection, order: sqlite3.Row) -> tuple[bool, QualityReport]:
    """(hash_ok, re-executed report) from the delivery archive, not from either party's claim."""
    archived = archived_deliverable(conn, order)
    if archived is None or canonical_hash(archived.rows) != order["content_hash"]:
        return False, QualityReport(passed=True, score=1.0, checks=[], evidence_hash="")
    criteria = AcceptanceCriteria.model_validate_json(order["acceptance_json"])
    return True, quality.evaluate(archived, criteria)


def policy_band(hash_ok: bool, report: QualityReport) -> PolicyBand:
    """Rule table (explainable for the judges):
    - evidence hash mismatch            -> RELEASE (the buyer's evidence is not what the seller signed)
    - every check passes                -> RELEASE (dispute rejected, seller paid)
    - any critical check fails          -> REFUND_FULL (schema / empty / stale / look-ahead)
    - only performance checks fail      -> REFUND_PARTIAL between 25% and 75%, default 50%
    """
    if not hash_ok:
        return PolicyBand(DisputeDecision.RELEASE, 0, 0, 0, "evidence hash mismatch: dispute rejected", ())
    failed = tuple(c.name for c in report.checks if not c.passed)
    if not failed:
        return PolicyBand(DisputeDecision.RELEASE, 0, 0, 0, "all acceptance checks pass on re-execution", ())
    critical = tuple(c.name for c in report.checks if not c.passed and c.critical)
    if critical:
        return PolicyBand(DisputeDecision.REFUND_FULL, 100, 100, 100,
                          f"critical checks failed: {', '.join(critical)}", failed)
    return PolicyBand(DisputeDecision.REFUND_PARTIAL, PARTIAL_MIN_PCT, PARTIAL_MAX_PCT, PARTIAL_DEFAULT_PCT,
                      f"performance below contract: {', '.join(failed)}", failed)


def validate(ruling: GuardianRuling, band: PolicyBand) -> str | None:
    """None if the proposal is inside the band and grounded in the evidence, else the reason it is rejected."""
    if ruling.decision is not band.decision:
        return f"decision {ruling.decision} not allowed, policy requires {band.decision}"
    if not band.min_pct <= ruling.refund_pct <= band.max_pct:
        return f"refund {ruling.refund_pct}% outside allowed {band.min_pct}-{band.max_pct}%"
    unknown = sorted(set(ruling.cited_checks) - set(band.failed_checks))
    if unknown:
        return f"cites checks that did not fail: {unknown}"
    if band.failed_checks and not ruling.cited_checks:
        return "must cite at least one failed check"
    if not ruling.rationale.strip():
        return "empty rationale"
    return None


def refund_for(amount_minor: int, pct: int) -> int:
    return 0 if pct <= 0 else max(1, amount_minor * pct // 100)


def decide(report: QualityReport, amount_minor: int) -> tuple[DisputeDecision, int, str]:
    """Rule-table decision without a guardian (kept for callers and tests)."""
    band = policy_band(True, report)
    return band.decision, refund_for(amount_minor, band.default_pct), band.reason


def open_and_resolve(conn: sqlite3.Connection, req: DisputeRequest, fee_bps: int,
                     ruling: GuardianRuling | None = None, guardian_run_id: str | None = None) -> DisputeOutcome:
    order = escrow.get_order(conn, req.order_id)
    if order["status"] != OrderStatus.DELIVERED:
        raise DomainError(f"order {req.order_id} is {order['status']}, only DELIVERED can be disputed")
    escrow._transition(conn, req.order_id, {OrderStatus.DELIVERED}, OrderStatus.DISPUTED)
    emit_event(conn, EventType.DISPUTE_OPENED, req.order_id,
               {**escrow._event_base(order), "status": str(OrderStatus.DISPUTED), "reason": req.reason})

    hash_ok, report = evidence(conn, order)  # archive only: never trust a proposal's own evidence
    band = policy_band(hash_ok, report)
    pct, rationale, source, summary = band.default_pct, band.reason, "rule-table", None
    if ruling is not None:
        problem = validate(ruling, band)
        if problem is None:
            pct, source, summary = ruling.refund_pct, ruling.source, ruling.rationale
            rationale = f"{band.reason}; guardian set {pct}%"
        else:
            rationale = f"{band.reason} (guardian proposal rejected: {problem})"

    refund = refund_for(order["amount_minor"], pct)
    if band.decision is DisputeDecision.RELEASE:
        escrow.settle(conn, req.order_id, report, fee_bps)
    else:
        escrow.refund(conn, req.order_id, refund, fee_bps, metrics=report.metrics)

    dispute_id = new_id("dsp")
    ts = now_iso()
    conn.execute(
        "INSERT INTO disputes (dispute_id, order_id, reason, evidence_json, evidence_hash, decision, refund_minor,"
        " rationale, llm_summary, opened_at, resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (dispute_id, req.order_id, req.reason, report.model_dump_json(), report.evidence_hash, str(band.decision),
         refund, rationale, summary, ts, ts),
    )
    emit_event(conn, EventType.DISPUTE_RESOLVED, req.order_id,
               {"order_id": req.order_id, "dispute_id": dispute_id, "decision": str(band.decision),
                "refund_minor": refund, "refund_pct": pct, "rationale": rationale, "ruling_source": source,
                "guardian_run_id": guardian_run_id,
                "failed_checks": json.dumps(list(band.failed_checks))})
    return DisputeOutcome(dispute_id=dispute_id, order_id=req.order_id, decision=band.decision, refund_minor=refund,
                          rationale=rationale, evidence=report, llm_summary=summary, ruling_source=source,
                          guardian_run_id=guardian_run_id)
