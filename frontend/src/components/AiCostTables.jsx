import { fmt } from '../api'
import { useT } from '../i18n.jsx'

/** AI FinOps: what each agent's reasoning costs (analytics.v_ai_cost_by_agent / v_ai_cost_by_model). */
export default function AiCostTables({ byAgent, byModel }) {
  const { t } = useT()
  if (!byAgent?.length) {
    return (
      <section className="card">
        <h3>{t('AI cost by agent')}</h3>
        <p className="muted">{t('No AI agent runs yet (rule mode or no round run).')}</p>
      </section>
    )
  }
  return (
    <section className="card">
      <h3>{t('AI cost by agent')}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('Agent')}</th>
              <th className="num">{t('Runs')}</th>
              <th className="num">{t('LLM calls')}</th>
              <th className="num">{t('Tool calls')}</th>
              <th className="num">{t('Tokens in / out')}</th>
              <th className="num">{t('AI spend')}</th>
              <th className="num">{t('AI spend per order')}</th>
              <th className="num">{t('Budget stops')}</th>
            </tr>
          </thead>
          <tbody>
            {byAgent.map((row) => (
              <tr key={row.agent_id}>
                <td>{row.agent_id} <span className="muted">({t(row.role === 'guardian' ? 'Guardian' : 'Buyer')})</span></td>
                <td className="num">{row.runs}</td>
                <td className="num">{row.llm_calls}</td>
                <td className="num">{row.tool_calls}</td>
                <td className="num">{fmt.tokens(row.input_tokens)} / {fmt.tokens(row.output_tokens)}</td>
                <td className="num">{fmt.microUsd(row.cost_micro_usd)}</td>
                <td className="num">{fmt.microUsd(row.cost_per_order_micro_usd)}</td>
                <td className="num">{row.budget_stops}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="subhead">{t('AI cost by model')}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('Model')}</th>
              <th className="num">{t('LLM calls')}</th>
              <th className="num">{t('Tokens in / out')}</th>
              <th className="num">{t('AI spend')}</th>
              <th className="num">{t('Avg latency')}</th>
            </tr>
          </thead>
          <tbody>
            {(byModel || []).map((row) => (
              <tr key={`${row.provider}-${row.model}`}>
                <td className="mono">{row.provider} · {row.model}</td>
                <td className="num">{row.llm_calls}</td>
                <td className="num">{fmt.tokens(row.input_tokens)} / {fmt.tokens(row.output_tokens)}</td>
                <td className="num">{fmt.microUsd(row.cost_micro_usd)}</td>
                <td className="num">{row.avg_latency_ms == null ? '-' : `${fmt.num(row.avg_latency_ms, 0)} ${t('ms')}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="kpi-hint">{t('Costs are estimates from the price table; verify on the provider bill.')}</p>
    </section>
  )
}
