import { fmt } from '../api'
import { useT } from '../i18n.jsx'

export default function ReputationBars({ agents }) {
  const { t } = useT()
  return (
    <section className="card">
      <h3>{t('Reputation')}</h3>
      <ul className="rep-list">
        {agents.map((agent) => {
          const score = Number(agent.reputation) || 0
          const width = Math.max(0, Math.min(100, score * 100))
          const label = fmt.num(agent.reputation, 3)
          return (
            <li key={agent.seller_agent_id}>
              <span className="rep-name">{agent.seller_agent_id}</span>
              <span className="rep-track" title={`${agent.seller_agent_id} ${label}`}>
                <span className="rep-fill" style={{ width: `${width}%` }} />
              </span>
              <span className="rep-value">{label}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
