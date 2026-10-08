import { useCallback, useState } from 'react'
import { api, fmt } from '../api'
import FlowStrip from '../components/FlowStrip'
import KpiRow from '../components/KpiRow'
import PageState from '../components/PageState'
import ResetDemoButton from '../components/ResetDemoButton'
import RoundTable from '../components/RoundTable'
import { useT } from '../i18n.jsx'
import { usePageData } from '../usePageData'

export default function Market() {
  const { t } = useT()
  const load = useCallback(() => api.summary(), [])
  const page = usePageData(load)
  const [symbols, setSymbols] = useState('AAPL, MSFT, NVDA')
  const [running, setRunning] = useState(false)
  const [roundError, setRoundError] = useState(null)
  const [purchases, setPurchases] = useState(null)
  const [reconciliation, setReconciliation] = useState(null)

  async function runRound() {
    const list = symbols.split(',').map((s) => s.trim()).filter(Boolean)
    setRunning(true)
    setRoundError(null)
    try {
      const body = await api.runRound(list, 1)
      setPurchases(body.purchases || [])
      setReconciliation(body.reconciliation || null)
      page.reload()
    } catch (err) {
      setRoundError(err)
    } finally {
      setRunning(false)
    }
  }

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
              setPurchases(null)
              setReconciliation(null)
              setRoundError(null)
              page.reload()
            }} />
          </form>
          {running && <p className="muted" role="status">{t('Agents are trading…')}</p>}
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
