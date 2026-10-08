"""Shared wire contracts between the two halves of the team.

FREEZE THIS FILE FIRST. Laptop A (economy) and laptop B (market + analytics) both code against
these models; change them only together. Money is always integer minor units (cents).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Capability(StrEnum):
    PRICES = "market.prices"            # OHLCV feed           (zoomcamp M1)
    FEATURES = "market.features"        # engineered features  (zoomcamp M2)
    SIGNAL_5D = "signal.direction.5d"   # 5-day up/down signal (zoomcamp M3)


class OrderStatus(StrEnum):
    FUNDS_HELD = "FUNDS_HELD"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    CANCELLED = "CANCELLED"


class EventType(StrEnum):
    AGENT_REGISTERED = "agent.registered"
    WALLET_FUNDED = "wallet.funded"
    PAYMENT_HELD = "payment.held"
    ORDER_DELIVERED = "order.delivered"
    PAYMENT_SETTLED = "payment.settled"
    DISPUTE_OPENED = "dispute.opened"
    DISPUTE_RESOLVED = "dispute.resolved"
    PAYMENT_REFUNDED = "payment.refunded"
    REPUTATION_UPDATED = "reputation.updated"
    POLICY_LEARNED = "policy.learned"          # buyer price-vs-reputation weight moved
    SIGNAL_VERIFIED = "signal.verified"        # realized 5-day direction, after the horizon
    LLM_USAGE = "llm.usage"                    # one per LLM call: tokens + cost (agents/accounting.py)
    AGENT_RUN_FINISHED = "agent.run.finished"  # one per agent run: totals + outcome


class DisputeDecision(StrEnum):
    REFUND_FULL = "REFUND_FULL"
    REFUND_PARTIAL = "REFUND_PARTIAL"
    RELEASE = "RELEASE"  # dispute rejected, seller is paid


# ---------------------------------------------------------------- discovery


class AgentCard(BaseModel):
    """What a seller publishes at /.well-known/agents.json (A2A-style agent card)."""

    agent_id: str
    name: str
    owner: str
    capability: Capability
    endpoint: str  # full URL of the agent, e.g. http://10.0.0.5:8002/agents/sig-momentum
    price_minor: int = Field(ge=0)
    currency: str = "USD"
    description: str = ""


class RankedCard(AgentCard):
    reputation: float
    score: float


class BuyerSignup(BaseModel):
    agent_id: str
    name: str
    owner: str
    initial_funding_minor: int = Field(ge=0)
    max_per_order_minor: int | None = None  # spend mandate enforced by the clearing house
    daily_limit_minor: int | None = None


class TaskSpec(BaseModel):
    capability: Capability
    symbol: str
    lookback_days: int = 180
    horizon_days: int = 5
    as_of: date | None = None  # point-in-time cutoff; None = today


# ---------------------------------------------------------------- payment (HTTP 402 flow)


class AcceptanceCriteria(BaseModel):
    """Machine-checkable contract terms. The adjudicator re-runs these; it trusts nobody's claims."""

    required_columns: list[str]
    min_rows: int = 20
    max_staleness_days: int = 7
    min_hit_rate: float | None = None  # signals only
    min_rank_ic: float | None = None   # signals only (IC idea from alpha-research repos)


class PaymentRequired(BaseModel):
    """Body of a seller's HTTP 402 response: a priced, expiring quote."""

    quote_id: str
    seller_agent_id: str
    amount_minor: int = Field(gt=0)
    currency: str = "USD"
    expires_at: datetime
    task: TaskSpec
    acceptance: AcceptanceCriteria


class HoldRequest(BaseModel):
    buyer_agent_id: str
    quote: PaymentRequired
    idempotency_key: str


class PaymentReceipt(BaseModel):
    """Issued by the clearing house after escrow hold; sent to the seller as the X-Payment header."""

    order_id: str
    quote_id: str
    buyer_agent_id: str
    seller_agent_id: str
    amount_minor: int
    signature: str  # HMAC over the fields above, see economy.receipts


# ---------------------------------------------------------------- delivery & verification


class Deliverable(BaseModel):
    order_id: str
    seller_agent_id: str
    capability: Capability
    symbol: str
    as_of: date
    columns: list[str]
    rows: list[dict[str, Any]]
    content_hash: str
    content_signature: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class DeliveryNotice(BaseModel):
    content_hash: str
    content_signature: str = ""
    latency_ms: int


class CheckResult(BaseModel):
    name: str
    passed: bool
    critical: bool
    detail: str = ""


class QualityReport(BaseModel):
    passed: bool
    score: float  # share of checks passed
    checks: list[CheckResult]
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence_hash: str = ""


class DisputeRequest(BaseModel):
    order_id: str
    reason: str
    # Ignored by the clearing house. The adjudicator re-runs checks on the archived delivery.
    deliverable: Deliverable | None = None
    parent_run_id: str | None = None  # buyer agent run that opened the dispute (links the two traces)


class GuardianRuling(BaseModel):
    """What the guardian proposes. Deterministic policy validates it before any money moves."""

    decision: DisputeDecision
    refund_pct: int = Field(ge=0, le=100)
    rationale: str
    cited_checks: list[str] = Field(default_factory=list)
    source: str = "rule-table"  # rule-table | guardian-llm


class DisputeOutcome(BaseModel):
    dispute_id: str
    order_id: str
    decision: DisputeDecision
    refund_minor: int
    rationale: str
    evidence: QualityReport
    llm_summary: str | None = None
    ruling_source: str = "rule-table"
    guardian_run_id: str | None = None


# ---------------------------------------------------------------- AI agent telemetry
# LLM cost is money too: integer micro-USD (1 USD = 1_000_000), never float.


class AgentStep(BaseModel):
    seq: int
    kind: str  # plan | llm | tool | policy | reflect | error
    name: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micro_usd: int = 0
    latency_ms: int = 0
    at: str = ""


class AgentRunReport(BaseModel):
    run_id: str
    agent_id: str
    role: str  # buyer | guardian
    goal: str
    provider: str
    model: str
    status: str = "running"  # running | completed | budget_stopped | failed
    parent_run_id: str | None = None
    started_at: str
    finished_at: str | None = None
    summary: str = ""
    tool_calls: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micro_usd: int = 0
    steps: list[AgentStep] = Field(default_factory=list)


class OrderView(BaseModel):
    order_id: str
    quote_id: str
    buyer_agent_id: str
    seller_agent_id: str
    capability: str
    symbol: str
    amount_minor: int
    refunded_minor: int
    status: OrderStatus
    created_at: str
    closed_at: str | None = None


# ---------------------------------------------------------------- helpers


def canonical_hash(obj: Any) -> str:
    """Stable sha256 over JSON (sorted keys, no whitespace). Used for deliverables and evidence."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
