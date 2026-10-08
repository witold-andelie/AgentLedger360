import { AlertTriangle, Brain, ShieldCheck, Wrench } from 'lucide-react'
import { fmt } from '../api'
import { useT } from '../i18n.jsx'

const KINDS = {
  llm: { Icon: Brain, label: 'LLM' },
  tool: { Icon: Wrench, label: 'Tool' },
  policy: { Icon: ShieldCheck, label: 'Policy' },
  error: { Icon: AlertTriangle, label: 'Error' },
}

function pretty(text) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text // clipped results are not valid JSON any more; show them as-is
  }
}

// Models often answer in Markdown; the trace shows plain text, so drop bold/heading markers.
const plain = (text) => String(text).replace(/\*\*/g, '').replace(/^#{1,6}\s+/gm, '')

function compactArgs(args) {
  const entries = Object.entries(args || {})
  if (entries.length === 0) return ''
  return entries.map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ')
}

/** One step of an agent run: an LLM call (tokens, cost), a tool call (args, result) or a policy event. */
export default function StepRow({ step, children }) {
  const { t } = useT()
  const kind = KINDS[step.kind] || KINDS.error
  const { Icon } = kind
  const detail = step.detail || {}
  const failed = step.kind === 'error' || (step.kind === 'tool' && detail.ok === false)
  const tone = failed ? 'bad' : step.kind === 'policy' ? 'policy' : ''
  const calls = detail.tool_calls || []
  const longText = step.kind === 'llm' && (step.name === 'plan' || step.name === 'reflect')

  return (
    <li className={`step ${tone}`}>
      <div className="step-line">
        <span className="step-seq num">{step.seq}</span>
        <span className="step-kind">
          <Icon size={14} aria-hidden="true" />
          {t(kind.label)}{step.kind === 'llm' ? ` · ${step.name}` : ''}
        </span>
        <div className="step-body">
          {step.kind === 'llm' && calls.length > 0 && (
            <p className="step-calls">→ {calls.join(', ')}</p>
          )}
          {step.kind === 'llm' && detail.text && (
            longText ? <pre className="step-text">{plain(detail.text)}</pre> : <p className="step-text clamp">{plain(detail.text)}</p>
          )}
          {step.kind === 'tool' && (
            <>
              <p className="step-calls mono">{step.name}({compactArgs(detail.args)})</p>
              <details className="step-result">
                <summary>{t(failed ? 'Error' : 'Result')}</summary>
                <pre>{pretty(String(detail.result ?? ''))}</pre>
              </details>
            </>
          )}
          {(step.kind === 'policy' || step.kind === 'error') && (
            <p className="step-text">
              <strong>{step.name}</strong>{' '}
              {Object.entries(detail).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(' · ')}
            </p>
          )}
        </div>
        <span className="step-meta num">
          {step.kind === 'llm' && (
            <>
              <span title={t('Tokens in / out')}>{fmt.tokens(step.input_tokens)} / {fmt.tokens(step.output_tokens)}</span>
              <span className="step-cost">{fmt.microUsd(step.cost_micro_usd)}</span>
            </>
          )}
          {step.latency_ms > 0 && <span className="muted">{step.latency_ms} {t('ms')}</span>}
        </span>
      </div>
      {children}
    </li>
  )
}
