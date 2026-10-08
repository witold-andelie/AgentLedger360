import { useEffect, useState } from 'react'
import { api, fmt } from '../api'
import { useT } from '../i18n.jsx'
import StatusBadge from './StatusBadge'

/** Persisted agent runs, newest first; click a row to open its full trace. */
export default function RunHistory({ nonce, selectedId, onSelect }) {
  const { t } = useT()
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.agentRuns(20).then(
      (rows) => { if (!cancelled) { setRuns(rows); setError(null) } },
      (err) => { if (!cancelled) setError(err) },
    )
    return () => { cancelled = true }
  }, [nonce])

  return (
    <section className="card">
      <h3>{t('Run history')}</h3>
      {error && <p role="alert" className="form-error">{error.message}</p>}
      {runs && runs.length === 0 && <p className="muted">{t('No agent runs yet')}</p>}
      {runs && runs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('Time')}</th>
                <th>{t('Agent')}</th>
                <th>{t('Status')}</th>
                <th className="num">{t('LLM calls')}</th>
                <th className="num">{t('Tool calls')}</th>
                <th className="num">{t('Tokens in / out')}</th>
                <th className="num">{t('AI spend')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className={run.run_id === selectedId ? 'selected' : ''}>
                  <td>
                    <button type="button" className="link-btn" onClick={() => onSelect(run.run_id)}>
                      {(run.started_at || '').slice(0, 19).replace('T', ' ')}
                    </button>
                  </td>
                  <td>{run.agent_id} <span className="muted">({t(run.role === 'guardian' ? 'Guardian' : 'Buyer')})</span></td>
                  <td><StatusBadge status={run.status} /></td>
                  <td className="num">{run.llm_calls}</td>
                  <td className="num">{run.tool_calls}</td>
                  <td className="num">{fmt.tokens(run.input_tokens)} / {fmt.tokens(run.output_tokens)}</td>
                  <td className="num">{fmt.microUsd(run.cost_micro_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
