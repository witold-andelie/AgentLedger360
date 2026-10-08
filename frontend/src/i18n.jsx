/* eslint-disable react-refresh/only-export-components --
   this infra file intentionally exports both the provider and the useT hook */
import { createContext, useCallback, useContext, useEffect } from 'react'

/**
 * English-only UI. t() returns the source string so call sites stay greppable.
 * A previously stored language choice is cleared so the page cannot come back in another language.
 */
const I18nContext = createContext(null)

export function LanguageProvider({ children }) {
  useEffect(() => {
    document.documentElement.lang = 'en'
    try { localStorage.removeItem('lang') } catch { /* private mode */ }
  }, [])

  const t = useCallback((s) => s, [])

  return <I18nContext.Provider value={{ lang: 'en', setLang: () => {}, t }}>{children}</I18nContext.Provider>
}

export function useT() {
  const ctx = useContext(I18nContext)
  if (!ctx) return { lang: 'en', setLang: () => {}, t: (s) => s }
  return ctx
}
