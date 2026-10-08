"""Guardian agent: the clearing house's LLM investigator that protects BOTH buyer and seller in a dispute.

It investigates with read-only tools (case file, evidence hash, re-run acceptance checks, both parties' track
records, policy bounds) and proposes a ruling through submit_ruling. The proposal only counts if it is inside
the deterministic policy band and cites checks that really failed (economy/disputes.validate); the platform
re-validates it inside the money-moving transaction. Runs BEFORE that transaction, so no DB write lock is
held while the model thinks.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from agentledger.agents.graph import as_json, build_agent_graph
from agentledger.agents.llm import make_chat_model
from agentledger.agents.telemetry import RunRecorder
from agentledger.config import Settings
from agentledger.contracts import AgentRunReport, DisputeDecision, DisputeRequest, GuardianRuling
from agentledger.db import connect
from agentledger.economy import disputes, escrow

GUARDIAN_ID = "guardian"

SYSTEM_PROMPT = """You are the independent Guardian of an escrow clearing house in an agent-to-agent market.
A buyer agent disputes a delivery from a seller agent. You protect BOTH sides: buyers from bad, stale or
manipulated data, sellers from unfounded or abusive disputes.
Investigate with the tools, then call submit_ruling exactly once.
Hard limits come from policy_bounds: use the allowed decision, a refund percentage inside the allowed range,
and cite the failed check names you relied on. Inside a partial-refund range, scale the refund by how far the
metrics missed the contract thresholds and by both parties' track records. Be brief and factual."""

PLAN_INSTRUCTION = "In at most 4 lines: which facts you need and which tools give them."
REFLECT_INSTRUCTION = "In at most 2 sentences for the audit log: the ruling and the decisive evidence."


class GuardianToolkit:
    def __init__(self, s: Settings, req: DisputeRequest) -> None:
        self.s, self.req = s, req
        self.ruling: GuardianRuling | None = None
        conn = connect(s)
        try:
            self.order = dict(escrow.get_order(conn, req.order_id))
            self.hash_ok, self.report = disputes.evidence(conn, escrow.get_order(conn, req.order_id))
            self.seller = self._track_record(conn, "seller_agent_id", self.order["seller_agent_id"])
            self.buyer = self._track_record(conn, "buyer_agent_id", self.order["buyer_agent_id"])
        finally:
            conn.close()
        self.band = disputes.policy_band(self.hash_ok, self.report)

    @staticmethod
    def _track_record(conn: Any, column: str, agent_id: str) -> dict[str, Any]:
        rows = conn.execute(
            f"SELECT o.status, d.decision FROM orders o LEFT JOIN disputes d ON d.order_id = o.order_id"
            f" WHERE o.{column} = ? AND o.status NOT IN ('FUNDS_HELD', 'DELIVERED')", (agent_id,)).fetchall()
        rep = conn.execute("SELECT reputation FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        decisions = [r["decision"] for r in rows if r["decision"]]
        return {"agent_id": agent_id, "closed_orders": len(rows),
                "completed": sum(r["status"] == "COMPLETED" for r in rows),
                "disputes": len(decisions),
                "disputes_rejected": decisions.count(str(DisputeDecision.RELEASE)),
                "full_refunds": decisions.count(str(DisputeDecision.REFUND_FULL)),
                "partial_refunds": decisions.count(str(DisputeDecision.REFUND_PARTIAL)),
                "reputation": round(rep["reputation"], 3) if rep and rep["reputation"] is not None else None}

    def tools(self) -> list[BaseTool]:
        kit = self

        @tool
        def get_case() -> str:
            """The disputed order: parties, amount, contract terms and the buyer's stated reason."""
            o = kit.order
            return as_json({"order_id": o["order_id"], "buyer": o["buyer_agent_id"], "seller": o["seller_agent_id"],
                            "symbol": o["symbol"], "amount_usd": o["amount_minor"] / 100,
                            "terms": o["acceptance_json"], "buyer_reason": kit.req.reason})

        @tool
        def check_evidence_hash() -> str:
            """Does the buyer's submitted data hash to the content_hash the seller signed at delivery?"""
            return as_json({"match": kit.hash_ok, "recorded_hash": kit.order["content_hash"],
                            "rows_submitted": len(kit.req.deliverable.rows)})

        @tool
        def rerun_acceptance_checks() -> str:
            """Re-execute the contract's deterministic acceptance checks on the submitted data."""
            if not kit.hash_ok:
                return "not run: evidence hash mismatch, the submitted data is not what the seller delivered"
            return as_json({"passed": kit.report.passed, "metrics": kit.report.metrics,
                            "checks": [c.model_dump() for c in kit.report.checks]})

        @tool
        def seller_track_record() -> str:
            """The seller's closed orders, dispute outcomes and reputation."""
            return as_json(kit.seller)

        @tool
        def buyer_track_record() -> str:
            """The buyer's closed orders and dispute outcomes (detects serial or abusive disputing)."""
            return as_json(kit.buyer)

        @tool
        def policy_bounds() -> str:
            """The rulings policy allows for this evidence: decision, refund % range, failed checks to cite."""
            b = kit.band
            return as_json({"decision": b.decision, "refund_pct_min": b.min_pct, "refund_pct_max": b.max_pct,
                            "default_pct": b.default_pct, "failed_checks": list(b.failed_checks),
                            "policy_reason": b.reason})

        @tool
        def submit_ruling(decision: str, refund_pct: int, rationale: str, cited_checks: list[str]) -> str:
            """Submit your ruling once. decision: RELEASE | REFUND_PARTIAL | REFUND_FULL; refund_pct 0-100."""
            try:
                ruling = GuardianRuling(decision=DisputeDecision(decision), refund_pct=refund_pct,
                                        rationale=rationale, cited_checks=cited_checks, source="guardian-llm")
            except ValueError as exc:
                return f"rejected: {exc}"
            problem = disputes.validate(ruling, kit.band)
            if problem:
                return f"rejected by policy: {problem}. Fix it and submit again."
            kit.ruling = ruling
            return "accepted: ruling recorded, the clearing house will execute it"

        return [get_case, check_evidence_hash, rerun_acceptance_checks, seller_track_record, buyer_track_record,
                policy_bounds, submit_ruling]


def investigate(s: Settings, req: DisputeRequest, *, model: Any = None) -> tuple[GuardianRuling | None,
                                                                                  AgentRunReport]:
    kit = GuardianToolkit(s, req)
    goal = (f"Rule on the buyer's dispute of order {req.order_id} "
            f"({kit.order['symbol']}, seller {kit.order['seller_agent_id']}).")
    recorder = RunRecorder(s, agent_id=GUARDIAN_ID, role="guardian", goal=goal, parent_run_id=req.parent_run_id)
    status, summary = "completed", ""
    try:
        graph = build_agent_graph(model=model or make_chat_model(s, max_tokens=1024), tools=kit.tools(),
                                  recorder=recorder, system_prompt=SYSTEM_PROMPT, plan_instruction=PLAN_INSTRUCTION,
                                  reflect_instruction=REFLECT_INSTRUCTION,
                                  should_stop=lambda: "ruling submitted" if kit.ruling else None)
        out = graph.invoke({"goal": goal}, {"recursion_limit": 10})
        summary = out.get("summary", "")
        if "budget" in out.get("stop_reason", ""):
            status = "budget_stopped"
    except Exception as exc:  # the rule table still decides; the failure is visible in the trace
        recorder.note("error", type(exc).__name__, message=str(exc)[:500])
        status, summary = "failed", f"guardian failed, rule table applies: {type(exc).__name__}"
    if kit.ruling is None:
        recorder.note("policy", "fallback", reason="no valid ruling submitted; rule table applies")
    return kit.ruling, recorder.finish(status, summary)
