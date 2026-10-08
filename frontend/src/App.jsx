import { useEffect, useState } from 'react'
import { Activity, Bot, Languages, ShieldCheck, Store, Users } from 'lucide-react'
import Market from './pages/Market'
import Agents from './pages/Agents'
import Customer360 from './pages/Customer360'
import DataQuality from './pages/DataQuality'
import AgentConsole from './pages/AgentConsole'
import { useT } from './i18n.jsx'

// Shell only: header, tab navigation, language toggle, view switch. Page content lives in pages/.
// Navigation is plain state (no router), same as EuroGoal. Add a view = add one entry here.
const VIEWS = [
  { id: 'market', label: 'Market', icon: Store, Page: Market },
  { id: 'console', label: 'Agent Console', icon: Bot, Page: AgentConsole },
  { id: 'agents', label: 'Agents', icon: Activity, Page: Agents },
  { id: 'customer360', label: 'Customer 360', icon: Users, Page: Customer360 },
  { id: 'quality', label: 'Data quality', icon: ShieldCheck, Page: DataQuality },
]

export default function App() {
  const { t, lang, setLang } = useT()
  const [view, setView] = useState('market')
  const current = VIEWS.find((v) => v.id === view) ?? VIEWS[0]
  const { Page } = current

  useEffect(() => {
    document.title = `${t(current.label)} - AgentLedger 360`
  }, [current, t])

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-logo">AL</div>
          <div className="brand-text">
            <h1>AgentLedger 360</h1>
            <p>{t('Agent-to-agent market for market intelligence')}</p>
          </div>
        </div>
        <div className="header-actions">
          <nav className="navigation-tabs">
            {VIEWS.map(({ id, label, icon: Icon }) => (
              <button key={id} id={`nav-tab-${id}`} className={`nav-tab ${view === id ? 'active' : ''}`}
                      onClick={() => setView(id)}>
                <Icon size={16} />
                {t(label)}
              </button>
            ))}
          </nav>
          <button className="lang-toggle" onClick={() => setLang(lang === 'en' ? 'zh' : 'en')}
                  title={lang === 'en' ? t('Switch to Chinese') : t('Switch to English')}>
            <Languages size={15} />
            {lang === 'en' ? '中' : 'EN'}
          </button>
        </div>
      </header>
      <main className="app-main">
        <Page />
      </main>
    </div>
  )
}
