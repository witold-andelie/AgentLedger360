import { fmt } from '../api'
import { useT } from '../i18n.jsx'
import StatusBadge from './StatusBadge'

export default function RoundTable({ purchases }) {
  const { t } = useT()
  return (
    <section className="card">
      <h3>{t('Round results')}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('Symbol')}</th>
              <th>{t('Seller')}</th>
              <th className="num">{t('Price')}</th>
              <th>{t('Outcome')}</th>
              <th className="num">{t('Hit rate')}</th>
              <th className="num">{t('Refund')}</th>
              <th>{t('Why')}</th>
            </tr>
          </thead>
          <tbody>
            {purchases.map((row) => {
              const why = row.rationale || (row.notes && row.notes[0]) || '-'
              return (
                <tr key={`${row.symbol}-${row.order_id || row.seller}`}>
                  <td>{row.symbol || '-'}</td>
                  <td>{row.seller || '-'}</td>
                  <td className="num">{fmt.usd(row.price_minor)}</td>
                  <td><StatusBadge status={row.status} /></td>
                  <td className="num">{fmt.pct(row.hit_rate)}</td>
                  <td className="num">{fmt.usd(row.refund_minor)}</td>
                  <td className="why">{why}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
