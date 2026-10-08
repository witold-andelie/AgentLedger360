import { useCallback } from 'react'
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
        <PipelineLineage />
        <EventFeed />
      </div>
    </PageState>
  )
}
