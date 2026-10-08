/* eslint-disable react-refresh/only-export-components --
   this infra file intentionally exports both the provider and the useT hook */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { ZH } from './translations'

/**
 * Lightweight i18n (same mechanism as EuroGoal, direction flipped for an English-speaking jury):
 * the ENGLISH source string is the key: t('Run market round'). In Chinese mode we look it up in ZH;
 * a missing key degrades to English, so the default demo language can never show a half-translated UI.
 */
const I18nContext = createContext(null)

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem('lang') || 'en' } catch { return 'en' }
  })

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
  }, [lang])

  const setLang = useCallback((l) => {
    try { localStorage.setItem('lang', l) } catch { /* private mode etc. */ }
    setLangState(l)
  }, [])

  const t = useCallback((s) => (lang === 'zh' ? (ZH[s] ?? s) : s), [lang])

  return <I18nContext.Provider value={{ lang, setLang, t }}>{children}</I18nContext.Provider>
}

export function useT() {
  const ctx = useContext(I18nContext)
  if (!ctx) return { lang: 'en', setLang: () => {}, t: (s) => s }
  return ctx
}
