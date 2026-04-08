import { ActionObject } from '../lib/types'
import { RankedActionObject } from '../lib/divisionContract'

function tone(action: ActionObject) {
  if (action.priority === 'critical') return 'bad'
  if (action.priority === 'high') return 'warn'
  return 'muted'
}

export function ActionBlock({ title = 'Recommended Next Actions', items }: { title?: string; items: Array<ActionObject | RankedActionObject> }) {
  return (
    <div className="card action-card">
      <div className="card-title">{title}</div>
      <div className="stack-list action-list">
        {items.length ? items.map((item, index) => (
          <div className={`list-item status-${tone(item)}`} key={item.id || index}>
            <div className="item-head">
              <strong>{index === 0 ? 'Do first' : index === 1 ? 'Do next' : 'Keep in view'}</strong>
              <span className="badge badge-neutral">{item.priority}</span>
            </div>
            <p>{item.required_action}</p>
            <small><strong>Owner:</strong> {item.owner} · <strong>Status:</strong> {item.status} · <strong>Due:</strong> {item.due_date}</small>
            <small><strong>Trigger KPI:</strong> {item.trigger_kpi} · <strong>Condition:</strong> {item.trigger_condition}</small>
          </div>
        )) : <div className="state-message">No action recommendations generated.</div>}
      </div>
    </div>
  )
}
