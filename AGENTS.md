# AGENTS.md - read this before touching the code

AgentLedger 360: AI agents discover, pay for (HTTP 402 + escrow), verify and dispute market-intelligence
services; every state change is an outbox event feeding a SQL warehouse (Customer 360, agent reliability,
data quality). Hackathon project, half-day budget, two developers on two laptops.

## 1. The system model is the map
- `docs/opm/agentledger_opm.dot` (render: `python scripts/render_opm.py`) is the OPM model of the whole system.
  Read SD, then follow the in-zoom edges: SD1 trade -> SD2 dispute -> SD3 analytics -> SD4 dev/deploy;
  SD5 unfolds how the LLM agents reason (tool loop, token meter, budgets).
- Every process shows its implementing module (grey) and the rules it must obey (orange `[R..]`).
- `docs/opm/OPM_GUIDE.md` has the OPL text, the thing-to-code table, the rules with their tests, and open gaps.
- If your change adds/removes/renames a process, object, state, event type or contract field, update the
  .dot + OPM_GUIDE.md + re-render IN THE SAME CHANGE.

## 2. Hard rules (full list R1-R18 in OPM_GUIDE.md section 4)
- LLM agents choose actions and propose rulings, but every money move is authorized by deterministic tools/policy,
  and a guardian ruling only counts inside the policy band (R1). `economy/` must never import `agents/`.
- Every LLM call is metered in integer micro-USD and runs stop at the tool/cost budget (R17); agent reports may
  only cite tool results (R18). Tests never call a real LLM: use `tests/scripted_llm.py`.
- Money is integer minor units, double-entry, balanced (R2).
- State change and its outbox event share one transaction (R3); order status only via `escrow._transition` (R4).
- `src/agentledger/contracts.py` and `src/agentledger/sql/001_core.sql` are frozen interfaces (R15).
- Every Python file must run on CPython 3.11 AND 3.13 (R13): no `type X = ...`, no `class C[T]`, no
  `sqlite3.connect(autocommit=...)`, no `itertools.batched`/`typing.override`; ISO-string timestamps in SQLite.
- `AgentLedger360_Case02_Architecture_Python311_313.md` is private: never commit, copy or publish it (R16).
- Frontend: follow `docs/FRONTEND_RULES.md` (stack, tokens, i18n, states); backend calls only through `frontend/src/api.js` (R14).

## 3. Commands
```bash
uv venv .venv313 --python 3.13 && uv pip install --python .venv313 -e ".[dev,ml,agent]"
python -m agentledger.demo --reset --as-of 2026-10-07     # CLI end-to-end demo
uvicorn agentledger.server:create_app --factory --port 8000  # API (+ frontend/dist if built)
python -m agentledger.analytics.pipeline                  # rebuild marts + DQ checks
scripts/check_compat.ps1   # or .sh - lint + tests on 3.11 and 3.13; must be green before merge
```

## 4. AI agents (SD5)
- `agents/graph.py`: LangGraph plan -> react (tool loop, budget) -> reflect, shared by both agents (revio pattern).
- `agents/buyer_agent.py`: procurement agent, 7 tools, policy enforced inside the tools.
- `agents/guardian.py`: dispute investigator, 7 read-only tools + `submit_ruling`, validated by `disputes.validate`.
- `agents/llm.py`: provider factory (`AL_LLM_PROVIDER` = mistral default | anthropic | openai_compat); `AL_AGENT_MODE`
  auto/llm/rule. `agents/accounting.py`: price table + micro-USD cost. `agents/telemetry.py`: trace, LIVE view, persist.
- One live round with `mistral-medium-latest` costs about $0.08-0.10 (buyer ~19 LLM calls, guardian ~4 per dispute).

## 5. Ownership (SD4)
- Laptop A / Dev A (3.11): `economy/`, `agents/`, `platform_api.py`, `runner.py`, `server.py`, `transport.py`,
  `sellers/app.py`, `Dockerfile`, `render.yaml`.
- Laptop B / Dev B (3.13): `market/`, `sellers/catalog.py`, `analytics/`, `sql/marts/`, `sql/quality_checks.sql`,
  `sql/002_analytics.sql`, `frontend/`.
- Shared (change together): `contracts.py`, `sql/001_core.sql`, `docs/opm/*`.
