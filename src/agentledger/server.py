"""Web entry point (Render, or locally with uvicorn).

    uvicorn agentledger.server:create_app --factory --host 0.0.0.0 --port 8000

AL_ROLE=all (default)  /api/* for the React frontend + clearing house (/platform) + sellers (/sellers, unless
                       AL_SELLER_URL points to a remote seller service) + the built frontend at "/".
                       The buyer agent runs in-process.
AL_ROLE=sellers        only the seller agents: deploy as a second Render service for real A2A over the internet.

The frontend API contract is documented in docs/FRONTEND_RULES.md; change both together.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import sqlite3
import threading
import time
from datetime import UTC, date, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agentledger.agents import accounting, llm, telemetry
from agentledger.analytics import pipeline
from agentledger.attacks import run_scenarios
from agentledger.config import Settings, load_settings
from agentledger.db import connect, transaction, verify_audit_chain, wipe_all
from agentledger.economy import ledger
from agentledger.governance import Capabilities, CapabilityGate
from agentledger.runner import BUYER, Market, run_summary, summarize
from agentledger.sellers.app import create_app as seller_app

log = logging.getLogger(__name__)


class RoundRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "NVDA"], max_length=8)
    rounds: int = Field(default=1, ge=1, le=5)


class AgentRoundRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["AAPL", "MSFT", "NVDA"], max_length=8)
    as_of: date | None = None


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _token_ok(expected: str | None, presented: str | None) -> bool:
    if not expected or not presented or len(presented) != len(expected):
        return False
    return hmac.compare_digest(presented, expected)


def _ai_spent_today_micro(conn: sqlite3.Connection) -> int:
    today = datetime.now(UTC).date().isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_micro_usd), 0) FROM agent_runs WHERE substr(started_at, 1, 10) = ?",
        (today,),
    ).fetchone()
    return int(row[0])


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or load_settings()
    if s.role == "sellers":
        return seller_app(s)

    gate = CapabilityGate(Capabilities.from_env())
    operator_token = s.admin_token or secrets.token_urlsafe(24)
    sellers = None if s.seller_url else seller_app(s)
    market = Market.in_process(s, sellers=sellers, operator_token=operator_token, gate=gate)
    try:
        market.bootstrap()  # buyer wallet is funded before the first page view
    except Exception:
        log.warning("startup bootstrap failed", exc_info=True)
        if not s.seller_url:
            raise

    app = FastAPI(title="AgentLedger 360")
    app.mount("/platform", market.platform)
    if sellers is not None:
        app.mount("/sellers", sellers)

    price = accounting.price_for(llm.model_name(s), s)
    jobs: dict[str, dict[str, Any]] = {}
    jobs_lock = threading.Lock()
    last_round_at: dict[str, float] = {}

    def after_round() -> dict[str, Any]:
        conn = connect(s)
        try:
            runs = pipeline.run(conn)
        finally:
            conn.close()
        check = market.router.get(f"{market.platform_url}/ledger/check").json()
        return {"pipeline": runs, "reconciliation": check}

    def run_with_children(run_id: str) -> dict[str, Any] | None:
        """One agent run (live while running, from the DB after) plus the guardian runs it triggered."""
        conn = connect(s)
        try:
            report = telemetry.live_snapshot(run_id) or telemetry.load_run(conn, run_id)
            if report is None:
                return None
            child_ids = [r["run_id"] for r in conn.execute(
                "SELECT run_id FROM agent_runs WHERE parent_run_id = ? ORDER BY started_at", (run_id,))]
            children = [c for c in (telemetry.load_run(conn, cid) for cid in child_ids) if c]
        finally:
            conn.close()
        children += [c for c in telemetry.live_children(run_id) if c.run_id not in child_ids]
        return {**report.model_dump(mode="json"), "children": [c.model_dump(mode="json") for c in children]}

    def spent_today_usd() -> float:
        conn = connect(s)
        try:
            return _ai_spent_today_micro(conn) / 1_000_000
        finally:
            conn.close()

    def admit_round(request: Request) -> str | None:
        """Rate-limit and optional run token. Returns a degrade reason when the daily AI budget is spent."""
        if s.run_token is not None and not _token_ok(s.run_token, request.headers.get("x-run-token")):
            raise HTTPException(403, "run token required (header X-Run-Token)")
        if s.round_min_interval_seconds > 0:
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            previous = last_round_at.get(ip)
            if previous is not None and now - previous < s.round_min_interval_seconds:
                raise HTTPException(429, "one round per minute from this address")
            last_round_at[ip] = now
        if spent_today_usd() >= s.daily_ai_budget_usd:
            return "daily AI budget reached"
        return None

    def require_admin(presented: str | None) -> None:
        if not _token_ok(operator_token, presented):
            raise HTTPException(403, "admin token required (header X-Admin-Token)")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        llm_on = market.mode == "llm"
        return {"status": "ok", "sellers": market.seller_url, "agent_mode": market.mode,
                "llm_provider": s.llm_provider if llm_on else None,
                "llm_model": llm.model_name(s) if llm_on else None,
                "price_per_m_tokens": ({"input_usd": price.input_per_m, "output_usd": price.output_per_m,
                                        "source": price.source} if price and llm_on else None),
                "budget": {"max_tool_calls": s.agent_max_tool_calls, "max_cost_usd": s.agent_max_cost_usd},
                "reset_requires_token": s.admin_token is not None,
                "capabilities": gate.snapshot(),
                "daily_ai_budget_usd": s.daily_ai_budget_usd,
                "ai_spent_today_usd": round(spent_today_usd(), 6),
                "run_requires_token": s.run_token is not None,
                "buyer_policy": _buyer_policy()}

    def _buyer_policy() -> dict[str, Any]:
        from agentledger.agents.learning import load_buyer_policy
        conn = connect(s)
        try:
            policy = load_buyer_policy(conn, BUYER.agent_id)
        finally:
            conn.close()
        return {"price_weight": policy["price_weight"], "observations": policy["observations"],
                "reason": policy["reason"]}

    @app.post("/api/admin/pause")
    def pause_market(x_admin_token: str | None = Header(default=None)) -> dict[str, bool | int]:
        require_admin(x_admin_token)
        gate.paused = True
        return gate.snapshot()

    @app.post("/api/admin/resume")
    def resume_market(x_admin_token: str | None = Header(default=None)) -> dict[str, bool | int]:
        require_admin(x_admin_token)
        gate.paused = False
        return gate.snapshot()

    @app.post("/api/attacks/run")
    def attacks_run() -> list[dict[str, Any]]:
        """Run the attack lab against a throwaway database. Does not spend LLM credit or touch the demo."""
        return run_scenarios(s)

    @app.get("/api/audit/verify")
    def audit_verify() -> dict[str, bool | int | None]:
        conn = connect(s)
        try:
            ok, bad = verify_audit_chain(conn)
        finally:
            conn.close()
        return {"ok": ok, "first_bad_seq": bad}

    @app.post("/api/demo/reset")
    def reset_demo(x_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        """Wipe every order, ledger entry, agent run and AI cost, then re-register sellers and refill the buyer."""
        if s.admin_token is not None and not hmac.compare_digest(x_admin_token or "", s.admin_token):
            raise HTTPException(403, "admin token required (header X-Admin-Token)")
        try:
            with market.exclusive():
                conn = connect(s)
                try:
                    wipe_all(conn)
                    with transaction(conn):
                        ledger.ensure_system_wallets(conn)
                finally:
                    conn.close()
                with jobs_lock:
                    jobs.clear()
                telemetry.clear_live()
                market.forget_bootstrap()
                sellers_registered = market.bootstrap()
        except RuntimeError as exc:
            raise HTTPException(409, f"{exc}; reset after it finishes") from exc
        return {"reset": True, "sellers": sellers_registered, "buyer_balance_minor": market.buyer.balance(),
                **after_round()}

    @app.post("/api/round")
    def run_round(req: RoundRequest, request: Request) -> dict[str, Any]:
        """Synchronous round (kept for the Market page). With an LLM agent this can take a minute."""
        degraded = admit_round(request)
        purchases: list[dict[str, Any]] = []
        try:
            for _ in range(req.rounds):
                purchases += [summarize(p) for p in market.run_round(req.symbols, force_rule=degraded is not None)]
        except Exception as exc:  # e.g. remote seller service asleep (Render free tier cold start)
            raise HTTPException(502, f"market round failed: {exc!r}") from exc
        body: dict[str, Any] = {"purchases": purchases, "agent_run": run_summary(market.last_run), **after_round()}
        if degraded:
            body["degraded"] = degraded
        return body

    # ---------------------------------------------------------------- live agent rounds (Agent Console)
    @app.post("/api/agent/rounds")
    def start_agent_round(req: AgentRoundRequest, request: Request) -> dict[str, str]:
        """Start a round in the background; poll GET /api/agent/rounds/{job_id} to watch the agents."""
        degraded = admit_round(request)
        job_id = telemetry.new_job_id()
        job: dict[str, Any] = {"job_id": job_id, "status": "running",
                               "mode": "rule" if degraded else market.mode, "run_id": None,
                               "purchases": None, "result": None, "error": None, "degraded": degraded}
        with jobs_lock:
            jobs[job_id] = job

        def on_start(run_id: str) -> None:
            job["run_id"] = run_id

        def work() -> None:
            try:
                job["purchases"] = [summarize(p) for p in market.run_round(
                    req.symbols, req.as_of, on_start, force_rule=degraded is not None)]
                job["result"] = after_round()
                job["status"] = "completed"
            except Exception as exc:  # surfaced to the UI, never swallowed
                job["error"], job["status"] = f"{type(exc).__name__}: {exc}", "failed"

        threading.Thread(target=work, name=job_id, daemon=True).start()
        return {"job_id": job_id}

    @app.get("/api/agent/rounds/{job_id}")
    def agent_round(job_id: str) -> dict[str, Any]:
        with jobs_lock:
            job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"unknown job {job_id}")
        return {**job, "run": run_with_children(job["run_id"]) if job["run_id"] else None}

    @app.get("/api/agent/runs")
    def agent_runs(limit: int = 20) -> list[dict[str, Any]]:
        conn = connect(s)
        try:
            return _rows(conn, "SELECT run_id, agent_id, role, status, parent_run_id, provider, model, started_at,"
                               " finished_at, tool_calls, llm_calls, input_tokens, output_tokens, cost_micro_usd,"
                               " summary FROM agent_runs ORDER BY started_at DESC LIMIT ?", (min(limit, 200),))
        finally:
            conn.close()

    @app.get("/api/agent/runs/{run_id}")
    def agent_run(run_id: str) -> dict[str, Any]:
        run = run_with_children(run_id)
        if run is None:
            raise HTTPException(404, f"unknown run {run_id}")
        return run

    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        conn = connect(s)
        try:
            kpi = conn.execute(
                "SELECT COUNT(*) AS orders,"
                " COALESCE(SUM(CASE WHEN final_status IN ('COMPLETED','PARTIALLY_REFUNDED')"
                "   THEN amount_minor - refunded_minor END), 0) AS settled_gmv_minor,"
                " COALESCE(AVG(disputed), 0) AS dispute_rate,"
                " COALESCE(SUM(fee_minor), 0) AS fees_minor"
                " FROM analytics.fact_orders"
            ).fetchone()
            last_run = conn.execute(
                "SELECT run_id FROM analytics.pipeline_runs ORDER BY started_at DESC LIMIT 1").fetchone()
            ai = conn.execute(
                "SELECT COUNT(*) AS ai_runs, COALESCE(SUM(llm_calls), 0) AS llm_calls,"
                " COALESCE(SUM(input_tokens + output_tokens), 0) AS ai_tokens,"
                " COALESCE(SUM(cost_micro_usd), 0) AS ai_cost_micro_usd FROM analytics.fact_agent_runs"
            ).fetchone()
            return {
                "kpi": {**dict(kpi), **dict(ai),
                        "buyer_balance_minor": ledger.balance(conn, ledger.wallet_id_for(BUYER.agent_id))},
                "ai_costs": _rows(conn, "SELECT * FROM analytics.v_ai_cost_by_agent ORDER BY cost_micro_usd DESC"),
                "ai_models": _rows(conn, "SELECT * FROM analytics.v_ai_cost_by_model"),
                "agents": _rows(conn, "SELECT * FROM analytics.v_agent_performance ORDER BY reputation DESC"),
                "customers": _rows(conn, "SELECT * FROM analytics.v_customer_360"),
                "rfm": _rows(conn, "SELECT buyer_agent_id, recency_days, frequency, monetary_minor,"
                                   " r_score, f_score, m_score, segment FROM analytics.v_customer_rfm"),
                "dq": _rows(conn, "SELECT check_name, violations, passed FROM analytics.dq_results"
                                  " WHERE run_id = ? ORDER BY check_name", (last_run["run_id"] if last_run else "",)),
                "orders": _rows(conn, "SELECT order_id, seller_agent_id, symbol, amount_minor, refunded_minor,"
                                      " final_status, latency_ms, hit_rate FROM analytics.fact_orders"
                                      " ORDER BY held_at DESC LIMIT 15"),
            }
        finally:
            conn.close()

    @app.get("/api/events")
    def events(limit: int = 60) -> list[dict[str, Any]]:
        conn = connect(s)
        try:
            return _rows(conn, "SELECT seq, event_type, aggregate_id, occurred_at, payload_json"
                               " FROM main.outbox ORDER BY seq DESC LIMIT ?", (min(limit, 500),))
        finally:
            conn.close()

    # Last: the built React app (frontend/dist) owns "/" - same pattern as the EuroGoal project.
    if s.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=s.frontend_dist, html=True), name="frontend")
    return app
