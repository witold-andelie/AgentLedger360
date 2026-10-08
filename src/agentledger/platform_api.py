"""Clearing house API: registry, wallets, escrow, delivery, settlement, disputes.

Run on laptop A:  uvicorn agentledger.platform_api:create_app --factory --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import hmac
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from agentledger.agents import llm, telemetry
from agentledger.config import Settings, load_settings
from agentledger.contracts import (
    AgentCard,
    AgentRunReport,
    BuyerSignup,
    Capability,
    Deliverable,
    DeliveryNotice,
    DisputeOutcome,
    DisputeRequest,
    HoldRequest,
    OrderView,
    PaymentReceipt,
    QualityReport,
    RankedCard,
    TaskSpec,
    canonical_hash,
)
from agentledger.db import connect, init_db, transaction
from agentledger.economy import DomainError, disputes, escrow, keys, ledger, receipts, registry
from agentledger.governance import Capabilities, CapabilityGate
from agentledger.transport import Router


def _token_ok(expected: str, presented: str | None) -> bool:
    if not expected or not presented or len(presented) != len(expected):
        return False
    return hmac.compare_digest(presented, expected)


def create_app(settings: Settings | None = None, operator_token: str = "",
               gate: CapabilityGate | None = None, router: Router | None = None) -> FastAPI:
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
            existing = conn.execute("SELECT 1 FROM agent_keys WHERE agent_id = ?", (card.agent_id,)).fetchone()
            agent_key = None if existing else keys.issue()
            if agent_key:
                keys.store(conn, card.agent_id, agent_key)
        body = {"agent_id": card.agent_id}
        if agent_key:
            body["agent_key"] = agent_key
        return body

    @app.post("/registry/buyers")
    def register_buyer(body: BuyerSignup, x_admin_token: str | None = Header(default=None),
                       conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, int | str]:
        with transaction(conn):
            created = registry.register_buyer(conn, body.agent_id, body.name, body.owner,
                                              max_per_order_minor=body.max_per_order_minor,
                                              daily_limit_minor=body.daily_limit_minor)
            operator = _token_ok(operator_token, x_admin_token)
            if created and body.initial_funding_minor:  # idempotent: re-signup never re-funds
                gate.require_funding(body.initial_funding_minor, operator)
                ledger.fund(conn, body.agent_id, body.initial_funding_minor)
            agent_key = None
            if created or operator:
                agent_key = keys.issue()
                keys.store(conn, body.agent_id, agent_key)
        result: dict[str, int | str] = {
            "agent_id": body.agent_id,
            "balance_minor": ledger.balance(conn, ledger.wallet_id_for(body.agent_id)),
        }
        if agent_key:
            result["agent_key"] = agent_key
        return result

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
    def hold(req: HoldRequest, x_agent_key: str | None = Header(default=None),
             conn: sqlite3.Connection = Depends(get_conn)) -> PaymentReceipt:
        gate.require_hold(req.quote.amount_minor)
        with transaction(conn):
            if not keys.matches(conn, req.buyer_agent_id, x_agent_key):
                raise DomainError("buyer key required", 403)
            return escrow.hold(conn, req, s.payment_secret)

    def _buyer_order(conn: sqlite3.Connection, order_id: str, presented: str | None) -> sqlite3.Row:
        order = escrow.get_order(conn, order_id)
        if not keys.matches(conn, order["buyer_agent_id"], presented):
            raise DomainError("buyer key required", 403)
        return order

    @app.post("/orders/expire")
    def expire_orders(conn: sqlite3.Connection = Depends(get_conn)) -> list[OrderView]:
        with transaction(conn):
            cancelled = escrow.expire_undelivered(conn, s.order_ttl_seconds)
            cutoff = (datetime.now(UTC) - timedelta(seconds=s.order_ttl_seconds)).isoformat(timespec="milliseconds")
            stale = conn.execute(
                "SELECT order_id FROM orders WHERE status = 'DELIVERED' AND delivered_at < ?", (cutoff,),
            ).fetchall()
            for item in stale:
                disputes.open_and_resolve(
                    conn,
                    DisputeRequest(order_id=item["order_id"],
                                   reason="auto-finalized: buyer did not decide before the delivery TTL"),
                    s.fee_bps,
                )
            return cancelled

    @app.post("/orders/{order_id}/fetch")
    def fetch_delivery(order_id: str, x_agent_key: str | None = Header(default=None),
                       conn: sqlite3.Connection = Depends(get_conn)) -> Deliverable:
        """The clearing house pays the seller and archives the rows. The buyer cannot report a different delivery."""
        if router is None:
            raise DomainError("seller transport is not configured", 503)
        with transaction(conn):
            order = _buyer_order(conn, order_id, x_agent_key)
        if order["status"] != "FUNDS_HELD":
            raise DomainError(f"order {order_id} is {order['status']}, only FUNDS_HELD can be fetched", 409)
        seller = conn.execute("SELECT endpoint FROM agents WHERE agent_id = ?",
                              (order["seller_agent_id"],)).fetchone()
        if seller is None or not seller["endpoint"]:
            raise DomainError("seller has no endpoint", 404)
        receipt = escrow._receipt(order, s.payment_secret)
        spec = TaskSpec(capability=Capability(order["capability"]), symbol=order["symbol"])
        started = time.perf_counter()
        response = router.post(
            f"{seller['endpoint']}/tasks", json=spec.model_dump(mode="json"),
            headers={"X-Payment": receipts.to_header(receipt)},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not 200 <= response.status_code < 300:
            raise DomainError(f"seller returned HTTP {response.status_code}", 502)
        deliverable = Deliverable.model_validate(response.json())
        content_hash = canonical_hash(deliverable.rows)
        if content_hash != deliverable.content_hash or not receipts.verify_content(
            s.payment_secret, order["seller_agent_id"], content_hash, deliverable.content_signature,
        ):
            raise DomainError("seller delivery failed signature or hash check", 409)
        notice = DeliveryNotice(content_hash=content_hash, content_signature=deliverable.content_signature,
                                latency_ms=latency_ms)
        with transaction(conn):
            escrow.mark_delivered(conn, order_id, notice, s.payment_secret)
            disputes.archive(conn, deliverable.model_copy(update={
                "content_hash": content_hash, "content_signature": deliverable.content_signature,
            }))
        return deliverable

    @app.post("/orders/{order_id}/accept")
    def accept(order_id: str, report: QualityReport, x_agent_key: str | None = Header(default=None),
               conn: sqlite3.Connection = Depends(get_conn)) -> OrderView:
        with transaction(conn):
            _buyer_order(conn, order_id, x_agent_key)
            return escrow.settle(conn, order_id, report, s.fee_bps)

    @app.post("/disputes")
    def dispute(req: DisputeRequest, x_agent_key: str | None = Header(default=None),
                conn: sqlite3.Connection = Depends(get_conn)) -> DisputeOutcome:
        with transaction(conn):
            _buyer_order(conn, req.order_id, x_agent_key)
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
