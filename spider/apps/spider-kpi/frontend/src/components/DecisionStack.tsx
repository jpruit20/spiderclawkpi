import { Card } from './Card'
import { DecisionAction } from '../lib/operatingModel'

function tone(action: DecisionAction) {
  if (action.trustState === 'trust_limited') return 'bad'
  if (action.trustState === 'conditional') return 'warn'
  if (action.confidence >= 0.8) return 'good'
  if (action.confidence >= 0.55) return 'warn'
  return 'bad'
}

function icon(action: DecisionAction) {
  if (action.signal === 'trust') return '!!'
  if (action.signal === 'conversion' || action.signal === 'revenue') return '▲'
  return '▼'
}

function trustBadgeClass(action: DecisionAction) {
  if (action.trustState === 'trust_limited') return 'badge-bad'
  if (action.trustState === 'conditional') return 'badge-warn'
  return 'badge-good'
}

export function DecisionStack({ actions }: { actions: DecisionAction[] }) {
  const topThree = actions.slice(0, 3)
  const remaining = actions.slice(3, 5)

  return (
    <Card title="Canonical Next 3 Actions">
      <div className="canonical-actions-grid">
        {topThree.map((action, index) => (
          <div className={`canonical-action status-${tone(action)}`} key={action.id}>
            <div className="canonical-rank">#{index + 1}</div>
            <div className="item-head">
              <strong>{icon(action)} {action.title}</strong>
              <span className={`badge ${trustBadgeClass(action)}`}>{action.trustLabel}</span>
            </div>
            <p>{action.why}</p>
            <div className="inline-badges">
              <span className={`badge ${action.severity === 'critical' ? 'badge-bad' : action.severity === 'high' ? 'badge-warn' : 'badge-neutral'}`}>{action.severity || 'medium'}</span>
              <span className="badge badge-good">{action.financialImpactLabel}</span>
              <span className="badge badge-neutral">confidence {action.confidence.toFixed(2)}</span>
              <span className="badge badge-neutral">{action.lifecycle.replace('_', ' ')}</span>
            </div>
            {action.confidencePenalty > 0 ? (
              <small>Confidence reduced from {action.baseConfidence.toFixed(2)} because {action.blockedBy.join(', ')} is degrading trust.</small>
            ) : (
              <small>Confidence holds at {action.confidence.toFixed(2)} because required sources are currently healthy.</small>
            )}
            <div className="decision-meta-grid">
              <div><small>Owner</small><p>{action.owner}</p></div>
              <div><small>SLA</small><p>{action.sla}</p></div>
              <div><small>Priority score</small><p>{action.priorityScore.toFixed(0)}</p></div>
            </div>
            <div className="nested-block">
              <small><strong>Recommended action:</strong> {action.recommendedAction || action.why}</small>
              <small><strong>Evidence:</strong> {action.evidenceSources?.join(', ') || 'n/a'}</small>
            </div>
          </div>
        ))}
      </div>

      {remaining.length ? (
        <div className="stack-list decision-secondary-list">
          {remaining.map((action) => (
            <div className={`list-item decision-item status-${tone(action)}`} key={action.id}>
              <div className="item-head">
                <strong>{action.canonicalRank}. {icon(action)} {action.title}</strong>
                <div className="inline-badges">
                  <span className={`badge ${trustBadgeClass(action)}`}>{action.trustLabel}</span>
                  <span className="badge badge-neutral">confidence {action.confidence.toFixed(2)}</span>
                </div>
              </div>
              <p>{action.why}</p>
              <small><strong>Owner:</strong> {action.owner} · <strong>SLA:</strong> {action.sla} · <strong>Evidence:</strong> {action.evidenceSources?.join(', ') || 'n/a'}</small>
            </div>
          ))}
        </div>
      ) : null}

      {!actions.length ? <div className="state-message">No prioritized actions available.</div> : null}
    </Card>
  )
}
