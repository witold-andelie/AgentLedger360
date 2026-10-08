import { AlertTriangle, Bot, Cpu, ShieldCheck } from 'lucide-react'
import { fmt } from '../api'
import { useT } from '../i18n.jsx'

/** Which brain is running: LLM agents (provider, model, price, budget) or the rule-based fallback. */
export default function AgentHeader({ health }) {
  const { t } = useT()
  const llm = health?.agent_mode === 'llm'
  const price = health?.price_per_m_tokens
  const budget = health?.budget
  return (
    <section className="card agent-head">
      <div className="agent-mode">
        <span className={`badge ${llm ? 'mode' : 'warn'}`}>
          {llm ? <Bot size={14} aria-hidden="true" /> : <Cpu size={14} aria-hidden="true" />}
          <span>{t(llm ? 'LLM agents' : 'Rule-based agents')}</span>
        </span>
        {llm ? (
          <span className="mono">{health.llm_provider} · {health.llm_model}</span>
        ) : (
          <span className="muted">{t('No LLM API key configured: the deterministic fallback agents are running.')}</span>
        )}
      </div>
      <dl className="agent-facts">
        <div>
          <dt>{t('Price per 1M tokens')}</dt>
          <dd>{price ? `$${price.input_usd} ${t('in')} / $${price.output_usd} ${t('out')}` : '-'}</dd>
        </div>
        <div>
          <dt>{t('Budget per agent run')}</dt>
          <dd>{budget ? `${budget.max_tool_calls} ${t('tool calls')} · $${budget.max_cost_usd.toFixed(2)}` : '-'}</dd>
        </div>
        <div>
          <dt>{t('Agents')}</dt>
          <dd>{t('Buyer (procurement) + Guardian (disputes)')}</dd>
        </div>
      </dl>
      {health?.buyer_policy && (
        <p className="kpi-hint">
          {t('Buyer policy')}: {t('price weight')} {Number(health.buyer_policy.price_weight).toFixed(2)}
          {' '}({health.buyer_policy.observations} {t('rounds learned')}
          {health.buyer_policy.reason ? `, ${t('latest reason')}: ${health.buyer_policy.reason}` : ''})
        </p>
      )}
      {price && <p className="kpi-hint">{t('Price source')}: {price.source} · {t('cost figures are estimates')}</p>}
      <CapabilityLine health={health} />
    </section>
  )
}

function CapabilityLine({ health }) {
  const { t } = useT()
  const caps = health?.capabilities
  if (!caps) return null
  const paused = caps.market_paused
  return (
    <div className="agent-mode">
      <span className={`badge ${paused ? 'warn' : 'good'}`}>
        {paused ? <AlertTriangle size={14} aria-hidden="true" /> : <ShieldCheck size={14} aria-hidden="true" />}
        <span>{t(paused ? 'Market paused' : 'Market open')}</span>
      </span>
      <span className="muted">
        {t('Global order cap')} {fmt.usd(caps.max_order_minor)}
        {' · '}
        {t(caps.open_funding ? 'Open funding on' : 'Open funding off')}
        {health.ai_spent_today_usd != null && ` · ${t('AI spent today')} $${Number(health.ai_spent_today_usd).toFixed(2)} / $${Number(health.daily_ai_budget_usd).toFixed(2)}`}
      </span>
    </div>
  )
}
