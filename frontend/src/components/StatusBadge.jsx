import { AlertTriangle, Check, Minus, X } from 'lucide-react'
import { useT } from '../i18n.jsx'

const LABELS = {
  COMPLETED: 'Completed',
  PARTIALLY_REFUNDED: 'Partial refund',
  REFUND_PARTIAL: 'Partial refund',
  REFUNDED: 'Full refund',
  REFUND_FULL: 'Full refund',
  RELEASE: 'Released to seller',
  SKIPPED: 'Skipped',
  PAYMENT_REJECTED: 'Payment rejected',
  SELLER_ERROR: 'Seller error',
  CANCELLED: 'Cancelled',
  FUNDS_HELD: 'Funds held',
  DELIVERED: 'Delivered',
  DISPUTED: 'Disputed',
  PASS: 'PASS',
  FAIL: 'FAIL',
  // agent run statuses (AgentRunReport.status)
  running: 'Running',
  completed: 'Completed',
  budget_stopped: 'Budget stop',
  failed: 'Failed',
}

const GOOD = new Set(['COMPLETED', 'RELEASE', 'PASS', 'completed'])
const WARN = new Set(['PARTIALLY_REFUNDED', 'REFUND_PARTIAL', 'budget_stopped'])
const BAD = new Set(['REFUNDED', 'REFUND_FULL', 'FAIL', 'PAYMENT_REJECTED', 'SELLER_ERROR', 'CANCELLED', 'failed'])

export default function StatusBadge({ status }) {
  const { t } = useT()
  const key = status || ''
  const tone = GOOD.has(key) ? 'good' : WARN.has(key) ? 'warn' : BAD.has(key) ? 'bad' : 'neutral'
  const Icon = tone === 'good' ? Check : tone === 'warn' ? AlertTriangle : tone === 'bad' ? X : Minus
  const label = LABELS[key] || key || 'Skipped'
  return (
    <span className={`badge ${tone}`}>
      <Icon size={14} aria-hidden="true" />
      <span>{t(label)}</span>
    </span>
  )
}
