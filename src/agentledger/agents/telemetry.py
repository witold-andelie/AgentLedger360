"""Agent run telemetry: every LLM call (tokens, cost) and tool call is a step of an AgentRunReport.

- RunRecorder meters the run and enforces the budgets (tool calls, micro-USD cost).
- LIVE exposes running reports to the web API so the UI can watch an agent think.
- persist_run writes the trace and its outbox events (llm.usage, agent.run.finished) in the caller's
  transaction, so AI cost reaches the warehouse like any other business event (rule R3).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from agentledger.agents import accounting, llm
from agentledger.config import Settings
from agentledger.contracts import AgentRunReport, AgentStep, EventType
from agentledger.db import emit_event, new_id, now_iso

DETAIL_LIMIT = 1_500  # characters of tool output kept per step (the UI shows it, the DB stores it)

LIVE: dict[str, AgentRunReport] = {}
_LIVE_LOCK = threading.Lock()


def clip(text: str, limit: int = DETAIL_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [+{len(text) - limit} chars]"


def live_snapshot(run_id: str) -> AgentRunReport | None:
    with _LIVE_LOCK:
        report = LIVE.get(run_id)
        return report.model_copy(deep=True) if report else None


def live_children(parent_run_id: str) -> list[AgentRunReport]:
    with _LIVE_LOCK:
        return [r.model_copy(deep=True) for r in LIVE.values() if r.parent_run_id == parent_run_id]


def clear_live() -> None:
    with _LIVE_LOCK:
        LIVE.clear()


class RunRecorder:
    def __init__(self, s: Settings, *, agent_id: str, role: str, goal: str,
                 parent_run_id: str | None = None) -> None:
        self.model = llm.model_name(s)
        self.price = accounting.price_for(self.model, s)
        self.max_cost_micro = int(s.agent_max_cost_usd * 1_000_000)
        self.max_tool_calls = s.agent_max_tool_calls
        self.report = AgentRunReport(run_id=new_id("run"), agent_id=agent_id, role=role, goal=goal,
                                     provider=s.llm_provider, model=self.model, parent_run_id=parent_run_id,
                                     started_at=now_iso())
        with _LIVE_LOCK:
            LIVE[self.report.run_id] = self.report

    @property
    def run_id(self) -> str:
        return self.report.run_id

    def _add(self, step: AgentStep) -> AgentStep:
        with _LIVE_LOCK:
            step.seq = len(self.report.steps) + 1
            step.at = now_iso()
            self.report.steps.append(step)
        return step

    def llm_call(self, node: str, message: Any, started: float, text: str = "") -> AgentStep:
        tokens_in, tokens_out = accounting.usage_from_message(message)
        cost = accounting.cost_micro_usd(self.price, tokens_in, tokens_out)
        calls = [c.get("name") for c in getattr(message, "tool_calls", None) or []]
        step = self._add(AgentStep(seq=0, kind="llm", name=node,
                                   detail={"text": clip(text), "tool_calls": calls},
                                   input_tokens=tokens_in, output_tokens=tokens_out, cost_micro_usd=cost,
                                   latency_ms=int((time.perf_counter() - started) * 1000)))
        with _LIVE_LOCK:
            r = self.report
            r.llm_calls += 1
            r.input_tokens += tokens_in
            r.output_tokens += tokens_out
            r.cost_micro_usd += cost
        return step

    def tool_call(self, name: str, args: dict[str, Any], result: str, started: float, ok: bool = True) -> None:
        self._add(AgentStep(seq=0, kind="tool", name=name,
                            detail={"args": args, "result": clip(result), "ok": ok},
                            latency_ms=int((time.perf_counter() - started) * 1000)))
        with _LIVE_LOCK:
            self.report.tool_calls += 1

    def note(self, kind: str, name: str, **detail: Any) -> None:
        self._add(AgentStep(seq=0, kind=kind, name=name, detail=detail))

    def budget_exhausted(self) -> str | None:
        r = self.report
        if r.tool_calls >= self.max_tool_calls:
            return f"tool-call budget {self.max_tool_calls} reached"
        if r.cost_micro_usd >= self.max_cost_micro:
            return f"cost budget {accounting.format_usd(self.max_cost_micro)} reached"
        return None

    def finish(self, status: str, summary: str) -> AgentRunReport:
        with _LIVE_LOCK:
            self.report.status = status
            self.report.summary = summary
            self.report.finished_at = now_iso()
        return self.report


def persist_run(conn: sqlite3.Connection, report: AgentRunReport, orders_touched: int = 0) -> None:
    """Write the run + steps + outbox events. Call inside db.transaction (one atomic unit)."""
    r = report
    conn.execute(
        "INSERT OR REPLACE INTO agent_runs (run_id, agent_id, role, goal, provider, model, status, parent_run_id,"
        " started_at, finished_at, summary, tool_calls, llm_calls, input_tokens, output_tokens, cost_micro_usd)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (r.run_id, r.agent_id, r.role, r.goal, r.provider, r.model, r.status, r.parent_run_id, r.started_at,
         r.finished_at or now_iso(), r.summary, r.tool_calls, r.llm_calls, r.input_tokens, r.output_tokens,
         r.cost_micro_usd),
    )
    conn.execute("DELETE FROM agent_steps WHERE run_id = ?", (r.run_id,))
    conn.executemany(
        "INSERT INTO agent_steps (run_id, seq, kind, name, detail_json, input_tokens, output_tokens,"
        " cost_micro_usd, latency_ms, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(r.run_id, st.seq, st.kind, st.name, json.dumps(st.detail, default=str), st.input_tokens,
          st.output_tokens, st.cost_micro_usd, st.latency_ms, st.at or now_iso()) for st in r.steps],
    )
    for st in r.steps:
        if st.kind == "llm":
            emit_event(conn, EventType.LLM_USAGE, r.run_id, {
                "run_id": r.run_id, "agent_id": r.agent_id, "role": r.role, "provider": r.provider,
                "model": r.model, "node": st.name, "input_tokens": st.input_tokens,
                "output_tokens": st.output_tokens, "cost_micro_usd": st.cost_micro_usd, "latency_ms": st.latency_ms,
            })
    emit_event(conn, EventType.AGENT_RUN_FINISHED, r.run_id, {
        "run_id": r.run_id, "agent_id": r.agent_id, "role": r.role, "status": r.status,
        "parent_run_id": r.parent_run_id, "tool_calls": r.tool_calls, "llm_calls": r.llm_calls,
        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_micro_usd": r.cost_micro_usd,
        "orders_touched": orders_touched,
    })
    with _LIVE_LOCK:  # finished runs are served from the DB from now on
        LIVE.pop(r.run_id, None)


def load_run(conn: sqlite3.Connection, run_id: str) -> AgentRunReport | None:
    row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    steps = [
        AgentStep(seq=s["seq"], kind=s["kind"], name=s["name"], detail=json.loads(s["detail_json"]),
                  input_tokens=s["input_tokens"], output_tokens=s["output_tokens"],
                  cost_micro_usd=s["cost_micro_usd"], latency_ms=s["latency_ms"], at=s["at"])
        for s in conn.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run_id,))
    ]
    return AgentRunReport(**{k: row[k] for k in AgentRunReport.model_fields if k != "steps"}, steps=steps)


def new_job_id() -> str:
    return new_id("job")
