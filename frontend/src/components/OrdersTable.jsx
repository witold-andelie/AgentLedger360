import { fmt } from '../api'
import { useT } from '../i18n.jsx'
import StatusBadge from './StatusBadge'

export default function OrdersTable({ orders }) {
  const { t } = useT()
  if (!orders?.length) return null
  return (
    <section className="card">
      <h3>{t('Recent orders')}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('Order')}</th>
              <th>{t('Symbol')}</th>
              <th>{t('Seller')}</th>
              <th className="num">{t('Amount')}</th>
              <th className="num">{t('Refund')}</th>
              <th>{t('Outcome')}</th>
              <th className="num">{t('Hit rate')}</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.order_id}>
                <td className="mono">{order.order_id}</td>
                <td>{order.symbol}</td>
                <td>{order.seller_agent_id}</td>
                <td className="num">{fmt.usd(order.amount_minor)}</td>
                <td className="num">{fmt.usd(order.refunded_minor)}</td>
                <td><StatusBadge status={order.final_status} /></td>
                <td className="num">{fmt.pct(order.hit_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
