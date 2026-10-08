import { fmt } from '../api'
import { useT } from '../i18n.jsx'

export default function KpiRow({ kpi }) {
  const { t } = useT()
  const tiles = [
    { label: 'Orders', value: kpi?.orders ?? 0 },
    { label: 'Settled GMV', value: fmt.usd(kpi?.settled_gmv_minor) },
    { label: 'Dispute rate', value: fmt.pct(kpi?.dispute_rate) },
    { label: 'Platform fees', value: fmt.usd(kpi?.fees_minor) },
    { label: 'Buyer wallet', value: fmt.usd(kpi?.buyer_balance_minor), hint: 'Simulated' },
    { label: 'AI spend', value: fmt.microUsd(kpi?.ai_cost_micro_usd ?? 0), hint: 'LLM tokens, estimate' },
    { label: 'LLM calls', value: kpi?.llm_calls ?? 0, hint: `${kpi?.ai_runs ?? 0} ${t('agent runs')}`, raw: true },
  ]
  return (
    <div className="kpi-grid">
      {tiles.map((tile) => (
        <article key={tile.label} className="card kpi-tile">
          <p className="kpi-label">{t(tile.label)}</p>
          <p className="kpi-value">{tile.value}</p>
          {tile.hint && <p className="kpi-hint">{tile.raw ? tile.hint : t(tile.hint)}</p>}
        </article>
      ))}
    </div>
  )
}
