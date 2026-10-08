import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

const WAKE_INTERVAL_MS = 5000
const WAKE_BUDGET_MS = 120000

/**
 * First paint wakes a sleeping server (health, retry 5s, give up after 2 min),
 * then runs loader. Later reloads skip the wake and keep the last payload.
 */
export function usePageData(loader) {
  const [status, setStatus] = useState('waking')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [nonce, setNonce] = useState(0)
  const woke = useRef(false)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    const started = Date.now()

    async function run() {
      setError(null)
      if (!woke.current) setStatus('waking')
      else setStatus('loading')

      while (!cancelled && !woke.current) {
        try {
          await api.health()
          woke.current = true
          break
        } catch (err) {
          if (Date.now() - started >= WAKE_BUDGET_MS) {
            if (!cancelled) {
              setStatus('error')
              setError(err instanceof Error ? err : new Error(String(err)))
            }
            return
          }
          await new Promise((resolve) => setTimeout(resolve, WAKE_INTERVAL_MS))
        }
      }
      if (cancelled) return
      setStatus('loading')
      try {
        const next = await loader()
        if (!cancelled) {
          setData(next)
          setStatus('ready')
        }
      } catch (err) {
        if (!cancelled) {
          setStatus('error')
          setError(err instanceof Error ? err : new Error(String(err)))
        }
      }
    }

    run()
    return () => { cancelled = true }
  }, [loader, nonce])

  return { status, data, error, reload }
}
