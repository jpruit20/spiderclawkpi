import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { ApiError, api } from '../lib/api'
import { currency, deltaPct, deltaDirection, fmtPct, fmtInt } from '../lib/format'
import { IssueRadarResponse, KPIDaily, OverviewResponse, SourceHealthItem, SupportOverviewResponse } from '../lib/types'
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((s, r) => s + (Number(r[key]) || 0), 0)
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
        const [o, s, i] = await Promise.all([api.overview(), api.supportOverview(), api.issues()])
        if (cancelled) return
        setOverview(o)
        setSupport(s)
        setIssues(i)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load dashboard')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const rows = overview?.daily_series || []
  const last7 = rows.slice(-7)
  const prior7 = rows.slice(-14, -7)
  const rev7 = sum(last7, 'revenue')
  const revPrior7 = sum(prior7, 'revenue')
  const ord7 = sum(last7, 'orders')
  const ordPrior7 = sum(prior7, 'orders')
  const sess7 = sum(last7, 'sessions')
  const sessPrior7 = sum(prior7, 'sessions')
  const conv7 = last7.length ? last7.reduce((s, r) => s + (r.conversion_rate || 0), 0) / last7.length : 0
  const convPrior7 = prior7.length ? prior7.reduce((s, r) => s + (r.conversion_rate || 0), 0) / prior7.length : 0
  const supportRows = (support?.rows || []) as KPIDaily[]
  const latestSupport = supportRows.length ? supportRows[supportRows.length - 1] : null
  const openBacklog = latestSupport?.open_backlog ?? 0
  const telemetry = overview?.telemetry || null
  const fleetReliability = telemetry?.latest?.session_reliability_score ?? null
  const sourceHealth = overview?.source_health || []
  const degradedSources = sourceHealth.filter((s: SourceHealthItem) => s.derived_status === 'unhealthy' || s.derived_status === 'stale')
  const topCluster = issues?.highest_business_risk?.[0] || issues?.clusters?.[0] || null

  const kpiCards = useMemo<KpiCardDef[]>(() => [
    {
      label: 'Revenue (7d)',
      value: currency(rev7),
      sub: `${last7.length} days`,
      truthState: 'canonical',
      delta: { text: deltaPct(rev7, revPrior7) + ' vs prior 7d', direction: deltaDirection(rev7, revPrior7) },
    },
    {
      label: 'Conversion',
      value: fmtPct(conv7 / 100, 2),
      sub: '7-day avg',
      truthState: 'canonical',
      delta: { text: deltaPct(conv7, convPrior7) + ' vs prior', direction: deltaDirection(conv7, convPrior7) },
    },
    {
      label: 'Support Queue',
      value: fmtInt(openBacklog),
      sub: 'open tickets',
      truthState: 'canonical',
      delta: openBacklog > 150 ? { text: 'Above target', direction: 'down' as const } : openBacklog < 80 ? { text: 'Healthy', direction: 'up' as const } : { text: 'Watch', direction: 'flat' as const },
    },
    {
      label: 'Fleet Health',
      value: fleetReliability != null ? fmtPct(fleetReliability) : '\u2014',
      sub: `${fmtInt(telemetry?.collection_metadata?.active_devices_last_24h)} devices (24h)`,
      truthState: telemetry ? 'proxy' : 'unavailable',
    },
  ], [rev7, revPrior7, conv7, convPrior7, openBacklog, fleetReliability, telemetry, last7.length])

  const chartRows = useMemo(() => {
    return last7.map((r) => ({
      date: r.business_date.slice(5),
      revenue: Math.round(r.revenue),
      orders: r.orders,
    }))
  }, [last7])

  const divisions = [
    { path: '/division/customer-experience', label: 'Customer Experience', status: `${fmtInt(openBacklog)} open tickets`, owner: 'Jeremiah' },
    { path: '/division/marketing', label: 'Marketing', status: `Conv ${fmtPct(conv7 / 100, 2)}`, owner: 'Bailey' },
    { path: '/division/product-engineering', label: 'Product / Engineering', status: fleetReliability != null ? `Fleet ${fmtPct(fleetReliability)}` : 'Loading', owner: 'Kyle' },
    { path: '/revenue', label: 'Revenue Engine', status: `${currency(rev7)} (7d)`, owner: 'Finance' },
    { path: '/issues', label: 'Issue Radar', status: `${issues?.clusters?.length || 0} clusters`, owner: 'Cross-team' },
    { path: '/system-health', label: 'System Health', status: degradedSources.length ? `${degradedSources.length} degraded` : 'All healthy', owner: 'Ops' },
  ]

  return (
    <div className="page-grid venom-page">
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Spider Command Center</h2>
          <p className="venom-subtitle">Executive overview — real-time company pulse</p>
        </div>
        {degradedSources.length > 0 ? (
          <span className="badge badge-warn">{degradedSources.length} degraded source{degradedSources.length > 1 ? 's' : ''}</span>
        ) : (
          <span className="badge badge-good">All sources healthy</span>
        )}
      </div>

      {loading ? <Card title="Loading"><div className="state-message">Loading command center…</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <VenomKpiStrip cards={kpiCards} />

          {/* Week-over-week deltas */}
          <div className="scope-note" style={{display:'flex', gap:12, flexWrap:'wrap'}}>
            <span className={`badge ${deltaDirection(rev7, revPrior7) === 'up' ? 'badge-good' : deltaDirection(rev7, revPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>Revenue {deltaPct(rev7, revPrior7)}</span>
            <span className={`badge ${deltaDirection(ord7, ordPrior7) === 'up' ? 'badge-good' : deltaDirection(ord7, ordPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>Orders {deltaPct(ord7, ordPrior7)}</span>
            <span className={`badge ${deltaDirection(sess7, sessPrior7) === 'up' ? 'badge-good' : deltaDirection(sess7, sessPrior7) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>Sessions {deltaPct(sess7, sessPrior7)}</span>
          </div>

          {/* Today's Briefing */}
          <section className="card venom-briefing">
            <div className="venom-panel-head">
              <strong>Today's Briefing</strong>
              <span className="venom-panel-hint">{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</span>
            </div>
            <div className="stack-list compact">
              {topCluster ? (
                <div className={`list-item status-${topCluster.severity === 'high' ? 'bad' : 'warn'}`}>
                  <div className="item-head">
                    <strong>#1 Issue: {topCluster.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge ${topCluster.severity === 'high' ? 'severity-high' : 'severity-medium'}`}>{topCluster.severity}</span>
                      {topCluster.owner_team ? <span className="badge badge-muted">{topCluster.owner_team}</span> : null}
                    </div>
                  </div>
                  <p>{(topCluster.details_json as any)?.priority_reason_summary || 'Review escalation queue for details'}</p>
                </div>
              ) : (
                <div className="list-item status-good">
                  <strong>{deltaDirection(rev7, revPrior7) === 'up' ? 'All clear — business is growing' : 'No high-priority issues detected'}</strong>
                  <p>{deltaDirection(rev7, revPrior7) === 'up' ? `Revenue ${deltaPct(rev7, revPrior7)} vs prior week — focus on growth initiatives` : 'Issue radar is clear — focus on growth initiatives'}</p>
                </div>
              )}
              <div className={`list-item status-${openBacklog > 150 ? 'bad' : openBacklog > 80 ? 'warn' : 'good'}`}>
                <div className="item-head">
                  <strong>Support: {fmtInt(openBacklog)} open tickets</strong>
                  <span className={`badge ${openBacklog > 150 ? 'badge-bad' : openBacklog > 80 ? 'badge-warn' : 'badge-good'}`}>{openBacklog > 150 ? 'Over capacity' : openBacklog > 80 ? 'Elevated' : 'Healthy'}</span>
                </div>
              </div>
              <div className={`list-item status-${degradedSources.length > 0 ? 'warn' : 'muted'}`}>
                <div className="item-head">
                  <strong>Data Trust</strong>
                  <span className={`badge ${degradedSources.length > 0 ? 'badge-warn' : 'badge-good'}`}>{degradedSources.length > 0 ? `${degradedSources.length} degraded` : 'All healthy'}</span>
                </div>
                {degradedSources.length > 0 ? <p>Degraded: {degradedSources.map((s: SourceHealthItem) => s.source).join(', ')}</p> : null}
              </div>
            </div>
          </section>

          {/* Revenue Trend */}
          <section className="card">
            <div className="venom-panel-head">
              <div>
                <strong>Revenue — Last 7 Days</strong>
                <p className="venom-chart-sub">{currency(rev7)} total</p>
              </div>
              <Link to="/revenue" className="analysis-link">Full report &#x2197;</Link>
            </div>
            {chartRows.length > 0 ? (
              <div className="chart-wrap-short">
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={chartRows}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#9fb0d4" tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip formatter={(value: number) => [currency(value), 'Revenue']} />
                    <Area type="monotone" dataKey="revenue" fill="rgba(110,168,255,0.15)" stroke="var(--blue)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : <div className="state-message">No revenue data available.</div>}
          </section>

          {/* Division Status Grid */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Division Overview</strong>
              <span className="venom-panel-hint">Click to open</span>
            </div>
            <div className="venom-drill-grid">
              {divisions.map((div) => (
                <Link key={div.path} to={div.path} className="venom-drill-tile">
                  <div>
                    <strong>{div.label}</strong>
                    <small>{div.status} · {div.owner}</small>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
