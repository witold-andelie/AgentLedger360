# Half-day hackathon plan (two laptops)

## 1. One sentence
**AI agents buy and sell "market intelligence" from each other in a marketplace**: the buyer agent discovers sellers through an agent card → HTTP 402 quote → escrow payment →
after the data arrives, acceptance runs automatically against the contract → settlement, or a dispute in which deterministic arbitration re-runs acceptance and decides the refund → reputation update → every event lands in the warehouse,
which produces Customer 360, agent reliability, and data-quality reports.

| Review requirement (Case 02) | Our implementation |
|---|---|
| Agent-to-agent discovery | `/.well-known/agents.json` agent card + a registry ranked by reputation − price |
| Payments | HTTP 402 quote → escrow → Ed25519 receipt as the `X-Payment` header → delivery |
| Wallets | Double-entry ledger, one wallet per agent, spend authorization (per-transaction / daily limits), survival tiers |
| Dispute resolution | The arbiter recomputes the hash and re-runs acceptance; a rule table decides full refund / partial refund / rejection |
| "And more" | Reputation moves with outcomes, an event-sourced warehouse, 9 data-quality and reconciliation checks, and the LLM only explains — it never moves money |

## 2. Trade-offs versus the original outline (half-day version)

| Original outline (2 days) | Half-day version | Reason |
|---|---|---|
| PostgreSQL | SQLite (core.db + attach analytics.db) | Zero install; the OLTP/OLAP split across two schemas is kept |
| Kafka | outbox table + cursor polling (same contract) | Stable for the demo; in an interview, say it "can be swapped 1:1 for a Kafka consumer" |
| Airflow | `analytics/pipeline.py` topological DAG + run log | Same task dependencies, idempotency, and failure propagation |
| LangGraph | Plain Python state machine + optional Claude | Zero learning cost; the LLM only explains (R1) |
| CSV cleaning service | Stock signal / feature / quote services (zoomcamp) | Acceptance is quantifiable (hit rate, Rank IC), so disputes have an objective basis |
| Streamlit | React + Vite frontend, served by FastAPI, deployed on Render | Same pattern as your EuroGoal project; that experience transfers directly |
| K8s | Not doing it | A Render Blueprint is enough |

## 3. Split of work (per OPM SD4)

| | Dev A / Laptop A | Dev B / Laptop B |
|---|---|---|
| Python | **3.11** (`.venv311`) | **3.13** (`.venv313`) |
| Owns | `economy/` `agents/` `platform_api.py` `runner.py` `server.py` `sellers/app.py` `Dockerfile` `render.yaml` | `market/` `sellers/catalog.py` `analytics/` `sql/marts` `sql/quality_checks.sql` `sql/002_analytics.sql` `frontend/` |
| Shared | `contracts.py`, `sql/001_core.sql`, `docs/opm/*` (R15: both people change these together) | same as left |

The two machines run different Python versions, so **every merge is naturally a 3.11/3.13 compatibility test**.

## 4. Schedule (about 5.5 hours)

| Time | A | B |
|---|---|---|
| 0:00–0:30 | Together: create a private GitHub repo, get `check_compat` green on both machines, read through the OPM, confirm the contract freeze | same as left |
| 0:30–2:00 | Escrow timeout refund (CANCELLED), seller-signed delivery, first Render deploy | Frontend Market page (per FRONTEND_RULES), signal tuning |
| 2:00–2:30 | Integration: frontend ↔ `/api/round`, two-machine mode (B runs sellers) | same as left |
| 2:30–4:00 | Optional: price negotiation, LLM explanation switch | Agents / Customer360 / DataQuality pages |
| 4:00–4:45 | Render deploy (single service), warm-up, screen-recording backup | Screenshots, README numbers, OPM diagram into the slides |
| 4:45–5:30 | Rehearse the 3-minute demo + interview talking points | same as left |

**Cut order** (when time runs short, cut from the top down): price negotiation → LLM → two-machine / two-service mode → seller signatures → timeout refund → frontend pages 2–4.
**Never cut**: the Market page demo, dispute refunds, reconciliation and DQ all green, and 3.11/3.13 both green.

## 5. Git rules
- `main` is always demoable; personal branches are `a/*` and `b/*`, **merge once an hour**, and run `scripts/check_compat.*` before each merge.
- `AgentLedger360_Case02_Architecture_Python311_313.md` stays local only (already in `.gitignore` / `.dockerignore`).
- A change to a contract, state, or event → in the same commit, update `docs/opm/agentledger_opm.dot` + `OPM_GUIDE.md` and re-render.

## 6. 3-minute demo script
1. (20s) The problem: agents that trade data and services need discovery, payment, acceptance, and dispute handling, and the whole path must be auditable.
2. (60s) On the Market page, click "Run market round": the cheapest `sig-hype` is selected → the data is stale → **full refund**;
   `sig-rsi` misses its performance bar → **50% refund**; `sig-momentum` → **settled**. Click again: hype's reputation has dropped, so it is no longer selected.
3. (40s) Agents page: reputation, success rate, and latency (= IT operations analytics); Customer 360 + RFM (= SAP CPIT Customer 360).
4. (30s) Data quality page: all 9 checks green, escrow balance = open orders (reconciliation), and the event stream is replayable.
5. (30s) One OPM diagram: the LLM only explains and never moves money (R1), a state change and its event share one transaction (R3), and 3.11/3.13 are both green.

## 7. Mapping to SAP iXp (IT Data & Analytics, CPIT, Customer 360 / BDC)
- **SQL (required)**: window functions (latest state, NTILE for RFM), CTEs, reconciliation queries, and DQ checks are all handwritten SQL.
- **Data pipeline**: outbox → raw_events (dedupe, cursor) → dim/fact → KPI views; idempotent rebuild; run log.
- **Customer 360**: `v_customer_360` + `v_customer_rfm` (reuse the RFM pattern from your golden_dragon_prague project).
- **Cloud infrastructure analytics**: seller latency, success rate, and dispute rate = service reliability metrics.
- **AI prototype**: an agent economy plus optional Claude, with a governance boundary (R1).
- **Governance / PO support**: the OPM model, rule table R1–R16, the DoD, and the compatibility gate.
- Wording: say only that this "conceptually corresponds to a BDC data product / data contract". **Do not claim integration with any SAP product**.

## 8. Sources we borrowed from (your 30 repos and 97 stars, already scanned)

| Source | What we took | Where it landed |
|---|---|---|
| DataTalksClub/stock-markets-analytics-zoomcamp | M1 data sources, M2 features (growth_Nd, RSI…), M3 direction prediction, M4 backtest and fees, M5 scripting + SQLite + scheduling | `market/*`, `analytics/pipeline.py` |
| witold-andelie/stock_analysis_wentao (HW2) | RSI<30 oversold entry strategy | `signals.rsi_reversion` (seller sig-rsi) |
| witold-andelie/golden_dragon_prague | RFM segmentation (NTILE), star schema, DQ process, interview-guide style | `v_customer_rfm`, section 7 of this document |
| witold-andelie/quant-alpha-foundation | IC / robustness diagnostics, synthetic-data fallback, Bruin topological execution, CI | `backtest.rank_ic`, `data.py`, `pipeline.py` |
| witold-andelie/PerpPulse | Evidence hashes, reconciliation scorecard, as-of cutoff, validation notes that do not overclaim | `disputes.py`, `quality_checks.sql`, README "Honest limits" |
| witold-andelie/revio | LLM orchestration + a deterministic analyzer, evidence-driven conclusions | R1: the LLM only explains; the rule table decides |
| EuroGoal (football match prediction) | React+Vite frontend, i18n, two-stage Docker build, Render Blueprint | `frontend/`, `Dockerfile`, `render.yaml` |
| Conway-Research/automaton | Balance decides the "survival tier", the wallet is the identity, constitutional rules | `buyer.TIERS`, the rule table |
| HKUDS/AI-Trader | An agent reads SKILL.md to onboard itself; signal publishing and points | `/SKILL.md`, `/.well-known/agents.json` |
| TauricResearch/TradingAgents | Analyst role split, point-in-time to prevent look-ahead | Seller personas, the `point_in_time` check |
| gplearn / GPLearnFinance3D / AlphaMaster | IC, IR, and RankIC factor evaluation | Acceptance clause `min_rank_ic` |
| freqtrade | dry-run / fee modeling | `backtest.fee_bps` |
| Coral-Protocol/AgentRadio | Passive awareness on a shared channel | Optional extension: the buyer subscribes to `reputation.updated` events |
| tt-a1i/archify, Recordly / openscreen | Architecture diagrams, screen recording | slides and the demo backup video |

## 9. Risks and contingencies
| Risk | Contingency |
|---|---|
| Poor venue network / Render sleep | Local `python -m agentledger.demo` and the local frontend can demo at any time; record the screen in advance |
| yfinance rate limits | Default to synthetic (deterministic, offline) |
| The two machines cannot reach each other | Single-machine in-process mode is functionally identical |
| No LLM quota | Default `AL_LLM=0`; every path is deterministic |
