import { useT } from '../i18n.jsx'

const TONE = {
  Champion: 'good',
  Loyal: 'warn',
  New: 'warn',
  'At Risk': 'bad',
  Lost: 'bad',
}

export default function RfmChip({ rfm }) {
  const { t } = useT()
  if (!rfm) return null
  const tone = TONE[rfm.segment] || 'neutral'
  return (
    <p className={`rfm-chip ${tone}`}>
      <span>{t(rfm.segment)}</span>
      <span className="rfm-scores">
        {t('Recency')} {rfm.r_score} · {t('Frequency')} {rfm.f_score} · {t('Monetary')} {rfm.m_score}
      </span>
    </p>
  )
}
