import { useCallback, useEffect, useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import { api, fmt } from '../api'
import AgentHeader from '../components/AgentHeader'
import AgentTrace from '../components/AgentTrace'
import CostMeter from '../components/CostMeter'
import PageState from '../components/PageState'
import ResetDemoButton from '../components/ResetDemoButton'
import RoundTable from '../components/RoundTable'
import RunHistory from '../components/RunHistory'
import { useT } from '../i18n.jsx'
import { usePageData } from '../usePageData'

const POLL_MS = 1500

/** Totals over the buyer run and the guardian runs it triggered (cost in integer micro-USD). */
function totalsOf(run) {
  const zero = { llmCalls: 0, toolCalls: 0, inputTokens: 0, outputTokens: 0, cost: 0, buyerCost: 0,
                 guardianCost: 0, buyerLlmCalls: 0, guardianLlmCalls: 0 }
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
    }
  }, zero)
}

function Economics({ purchases, aiCost }) {
  const { t } = useT()
  const bought = purchases.filter((p) => p.order_id && p.status !== 'PAYMENT_REJECTED')
  const paid = bought.reduce((sum, p) => sum + (p.price_minor || 0), 0)
  const refunded = bought.reduce((sum, p) => sum + (p.refund_minor || 0), 0)
  const perOrder = bought.length ? Math.round(aiCost / bought.length) : null
  return (
    <section className="card">
      <h3>{t('Unit economics of this round')}</h3>
      <dl className="recon-facts">
        <div><dt>{t('Orders')}</dt><dd>{bought.length}</dd></div>
        <div><dt>{t('Data bought')}</dt><dd>{fmt.usd(paid)}</dd></div>
        <div><dt>{t('Refunded')}</dt><dd>{fmt.usd(refunded)}</dd></div>
        <div><dt>{t('AI spend')}</dt><dd>{fmt.microUsd(aiCost)}</dd></div>
        <div><dt>{t('AI spend per order')}</dt><dd>{perOrder === null ? '-' : fmt.microUsd(perOrder)}</dd></div>
      </dl>
    </section>
  )
}

export default function AgentConsole() {
  const { t } = useT()
  const loadHealth = useCallback(() => api.health(), [])
  const page = usePageData(loadHealth)
  const health = page.data
  const [symbols, setSymbols] = useState('AAPL, MSFT, NVDA')
  const [starting, setStarting] = useState(false)
  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [startError, setStartError] = useState(null)
  const [pollError, setPollError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [historyNonce, setHistoryNonce] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const busy = starting || job?.status === 'running'

  // Poll the background job until it leaves "running"; one job at a time, cleaned up on unmount.
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
        else setHistoryNonce((n) => n + 1)
      } catch (err) {
        if (cancelled) return
        setPollError(err)
        timer = setTimeout(poll, POLL_MS * 2) // transient (e.g. server busy): keep trying
      }
    }
    poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [jobId])

  // Elapsed-time clock while a round runs.
  useEffect(() => {
    if (!busy) return undefined
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [busy])

  async function start() {
    const list = symbols.split(',').map((s) => s.trim()).filter(Boolean)
    if (list.length === 0 || busy) return
    setStarting(true)
    setStartError(null)
    setSelected(null)
    setJob(null)
    try {
      const { job_id: id } = await api.startAgentRound(list)
      setJobId(id)
    } catch (err) {
      setStartError(err)
    } finally {
      setStarting(false)
    }
  }

  async function openRun(runId) {
    try {
      setSelected(await api.agentRun(runId))
    } catch (err) {
      setStartError(err)
    }
  }

  const liveRun = job?.run || null
  const shownRun = busy ? liveRun : selected || liveRun
  const totals = totalsOf(shownRun)
  const startedAt = liveRun?.started_at ? Date.parse(liveRun.started_at) : null
  const elapsed = busy && startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : null
  const finished = job && job.status !== 'running' && !selected
  const llmMode = health?.agent_mode === 'llm'

  return (
    <PageState status={page.status} error={page.error} onRetry={page.reload} hasData={Boolean(health)}>
      <div className="page">
        <header className="page-head">
          <h2>{t('Agent Console')}</h2>
          <p className="muted">{t('Watch the buyer agent plan, call tools and pay, and the guardian agent rule on disputes, with every token costed.')}</p>
        </header>

        <AgentHeader health={health} />

        <section className="card">
          <form className="round-form" onSubmit={(event) => { event.preventDefault(); start() }}>
            <label className="symbol-field">
              <span>{t('Symbols')}</span>
              <input value={symbols} onChange={(event) => setSymbols(event.target.value)} disabled={busy}
                     aria-label={t('Symbols')} />
            </label>
            <button type="submit" className="btn btn-primary btn-icon" disabled={busy}>
              {busy ? <Loader2 className="spin" size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
              {t('Run agent round')}
            </button>
            <ResetDemoButton health={health} disabled={busy} onDone={() => {
              setJobId(null)
              setJob(null)
              setSelected(null)
              setStartError(null)
              setHistoryNonce((n) => n + 1)
              page.reload()
            }} />
          </form>
          <p className="kpi-hint">
            {llmMode
              ? t('Each round calls the LLM and spends real API credit (about $0.08-0.10 with the default model).')
              : t('Rule mode: no LLM is called and no AI cost is incurred.')}
          </p>
          {busy && (
            <p className="muted" role="status">
              {t('Agents are trading…')}{elapsed !== null ? ` ${elapsed}s` : ''}
            </p>
          )}
          {pollError && busy && <p className="form-error" role="status">{t('Connection hiccup, retrying…')} {pollError.message}</p>}
          {(startError || job?.status === 'failed') && (
            <p className="form-error" role="alert">
              {startError?.message || job?.error}
              <button type="button" className="btn" onClick={start} disabled={busy}>{t('Retry')}</button>
            </p>
          )}
        </section>

        {shownRun && <CostMeter totals={totals} budgetUsd={shownRun.role === 'buyer' ? health?.budget?.max_cost_usd : null} />}

        {shownRun && <AgentTrace run={shownRun} live={busy} />}
        {!shownRun && busy && (
          <section className="card state-panel" role="status">
            <Loader2 className="spin" size={18} aria-hidden="true" />
            <p>{t(llmMode ? 'Starting the agent…' : 'Rule-based round running…')}</p>
          </section>
        )}
        {!shownRun && !busy && !job && (
          <section className="card empty-hint"><p>{t('Press Run agent round to watch the agents work, or open a past run below.')}</p></section>
        )}
        {finished && !liveRun && (
          <section className="card empty-hint"><p>{t('Rule mode: this round ran without an LLM, so there is no trace to show.')}</p></section>
        )}

        {finished && job.purchases && <RoundTable purchases={job.purchases} />}
        {finished && job.purchases && <Economics purchases={job.purchases} aiCost={totals.cost} />}
        {!busy && shownRun?.summary && (
          <section className="card">
            <h3>{t("Agent's final report")}</h3>
            <pre className="report">{shownRun.summary.replace(/\*\*/g, '')}</pre>
          </section>
        )}
        {finished && job.result?.reconciliation && (
          <section className={`card recon ${job.result.reconciliation.ok ? 'good' : 'bad'}`} role="status">
            <p className="recon-title">
              {job.result.reconciliation.ok ? '✓' : '✗'}{' '}
              {t(job.result.reconciliation.ok ? 'Escrow matches open orders' : 'Escrow does not match open orders')}
            </p>
          </section>
        )}

        <RunHistory nonce={historyNonce} selectedId={selected?.run_id} onSelect={openRun} />
      </div>
    </PageState>
  )
}
