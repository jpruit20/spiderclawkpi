import { Card } from './Card'
import { DecisionAction } from '../lib/operatingModel'

function tone(action: DecisionAction) {
  if (action.confidence >= 0.8) return 'good'
  if (action.confidence >= 0.55) return 'warn'
  return 'bad'
}

function icon(action: DecisionAction) {
  if (action.signal === 'trust') return '!!'
  if (action.signal === 'conversion' || action.signal === 'revenue') return '▲'
  return '▼'
}

export function DecisionStack({ actions }: { actions: DecisionAction[] }) {
  return (
    <Card title="Decision Stack">
      <div className="stack-list">
        {actions.slice(0, 5).map((action, index) => (
          <div className={`list-item decision-item status-${tone(action)}`} key={action.id}>
            <div className="item-head">
              <strong>{index + 1}. {icon(action)} {action.title}</strong>
              <div className="inline-badges">
                <span className="badge badge-good">{action.financialImpactLabel}</span>
                <span className="badge badge-neutral">confidence {action.confidence.toFixed(2)}</span>
                <span className="badge badge-neutral">{action.lifecycle.replace('_', ' ')}</span>
              </div>
            </div>
            <p>{action.why}</p>
            <div className="decision-meta-grid">
              <div><small>Owner</small><p>{action.owner}</p></div>
              <div><small>SLA</small><p>{action.sla}</p></div>
              <div><small>Priority score</small><p>{action.priorityScore.toFixed(0)}</p></div>
            </div>
          </div>
        ))}
        {!actions.length ? <div className="state-message">No prioritized actions available.</div> : null}
      </div>
    </Card>
  )
}
