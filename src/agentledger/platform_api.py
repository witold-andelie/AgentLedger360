"""Clearing house API: registry, wallets, escrow, delivery, settlement, disputes.

Run on laptop A:  uvicorn agentledger.platform_api:create_app --factory --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import hmac
import sqlite3
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from agentledger.agents import llm, telemetry
from agentledger.config import Settings, load_settings
from agentledger.contracts import (
    AgentCard,
    AgentRunReport,
    BuyerSignup,
    Capability,
    DeliveryNotice,
    DisputeOutcome,
    DisputeRequest,
    HoldRequest,
    OrderView,
    PaymentReceipt,
    QualityReport,
    RankedCard,
)
from agentledger.db import connect, init_db, transaction
from agentledger.economy import DomainError, disputes, escrow, ledger, registry
from agentledger.governance import Capabilities, CapabilityGate


def _token_ok(expected: str, presented: str | None) -> bool:
    if not expected or not presented or len(presented) != len(expected):
        return False
    return hmac.compare_digest(presented, expected)


def create_app(settings: Settings | None = None, operator_token: str = "",
               gate: CapabilityGate | None = None) -> FastAPI:
    s = settings or load_settings()
    gate = gate or CapabilityGate(Capabilities.from_env())
    boot = connect(s)
    try:
        init_db(boot)
        with transaction(boot):
            ledger.ensure_system_wallets(boot)
    finally:
        boot.close()

    guardian_llm = llm.resolve_mode(s) == "llm" and gate.caps.llm_rulings

    app = FastAPI(title="AgentLedger clearing house")

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(s)
        try:
            yield conn
        finally:
            conn.close()

    @app.exception_handler(DomainError)
    def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.IntegrityError)
    def integrity_error(_: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": f"integrity: {exc}"})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ---------------------------------------------------------------- registry / discovery
    @app.post("/registry/sellers")
    def register_seller(card: AgentCard, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, str]:
        with transaction(conn):
            registry.register_seller(conn, card)
        return {"agent_id": card.agent_id}

    @app.post("/registry/buyers")
    def register_buyer(body: BuyerSignup, x_admin_token: str | None = Header(default=None),
                       conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, int | str]:
        with transaction(conn):
            created = registry.register_buyer(conn, body.agent_id, body.name, body.owner,
                                              max_per_order_minor=body.max_per_order_minor,
                                              daily_limit_minor=body.daily_limit_minor)
            if created and body.initial_funding_minor:  # idempotent: re-signup never re-funds
                gate.require_funding(body.initial_funding_minor, _token_ok(operator_token, x_admin_token))
                ledger.fund(conn, body.agent_id, body.initial_funding_minor)
        return {"agent_id": body.agent_id, "balance_minor": ledger.balance(conn, ledger.wallet_id_for(body.agent_id))}

    @app.get("/registry/search")
    def search(capability: Capability, max_price_minor: int | None = None,
               conn: sqlite3.Connection = Depends(get_conn)) -> list[RankedCard]:
        return registry.search(conn, capability, max_price_minor)

    @app.get("/wallets/{agent_id}")
    def wallet(agent_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, int | str | None]:
        wid = ledger.wallet_id_for(agent_id)
        row = conn.execute("SELECT max_per_order_minor, daily_limit_minor FROM wallets WHERE wallet_id = ?",
                           (wid,)).fetchone()
        return {"wallet_id": wid, "balance_minor": ledger.balance(conn, wid),
                "max_per_order_minor": row["max_per_order_minor"] if row else None,
                "daily_limit_minor": row["daily_limit_minor"] if row else None,
                "spent_today_minor": ledger.spent_today(conn, wid)}

    # ---------------------------------------------------------------- payment lifecycle
    @app.post("/escrow/hold")
    def hold(req: HoldRequest, conn: sqlite3.Connection = Depends(get_conn)) -> PaymentReceipt:
        gate.require_hold(req.quote.amount_minor)
        with transaction(conn):
            return escrow.hold(conn, req, s.payment_secret)

    @app.post("/orders/expire")
    def expire_orders(conn: sqlite3.Connection = Depends(get_conn)) -> list[OrderView]:
        with transaction(conn):
            return escrow.expire_undelivered(conn, s.order_ttl_seconds)

    @app.post("/orders/{order_id}/delivered")
    def delivered(order_id: str, notice: DeliveryNotice, conn: sqlite3.Connection = Depends(get_conn)) -> OrderView:
        with transaction(conn):
            return escrow.mark_delivered(conn, order_id, notice, s.payment_secret)

    @app.post("/orders/{order_id}/accept")
    def accept(order_id: str, report: QualityReport, conn: sqlite3.Connection = Depends(get_conn)) -> OrderView:
        with transaction(conn):
            return escrow.settle(conn, order_id, report, s.fee_bps)

    @app.post("/disputes")
    def dispute(req: DisputeRequest, conn: sqlite3.Connection = Depends(get_conn)) -> DisputeOutcome:
        ruling, run = None, None
        if guardian_llm and escrow.get_order(conn, req.order_id)["status"] == "DELIVERED":
            from agentledger.agents import guardian  # LLM investigation runs outside the write transaction

            ruling, run = guardian.investigate(s, req)
        with transaction(conn):
            outcome = disputes.open_and_resolve(conn, req, s.fee_bps, ruling, run.run_id if run else None)
            if run is not None:
                telemetry.persist_run(conn, run, orders_touched=1)
        return outcome

    # ---------------------------------------------------------------- agent telemetry (AI FinOps)
    @app.post("/telemetry/agent-runs")
    def store_run(report: AgentRunReport, orders_touched: int = 0,
                  conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, str]:
        with transaction(conn):
            telemetry.persist_run(conn, report, orders_touched)
        return {"run_id": report.run_id}

    @app.get("/agent-runs")
    def agent_runs(limit: int = 20, parent_run_id: str | None = None,
                   conn: sqlite3.Connection = Depends(get_conn)) -> list[dict[str, object]]:
        sql = "SELECT * FROM agent_runs" + (" WHERE parent_run_id = ?" if parent_run_id else "")
        params: tuple[object, ...] = (parent_run_id,) if parent_run_id else ()
        rows = conn.execute(sql + " ORDER BY started_at DESC LIMIT ?", (*params, min(limit, 200))).fetchall()
        return [dict(r) for r in rows]

    @app.get("/agent-runs/{run_id}")
    def agent_run(run_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> AgentRunReport:
        report = telemetry.live_snapshot(run_id) or telemetry.load_run(conn, run_id)
        if report is None:
            raise DomainError(f"unknown run {run_id}", 404)
        return report

    @app.get("/orders")
    def orders(conn: sqlite3.Connection = Depends(get_conn)) -> list[OrderView]:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at").fetchall()
        return [escrow.to_view(r) for r in rows]

    @app.get("/ledger/check")
    def ledger_check(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, int | bool]:
        """Reconciliation: every txn balances and escrow equals the money still owed on open orders."""
        unbalanced = conn.execute(
            "SELECT COUNT(*) FROM (SELECT txn_id FROM ledger_entries GROUP BY txn_id HAVING SUM(amount_minor) <> 0)"
        ).fetchone()[0]
        open_minor = conn.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) FROM orders WHERE status IN ('FUNDS_HELD','DELIVERED','DISPUTED')"
        ).fetchone()[0]
        escrow_minor = ledger.balance(conn, ledger.ESCROW)
        return {"unbalanced_txns": unbalanced, "escrow_minor": escrow_minor, "open_orders_minor": open_minor,
                "ok": unbalanced == 0 and escrow_minor == open_minor}

    return app
