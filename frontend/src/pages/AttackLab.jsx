import { useState } from 'react'
import { ShieldCheck, ShieldX } from 'lucide-react'
import { api } from '../api'
import { useT } from '../i18n.jsx'

export default function AttackLab() {
  const { t } = useT()
  const [rows, setRows] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(null)

  async function run() {
    setRunning(true)
    setError(null)
    try {
      setRows(await api.runAttacks())
    } catch (err) {
      setError(err)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <h2>{t('Attack lab')}</h2>
        <p className="muted">{t('Each button is one attack against a throwaway market. Nothing here spends LLM credit or touches the demo ledger.')}</p>
      </header>
      <section className="card">
        <button type="button" className="btn btn-primary" onClick={run} disabled={running}>
          {running ? t('Running attacks…') : t('Run all attacks')}
        </button>
        {error && <p className="form-error" role="alert">{error.message}</p>}
      </section>
      {rows && rows.length === 0 && <section className="card empty-hint"><p>{t('No attacks ran.')}</p></section>}
      {rows && rows.length > 0 && (
        <section className="card">
          <ul className="check-list">
            {rows.map((row) => (
              <li key={row.id}>
                <button type="button" className="btn" onClick={() => setOpen(open === row.id ? null : row.id)}>
                  <span className={`badge ${row.blocked ? 'good' : 'bad'}`}>
                    {row.blocked
                      ? <ShieldCheck size={14} aria-hidden="true" />
                      : <ShieldX size={14} aria-hidden="true" />}
                    <span>{row.blocked ? t('Blocked') : t('Not blocked')}</span>
                  </span>
                  <span className="mono">{row.rule}</span>
                  <span>{row.title}</span>
                </button>
                {open === row.id && (
                  <p className="muted mono">{row.http_status ? `HTTP ${row.http_status}. ` : ''}{row.detail}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
