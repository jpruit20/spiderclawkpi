import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { DecisionStack } from '../components/DecisionStack'
import { TrendChart } from '../components/TrendChart'
import { ApiError, api, getApiBase } from '../lib/api'
import { compareValue, formatDeltaPct, priorPeriodRows } from '../lib/compare'
import { backlogAction, currency, DecisionAction, issueAction, rankActions, summarizeLifecycle, topDiagnosticAction, trustAction } from '../lib/operatingModel'
import { KPIDaily, OverviewResponse, SupportOverviewResponse, IssueRadarResponse } from '../lib/types'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

export function CommandCenter() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [support, setSupport] = useState<SupportOverviewResponse | null>(null)
  const [issues, setIssues] = useState<IssueRadarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [overviewPayload, supportPayload, issuesPayload] = await Promise.all([
          api.overview(),
          api.supportOverview(),
          api.issues(),
        ])
        if (cancelled) return
        setOverview(overviewPayload)
        setSupport(supportPayload)
        setIssues(issuesPayload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load command center')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const rows = useMemo(() => [...(overview?.daily_series || [])].sort((a, b) => a.business_date.localeCompare(b.business_date)), [overview])
  const currentRows = rows.slice(-7)
  const priorRows = useMemo(() => priorPeriodRows(rows, currentRows[0]?.business_date || '', currentRows.length), [rows, currentRows])
  const latest = currentRows.at(-1)
  const sourceHealth = overview?.source_health || []
  const revenue = sum(currentRows, 'revenue')
  const priorRevenue = sum(priorRows, 'revenue')
  const sessions = sum(currentRows, 'sessions')
  const priorSessions = sum(priorRows, 'sessions')
  const orders = sum(currentRows, 'orders')
  const priorOrders = sum(priorRows, 'orders')
  const aov = orders ? revenue / orders : 0
  const conv = sessions ? (orders / sessions) * 100 : 0
  const priorConv = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const supportRows = support?.rows || []
  const actions = useMemo(() => {
    const built: DecisionAction[] = [
      ...topDiagnosticAction(currentRows, sourceHealth, overview?.diagnostics || [], overview?.recommendations || []),
      ...issueAction(issues?.clusters?.[0], latest, sourceHealth),
      ...backlogAction(supportRows, sourceHealth),
      ...trustAction(sourceHealth, latest),
    ]
    return rankActions(built).slice(0, 5)
  }, [currentRows, sourceHealth, overview, issues, latest, supportRows])
  const lifecycle = summarizeLifecycle(actions)
  const revenueDelta = compareValue(revenue, priorRows.length === currentRows.length ? priorRevenue : null, 'Revenue')
  const convDelta = compareValue(conv, priorRows.length === currentRows.length ? priorConv : null, 'Conversion')

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Command Center</h2>
        <p>What to do next, why it matters, and the weekly revenue at stake.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Command Center"><div className="state-message">Loading decision system…</div></Card> : null}
      {error ? <Card title="Command Center Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="three-col">
            <Card title="Revenue Direction">
              <div className="hero-metric">{formatDeltaPct(revenueDelta.deltaPct)}</div>
              <div className="state-message">{currency(revenue)} this week · impact baseline for prioritization</div>
            </Card>
            <Card title="Conversion Direction">
              <div className="hero-metric">{formatDeltaPct(convDelta.deltaPct)}</div>
              <div className="state-message">{conv.toFixed(2)}% current conversion · every action ties to recovered orders</div>
            </Card>
            <Card title="Action Lifecycle">
              <div className="mini-metrics">
                <small>open {lifecycle.open} · in progress {lifecycle.in_progress}</small>
                <small>validated {lifecycle.validated} · closed {lifecycle.closed}</small>
                <small>revenue recovered signal {currency(lifecycle.revenueRecovered)}/week</small>
              </div>
            </Card>
          </div>
          <DecisionStack actions={actions} />
          <div className="two-col two-col-equal">
            <Card title="10-second decision view">
              <div className="stack-list compact">
                <div className="list-item status-good"><strong>Do now</strong><p>{actions[0]?.title || 'No action ranked yet.'}</p></div>
                <div className="list-item status-warn"><strong>Why</strong><p>{actions[0]?.why || 'Need live inputs to rank next action.'}</p></div>
                <div className="list-item status-muted"><strong>Financial impact</strong><p>{actions[0]?.financialImpactLabel || '$0/week'} · owner {actions[0]?.owner || 'TBD'} · SLA {actions[0]?.sla || 'n/a'}</p></div>
              </div>
            </Card>
            <Card title="Trust Layer">
              <div className="stack-list compact">
                {sourceHealth.filter((row) => ['shopify','triplewhale','freshdesk','clarity','ga4'].includes(row.source)).map((row) => (
                  <div className={`list-item status-${row.derived_status === 'healthy' ? 'good' : row.derived_status === 'failed' ? 'bad' : 'warn'}`} key={row.source}>
                    <div className="item-head"><strong>{row.source}</strong><span className="badge badge-neutral">{row.derived_status}</span></div>
                    <small>{row.status_summary}</small>
                  </div>
                ))}
              </div>
            </Card>
          </div>
          <Card title="Command Center Trend">
            {currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'revenue', label: 'Revenue', color: '#6ea8ff', axisId: 'left' }, { key: 'orders', label: 'Orders', color: '#39d08f', axisId: 'right' }]} /> : <div className="state-message">No KPI rows returned.</div>}
          </Card>
        </>
      ) : null}
    </div>
  )
}
