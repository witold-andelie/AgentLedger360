import { useState } from 'react'
import { api } from '../api'
import { useT } from '../i18n.jsx'

export default function EventFeed() {
  const { t } = useT()
  const [open, setOpen] = useState(false)
  const [events, setEvents] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function toggle() {
    const next = !open
    setOpen(next)
    if (!next || events !== null) return
    setLoading(true)
    setError(null)
    try {
      setEvents(await api.events(60))
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="card">
      <button type="button" className="btn" onClick={toggle} aria-expanded={open}>
        {t(open ? 'Hide event log' : 'Show event log')}
      </button>
      {open && loading && <p className="muted">{t('Loading…')}</p>}
      {open && error && (
        <p role="alert">{error.message} <button type="button" className="btn" onClick={() => { setEvents(null); setOpen(false) }}>{t('Retry')}</button></p>
      )}
      {open && events && events.length === 0 && <p className="muted">{t('No events yet')}</p>}
      {open && events && events.length > 0 && (
        <div className="table-wrap">
          <table className="mono event-table">
            <thead>
              <tr>
                <th className="num">{t('Seq')}</th>
                <th>{t('Type')}</th>
                <th>{t('Aggregate')}</th>
                <th>{t('Time')}</th>
                <th>{t('Payload')}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.seq}>
                  <td className="num">{event.seq}</td>
                  <td>{event.event_type}</td>
                  <td>{event.aggregate_id}</td>
                  <td>{event.occurred_at}</td>
                  <td className="payload">{event.payload_json}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
