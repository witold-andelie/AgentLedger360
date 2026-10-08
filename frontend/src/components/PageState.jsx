import { Loader2 } from 'lucide-react'
import { useT } from '../i18n.jsx'

export default function PageState({ status, error, onRetry, hasData, children }) {
  const { t } = useT()
  if (!hasData && status === 'waking') {
    return (
      <section className="card state-panel" role="status">
        <Loader2 className="spin" size={18} aria-hidden="true" />
        <p>{t('Waking up the server…')}</p>
      </section>
    )
  }
  if (!hasData && (status === 'loading' || status === 'waking')) {
    return (
      <section className="card state-panel" role="status">
        <p>{t('Loading…')}</p>
      </section>
    )
  }
  if (!hasData && status === 'error') {
    return (
      <section className="card state-panel" role="alert">
        <p>{error?.message || t('Cannot reach the API backend. Is the FastAPI server running?')}</p>
        <button type="button" className="btn btn-primary" onClick={onRetry}>{t('Retry')}</button>
      </section>
    )
  }
  return (
    <>
      {status === 'error' && hasData && (
        <section className="card state-panel" role="alert">
          <p>{error?.message}</p>
          <button type="button" className="btn btn-primary" onClick={onRetry}>{t('Retry')}</button>
        </section>
      )}
      {children}
    </>
  )
}
