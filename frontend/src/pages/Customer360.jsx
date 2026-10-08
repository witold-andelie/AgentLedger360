import { useCallback } from 'react'
import { api } from '../api'
import CustomerProfile from '../components/CustomerProfile'
import OrdersTable from '../components/OrdersTable'
import PageState from '../components/PageState'
import { useT } from '../i18n.jsx'
import { usePageData } from '../usePageData'

export default function Customer360() {
  const { t } = useT()
  const load = useCallback(() => api.summary(), [])
  const page = usePageData(load)
  const customers = page.data?.customers || []
  const rfm = page.data?.rfm || []
  const byBuyer = Object.fromEntries(rfm.map((row) => [row.buyer_agent_id, row]))

  return (
    <PageState status={page.status} error={page.error} onRetry={page.reload} hasData={Boolean(page.data)}>
      <div className="page">
        <header className="page-head">
          <h2>{t('Customer 360')}</h2>
        </header>
        {customers.length === 0 ? (
          <section className="card empty-hint"><p>{t('Press Run market round')}</p></section>
        ) : (
          <div className="profile-grid">
            {customers.map((customer) => (
              <CustomerProfile
                key={customer.buyer_agent_id}
                customer={customer}
                rfm={byBuyer[customer.buyer_agent_id]}
              />
            ))}
          </div>
        )}
        <OrdersTable orders={page.data?.orders} />
      </div>
    </PageState>
  )
}
