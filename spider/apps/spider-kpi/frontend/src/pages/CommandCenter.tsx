import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { DecisionStack } from '../components/DecisionStack'
import { ApiError, api, getApiBase } from '../lib/api'
import { compareValue, priorPeriodRows } from '../lib/compare'
import { backlogAction, currency, DecisionAction, issueAction, rankActions, summarizeTrust, topDiagnosticAction, trustAction } from '../lib/operatingModel'
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
  const supportRows = support?.rows || []
  const revenue = sum(currentRows, 'revenue')
  const priorRevenue = sum(priorRows, 'revenue')
  const sessions = sum(currentRows, 'sessions')
  const priorSessions = sum(priorRows, 'sessions')
  const orders = sum(currentRows, 'orders')
  const priorOrders = sum(priorRows, 'orders')
  const conv = sessions ? (orders / sessions) * 100 : 0
  const priorConv = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const revenueDelta = compareValue(revenue, priorRows.length === currentRows.length ? priorRevenue : null, 'Revenue')
  const convDelta = compareValue(conv, priorRows.length === currentRows.length ? priorConv : null, 'Conversion')

  const actions = useMemo(() => {
    const built: DecisionAction[] = [
      ...topDiagnosticAction(currentRows, sourceHealth, overview?.diagnostics || [], overview?.recommendations || []),
      ...issueAction(issues?.clusters?.[0], latest, sourceHealth),
      ...backlogAction(supportRows, sourceHealth),
      ...trustAction(sourceHealth, latest),
    ]
    return rankActions(built).slice(0, 5)
  }, [currentRows, sourceHealth, overview, issues, latest, supportRows])

  const trust = summarizeTrust(sourceHealth)

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Command Center</h2>
        <p>Only the highest-priority risks and opportunities, with owner, action, impact, and SLA.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Command Center"><div className="state-message">Loading decision system…</div></Card> : null}
      {error ? <Card title="Command Center Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className={`trust-banner ${trust.degraded ? 'trust-banner-degraded' : 'trust-banner-healthy'}`}>
            <div>
              <strong>{trust.degraded ? 'Decision confidence degraded' : 'Decision confidence healthy'}</strong>
              <p>{trust.degraded ? `${trust.degradedSources.join(', ')} is limiting confidence on some ranked items.` : 'Core sources are healthy enough for decision-grade prioritization.'}</p>
            </div>
            <div className="inline-badges">
              <span className="badge badge-neutral">revenue {currency(revenue)}</span>
              <span className="badge badge-neutral">revenue Δ {revenueDelta.deltaPct?.toFixed(1) ?? 'n/a'}%</span>
              <span className="badge badge-neutral">conversion Δ {convDelta.deltaPct?.toFixed(1) ?? 'n/a'}%</span>
            </div>
          </div>
          <DecisionStack actions={actions} />
          <Card title="Diagnostic drill-downs">
            <div className="stack-list compact">
              <div className="list-item status-muted"><strong>View friction details</strong><p><a href="/friction">Open Friction Map</a></p></div>
              <div className="list-item status-muted"><strong>View root cause</strong><p><a href="/root-cause">Open Root Cause</a></p></div>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
