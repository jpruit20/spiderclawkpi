import { Card } from './Card'
import { RankedActionObject } from '../lib/divisionContract'

function tone(action: RankedActionObject) {
  if (action.truth_state === 'blocked') return 'bad'
  if (action.truth_state === 'degraded' || action.truth_state === 'estimated') return 'warn'
  if (action.priority === 'critical') return 'bad'
  if (action.priority === 'high') return 'warn'
  return 'good'
}

function icon(action: RankedActionObject) {
  if (action.trigger_kpi.includes('trust') || action.trigger_kpi.includes('source') || action.trigger_kpi.includes('health')) return '!!'
  if (action.trigger_kpi.includes('revenue') || action.trigger_kpi.includes('conversion')) return '▲'
  return '▼'
}

function truthBadgeClass(action: RankedActionObject) {
  if (action.truth_state === 'blocked') return 'badge-bad'
  if (action.truth_state === 'degraded' || action.truth_state === 'estimated') return 'badge-warn'
  return 'badge-good'
}

export function DecisionStack({ actions }: { actions: RankedActionObject[] }) {
  const topThree = actions.slice(0, 3)
  const remaining = actions.slice(3, 5)

  return (
    <Card title="Canonical Next 3 Actions">
      <div className="canonical-actions-grid">
        {topThree.map((action, index) => (
          <div className={`canonical-action status-${tone(action)}`} key={action.id}>
            <div className="canonical-rank">#{index + 1}</div>
            <div className="item-head">
              <strong>{icon(action)} {action.trigger_kpi}</strong>
              <span className={`badge ${truthBadgeClass(action)}`}>{action.truth_state}</span>
            </div>
            <p>{action.required_action}</p>
            <div className="inline-badges">
              <span className={`badge ${action.priority === 'critical' ? 'badge-bad' : action.priority === 'high' ? 'badge-warn' : 'badge-neutral'}`}>{action.priority}</span>
              <span className="badge badge-neutral">score {action.ranking_score.toFixed(0)}</span>
              <span className="badge badge-neutral">{action.status}</span>
            </div>
            <small>{action.ranking_reason}</small>
            <div className="decision-meta-grid">
              <div><small>Owner</small><p>{action.owner}</p></div>
              <div><small>Due</small><p>{action.due_date}</p></div>
              <div><small>Top-rank allowed</small><p>{action.can_top_rank ? 'yes' : 'no'}</p></div>
            </div>
            <div className="nested-block">
              <small><strong>Trigger:</strong> {action.trigger_condition}</small>
              <small><strong>Evidence:</strong> {action.evidence.join(', ') || 'n/a'}</small>
            </div>
          </div>
        ))}
      </div>

      {remaining.length ? (
        <div className="stack-list decision-secondary-list">
          {remaining.map((action, index) => (
            <div className={`list-item decision-item status-${tone(action)}`} key={action.id}>
              <div className="item-head">
                <strong>{index + 4}. {icon(action)} {action.trigger_kpi}</strong>
                <div className="inline-badges">
                  <span className={`badge ${truthBadgeClass(action)}`}>{action.truth_state}</span>
                  <span className="badge badge-neutral">score {action.ranking_score.toFixed(0)}</span>
                </div>
              </div>
              <p>{action.required_action}</p>
              <small><strong>Owner:</strong> {action.owner} · <strong>Due:</strong> {action.due_date} · <strong>Evidence:</strong> {action.evidence.join(', ') || 'n/a'}</small>
            </div>
          ))}
        </div>
      ) : null}

      {!actions.length ? <div className="state-message">No prioritized actions available.</div> : null}
    </Card>
  )
}
