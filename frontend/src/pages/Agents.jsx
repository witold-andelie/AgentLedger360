import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import AgentCardGrid from '../components/AgentCardGrid'
import AgentTable from '../components/AgentTable'
import PageState from '../components/PageState'
import ReputationBars from '../components/ReputationBars'
import { useT } from '../i18n.jsx'
import { usePageData } from '../usePageData'

export default function Agents() {
  const { t } = useT()
  const load = useCallback(() => api.summary(), [])
  const page = usePageData(load)
  const [cards, setCards] = useState(null)
  const [cardError, setCardError] = useState(null)

  useEffect(() => {
    if (!page.data) return undefined
    let cancelled = false
    api.agentCards().then(
      (rows) => { if (!cancelled) setCards(rows) },
      (err) => { if (!cancelled) setCardError(err) },
    )
    return () => { cancelled = true }
  }, [page.data])

  const agents = page.data?.agents || []

  return (
    <PageState status={page.status} error={page.error} onRetry={page.reload} hasData={Boolean(page.data)}>
      <div className="page">
        <header className="page-head">
          <h2>{t('Agents')}</h2>
        </header>
        {agents.length === 0 ? (
          <section className="card empty-hint"><p>{t('Press Run market round')}</p></section>
        ) : (
          <>
            <ReputationBars agents={agents} />
            <AgentTable agents={agents} />
          </>
        )}
        <AgentCardGrid cards={cards} error={cardError} />
      </div>
    </PageState>
  )
}
