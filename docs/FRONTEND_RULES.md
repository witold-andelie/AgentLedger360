# Frontend framework and rules

> Implement frontend pages according to these rules (React + Vite; the shell, API client, i18n, and design tokens are already in place). Anyone, including an AI agent, may implement or modify pages directly, as long as they follow the rules below.
> Reference implementation: `D:\AI_Models\football match prediction\frontend` (EuroGoal). Keep the same stack and the same patterns.

## 1. Stack (same as EuroGoal; do not add dependencies)

| Item | Choice | Notes |
|---|---|---|
| Framework | React 19 + Vite 5 | `npm run dev / build / lint` |
| Icons | lucide-react | The only UI dependency |
| Routing | **No router** | The `VIEWS` array in `App.jsx` plus `useState` switches views. Adding a page means adding one entry |
| Charts | **No chart library** | Bar charts use a CSS width percentage (the EuroGoal `PredictionGauge` approach). That is enough, and it adds no risk |
| Styles | A single `src/index.css` | Tokens and the shell are at the top. Append component styles as blocks at the end |
| i18n | In-house `i18n.jsx` | Visible copy is English. Do not add a second language, a language toggle, or a translations dictionary. Write copy as `t('English text')`; `t()` returns that English string |

Say so in the group before adding any npm dependency.

## 2. Layout and responsibilities

```text
frontend/
├── index.html            # meta and title only; no logic
├── vite.config.js        # dev proxy: /api /platform /sellers -> :8000
└── src/
    ├── main.jsx          # mount + LanguageProvider (do not change)
    ├── App.jsx           # shell: header and tabs (add or remove pages only here). Do not add a language toggle
    ├── api.js            # the only place that calls the backend, plus fmt for money and percentages
    ├── agentRound.jsx    # shared background trading round (trading floor and agent console). Only one round runs at a time
    ├── i18n.jsx          # useT() -> { t }. t('English text') returns that English string
    ├── translations.js   # do not add a translations dictionary. Visible copy is English
    ├── index.css         # tokens + shell + component style blocks
    ├── pages/            # one file per view. The file-header comment is that page's requirements (read it first)
    │   ├── Market.jsx        # demo main screen: KPIs + run one round + results table
    │   ├── Agents.jsx        # seller reputation / reliability
    │   ├── Customer360.jsx   # buyer 360 + RFM
    │   └── DataQuality.jsx   # DQ checks + pipeline + event stream
    └── components/       # reusable components: one component per file, PascalCase, default export
```

## 3. API contract (backend `src/agentledger/server.py`; changes must stay in sync on both sides)

| Call | Method / path | Returns |
|---|---|---|
| `api.health()` | GET `/api/health` | `{status, sellers, agent_mode, llm_provider, llm_model, price_per_m_tokens, budget}` |
| `api.summary()` | GET `/api/summary` | `{kpi, agents[], customers[], rfm[], dq[], orders[], ai_costs[], ai_models[]}` |
| `api.events(n)` | GET `/api/events?limit=n` | `[{seq, event_type, aggregate_id, occurred_at, payload_json}]` |
| `api.runRound(symbols, rounds)` | POST `/api/round` | `{purchases[], agent_run, pipeline[], reconciliation}`. In LLM mode this can take 30–90 seconds |
| `api.startAgentRound(symbols)` | POST `/api/agent/rounds` | `{job_id}`. Returns immediately; the round runs in the background |
| `api.agentRound(jobId)` | GET `/api/agent/rounds/{job_id}` | `{status, mode, run, purchases, result, error}`. Poll every 1.5 seconds while it is running |
| `api.agentRuns(n)` | GET `/api/agent/runs` | historical runs (summaries only) |
| `api.agentRun(runId)` | GET `/api/agent/runs/{run_id}` | full trace `steps[]` plus child runs `children[]` (guardian) |
| `api.resetDemo(token)` | POST `/api/demo/reset` | clears orders, the ledger, agent runs, and AI costs, then re-funds the buyer wallet. When `health.reset_requires_token` is true, `X-Admin-Token` is required. Returns 409 when a round is running |
| `api.agentCards()` | GET `/sellers/.well-known/agents.json` | list of seller agent cards |

Field rules:

- **Every amount is an integer number of cents (`*_minor`)**. Display amounts only with `fmt.usd()`. The frontend does no floating-point money math.
- Rates (`success_rate`, `dispute_rate`, `hit_rate`) are decimals from 0 to 1. Use `fmt.pct()` / `fmt.num()`.
- `kpi`: `orders, settled_gmv_minor, dispute_rate, fees_minor, buyer_balance_minor`.
- `purchases[]`: `symbol, seller, price_minor, status, order_id, latency_ms, hit_rate, refund_minor, rationale, notes[]`.
- `status` values: `COMPLETED | REFUND_PARTIAL | REFUND_FULL | RELEASE | SKIPPED | PAYMENT_REJECTED | SELLER_ERROR`.
  Order `final_status`: `COMPLETED | PARTIALLY_REFUNDED | REFUNDED | ...` (see `contracts.py`).
- Errors are always a non-2xx HTTP status plus `{"detail": "..."}`. `api.js` already turns that into `Error(detail)`.

## 4. Visual and data-visualization rules

1. **Use tokens only** (the CSS variables at the top of `index.css`). Do not write a raw hex color in a component. Dark and light follow `prefers-color-scheme` automatically.
2. **A single-series chart uses only the one color `--primary`** (for example the reputation bar chart). Do not change color by rank. Do not use a rainbow palette.
3. **Status colors express outcomes only**: `--status-good / warn / bad`, and they must appear **together with an icon and a text label** (✓ PASS / ✗ FAIL, Completed / Partial refund / Full refund). Color alone is not enough.
4. No dual Y-axis. Do not put a number on every data point (put one value at the end of the bar only).
5. Hover hints use the `title` attribute or a simple tooltip. Right-align numbers in tables and set `font-variant-numeric: tabular-nums`.
6. Text uses `--text-*`. Do not paint text in a series color.
7. At 640px and below, use a single column. Wrap tables in `overflow-x: auto`. The page must not scroll horizontally.

## 5. State handling (every page must have these)

- **loading**: disable the button and show a progressive message such as "Agents are trading…".
- **empty**: when no round has been run yet, show the prompt "Press Run market round" instead of an empty table.
- **error**: show `error.message` and a Retry button.
- **Render cold start**: a free instance sleeps, and the first request after sleep takes about 50 seconds. When the first `api.health()` call fails, show "Waking up the server…" and retry every 5 seconds for at most 2 minutes.

## 6. i18n rules

- Wrap every visible string in JSX in `t('English text')`. Visible copy is English. Do not add a second language, a language toggle, or a translations dictionary. `t()` returns that English string.
- Do not pass data values (agent ids, ticker symbols, amounts) through `t()`.
- Do not store a language choice. Do not store business data in the browser.

## 7. How the pages match the demo script

1. **Market** (main screen): click "Run market round" and the results table appears in this order: `sig-hype` is fully refunded (stale) → `sig-rsi` is partially refunded → `sig-momentum` completes → reconciliation ✓. Click two or three times in a row. The reputation change is visible on the **Agents** page.
2. **Agents**: reputation bar chart plus a reliability table (the "IT / cloud-operations analytics" talk track: success rate, latency, dispute rate).
3. **Customer 360**: buyer profile plus RFM segments (the SAP CPIT Customer 360 talk track).
4. **Data quality**: all 9 checks PASS, plus pipeline lineage, plus the outbox event stream (the data-governance, reconciliation, and replay talk track).

## 8. Development and deployment

```bash
# Backend (repository root)
uvicorn agentledger.server:create_app --factory --port 8000
# Frontend
cd frontend && npm install && npm run dev        # http://localhost:5173, proxied to :8000
npm run lint && npm run build                    # must pass before commit
```

- After the first `npm install`, **commit `package-lock.json`**, then change `npm install` in the Dockerfile to `npm ci`.
- Production: Render Blueprint (`render.yaml`, runtime docker). The Dockerfile builds the frontend first. FastAPI mounts `frontend/dist` at `/`. Same origin, so CORS is not required.

## 9. Prohibited

- Do not call `fetch` anywhere except `api.js`. Do not hardcode a backend address in the frontend (same-origin relative paths).
- Do not do floating-point math on amounts. Do not put any secret in the frontend.
- UI copy must not imply real funds, real trading advice, or integration with any SAP product (simulated funds, for demonstration).
- Do not change the mechanism of `main.jsx` or `i18n.jsx`. Do not introduce a router, a UI component library, a chart library, or a CSS framework.

## 10. Frontend definition of done

- [ ] All 4 pages have loading, empty, and error states
- [ ] The Market page can run the full demo script, and the reconciliation result is visible
- [ ] Visible copy is English. There is no second language, no language toggle, and no translations dictionary. Every visible string uses `t('English text')`, and `t()` returns that English string (data values excepted)
- [ ] No horizontal scroll at a width of 640px
- [ ] `npm run lint` and `npm run build` pass, and a local `docker build .` of the image passes

## 11. AI agent page (Agent Console) and token-cost display

The organizers require a **real AI agent that actually does the work**, and a **display of the cost incurred by token use**. The backend already implements this (LangGraph: plan → react tool loop → reflect; buyer agent plus arbitrator guardian agent). The frontend presents it. Page: `pages/AgentConsole.jsx`.

**Data shapes**

- `run` (AgentRunReport): `run_id, agent_id, role (buyer|guardian), status (running|completed|budget_stopped|failed), provider, model, llm_calls, tool_calls, input_tokens, output_tokens, cost_micro_usd, summary, steps[], children[]`.
- `step`: `seq, kind (plan|llm|tool|policy|error), name, detail, input_tokens, output_tokens, cost_micro_usd, latency_ms, at`.
  - `kind=llm`: `detail.text` (the model's text) and `detail.tool_calls` (the tool names requested in this step).
  - `kind=tool`: `detail.args`, `detail.result` (already truncated to 1500 characters), and `detail.ok`.
  - `kind=policy`: budget stop, grounding drop, automatic close-out, guardian fallback. **These must be highlighted.** They are the evidence that deterministic policy keeps the LLM in check.

**Cost display rules**

1. LLM cost is an **integer number of micro-USD**. Display it only with `fmt.microUsd()` (show 4 decimal places when the amount is less than 1 cent). Token counts use `fmt.tokens()`.
2. Each llm step shows input tokens, output tokens, cost, and latency. The running total accumulates live (updated on each poll) and is shown beside the budget (`health.budget.max_cost_usd`) as progress.
3. The price source must be visible: `health.price_per_m_tokens.source`. Some Mistral prices come from a third-party tracking site, so the page must say "estimate".
4. When the run finishes, show unit economics: `AI spend $x for N orders = $y per order`, and compare data-procurement spend (cents) with AI spend (micro-USD). Do not mix the two units in one calculation. Format each separately.
5. Add two cells to the KPI row on the Market page: `AI spend` (`kpi.ai_cost_micro_usd`) and `LLM calls` (`kpi.llm_calls`). The Agents page may add an "AI cost by agent / by model" table (`ai_costs[]`, `ai_models[]`).
6. When `agent_mode === 'rule'`, the page must explicitly say "rule mode (no API key configured)". Do not pretend it is an LLM.

**Polling**: after `startAgentRound` returns a `job_id`, call `agentRound` every 1.5 seconds. Stop when `status !== 'running'`. Clear the timer when the page unmounts. Only one job is allowed at a time.

**Demo script (Agent Console)**: click Run and the audience sees plan, then tool calls appear one by one (check_wallet → search_sellers → request_quote → buy → verify_delivery → open_dispute), then the guardian child run expands (6 investigation tools in parallel, then submit_ruling is checked by policy), then the buyer switches seller and the purchase completes, then the final report and the cost total (about $0.08–0.10 per round, a Mistral Medium estimate).
