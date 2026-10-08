/* eslint-disable react-refresh/only-export-components --
   infra file: exports the provider, the hook and a pure helper together (same pattern as i18n.jsx) */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, rememberRunToken } from './api'
import { useT } from './i18n.jsx'

const POLL_MS = 1500

/**
 * One background market round shared by every page (the backend also runs one round at a time):
 * start it on Market, watch it live on Agent Console. Polls GET /api/agent/rounds/{job_id} every 1.5 s.
 */
const AgentRoundContext = createContext(null)

export function AgentRoundProvider({ children }) {
  const { t } = useT()
  const [starting, setStarting] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [startedAt, setStartedAt] = useState(null)
  const [startError, setStartError] = useState(null)
  const [pollError, setPollError] = useState(null)
  const [finishedCount, setFinishedCount] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const busy = starting || job?.status === 'running'

  useEffect(() => {
    if (!jobId) return undefined
    let cancelled = false
    let timer = null
    async function poll() {
      try {
        const next = await api.agentRound(jobId)
        if (cancelled) return
        setJob(next)
        setPollError(null)
        if (next.status === 'running') timer = setTimeout(poll, POLL_MS)
        else setFinishedCount((n) => n + 1)
      } catch (err) {
        if (cancelled) return
        setPollError(err)
        timer = setTimeout(poll, POLL_MS * 2) // transient (server busy, cold start): keep trying
      }
    }
    poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [jobId])

  useEffect(() => {
    if (!busy) return undefined
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [busy])

  const start = useCallback(async (symbols) => {
    if (busy || symbols.length === 0) return
    setStarting(true)
    setStartError(null)
    setPollError(null)
    setJob(null)
    setStartedAt(Date.now())
    try {
      let started
      try {
        started = await api.startAgentRound(symbols)
      } catch (err) {
        if (!/run token/i.test(err.message)) throw err
        const token = window.prompt(t('Run token'))
        if (!token) throw err
        rememberRunToken(token)
        started = await api.startAgentRound(symbols)
      }
      setJobId(started.job_id)
    } catch (err) {
      setStartError(err)
    } finally {
      setStarting(false)
    }
  }, [busy, t])

  const clear = useCallback(() => {
    setJobId(null)
    setJob(null)
    setStartError(null)
    setPollError(null)
  }, [])

  const value = useMemo(() => ({
    job,
    busy,
    startError,
    pollError,
    finishedCount,
    elapsed: busy && startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : null,
    start,
    clear,
  }), [job, busy, startError, pollError, finishedCount, startedAt, now, start, clear])

  return <AgentRoundContext.Provider value={value}>{children}</AgentRoundContext.Provider>
}

export function useAgentRound() {
  const ctx = useContext(AgentRoundContext)
  if (!ctx) throw new Error('useAgentRound must be used inside <AgentRoundProvider>')
  return ctx
}

/** Totals over a buyer run and the guardian runs it triggered (cost in integer micro-USD). */
export function totalsOf(run) {
  const zero = { llmCalls: 0, toolCalls: 0, inputTokens: 0, outputTokens: 0, cost: 0, buyerCost: 0,
                 guardianCost: 0, buyerLlmCalls: 0, guardianLlmCalls: 0, steps: 0 }
  if (!run) return zero
  return [run, ...(run.children || [])].reduce((acc, r) => {
    const guardian = r.role === 'guardian'
    return {
      llmCalls: acc.llmCalls + r.llm_calls,
      toolCalls: acc.toolCalls + r.tool_calls,
      inputTokens: acc.inputTokens + r.input_tokens,
      outputTokens: acc.outputTokens + r.output_tokens,
      cost: acc.cost + r.cost_micro_usd,
      buyerCost: acc.buyerCost + (guardian ? 0 : r.cost_micro_usd),
      guardianCost: acc.guardianCost + (guardian ? r.cost_micro_usd : 0),
      buyerLlmCalls: acc.buyerLlmCalls + (guardian ? 0 : r.llm_calls),
      guardianLlmCalls: acc.guardianLlmCalls + (guardian ? r.llm_calls : 0),
      steps: acc.steps + (r.steps || []).length,
    }
  }, zero)
}
