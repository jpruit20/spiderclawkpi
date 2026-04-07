import { useEffect, useMemo, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { buildDepartmentViews } from '../lib/departmentViews'
import { backlogAction, DecisionAction, issueAction, rankActions, topDiagnosticAction, trustAction } from '../lib/operatingModel'
import { FreshdeskAgentDailyItem, FreshdeskTicketItem, IssueRadarResponse, KPIDaily, OverviewResponse, SupportOverviewResponse } from '../lib/types'

function severityTone(value: string) {
  if (value === 'critical') return 'bad'
  if (value === 'high') return 'warn'
  return 'muted'
}

export function DepartmentViews() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [support, setSupport] = useState<SupportOverviewResponse | null>(null)
  const [issues, setIssues] = useState<IssueRadarResponse | null>(null)
  const [dailyRows, setDailyRows] = useState<KPIDaily[]>([])
  const [agents, setAgents] = useState<FreshdeskAgentDailyItem[]>([])
  const [tickets, setTickets] = useState<FreshdeskTicketItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [overviewPayload, supportPayload, issuesPayload, dailyPayload, agentsPayload, ticketsPayload] = await Promise.all([
          api.overview(),
          api.supportOverview(),
          api.issues(),
          api.dailyKpis(),
          api.supportAgents(),
          api.supportTickets(),
        ])
        if (cancelled) return
        setOverview(overviewPayload)
        setSupport(supportPayload)
        setIssues(issuesPayload)
        setDailyRows([...dailyPayload].sort((a, b) => a.business_date.localeCompare(b.business_date)))
        setAgents(agentsPayload || [])
        setTickets(ticketsPayload || [])
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load department views')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const decisionActions = useMemo(() => {
    const currentRows = (overview?.daily_series || []).slice(-7)
    const latest = currentRows.at(-1)
    const sourceHealth = overview?.source_health || []
    const supportRows = support?.rows || []
    const built: DecisionAction[] = [
      ...topDiagnosticAction(currentRows, sourceHealth, overview?.diagnostics || [], overview?.recommendations || []),
      ...issueAction(issues?.clusters?.[0], latest, sourceHealth),
      ...backlogAction(supportRows, sourceHealth),
      ...trustAction(sourceHealth, latest),
    ]
    return rankActions(built)
  }, [overview, support, issues])

  const views = useMemo(() => buildDepartmentViews({
    dailyRows,
    supportRows: support?.rows || [],
    sourceHealth: overview?.source_health || [],
    issueClusters: issues?.clusters || [],
    decisionActions,
    supportAgents: agents,
    supportTickets: tickets,
  }), [dailyRows, support, overview, issues, decisionActions, agents, tickets])

  const pageActions = [
    'Keep high-level KPI rows above low-level evidence so each leader can answer “what matters now?” first.',
    'Use named owners and SLAs in every department section; do not leave actions as abstract observations.',
    'Treat AWS / Venom and ERP gaps as explicit confidence limits instead of silently implying full coverage.',
  ]

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Department Operating Views</h2>
        <p>Leader-by-leader operating system layer built on top of the current dashboard architecture.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>

      <ActionBlock title="Operating rules" items={pageActions} />
      {loading ? <Card title="Department Views"><div className="state-message">Loading operating views…</div></Card> : null}
      {error ? <Card title="Department Views Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? views.map((view) => (
        <section className="department-section" key={view.key}>
          <div className="department-head">
            <div>
              <h3>{view.leader}</h3>
              <p>{view.department} · {view.summary}</p>
            </div>
          </div>
          <div className="three-col">
            {view.highLevelKpis.map((kpi) => (
              <Card key={`${view.key}-${kpi.label}`} title={kpi.label}>
                <div className="hero-metric hero-metric-sm">{kpi.value}</div>
              </Card>
            ))}
          </div>
          <div className="three-col">
            <Card title="What’s working">
              <div className="stack-list compact">
                {view.whatsWorking.map((item, index) => <div className="list-item status-good" key={index}><p>{item}</p></div>)}
                {!view.whatsWorking.length ? <div className="list-item status-muted"><p>No strong positive signal yet.</p></div> : null}
              </div>
            </Card>
            <Card title="What’s not working">
              <div className="stack-list compact">
                {view.whatsNot.map((item, index) => <div className="list-item status-bad" key={index}><p>{item}</p></div>)}
                {!view.whatsNot.length ? <div className="list-item status-good"><p>No urgent failure signal surfaced for this view.</p></div> : null}
              </div>
            </Card>
            <Card title="Low-level signals">
              <div className="stack-list compact">
                {view.lowLevelSignals.map((item, index) => <div className="list-item status-muted" key={index}><p>{item}</p></div>)}
              </div>
            </Card>
          </div>
          <Card title="What to do next">
            <div className="stack-list">
              {view.actions.map((action, index) => (
                <div className={`list-item status-${severityTone(action.severity)}`} key={`${view.key}-action-${index}`}>
                  <div className="item-head">
                    <strong>{action.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge ${action.severity === 'critical' ? 'badge-bad' : action.severity === 'high' ? 'badge-warn' : 'badge-neutral'}`}>{action.severity}</span>
                      <span className="badge badge-good">{action.impact}</span>
                    </div>
                  </div>
                  <p>{action.whatToDo}</p>
                  <small><strong>Owner:</strong> {action.owner} · <strong>SLA:</strong> {action.sla}</small>
                  <small><strong>Evidence:</strong> {action.evidence.join(', ')}</small>
                </div>
              ))}
            </div>
          </Card>
        </section>
      )) : null}
    </div>
  )
}
