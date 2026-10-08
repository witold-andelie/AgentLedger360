# AgentLedger 360 — OPM Rule-Framework Guide (for the agent / developer taking over)

This directory is the project's **single source of truth** for the system model:

| File | Role |
|---|---|
| `agentledger_opm.dot` | OPM diagram (ISO 19450 notation, Graphviz DOT). **Change the model only in this file** |
| `agentledger_opm.svg` | Full diagram (all OPDs + legend + rule table) |
| `opm_SD.svg` … `opm_SD4.svg` | One image per OPD, for easier reading |
| `OPM_GUIDE.md` (this document) | OPL text, thing-to-code map, rule-to-test map, handover workflow |

Re-render with `python scripts/render_opm.py` (requires the Graphviz `dot` binary).

---

## 0. Handover workflow (mandatory)

1. **Read SD first, then follow the dashed "in-zoomed in" edges downward**: SD → SD1 (trade) → SD2 (dispute) → SD3 (analytics) → SD4 (dev and deploy).
2. **Before changing code**: in the DOT, find the process (ellipse) you are about to change. Read its grey small print (implementing module) and its orange label `[R…]` (rules it must obey).
3. **After changing code**, if you changed any of the following, update `agentledger_opm.dot` and this document and re-render **in the same commit**:
   - added, removed, or renamed a process, an object, or a state (for example a new `CANCELLED` timeout-refund flow)
   - changed an object's set of states (`OrderStatus`, `DisputeDecision`, …)
   - changed `contracts.py`, `sql/001_core.sql`, an event type, or a payload (R15: both developers must agree)
   - changed where a rule is enforced
4. Before every merge, run the compatibility gate: `scripts/check_compat.ps1` (Windows) or `scripts/check_compat.sh` (3.11 + 3.13 + ruff).
5. If you are not sure whether a change breaks a rule, look at the "How verified" column in section 4 and run the corresponding test.

---

## 1. Notation cheat sheet (matches the legend)

| Mark | DOT syntax | Meaning |
|---|---|---|
| Rectangle (green) | `shape=box color="#2E7D32"` | Object (informational) |
| Double border | `peripheries=2` | Physical object (a person, a laptop) |
| Dashed border | `style=dashed` | Environmental object (outside the system: Render, the Claude API, the jury, a market-data source) |
| Ellipse (blue) | `shape=ellipse color="#1565C0"` | Process |
| Rounded box inside an object (brown) | HTML nested table `STYLE="rounded"` + `PORT` | State; an edge to `Object:port` is a state-level link |
| Plain arrow, object → process | default | Consumption |
| Plain arrow, process → object | default | Result |
| Double-headed arrow | `dir=both` | Effect (changes the object without consuming it) |
| Open-circle arrowhead | `arrowhead=odot` | Instrument (a non-human enabler — **in OPM an AI agent is an instrument, not an agent**) |
| Filled-circle arrowhead | `arrowhead=dot` | Agent (a human enabler) |
| Label `c` | `label="c: ..."` | Condition link: if the condition is not met, skip that process |
| Thick blue arrow "invokes" | `style=bold arrowhead=vee` | Invocation link |
| Black triangle | `shape=triangle fillcolor=black` | Aggregation-participation |
| White triangle, double outline | `shape=triangle peripheries=2` | Exhibition-characterization (attribute) |
| Grey dashed "in-zoomed in SDn" | `lhead=cluster_SDn` | Unfolding: the parent process is expanded in the child OPD |
| Orange `[R2 R5]` | third line of the process label | Rules that process must obey (see section 4) |

In an in-zoomed diagram, processes **from top to bottom = time order** (the order is pinned by invisible edges).

---

## 2. OPL (Object-Process Language) — one-to-one with the diagram

### SD — System Diagram
- **Trading Market Intelligence** requires Buyer Agent, Seller Agents, Clearing House and Price Oracle.
- **Trading Market Intelligence** requires Claude API, if `AL_LLM=1` (condition).
- **Trading Market Intelligence** affects Double-entry Ledger.
- **Trading Market Intelligence** yields Verified Market Intelligence and Event Log.
- **Producing Analytics** requires Event Log and yields Analytics Warehouse & KPIs.
- Dev Team handles **Developing & Deploying**, which yields Running Web App.
- Running Web App is an instrument of **Trading Market Intelligence** and **Producing Analytics**.
- Hackathon Jury & SAP Interviewer (environmental) is the beneficiary; it reviews KPIs and outcomes.
- Trading Market Intelligence zooms into SD1; Producing Analytics zooms into SD3; Developing & Deploying zooms into SD4.

### SD1 — Trading Market Intelligence (in-zoomed)
- Seller Agent exhibits Reputation. Buyer Wallet exhibits Spend Mandate.
- **Publishing Agent Cards** requires Seller Agent and yields Agent Card.
- **Registering** requires Agent Card, yields Registry and Reputation (initial 0.5).
- **Funding Buyer** yields Money at state *in buyer wallet* (once per buyer).
- **Assessing Tier** requires Buyer Agent and Buyer Wallet, and yields Survival Tier at one of *normal, low_compute, critical, dead*.
- **Discovering & Ranking** occurs if Survival Tier is not *dead*; requires Registry and Reputation; yields Ranked Cards.
- **Quoting (HTTP 402)** requires the top Ranked Card; yields Quote at *issued* and Acceptance Criteria.
- **Holding in Escrow** occurs if Quote is *issued* (not *expired*) and the amount is within Spend Mandate; changes Money from *in buyer wallet* to *in escrow*; yields Order at *FUNDS_HELD* and Payment Receipt.
- **Delivering (paid)** occurs if Payment Receipt is valid; changes Quote from *issued* to *redeemed*; yields Deliverable, including `content_hash` and the seller HMAC `content_signature` (`receipts.sign_content`; per-seller key derived from the shared secret).
- **Recording Delivery** changes Order from *FUNDS_HELD* to *DELIVERED* only after `receipts.verify_content` accepts the seller HMAC (R4, R7). A missing or bad signature is rejected and the order stays *FUNDS_HELD*. The buyer forwards the seller's hash and signature; it does not report an unverified hash of its own.
- **Expiring** occurs if Order is *FUNDS_HELD* and undelivered longer than the order TTL; changes Money from *in escrow* back to *in buyer wallet* (full refund, no fee) and Order to *CANCELLED*; affects Reputation (failed outcome); invokes **Emitting Events** (`payment.refunded` with status CANCELLED).
- **Verifying Contract** requires Deliverable, Acceptance Criteria and Price Oracle; yields Quality Report at *passed* or *failed*.
- **Settling** occurs if Quality Report is *passed*; changes Order from *DELIVERED* to *COMPLETED*; changes Money from *in escrow* to *with seller* and *platform fees*; affects Reputation (+).
- **Resolving Dispute** occurs if Quality Report is *failed*; changes Order from *DELIVERED* (detail in SD2).
- Holding in Escrow, Recording Delivery, Expiring, Settling and Resolving Dispute invoke **Emitting Events**, which yields Outbox Event.

### SD2 — Resolving Dispute (in-zoomed)
- **Opening** changes Order from *DELIVERED* to *DISPUTED*.
- **Checking Evidence Hash** yields Evidence at *hash matches* or *hash mismatch*.
- **Re-executing Acceptance** occurs if Evidence is *hash matches*; requires Acceptance Criteria (frozen at hold); yields Re-executed Quality Report.
- **Deciding** requires Re-executed Quality Report (or Evidence at *hash mismatch* → RELEASE); yields Decision at *RELEASE*, *REFUND_PARTIAL* or *REFUND_FULL*.
- **Refunding** occurs if Decision is *REFUND_PARTIAL* or *REFUND_FULL*; consumes Escrowed Money; changes Order from *DISPUTED* to *PARTIALLY_REFUNDED* or *REFUNDED*.
- **Releasing** occurs if Decision is *RELEASE*; consumes Escrowed Money; changes Order from *DISPUTED* to *COMPLETED*.
- Refunding and Releasing invoke **Updating Reputation**, which affects Seller Reputation.
- **Re-executing Acceptance** also yields Policy Band (allowed decision + refund % range, `disputes.policy_band`).
- **Guardian Investigating** occurs if AL_AGENT_MODE resolves to llm; requires LLM (guardian brain), Re-executed
  Quality Report and Policy Band; yields Ruling Proposal (decision, refund %, cited checks). Unfolded in SD5.
- **Deciding** requires Policy Band and, if it is inside the band and cites failed checks, Ruling Proposal;
  otherwise it uses the band default (`disputes.validate`).
- **Recording** yields Dispute Record (rationale + guardian text + ruling source).
- *The LLM reaches Deciding only through `disputes.validate`; nothing from the LLM reaches Refunding or Releasing* (R1).

### SD3 — Producing Analytics (in-zoomed)
- **Ingesting Events** requires Outbox (rows with seq > cursor); affects Ingest Cursor; yields Raw Events; invokes **Logging Run**.
- **Building dim_agents** and **Building fact_orders** require Raw Events and yield dim_agents and fact_orders.
- dim_agents and fact_orders feed KPI Views (`v_customer_360`, `v_agent_performance`, `v_daily_kpis`, `v_customer_rfm`).
- **Checking Data Quality** requires fact_orders and Core OLTP tables (reconciliation); yields DQ Result at *PASS* or *FAIL* (x9).
- **Serving API** requires KPI Views and DQ Result; yields API JSON.
- Viewer handles **Rendering Dashboard**, which requires API JSON and Shared Round State and yields React Pages
  (Market with AI-spend KPIs, Agent Console with live trace and cost, Agents with AI cost tables, Customer 360,
  Data quality).
- Viewer handles **Running Round in Background**, which yields Background Round Job at *running*, then
  *completed* or *failed*; a completed job invokes the pipeline (Ingesting Events ...).
- **Polling Round** requires Background Round Job at *running* and affects Shared Round State, so a round started
  on Market is the same round the Agent Console shows.

### SD5 — Agent Reasoning (unfolded; used by Buyer Agent in SD1 and Guardian in SD2)
- **Planning** requires Goal and LLM Provider; yields Message History and Agent Run Report at *running*.
- **Acting** requires LLM Provider; affects Message History; invokes **Calling Tool** once per tool_call and
  **Metering** once per LLM call.
- **Calling Tool** requires Tool Set and occurs if the Tool-side Policy Gate allows the call (rejections come back
  to the model as text).
- **Metering** affects Token Meter and invokes **Checking Budget**, which yields Budget at *within* or *exhausted*.
- **Reflecting** occurs when the model stops calling tools or Budget is *exhausted*; changes Agent Run Report from
  *running* to *completed* (or *budget_stopped* / *failed*).
- **Grounding** affects Agent Run Report: order ids not produced by tool results are removed.
- **Auto-finalizing** requires the Policy Gate: deliveries the model left undecided are verified, then accepted
  or disputed by policy.
- **Persisting Telemetry** requires Agent Run Report at *completed*; yields llm.usage and agent.run.finished events
  (one transaction with the trace) that feed SD3.

### SD4 — Developing & Deploying (in-zoomed)
- Codebase consists of Frozen Contract, Economy part (A) and Market & Analytics part (B).
- Dev A and Dev B handle **Freezing Contract**, which yields Frozen Contract.
- Dev A handles **Implementing A**; Dev B handles **Implementing B**; both require Frozen Contract.
- **Checking Compatibility** requires both parts; yields Compat Gate at *green on 3.11 AND 3.13* or *red* (red → fix).
- **Merging** occurs if Compat Gate is *green*; yields GitHub main branch.
- **Building Image** yields Container Image; **Deploying** yields Render Web Service at *asleep*.
- **Warming Up** changes Render Web Service from *asleep* to *awake*.
- Presenter handles **Presenting Demo**, which occurs if Render Web Service is *awake* and requires Demo Data at *fresh*.
- Presenter handles **Resetting Demo**, which requires Admin Token (only if one is set) and changes Demo Data from
  *used* to *fresh* (all rows wiped, sellers re-registered, buyer refilled to $30).

---

## 3. Thing → code map (navigation table for handover)

| OPM thing | Kind | Code | Owner |
|---|---|---|---|
| Agent Card / Quote / Receipt / Deliverable / Quality Report / Decision | object | `src/agentledger/contracts.py` | A+B (frozen) |
| Order (7 states) | object | `contracts.OrderStatus`, `core.orders`, `economy/escrow.py` | A |
| Money / Ledger | object | `economy/ledger.py`, `core.ledger_entries` | A |
| Registry / Reputation | object | `economy/registry.py`, `core.agents` | A |
| Survival Tier / Buyer Agent | object | `agents/buyer.py` | A |
| Seller Agents | object | `sellers/catalog.py` (B), `sellers/app.py` (A: 402 paywall) | A/B |
| Price Oracle | environmental object | `market/data.py` | B |
| Acceptance Criteria / Verifying | object / process | `market/quality.py`, `market/backtest.py` | B |
| Signals (sellers' models) | — | `market/signals.py`, `market/features.py` | B |
| Holding / Delivering / Recording Delivery / Settling | process | `escrow.hold`, clearing-house `POST /orders/{id}/fetch` (archives rows), `escrow.mark_delivered`, `escrow.settle`, `platform_api.py` | A |
| Expiring | process | `escrow.expire_undelivered` | A |
| Resolving Dispute (SD2) | process | `economy/disputes.py` (`policy_band` / `validate`) | A |
| Guardian Investigating (SD2) | process | `agents/guardian.py` | A |
| Buyer Agent brain (SD1 → SD5) | object | `agents/buyer_agent.py` (7 tools + tool-side policy) | A |
| Planning / Acting / Reflecting (SD5) | process | `agents/graph.py` (LangGraph) | A |
| LLM Provider (SD5) | environmental object | `agents/llm.py` (Mistral by default / Claude / OpenAI-compatible) | A |
| Token Meter / Budget / Agent Run Report (SD5) | object | `agents/accounting.py`, `agents/telemetry.py`, `sql/003_agents.sql` | A |
| Building AI cost facts (SD3) | process | `sql/marts/fact_llm_calls.sql`, views `v_ai_cost_by_agent/model` | B |
| Agent Console page | — | `frontend/src/pages/AgentConsole.jsx` (rules §11) | frontend owner |
| Running Round in Background / Background Round Job (SD3) | process / object | `server.py` `/api/agent/rounds` | A |
| Polling Round / Shared Round State (SD3) | process / object | `frontend/src/agentRound.jsx` | frontend owner |
| AI cost page elements | — | `components/KpiRow.jsx`, `components/AiCostTables.jsx` | frontend owner |
| Resetting Demo / Demo Data / Admin Token (SD4) | process / object | `server.py` `/api/demo/reset`, `db.wipe_all`, `components/ResetDemoButton.jsx` | A |
| Emitting Events / Audit Chain | process | `db.emit_event`, `db.verify_audit_chain`, `sql/004_security.sql` | A |
| Capability switches | object | `governance.py` | A |
| Market round orchestration | process | `runner.py` (CLI `demo.py`, Web `server.py /api/round`) | A |
| Ingesting / Building / DQ / Logging | process | `analytics/ingest.py`, `analytics/pipeline.py`, `sql/marts/*`, `sql/quality_checks.sql` | B |
| KPI Views | object | `sql/002_analytics.sql` | B |
| Serving API | process | `server.py` | A |
| Rendering Dashboard | process | `frontend/` (rules: `docs/FRONTEND_RULES.md`) | frontend owner |
| Compat Gate | object | `scripts/check_compat.*`, `.github/workflows/ci.yml` | A+B |
| Container Image / Render | object | `Dockerfile`, `render.yaml` | A |

---

## 4. Rules (invariants) → where enforced → how verified

| ID | Rule | Where enforced | How verified |
|---|---|---|---|
| R1 | An LLM agent chooses actions and proposes rulings; every movement of funds is authorized by a deterministic tool or policy; a ruling takes effect only inside the policy band | tool-side checks in `buyer_agent`, `disputes.validate`, `escrow.*` | `tests/test_agents.py` (an out-of-band ruling falls back to the rule table); `economy/` must not import `agents` |
| R2 | Amounts are integer cents; each ledger transaction's debits and credits sum to 0; only treasury may be negative | `ledger.post` | `tests/test_economy.py`; DQ `ledger_txns_balanced`, `no_negative_agent_balance` |
| R3 | A state change and its outbox event share one transaction | `db.transaction` (`BEGIN IMMEDIATE`) + `emit_event` | DQ `ingestion_complete`, `oltp_vs_warehouse_order_count` |
| R4 | Order status may only be compare-and-set through `_transition` | `escrow._transition` | `test_settle_pays_seller_minus_fee_and_cannot_repeat` |
| R5 | Idempotency: repeating hold with the same key returns the same order; a buyer is funded only once; a receipt is redeemed only once | `escrow.hold`, `registry.register_buyer`, `sellers/app.py` `redeemed` | `test_hold_is_idempotent_and_receipt_verifies` |
| R6 | Check the spend mandate (per-order / daily cap) before debiting; the survival tier caps the price | `escrow.hold`, `buyer.TIERS` | `test_insufficient_funds_and_mandate_are_enforced` |
| R7 | The seller executes the task **as quoted**; it verifies the payment HMAC, the amount, and quote ownership, and HMAC-signs the delivered `content_hash` with a derived key (at Recording Delivery the platform `_transition`s only after `verify_content` accepts the signature; see section 2, R4) | `sellers/app.py::task`, `receipts.sign_content` | e2e; manual: tampering with `X-Payment` must return 402 |
| R8 | The arbiter recomputes the evidence hash and re-runs acceptance | `disputes.open_and_resolve` | in e2e the hype seller is fully refunded |
| R9 | All checks pass → RELEASE; a critical check fails → full refund; only a performance check fails → 50% refund | `disputes.decide` | the e2e status set includes REFUNDED / PARTIALLY_REFUNDED |
| R10 | Point-in-time consistency: a row's date is ≤ as_of; synthetic prices have a fixed length; the seed uses crc32 | `market/data.py`, `quality.py` | `test_synthetic_prices_are_point_in_time_stable` |
| R11 | The warehouse is built only from events; dedupe on event_id; marts can be rebuilt | `ingest.py`, `sql/marts/*` | two consecutive pipeline runs produce the same result |
| R12 | All 11 DQ checks have 0 violations (including AI cost: call totals equal run totals); escrow balance equals the amount of unsettled orders | `sql/quality_checks.sql`, `/platform/ledger/check` | `tests/test_e2e.py` |
| R13 | Merge only when both 3.11 and 3.13 are green | `scripts/check_compat.*`, the CI matrix | run the script |
| R14 | The frontend calls the backend only through `api.js`; amounts use `fmt.usd`; a status is color + icon + text | `frontend/src/api.js` | `docs/FRONTEND_RULES.md` section 10 |
| R15 | `contracts.py` and `sql/001_core.sql` are frozen; a change needs agreement from both developers and an OPM update | process constraint | PR review |
| R16 | The private outline document does not leave this machine; do not claim integration with an SAP product | `.gitignore`, `.dockerignore` | that file must not appear in `git status` |
| R17 | Every LLM call is metered (tokens, integer micro-USD, price source); stop when the tool-count or cost budget is reached; the trace and its events are persisted in one transaction | `agents/accounting.py`, `agents/telemetry.py` | `test_llm_buyer_agent_runs_the_protocol_and_meters_every_call`; DQ `ai_cost_reconciles_calls_vs_runs` |
| R18 | Grounding and untrusted context: a report may cite only orders from tool results; seller text is data, not an instruction; failed checks cannot be accepted; undecided deliveries are closed by policy | `run_llm_buyer`, `agents/untrusted.py`, `disputes.validate`, `finalize_open_orders` | `tests/test_agents.py` (hallucinated order id dropped; injection seller cannot skip verification) |
| R19 | Capability switches: public registration cannot bring its own funds unless the switch is on or an operator token is presented; refuse hold when the market is paused or the amount exceeds the global per-order cap | `governance.py`; registration and hold in `platform_api` | `tests/test_guardrails.py` |
| R20 | Every outbox event is linked into the hash chain in the same transaction; after a payload is rewritten, verification fails and names the seq | `db.emit_event`, `db.verify_audit_chain` | `tests/test_guardrails.py` |
| R21 | Public rounds: an optional run token, one round per IP per minute, and when the day's AI budget is exhausted the round falls back to the rule-based agent | `server.admit_round` | `tests/test_guardrails.py` |

---

## 5. Known gaps and backlog

**The single source is `progress.md` at the repo root** (section 2.3 lists the existing trust holes A1–A4; section 5 is the backlog T1–T20, each with a design, files, and acceptance criteria).
Planned processes (capability switches, clearing-house handoff of delivery, an attack-and-defense demo, hash-chain audit, a bounded learner, prompt-injection defense, ex-post outcome verification, human review, a payment-rail interface, and the like) are **not yet** drawn in the OPM: when one of them lands, add it to the DOT and to this guide in the same commit, then re-render.
