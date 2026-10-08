import { Database, Lock, Package, Receipt, Scale, Search, ShieldCheck } from 'lucide-react'
import { useT } from '../i18n.jsx'

const STEPS = [
  ['Discover', Search],
  ['402 quote', Receipt],
  ['Escrow', Lock],
  ['Delivery', Package],
  ['Verify', ShieldCheck],
  ['Settle or dispute', Scale],
  ['Warehouse', Database],
]

export default function FlowStrip() {
  const { t } = useT()
  return (
    <section className="card">
      <ol className="flow-strip">
        {STEPS.map(([label, Icon], index) => (
          <li key={label}>
            <span className="flow-step">
              <Icon size={16} aria-hidden="true" />
              {t(label)}
            </span>
            {index < STEPS.length - 1 && <span className="flow-arrow" aria-hidden="true">→</span>}
          </li>
        ))}
      </ol>
      <p className="muted">{t('Simulated clearing house. No real funds move.')}</p>
    </section>
  )
}
