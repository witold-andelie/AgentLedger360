import { fmt } from '../api'
import { useT } from '../i18n.jsx'

export default function AgentTable({ agents }) {
  const { t } = useT()
  return (
    <section className="card">
      <h3>{t('Agents')}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('Seller')}</th>
              <th>{t('Capability')}</th>
              <th className="num">{t('Orders')}</th>
              <th className="num">{t('Success rate')}</th>
              <th className="num">{t('Dispute rate')}</th>
              <th className="num">{t('Revenue')}</th>
              <th className="num">{t('Avg latency')}</th>
              <th className="num">{t('Hit rate')}</th>
              <th className="num">{t('Rank IC')}</th>
              <th className="num">{t('Realized hit rate')}</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agent) => (
              <tr key={agent.seller_agent_id}>
                <td>{agent.seller_agent_id}</td>
                <td>{agent.capability || '-'}</td>
                <td className="num">{agent.orders_total}</td>
                <td className="num">{fmt.pct(agent.success_rate)}</td>
                <td className="num">{fmt.pct(agent.dispute_rate)}</td>
                <td className="num">{fmt.usd(agent.seller_revenue_minor)}</td>
                <td className="num">{agent.avg_latency_ms == null ? '-' : `${fmt.num(agent.avg_latency_ms, 0)} ${t('ms')}`}</td>
                <td className="num">{fmt.pct(agent.avg_hit_rate)}</td>
                <td className="num">{fmt.num(agent.avg_rank_ic, 3)}</td>
                <td className="num">{fmt.pct(agent.realized_hit_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
