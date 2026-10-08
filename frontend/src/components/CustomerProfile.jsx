import { fmt } from '../api'
import { useT } from '../i18n.jsx'
import RfmChip from './RfmChip'

export default function CustomerProfile({ customer, rfm }) {
  const { t } = useT()
  const fields = [
    ['Orders', customer.orders_total],
    ['Completed orders', customer.orders_completed],
    ['Disputed orders', customer.orders_disputed],
    ['Net spend', fmt.usd(customer.net_spend_minor)],
    ['Refunded', fmt.usd(customer.refunded_minor)],
    ['Avg hit rate', fmt.pct(customer.avg_signal_hit_rate)],
  ]
  return (
    <article className="card profile-card">
      <header className="profile-head">
        <h3>{customer.buyer_agent_id}</h3>
        <RfmChip rfm={rfm} />
      </header>
      <dl className="profile-facts">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt>{t(label)}</dt>
            <dd>{value ?? '-'}</dd>
          </div>
        ))}
      </dl>
    </article>
  )
}
