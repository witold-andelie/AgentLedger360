import { fmt } from '../api'
import { useT } from '../i18n.jsx'

export default function AgentCardGrid({ cards, error }) {
  const { t } = useT()
  return (
    <section className="card">
      <h3>{t('Agent cards')}</h3>
      {error && <p className="muted" role="status">{t('Seller cards are unavailable')}</p>}
      {!cards && !error && <p className="muted">{t('Loading…')}</p>}
      {cards && (
        <ul className="card-grid">
          {cards.map((card) => (
            <li key={card.agent_id} className="agent-card">
              <p className="agent-card-name">{card.name}</p>
              <p className="muted">{card.agent_id}</p>
              <p>{card.capability}</p>
              <p className="num">{fmt.usd(card.price_minor)}</p>
              <p className="endpoint">{card.endpoint}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
