import { useCallback, useEffect, useState } from 'react'
import { Eye } from 'lucide-react'
import { api, fmt } from '../api'
import FlowStrip from '../components/FlowStrip'
import KpiRow from '../components/KpiRow'
import PageState from '../components/PageState'
import ResetDemoButton from '../components/ResetDemoButton'
import RoundTable from '../components/RoundTable'
import { totalsOf, useAgentRound } from '../agentRound.jsx'
import { useT } from '../i18n.jsx'
import { usePageData } from '../usePageData'

export default function Market({ onNavigate }) {
  const { t } = useT()
  const load = useCallback(() => api.summary(), [])
  const page = usePageData(load)
  const round = useAgentRound()
  const { job, busy: running, startError, pollError, elapsed } = round
  const [symbols, setSymbols] = useState('AAPL, MSFT, NVDA')

  // The round runs in the background (shared with Agent Console); refresh the KPIs when it ends.
  const reload = page.reload
  const jobStatus = job?.status
  useEffect(() => {
    if (jobStatus && jobStatus !== 'running') reload()
  }, [jobStatus, reload])

  function runRound() {
    round.start(symbols.split(',').map((s) => s.trim()).filter(Boolean))
  }

  const finished = job && job.status !== 'running'
  const purchases = finished ? job.purchases : null
  const reconciliation = finished ? job.result?.reconciliation || null : null
  const roundError = startError || (job?.status === 'failed' ? new Error(job.error) : null)
  const live = totalsOf(job?.run)
  const kpi = page.data?.kpi
  const empty = (kpi?.orders ?? 0) === 0 && purchases === null

  return (
    <PageState status={page.status} error={page.error} onRetry={page.reload} hasData={Boolean(page.data)}>
      <div className="page">
        <header className="page-head">
          <h2>{t('Market')}</h2>
        </header>
        <KpiRow kpi={kpi} />
        <section className="card">
          <form className="round-form" onSubmit={(event) => { event.preventDefault(); runRound() }}>
            <label className="symbol-field">
              <span>{t('Symbols')}</span>
              <input
                value={symbols}
                onChange={(event) => setSymbols(event.target.value)}
                aria-label={t('Symbols')}
                disabled={running}
              />
            </label>
            <button type="submit" id="run-round" className="btn btn-primary" disabled={running}>
              {t('Run market round')}
            </button>
            <ResetDemoButton disabled={running} onDone={() => {
              round.clear()
              page.reload()
            }} />
          </form>
          {running && (
            <div className="round-progress" role="status">
              <p className="muted">
                {t('Agents are trading…')}
                {elapsed !== null ? ` ${elapsed}s` : ''}
                {job?.run ? ` · ${live.steps} ${t('steps')} · ${fmt.microUsd(live.cost)} ${t('AI spend so far')}` : ''}
              </p>
              {job?.run && onNavigate && (
                <button type="button" className="btn btn-icon" onClick={() => onNavigate('console')}>
                  <Eye size={16} aria-hidden="true" />
                  {t('Watch live in Agent Console')}
                </button>
              )}
            </div>
          )}
          {pollError && running && <p className="form-error" role="status">{t('Connection hiccup, retrying…')} {pollError.message}</p>}
          {roundError && (
            <p className="form-error" role="alert">
              {roundError.message}
              <button type="button" className="btn" onClick={runRound} disabled={running}>{t('Retry')}</button>
            </p>
          )}
        </section>
        <FlowStrip />
        {empty && (
          <section className="card empty-hint">
            <p>{t('Press Run market round')}</p>
          </section>
        )}
        {purchases && purchases.length > 0 && <RoundTable purchases={purchases} />}
        {reconciliation && (
          <section className={`card recon ${reconciliation.ok ? 'good' : 'bad'}`} role="status">
            <p className="recon-title">
              {reconciliation.ok ? '✓' : '✗'}{' '}
              {t(reconciliation.ok ? 'Escrow matches open orders' : 'Escrow does not match open orders')}
            </p>
            <dl className="recon-facts">
              <div>
                <dt>{t('Escrow balance')}</dt>
                <dd>{fmt.usd(reconciliation.escrow_minor)}</dd>
              </div>
              <div>
                <dt>{t('Open orders')}</dt>
                <dd>{fmt.usd(reconciliation.open_orders_minor)}</dd>
              </div>
              <div>
                <dt>{t('Unbalanced transactions')}</dt>
                <dd>{reconciliation.unbalanced_txns}</dd>
              </div>
            </dl>
          </section>
        )}
      </div>
    </PageState>
  )
}
