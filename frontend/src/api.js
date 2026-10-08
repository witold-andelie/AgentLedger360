// The ONLY place that calls the backend. Pages import these functions, never fetch() directly.
// Contract source of truth: src/agentledger/server.py (+ docs/FRONTEND_RULES.md section 3).
// Money arrives as integer minor units (cents) -> format with fmt.usd(), never do float math on it.

// Remembered only for this page load. Not written to localStorage.
let sessionRunToken = ''

export function rememberRunToken(token) {
  sessionRunToken = token || ''
}

async function request(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(sessionRunToken ? { 'X-Run-Token': sessionRunToken } : {}),
    ...(options.headers || {}),
  }
  const res = await fetch(path, { ...options, headers })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `${res.status} ${res.statusText}`)
  return body
}

export const api = {
  /** GET /api/health -> { status, sellers } */
  health: () => request('/api/health'),

  /** GET /api/summary -> { kpi, agents[], customers[], rfm[], dq[], orders[] } */
  summary: () => request('/api/summary'),

  /** GET /api/events?limit=N -> [{ seq, event_type, aggregate_id, occurred_at, payload_json }] */
  events: (limit = 60) => request(`/api/events?limit=${limit}`),

  /** POST /api/round { symbols[], rounds } -> { purchases[], pipeline[], reconciliation } (may take seconds) */
  runRound: (symbols, rounds = 1) =>
    request('/api/round', { method: 'POST', body: JSON.stringify({ symbols, rounds }) }),

  /** GET /sellers/.well-known/agents.json -> agent cards (only when sellers run in-process) */
  agentCards: () => request('/sellers/.well-known/agents.json'),

  // ---- AI agents (docs/FRONTEND_RULES.md section 11) ----
  // /api/health also returns { agent_mode: 'llm'|'rule', llm_provider, llm_model, price_per_m_tokens, budget }

  /** POST /api/agent/rounds { symbols[], as_of? } -> { job_id }  (returns at once; the round runs in background) */
  startAgentRound: (symbols, asOf = null) =>
    request('/api/agent/rounds', { method: 'POST', body: JSON.stringify({ symbols, as_of: asOf }) }),

  /** GET /api/agent/rounds/{job_id} -> { status: running|completed|failed, mode, run, purchases, result, error }
   *  run = AgentRunReport + children[] (guardian runs); poll every ~1.5 s while status === 'running' */
  agentRound: (jobId) => request(`/api/agent/rounds/${encodeURIComponent(jobId)}`),

  /** GET /api/agent/runs?limit=N -> run rows (totals only, newest first) */
  agentRuns: (limit = 20) => request(`/api/agent/runs?limit=${limit}`),

  /** GET /api/agent/runs/{run_id} -> AgentRunReport with steps[] + children[] */
  agentRun: (runId) => request(`/api/agent/runs/${encodeURIComponent(runId)}`),

  /** POST /api/demo/reset -> { reset, buyer_balance_minor, pipeline, reconciliation }
   *  Wipes all demo data. Needs header X-Admin-Token when health.reset_requires_token is true. */
  resetDemo: (token = null) =>
    request('/api/demo/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { 'X-Admin-Token': token } : {}) },
    }),

  /** GET /api/audit/verify -> { ok, first_bad_seq } */
  auditVerify: () => request('/api/audit/verify'),

  /** POST /api/attacks/run -> [{ id, title, blocked, rule, http_status, detail }] */
  runAttacks: () => request('/api/attacks/run', { method: 'POST' }),
}

export const fmt = {
  usd: (minor) => (minor == null ? '-' : `$${(minor / 100).toFixed(2)}`),
  /** LLM cost arrives as integer micro-USD; sub-cent values need 4 decimals. */
  microUsd: (micro) => {
    if (micro == null) return '-'
    const usd = micro / 1_000_000
    return usd === 0 ? '$0.00' : usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(3)}`
  },
  tokens: (n) => (n == null ? '-' : n < 1000 ? String(n) : `${(n / 1000).toFixed(1)}k`),
  pct: (x) => (x == null ? '-' : `${Math.round(x * 100)}%`),
  num: (x, digits = 3) => (x == null ? '-' : Number(x).toFixed(digits)),
}
