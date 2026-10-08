import { fmt } from '../api'
import { useT } from '../i18n.jsx'

/** Running token / cost totals for one round (buyer run + guardian child runs) and the buyer's budget use. */
export default function CostMeter({ totals, budgetUsd }) {
  const { t } = useT()
  const budgetMicro = budgetUsd ? budgetUsd * 1_000_000 : 0
  const used = budgetMicro ? Math.min(100, (totals.buyerCost / budgetMicro) * 100) : 0
  const tiles = [
    { label: 'LLM calls', value: totals.llmCalls, hint: `${t('Buyer')} ${totals.buyerLlmCalls} · ${t('Guardian')} ${totals.guardianLlmCalls}` },
    { label: 'Tool calls', value: totals.toolCalls },
    { label: 'Tokens in / out', value: `${fmt.tokens(totals.inputTokens)} / ${fmt.tokens(totals.outputTokens)}` },
    { label: 'AI spend', value: fmt.microUsd(totals.cost),
      hint: `${t('Buyer')} ${fmt.microUsd(totals.buyerCost)} · ${t('Guardian')} ${fmt.microUsd(totals.guardianCost)}` },
  ]
  return (
    <section className="cost-meter">
      <div className="kpi-grid">
        {tiles.map((tile) => (
          <article key={tile.label} className="card kpi-tile">
            <p className="kpi-label">{t(tile.label)}</p>
            <p className="kpi-value">{tile.value}</p>
            {tile.hint && <p className="kpi-hint">{tile.hint}</p>}
          </article>
        ))}
      </div>
      {budgetMicro > 0 && (
        <div className="budget-line" title={`${fmt.microUsd(totals.buyerCost)} / $${budgetUsd.toFixed(2)}`}>
          <span className="kpi-label">{t('Buyer budget used')}</span>
          <span className="rep-track"><span className="rep-fill" style={{ width: `${used}%` }} /></span>
          <span className="rep-value">{used.toFixed(1)}%</span>
        </div>
      )}
    </section>
  )
}
