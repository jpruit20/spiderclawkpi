import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { DecisionStack } from '../components/DecisionStack'
import { ApiError, api, getApiBase } from '../lib/api'
import { compareValue, priorPeriodRows } from '../lib/compare'
import { currency, summarizeTrust } from '../lib/operatingModel'
import { BlockedStateOutput, KPIDaily, KPIObject, OverviewResponse, SupportOverviewResponse, IssueRadarResponse } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, buildTextKpi, enforceActionContract, RankedActionObject, truthStateFromSource } from '../lib/divisionContract'

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

  const trust = summarizeTrust(sourceHealth)
  const snapshotTimestamp = latest?.business_date ? `${latest.business_date}T23:59:59Z` : new Date().toISOString()
  const kpis: KPIObject[] = useMemo(() => [
    buildNumericKpi({ key: 'command_center_revenue', currentValue: revenue, targetValue: priorRevenue || null, priorValue: priorRevenue || null, owner: 'Joseph', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'command_center_conversion', currentValue: conv, targetValue: priorConv || null, priorValue: priorConv || null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'command_center_support_backlog', currentValue: Number(supportRows.at(-1)?.open_backlog || 0), targetValue: 100, priorValue: null, owner: 'Jeremiah', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'command_center_top_issue', currentValue: issues?.clusters?.[0]?.title || 'No cluster returned', targetValue: 'No high-risk issue', owner: issues?.clusters?.[0]?.owner_team || 'TBD', status: issues?.clusters?.[0] ? 'red' : 'yellow', truthState: truthStateFromSource(sourceHealth, ['freshdesk', 'clarity', 'ga4'], 'proxy'), lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'command_center_data_trust', currentValue: trust.degraded ? `Degraded: ${trust.degradedSources.join(', ')}` : 'Healthy', targetValue: 'Healthy', owner: 'Joseph', status: trust.degraded ? 'red' : 'green', truthState: truthStateFromSource(sourceHealth, ['shopify', 'triplewhale', 'freshdesk', 'clarity', 'ga4'], 'canonical'), lastUpdated: snapshotTimestamp }),
  ], [revenue, priorRevenue, conv, priorConv, supportRows, issues, sourceHealth, snapshotTimestamp])

  const blockedStates: Record<string, BlockedStateOutput> = {
    command_center_data_trust: buildBlockedState({
      decision_blocked: 'Whether the top-ranked intervention should be treated as decision-grade',
      missing_source: trust.degradedSources.join(', ') || 'none',
      still_trustworthy: ['healthy source subset', 'visible top-line metrics'],
      owner: 'Joseph',
      required_action_to_unblock: 'Restore degraded connectors before trusting dependent actions',
    }),
  }

  const actions: RankedActionObject[] = useMemo(() => enforceActionContract([
    actionFromKpi({
      id: 'cc-revenue',
      triggerKpi: kpis[0],
      triggerCondition: 'revenue delta negative vs prior period',
      owner: 'Joseph',
      requiredAction: 'Review the highest-confidence revenue drag before allocating more budget or staffing.',
      priority: revenueDelta.deltaPct !== null && revenueDelta.deltaPct < 0 ? 'critical' : 'high',
      evidence: ['overview', 'diagnostics', 'recommendations'],
      dueDate: '48h',
      snapshotTimestamp,
      baseRankingScore: Math.abs(revenueDelta.deltaPct || 0) + 90,
    }),
    actionFromKpi({
      id: 'cc-top-issue',
      triggerKpi: kpis[3],
      triggerCondition: 'highest-business-risk cluster exists',
      owner: issues?.clusters?.[0]?.owner_team || 'TBD',
      requiredAction: `Escalate now: ${issues?.clusters?.[0]?.title || 'No priority cluster returned yet.'}`,
      priority: 'high',
      evidence: ['issue radar', 'freshdesk', 'clarity', 'ga4'],
      dueDate: '24h',
      snapshotTimestamp,
      baseRankingScore: Number(issues?.clusters?.[0]?.details_json?.priority_score || 60),
    }),
    actionFromKpi({
      id: 'cc-support-backlog',
      triggerKpi: kpis[2],
      triggerCondition: 'support backlog elevated',
      owner: 'Jeremiah',
      requiredAction: 'Reduce support backlog before it suppresses conversion and repeat contact volume rises.',
      priority: Number(supportRows.at(-1)?.open_backlog || 0) > 150 ? 'critical' : 'high',
      evidence: ['support overview', 'freshdesk'],
      dueDate: '24h',
      snapshotTimestamp,
      baseRankingScore: Number(supportRows.at(-1)?.open_backlog || 0),
    }),
    actionFromKpi({
      id: 'cc-data-trust',
      triggerKpi: kpis[4],
      triggerCondition: 'source health degraded',
      owner: 'Joseph',
      requiredAction: 'Restore degraded sources before changing spend, UX, or queue priorities.',
      priority: trust.degraded ? 'critical' : 'medium',
      evidence: trust.degradedSources,
      dueDate: '4h',
      snapshotTimestamp,
      baseRankingScore: trust.degraded ? 120 : 30,
      blockedState: blockedStates.command_center_data_trust,
    }),
  ]).slice(0, 5), [kpis, revenueDelta.deltaPct, issues, supportRows, trust, snapshotTimestamp])

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
