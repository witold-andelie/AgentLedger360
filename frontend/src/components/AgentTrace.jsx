import { Scale } from 'lucide-react'
import { fmt } from '../api'
import { useT } from '../i18n.jsx'
import StatusBadge from './StatusBadge'
import StepRow from './StepRow'

function RunHead({ run }) {
  const { t } = useT()
  return (
    <div className="run-head">
      <StatusBadge status={run.status} />
      <span className="mono">{run.run_id}</span>
      <span className="muted">{run.agent_id} · {run.model}</span>
      <span className="muted num">
        {run.llm_calls} {t('LLM calls')} · {run.tool_calls} {t('tool calls')} · {fmt.tokens(run.input_tokens)} / {fmt.tokens(run.output_tokens)} {t('tokens')} · {fmt.microUsd(run.cost_micro_usd)}
      </span>
    </div>
  )
}

function GuardianRun({ run }) {
  const { t } = useT()
  return (
    <div className="guardian-run">
      <p className="guardian-title"><Scale size={14} aria-hidden="true" /> {t('Guardian agent investigates the dispute')}</p>
      <RunHead run={run} />
      <ol className="trace-list">
        {(run.steps || []).map((step) => <StepRow key={step.seq} step={step} />)}
      </ol>
    </div>
  )
}

/** Live trace of one agent run; guardian runs are nested under the dispute that triggered them. */
export default function AgentTrace({ run, live }) {
  const { t } = useT()
  const children = run.children || []
  const placed = new Set()
  const childrenFor = (step) => {
    const orderId = step.kind === 'tool' && step.name === 'open_dispute' ? step.detail?.args?.order_id : null
    if (!orderId) return []
    const matches = children.filter((c) => !placed.has(c.run_id) && (c.goal || '').includes(orderId))
    matches.forEach((c) => placed.add(c.run_id))
    return matches
  }
  const rows = (run.steps || []).map((step) => (
    <StepRow key={step.seq} step={step}>
      {childrenFor(step).map((child) => <GuardianRun key={child.run_id} run={child} />)}
    </StepRow>
  ))
  const orphans = children.filter((c) => !placed.has(c.run_id))

  return (
    <section className="card">
      <h3>{t(run.role === 'guardian' ? 'Guardian agent trace' : 'Buyer agent trace')}{live ? ` · ${t('live')}` : ''}</h3>
      <p className="muted goal">{run.goal}</p>
      <RunHead run={run} />
      {rows.length === 0 ? <p className="muted">{t('Waiting for the first step…')}</p> : <ol className="trace-list">{rows}</ol>}
      {orphans.map((child) => <GuardianRun key={child.run_id} run={child} />)}
    </section>
  )
}
