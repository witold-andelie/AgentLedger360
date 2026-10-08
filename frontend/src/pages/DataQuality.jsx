import { useCallback, useEffect, useState } from 'react'
import { ShieldCheck, ShieldX } from 'lucide-react'
import { api } from '../api'
import CheckList from '../components/CheckList'
import EventFeed from '../components/EventFeed'
import PageState from '../components/PageState'
import PipelineLineage from '../components/PipelineLineage'
import { useT } from '../i18n.jsx'
import { usePageData } from '../usePageData'

export default function DataQuality() {
  const { t } = useT()
  const load = useCallback(() => api.summary(), [])
  const page = usePageData(load)
  const checks = page.data?.dq || []
  const [audit, setAudit] = useState(null)

  useEffect(() => {
    if (!page.data) return undefined
    let cancelled = false
    api.auditVerify().then(
      (body) => { if (!cancelled) setAudit(body) },
      () => { if (!cancelled) setAudit(null) },
    )
    return () => { cancelled = true }
  }, [page.data])

  return (
    <PageState status={page.status} error={page.error} onRetry={page.reload} hasData={Boolean(page.data)}>
      <div className="page">
        <header className="page-head">
          <h2>{t('Data quality')}</h2>
        </header>
        {checks.length === 0 ? (
          <section className="card empty-hint"><p>{t('Press Run market round')}</p></section>
        ) : (
          <CheckList checks={checks} />
        )}
        {audit && (
          <section className={`card recon ${audit.ok ? 'good' : 'bad'}`} role="status">
            <p className="recon-title">
              {audit.ok ? <ShieldCheck size={16} aria-hidden="true" /> : <ShieldX size={16} aria-hidden="true" />}
              {' '}
              {audit.ok
                ? t('Audit chain verified')
                : `${t('Audit chain broken at event')} ${audit.first_bad_seq}`}
            </p>
          </section>
        )}
        <PipelineLineage />
        <EventFeed />
      </div>
    </PageState>
  )
}
