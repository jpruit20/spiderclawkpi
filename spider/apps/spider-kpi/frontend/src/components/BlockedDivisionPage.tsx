import { Card } from './Card'

export interface ReadinessItem {
  label: string
  status: 'ready' | 'partial' | 'blocked'
  detail: string
}

export interface BlockedActionItem {
  title: string
  owner: string
  sla: string
  why: string
  nextStep: string
}

export function BlockedDivisionPage(props: {
  title: string
  owner: string
  summary: string
  blockedReason: string
  readiness: ReadinessItem[]
  actions: BlockedActionItem[]
  requiredMetrics: string[]
  sources: string[]
  drilldowns?: Array<{ label: string; href: string }>
}) {
  const { title, owner, summary, blockedReason, readiness, actions, requiredMetrics, sources, drilldowns = [] } = props
  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>{title}</h2>
        <p>{summary}</p>
      </div>
      <div className="trust-banner trust-banner-degraded">
        <div>
          <strong>Blocked-state operator page</strong>
          <p>{blockedReason}</p>
        </div>
        <div className="inline-badges">
          <span className="badge badge-neutral">owner {owner}</span>
          <span className="badge badge-warn">truth-first blocked state</span>
        </div>
      </div>
      <div className="three-col">
        <Card title="Readiness">
          <div className="stack-list compact">
            {readiness.map((item) => (
              <div className={`list-item status-${item.status === 'ready' ? 'good' : item.status === 'partial' ? 'warn' : 'bad'}`} key={item.label}>
                <strong>{item.label}</strong>
                <p>{item.detail}</p>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Required metrics">
          <div className="stack-list compact">
            {requiredMetrics.map((item) => <div className="list-item status-muted" key={item}><p>{item}</p></div>)}
          </div>
        </Card>
        <Card title="Required sources">
          <div className="stack-list compact">
            {sources.map((item) => <div className="list-item status-muted" key={item}><p>{item}</p></div>)}
          </div>
        </Card>
      </div>
      <Card title="What should happen next">
        <div className="stack-list">
          {actions.map((item) => (
            <div className="list-item status-warn" key={item.title}>
              <div className="item-head">
                <strong>{item.title}</strong>
                <span className="badge badge-neutral">{item.sla}</span>
              </div>
              <p>{item.nextStep}</p>
              <small><strong>Owner:</strong> {item.owner}</small>
              <small><strong>Why:</strong> {item.why}</small>
            </div>
          ))}
        </div>
      </Card>
      {drilldowns.length ? (
        <Card title="Drill-downs">
          <div className="stack-list compact">
            {drilldowns.map((item) => <div className="list-item status-muted" key={item.href}><p><a href={item.href}>{item.label}</a></p></div>)}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
