import { useT } from '../i18n.jsx'

export default function PipelineLineage() {
  const { t } = useT()
  return (
    <section className="card">
      <h3>{t('Pipeline')}</h3>
      <div className="lineage">
        <span className="lineage-box">ingest_events</span>
        <span className="flow-arrow" aria-hidden="true">→</span>
        <span className="lineage-split">
          <span className="lineage-box">build_dim_agents</span>
          <span className="lineage-box">build_fact_orders</span>
        </span>
        <span className="flow-arrow" aria-hidden="true">→</span>
        <span className="lineage-box">data_quality_checks</span>
      </div>
      <p className="muted">{t('Rebuilt from the outbox on every round.')}</p>
    </section>
  )
}
