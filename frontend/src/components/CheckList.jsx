import { useT } from '../i18n.jsx'
import StatusBadge from './StatusBadge'

export default function CheckList({ checks }) {
  const { t } = useT()
  return (
    <section className="card">
      <h3>{t('Checks')}</h3>
      <ul className="check-list">
        {checks.map((check) => (
          <li key={check.check_name}>
            <StatusBadge status={check.passed === 1 ? 'PASS' : 'FAIL'} />
            <span className="check-name">{check.check_name}</span>
            <span className="num check-count">{t('Violations')} {check.violations}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
