import { useEffect, useState } from 'react'
import { api } from '../api'
import { useT } from '../i18n.jsx'

/** Disputes waiting for a person. The clearing house has not moved the money yet. */
export default function ReviewQueue() {
  const { t } = useT()
  const [rows, setRows] = useState([])
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)

  function reload() {
    api.reviews().then(setRows).catch((err) => setError(err))
  }

  useEffect(() => {
    let cancelled = false
    api.reviews().then((next) => { if (!cancelled) setRows(next) }).catch((err) => { if (!cancelled) setError(err) })
    return () => { cancelled = true }
  }, [])

  async function decide(row) {
    const token = window.prompt(t('Admin token'))
    if (token === null) return
    const humanId = window.prompt(t('Your name'))
    if (!humanId) return
    const rationale = window.prompt(t('Why this ruling'))
    if (!rationale) return
    const pctText = window.prompt(t('Refund percent'), String(row.proposed_pct))
    if (pctText === null) return
    setError(null)
    setMessage(null)
    try {
      const body = await api.decideReview(row.order_id, {
        human_id: humanId,
        rationale,
        decision: row.decision,
        refund_pct: Number(pctText),
        cited_checks: row.failed_checks || [],
      }, token || null)
      setMessage(`${row.order_id}: ${body.decision}`)
      reload()
    } catch (err) {
      setError(err)
    }
  }

  if (!rows.length && !error) return null
  return (
    <section className="card">
      <h3>{t('Pending reviews')}</h3>
      {error && <p className="form-error" role="alert">{error.message}</p>}
      {message && <p className="muted" role="status">{message}</p>}
      <ul className="check-list">
        {rows.map((row) => (
          <li key={row.order_id}>
            <span className="mono">{row.order_id}</span>
            <span>{row.reason}</span>
            <span className="num">{row.min_pct}–{row.max_pct}%</span>
            <button type="button" className="btn" onClick={() => decide(row)}>{t('Decide')}</button>
          </li>
        ))}
      </ul>
    </section>
  )
}
