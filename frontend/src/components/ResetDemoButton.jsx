import { useState } from 'react'
import { Loader2, RotateCcw } from 'lucide-react'
import { api, fmt } from '../api'
import { useT } from '../i18n.jsx'

/** Wipes orders, ledger, agent runs and AI costs, then refills the buyer wallet. Asks before acting. */
export default function ResetDemoButton({ health, disabled, onDone }) {
  const { t } = useT()
  const [resetting, setResetting] = useState(false)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  async function reset() {
    if (!window.confirm(t('Reset the demo? All orders, agent runs and AI costs are deleted and the buyer wallet is refilled.'))) {
      return
    }
    let token = null
    if (health?.reset_requires_token) {
      token = window.prompt(t('Admin token'))
      if (!token) return
    }
    setResetting(true)
    setMessage(null)
    setError(null)
    try {
      let body
      try {
        body = await api.resetDemo(token)
      } catch (err) {
        // Pages without health info learn about the token from the 403 and ask once.
        if (token || !/admin token/i.test(err.message)) throw err
        token = window.prompt(t('Admin token'))
        if (!token) return
        body = await api.resetDemo(token)
      }
      setMessage(`${t('Demo reset: buyer wallet refilled to')} ${fmt.usd(body.buyer_balance_minor)}`)
      onDone?.(body)
    } catch (err) {
      setError(err)
    } finally {
      setResetting(false)
    }
  }

  return (
    <span className="reset-demo">
      <button type="button" className="btn btn-icon" onClick={reset} disabled={disabled || resetting}>
        {resetting ? <Loader2 className="spin" size={16} aria-hidden="true" /> : <RotateCcw size={16} aria-hidden="true" />}
        {t('Reset demo')}
      </button>
      {message && <span className="muted" role="status">{message}</span>}
      {error && <span className="form-error" role="alert">{error.message}</span>}
    </span>
  )
}
