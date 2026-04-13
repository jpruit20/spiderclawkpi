import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ApiError, api } from '../lib/api'
import { fmtPct, fmtInt, fmtDecimal, fmtDuration, formatFreshness } from '../lib/format'
import type { GithubIssuesResponse, IssueRadarResponse, MarketIntelligence, MarketPost, TelemetryHistoryDailyRow, TelemetrySummary, TrendMomentum, CXSnapshotResponse } from '../lib/types'
import {
  BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Line, Area, ComposedChart, PieChart, Pie, Cell,
} from 'recharts'

/* ------------------------------------------------------------------ */
/*  Sub-view navigation                                               */
/* ------------------------------------------------------------------ */
type SubView = 'fleet' | 'voice' | 'roadmap'

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */
type TimeRange = '24h' | '1w' | '2w' | '1m'

function rangeToDays(r: TimeRange): number {
  const mapping: Record<TimeRange, number> = { '24h': 1, '1w': 7, '2w': 14, '1m': 30 }
  return mapping[r] ?? 30
}

function buildPeakHours(historyRows: TelemetryHistoryDailyRow[]) {
  const hourTotals: Record<string, number> = {}
  for (const row of historyRows) {
    for (const [hour, count] of Object.entries(row.peak_hour_distribution || {})) {
      hourTotals[hour] = (hourTotals[hour] || 0) + (count as number)
    }
  }
  return Array.from({ length: 24 }, (_, i) => ({ hour: `${String(i).padStart(2, '0')}:00`, events: hourTotals[String(i)] || 0 }))
}

function buildModelBreakdown(historyRows: TelemetryHistoryDailyRow[]) {
  const totals: Record<string, number> = {}
  for (const row of historyRows.slice(-30)) {
    for (const [model, count] of Object.entries(row.model_distribution || {})) {
      totals[model] = (totals[model] || 0) + (count as number)
    }
  }
  return Object.entries(totals).sort(([, a], [, b]) => b - a).slice(0, 8).map(([model, events]) => ({ model, events }))
}

function buildFirmwareBreakdown(historyRows: TelemetryHistoryDailyRow[]) {
  const totals: Record<string, number> = {}
  for (const row of historyRows.slice(-30)) {
    for (const [fw, count] of Object.entries(row.firmware_distribution || {})) {
      totals[fw] = (totals[fw] || 0) + (count as number)
    }
  }
  return Object.entries(totals).sort(([, a], [, b]) => b - a).slice(0, 8).map(([firmware, events]) => ({ firmware, events }))
}

function sentimentColor(s: number | undefined): string {
  if (s == null) return 'var(--muted)'
  if (s >= 0.3) return 'var(--green)'
  if (s >= -0.1) return 'var(--orange)'
  return 'var(--red)'
}

function severityBadge(s: string) {
  const colors: Record<string, string> = { critical: 'badge-bad', high: 'badge-warn', medium: 'badge-neutral', low: 'badge-muted' }
  return <span className={`badge ${colors[s] || 'badge-neutral'}`}>{s}</span>
}

function momentumBadge(m: string) {
  const colors: Record<string, string> = { strong: 'var(--green)', growing: 'var(--blue)', emerging: 'var(--orange)' }
  return <span style={{ color: colors[m] || 'var(--muted)', fontWeight: 600, fontSize: 11, textTransform: 'uppercase' as const }}>{m}</span>
}

const DRILL_ROUTES: { path: string; label: string; icon: string }[] = [
  { path: '/analysis/cook-failures', label: 'Cook failures', icon: '\ud83d\udd25' },
  { path: '/analysis/temp-curves', label: 'Temp curves', icon: '\ud83d\udcc8' },
  { path: '/analysis/session-clusters', label: 'Session clusters', icon: '\u25cb' },
  { path: '/analysis/rssi-impact', label: 'RSSI impact', icon: '\ud83d\udcf6' },
  { path: '/analysis/probe-health', label: 'Probe health', icon: '\ud83e\ude7a' },
  { path: '/analysis/firmware-model', label: 'Firmware model', icon: '\u2699\ufe0f' },
]

const CHART_COLORS = ['#6ea8ff', '#4ade80', '#f59e0b', '#ef4444', '#a78bfa', '#f472b6', '#38bdf8', '#fb923c']

/* ------------------------------------------------------------------ */
/*  Main component                                                    */
/* ------------------------------------------------------------------ */
export function ProductEngineeringDivision() {
  const [view, setView] = useState<SubView>('fleet')
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [githubIssues, setGithubIssues] = useState<GithubIssuesResponse | null>(null)
  const [issueRadar, setIssueRadar] = useState<IssueRadarResponse | null>(null)
  const [marketIntel, setMarketIntel] = useState<MarketIntelligence | null>(null)
  const [cxSnapshot, setCxSnapshot] = useState<CXSnapshotResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<TimeRange>('1m')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const days = rangeToDays(range)
        const [telData, issuesData, radarData, miData, cxData] = await Promise.all([
          api.telemetrySummary(days),
          api.engineeringIssues().catch(() => null),
          api.issues().catch(() => null),
          api.marketIntelligence(30).catch(() => null),
          api.cxSnapshot().catch(() => null),
        ])
        if (!cancelled) {
          setTelemetry(telData)
          setGithubIssues(issuesData)
          setIssueRadar(radarData)
          setMarketIntel(miData)
          setCxSnapshot(cxData)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load product data')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [range])

  /* Telemetry derived values */
  const collection = telemetry?.collection_metadata || null
  const derived = telemetry?.analytics?.derived_metrics || null
  const latest = telemetry?.latest || null
  const analytics = telemetry?.analytics || null
  const historyDaily = telemetry?.history_daily || []

  const streamBacked = collection?.sample_source === 'dynamodb_stream'
  const sampleSize = Math.max(telemetry?.slice_snapshot?.sessions_derived || 0, collection?.distinct_devices_observed || 0)

  const activeCooks = derived?.active_cooks_now ?? collection?.active_devices_last_15m ?? 0
  const devicesReporting = derived?.devices_reporting_last_5m ?? collection?.active_devices_last_5m ?? 0
  const successRate = derived?.session_success_rate ?? latest?.session_reliability_score ?? null
  const disconnectRate = derived?.disconnect_proxy_rate ?? latest?.disconnect_rate ?? null
  const stabilityScore = derived?.stability_score ?? latest?.temp_stability_score ?? null
  const overshootRate = derived?.overshoot_rate ?? null
  const p50Stabilize = derived?.time_to_stabilize_p50_seconds ?? null
  const p95Stabilize = derived?.time_to_stabilize_p95_seconds ?? null
  const medianCookDuration = derived?.median_cook_duration_seconds ?? null
  const p95CookDuration = derived?.p95_cook_duration_seconds ?? null
  const medianRssi = derived?.median_rssi_now ?? null
  const probeErrorRate = analytics?.probe_failure_rate ?? null
  const devices24h = collection?.active_devices_last_24h ?? 0
  const devices60m = collection?.active_devices_last_60m ?? 0

  const rangedHistory = useMemo(() => {
    if (!historyDaily.length) return []
    const days = rangeToDays(range)
    return historyDaily.slice(-days)
  }, [historyDaily, range])

  const fleetChartRows = useMemo(() => rangedHistory.map((row) => ({
    date: row.business_date.slice(5),
    active_devices: row.active_devices,
    engaged_devices: row.engaged_devices,
    error_rate: row.total_events > 0 ? Math.round((row.error_events / row.total_events) * 10000) / 100 : 0,
  })), [rangedHistory])

  const peakHourData = useMemo(() => buildPeakHours(rangedHistory), [rangedHistory])
  const modelData = useMemo(() => buildModelBreakdown(rangedHistory), [rangedHistory])
  const firmwareData = useMemo(() => buildFirmwareBreakdown(rangedHistory), [rangedHistory])

  const historyStats = useMemo(() => {
    if (!rangedHistory.length) return null
    const avgDevices = rangedHistory.reduce((s, r) => s + r.active_devices, 0) / rangedHistory.length
    const totalErrors = rangedHistory.reduce((s, r) => s + r.error_events, 0)
    const totalEvents = rangedHistory.reduce((s, r) => s + r.total_events, 0)
    const peakDay = rangedHistory.reduce((best, r) => r.active_devices > (best?.active_devices || 0) ? r : best, rangedHistory[0])
    return { avgDevices, totalErrors, totalEvents, errorRate: totalEvents > 0 ? totalErrors / totalEvents : 0, peakDay }
  }, [rangedHistory])

  /* Issue Radar: product-related clusters */
  const productClusters = useMemo(() => {
    if (!issueRadar?.clusters) return []
    return issueRadar.clusters
      .filter(c => {
        const d = c.details_json || {}
        const themes: string[] = [d.theme, ...(d.secondary_themes || [])]
        const productThemes = ['temperature_control_venom', 'ignition_startup', 'app_connectivity', 'assembly', 'parts_replacement', 'probe_issues', 'wifi_connectivity']
        return themes.some(t => productThemes.includes(t)) || (d.affected_products && d.affected_products.length > 0)
      })
      .sort((a, b) => (b.details_json?.priority_score || 0) - (a.details_json?.priority_score || 0))
  }, [issueRadar])

  /* CX actions that are product-related */
  const productActions = useMemo(() => {
    if (!cxSnapshot?.actions) return []
    const productKpis = ['reopen_rate', 'escalation_rate', 'avg_close_time']
    return cxSnapshot.actions.filter(a => productKpis.includes(a.trigger_kpi) || a.co_owner === 'Kyle')
  }, [cxSnapshot])

  /* Market intel: product innovation ideas + competitor pain points */
  const innovations = marketIntel?.product_innovation?.posts || []
  const competitorPains = marketIntel?.competitor_pain_points?.posts || []
  const purchaseIntents = marketIntel?.purchase_intent?.posts || []
  const trendMomentum = marketIntel?.trend_momentum || []

  /* Firmware/grill health from telemetry */
  const firmwareHealth = telemetry?.firmware_health || []
  const grillTypeHealth = telemetry?.grill_type_health || []
  const topErrors = telemetry?.top_error_codes || []
  const issuePatterns = telemetry?.top_issue_patterns || []

  /* ------------------------------------------------------------------
   * Generate auto-insights for the product team
   * ------------------------------------------------------------------ */
  const productInsights = useMemo(() => {
    const items: { icon: string; text: string; severity: 'good' | 'warn' | 'bad' | 'info' }[] = []

    // Reliability insight
    if (successRate != null) {
      if (successRate >= 0.95) items.push({ icon: '\u2705', text: `Session reliability is excellent at ${fmtPct(successRate)} — no firmware intervention needed.`, severity: 'good' })
      else if (successRate >= 0.85) items.push({ icon: '\u26a0\ufe0f', text: `Session reliability at ${fmtPct(successRate)} — review disconnect patterns and consider firmware patch.`, severity: 'warn' })
      else items.push({ icon: '\ud83d\udea8', text: `Session reliability critically low at ${fmtPct(successRate)} — immediate investigation required.`, severity: 'bad' })
    }

    // Overshoot insight
    if (overshootRate != null && overshootRate > 0.15) {
      items.push({ icon: '\ud83c\udf21\ufe0f', text: `Temperature overshoot rate at ${fmtPct(overshootRate)} (>15% threshold) — PID tuning review recommended for affected models.`, severity: 'warn' })
    }

    // WiFi insight
    if (medianRssi != null && medianRssi < -75) {
      items.push({ icon: '\ud83d\udcf6', text: `Median RSSI at ${medianRssi} dBm — weak signal causing disconnects. Consider antenna design improvement or documentation update.`, severity: 'warn' })
    }

    // Firmware fragmentation
    if (firmwareHealth.length > 3) {
      const unhealthy = firmwareHealth.filter(f => f.severity === 'warning' || f.severity === 'critical')
      if (unhealthy.length > 0) {
        items.push({ icon: '\u2699\ufe0f', text: `${unhealthy.length} firmware version(s) showing degraded health — prioritize OTA update push for ${unhealthy.map(f => f.key).join(', ')}.`, severity: 'warn' })
      }
    }

    // Product issue clusters
    if (productClusters.length > 0) {
      const topCluster = productClusters[0]
      const d = topCluster.details_json || {}
      items.push({ icon: '\ud83d\udce6', text: `Top product issue: "${topCluster.title}" (${d.total_tickets || '?'} tickets, ${topCluster.severity} severity) — ${d.trend_label || 'stable'} trend.`, severity: topCluster.severity === 'critical' ? 'bad' : 'warn' })
    }

    // Innovation signals
    if (innovations.length > 0) {
      items.push({ icon: '\ud83d\udca1', text: `${innovations.length} product innovation signals detected from market conversations — review for roadmap alignment.`, severity: 'info' })
    }

    // Competitor pain points
    if (competitorPains.length > 0) {
      items.push({ icon: '\ud83c\udfaf', text: `${competitorPains.length} competitor pain points captured — potential differentiation opportunities for Spider Grills.`, severity: 'info' })
    }

    if (items.length === 0) {
      items.push({ icon: '\u2705', text: 'All product health metrics within normal ranges. No action required.', severity: 'good' })
    }

    return items
  }, [successRate, overshootRate, medianRssi, firmwareHealth, productClusters, innovations, competitorPains])


  return (
    <div className="page-grid venom-page">
      {/* Header */}
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Product Development Hub</h2>
          <p className="venom-subtitle">
            {streamBacked ? 'Live' : 'Degraded'} · Updated {formatFreshness(collection?.newest_sample_timestamp_seen)} · {fmtInt(devicesReporting || activeCooks)} devices reporting
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 4, background: 'var(--panel-2)', borderRadius: 8, padding: 2 }}>
            {([
              { key: 'fleet' as SubView, label: 'Fleet Health' },
              { key: 'voice' as SubView, label: 'Voice of Customer' },
              { key: 'roadmap' as SubView, label: 'Innovation Radar' },
            ]).map(tab => (
              <button key={tab.key} className={`range-button${view === tab.key ? ' active' : ''}`} onClick={() => setView(tab.key)}>{tab.label}</button>
            ))}
          </div>
          <div className="venom-range-group">
            {([
              { key: '24h' as TimeRange, label: '24h' },
              { key: '1w' as TimeRange, label: '7d' },
              { key: '2w' as TimeRange, label: '14d' },
              { key: '1m' as TimeRange, label: '30d' },
            ]).map(r => (
              <button key={r.key} className={`range-button${range === r.key ? ' active' : ''}`} onClick={() => setRange(r.key)}>{r.label}</button>
            ))}
          </div>
        </div>
      </div>

      {loading ? <Card title="Product Hub"><div className="state-message">Loading product data...</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          {/* Product Intelligence Briefing — always visible */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Product Intelligence Briefing</strong>
              <span className="venom-panel-hint">{productInsights.length} signal{productInsights.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="stack-list compact">
              {productInsights.map((insight, i) => (
                <div key={i} className={`list-item status-${insight.severity === 'good' ? 'good' : insight.severity === 'warn' ? 'warn' : insight.severity === 'bad' ? 'bad' : 'muted'}`}>
                  <span>{insight.icon} {insight.text}</span>
                </div>
              ))}
            </div>
          </section>

          {/* ============================================================ */}
          {/*  VIEW 1: FLEET HEALTH                                        */}
          {/* ============================================================ */}
          {view === 'fleet' && (
            <>
              <TruthLegend />

              {/* KPI Strip */}
              <div className="venom-kpi-strip">
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Active Cooks</div>
                  <div className="venom-kpi-value">{fmtInt(activeCooks)}</div>
                  <div className="venom-kpi-sub">{fmtInt(devicesReporting)} devices reporting (5m)</div>
                  <div className="venom-kpi-badges">
                    <TruthBadge state="proxy" />
                    {devices60m > 0 && <span className="venom-delta venom-delta-up">{fmtInt(devices60m)} in 60m · {fmtInt(devices24h)} in 24h</span>}
                  </div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Reliability</div>
                  <div className="venom-kpi-value">{fmtPct(successRate)}</div>
                  <div className="venom-kpi-sub">session success · n={fmtInt(sampleSize)}</div>
                  <div className="venom-kpi-badges">
                    <TruthBadge state="estimated" />
                    {historyStats && <span className="venom-delta venom-delta-flat">error rate: {fmtPct(historyStats.errorRate)}</span>}
                  </div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Control Quality</div>
                  <div className="venom-kpi-value">{fmtDecimal(stabilityScore)}</div>
                  <div className="venom-kpi-sub">stability · p50 stabilize {fmtDuration(p50Stabilize)}</div>
                  <div className="venom-kpi-badges"><TruthBadge state="estimated" /></div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Product Issues</div>
                  <div className="venom-kpi-value">{productClusters.length}</div>
                  <div className="venom-kpi-sub">active clusters from support + telemetry</div>
                  <div className="venom-kpi-badges">
                    {productClusters.filter(c => c.severity === 'critical').length > 0 && (
                      <span className="venom-delta venom-delta-down">{productClusters.filter(c => c.severity === 'critical').length} critical</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Fleet Activity Chart */}
              <section className="card">
                <div className="venom-panel-head">
                  <div>
                    <strong>Fleet Activity — Daily Active Devices</strong>
                    <p className="venom-chart-sub">Showing {rangedHistory.length} day{rangedHistory.length !== 1 ? 's' : ''} of data</p>
                  </div>
                  {historyStats?.peakDay && <span className="venom-panel-hint">Peak: {historyStats.peakDay.active_devices} on {historyStats.peakDay.business_date}</span>}
                </div>
                {fleetChartRows.length > 0 ? (
                  <div className="chart-wrap">
                    <ResponsiveContainer width="100%" height={300}>
                      <ComposedChart data={fleetChartRows}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                        <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 11 }} />
                        <YAxis yAxisId="left" stroke="#9fb0d4" />
                        <YAxis yAxisId="right" orientation="right" stroke="#9fb0d4" tickFormatter={(v: number) => `${v}%`} />
                        <Tooltip />
                        <Legend />
                        <Area yAxisId="left" type="monotone" name="Active devices" dataKey="active_devices" fill="rgba(110,168,255,0.15)" stroke="var(--blue)" strokeWidth={2} />
                        <Line yAxisId="left" type="monotone" name="Engaged (cooking)" dataKey="engaged_devices" stroke="var(--green)" strokeWidth={2} dot={false} />
                        <Line yAxisId="right" type="monotone" name="Error rate %" dataKey="error_rate" stroke="var(--red)" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : <div className="state-message">No historical daily data available yet. Run the S3 import to populate fleet history.</div>}
              </section>

              {/* Reliability + Control Quality */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Reliability Breakdown</strong>
                    <Link to="/issues" className="analysis-link">View issues &#x2197;</Link>
                  </div>
                  <div className="venom-breakdown-list">
                    <div className="venom-breakdown-row"><span>Session success</span><span className="venom-breakdown-val">{fmtPct(successRate)}</span><TruthBadge state="estimated" /></div>
                    <div className="venom-breakdown-row"><span>Disconnect (proxy)</span><span className="venom-breakdown-val">{fmtPct(disconnectRate)}</span><TruthBadge state="proxy" /></div>
                    <div className="venom-breakdown-row"><span>Probe error rate</span><span className="venom-breakdown-val">{fmtPct(probeErrorRate)}</span></div>
                    <div className="venom-breakdown-row"><span>Median RSSI</span><span className="venom-breakdown-val">{medianRssi != null ? `${medianRssi} dBm` : '\u2014'}</span></div>
                  </div>
                  {/* Grill type health */}
                  {grillTypeHealth.length > 0 && (
                    <>
                      <div className="venom-breakdown-label" style={{ marginTop: 12 }}>By Grill Type</div>
                      <div className="venom-breakdown-list">
                        {grillTypeHealth.map((g, i) => (
                          <div key={i} className="venom-breakdown-row">
                            <span>{g.key}</span>
                            <span className="venom-breakdown-val" style={{ color: g.severity === 'critical' ? 'var(--red)' : g.severity === 'warning' ? 'var(--orange)' : 'var(--green)' }}>{fmtDecimal(g.health_score)} health</span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                  <small className="venom-panel-footer">n={fmtInt(sampleSize)} sessions</small>
                </section>

                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Control Quality</strong>
                    <Link to="/analysis/temp-curves" className="analysis-link">View curves &#x2197;</Link>
                  </div>
                  <div className="venom-bar-list">
                    <div className="venom-bar-row"><span className="venom-bar-label">p50 stabilize</span><BarIndicator value={p50Stabilize || 0} max={p95Stabilize || 1200} color="var(--blue)" /><span className="venom-bar-value">{fmtDuration(p50Stabilize)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">p95 stabilize</span><BarIndicator value={p95Stabilize || 0} max={p95Stabilize || 1200} color="var(--red)" /><span className="venom-bar-value">{fmtDuration(p95Stabilize)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Overshoot rate</span><BarIndicator value={(overshootRate || 0) * 100} max={100} color="var(--orange)" /><span className="venom-bar-value">{fmtPct(overshootRate, 0)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Stability score</span><BarIndicator value={(stabilityScore || 0) * 100} max={100} color="var(--green)" /><span className="venom-bar-value">{fmtDecimal(stabilityScore)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Median cook</span><BarIndicator value={medianCookDuration || 0} max={p95CookDuration || 14400} color="#9b7bff" /><span className="venom-bar-value">{fmtDuration(medianCookDuration)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Cook p95</span><BarIndicator value={p95CookDuration || 0} max={p95CookDuration || 14400} color="var(--red)" /><span className="venom-bar-value">{fmtDuration(p95CookDuration)}</span></div>
                  </div>
                </section>
              </div>

              {/* Model + Firmware + Peak Hours */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head"><strong>Peak Cooking Hours</strong></div>
                  {peakHourData.some(r => r.events > 0) ? (
                    <div className="chart-wrap-short">
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={peakHourData}>
                          <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                          <XAxis dataKey="hour" stroke="#9fb0d4" tick={{ fontSize: 10 }} interval={2} />
                          <YAxis stroke="#9fb0d4" />
                          <Tooltip />
                          <Bar dataKey="events" name="Events" fill="var(--blue)" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <div className="state-message">Peak hour data populates after S3 history import.</div>}
                </section>
                <section className="card">
                  <div className="venom-panel-head"><strong>Grill Model Mix</strong></div>
                  {modelData.length > 0 ? (
                    <div className="chart-wrap-short">
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={modelData} layout="vertical">
                          <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                          <XAxis type="number" stroke="#9fb0d4" />
                          <YAxis type="category" dataKey="model" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={120} />
                          <Tooltip />
                          <Bar dataKey="events" name="Events" fill="var(--green)" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <div className="state-message">Model distribution populates after S3 history import.</div>}
                </section>
              </div>

              {/* Firmware + Error Codes */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Firmware Versions in Field</strong>
                    <Link to="/analysis/firmware-model" className="analysis-link">Details &#x2197;</Link>
                  </div>
                  {firmwareData.length > 0 ? (
                    <div className="chart-wrap-short">
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={firmwareData} layout="vertical">
                          <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                          <XAxis type="number" stroke="#9fb0d4" />
                          <YAxis type="category" dataKey="firmware" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={80} />
                          <Tooltip />
                          <Bar dataKey="events" name="Events" fill="var(--orange)" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <div className="state-message">Firmware data populates after S3 history import.</div>}
                  {/* Firmware health table */}
                  {firmwareHealth.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div className="venom-breakdown-label">Firmware Health</div>
                      <div className="venom-breakdown-list">
                        {firmwareHealth.map((f, i) => (
                          <div key={i} className="venom-breakdown-row">
                            <span>{f.key}</span>
                            <span className="venom-breakdown-val">{f.sessions} sessions</span>
                            <span style={{ color: f.severity === 'critical' ? 'var(--red)' : f.severity === 'warning' ? 'var(--orange)' : 'var(--green)', fontWeight: 600, fontSize: 12 }}>
                              {fmtDecimal(f.health_score)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
                <section className="card">
                  <div className="venom-panel-head"><strong>Top Error Codes</strong></div>
                  {topErrors.length > 0 ? (
                    <div className="venom-breakdown-list">
                      {topErrors.map((e, i) => (
                        <div key={i} className="venom-breakdown-row">
                          <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{e.error_code}</span>
                          <span className="venom-breakdown-val">{fmtInt(e.count)} events</span>
                          <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtPct(e.pct_of_errors)}</span>
                        </div>
                      ))}
                    </div>
                  ) : <div className="state-message">No error codes captured yet.</div>}
                  {/* Issue patterns */}
                  {issuePatterns.length > 0 && (
                    <div style={{ marginTop: 16 }}>
                      <div className="venom-breakdown-label">Detected Issue Patterns</div>
                      <div className="stack-list compact">
                        {issuePatterns.map((p, i) => (
                          <div key={i} className={`list-item status-${p.severity === 'critical' ? 'bad' : p.severity === 'warning' ? 'warn' : 'muted'}`}>
                            <div className="item-head"><strong>{p.pattern.replace(/_/g, ' ')}</strong>{severityBadge(p.severity)}</div>
                            <p>{p.description}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              </div>

              {/* P0/P1 Engineering Issues + Product Issue Clusters */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>P0/P1 Engineering Issues</strong>
                    {githubIssues?.repo && <a href={`https://github.com/${githubIssues.repo}/issues`} target="_blank" rel="noopener noreferrer" className="analysis-link">GitHub &#x2197;</a>}
                  </div>
                  {githubIssues?.error ? (
                    <div className="state-message warn">{githubIssues.error}</div>
                  ) : githubIssues?.issues && githubIssues.issues.length > 0 ? (
                    <div className="stack-list compact">
                      {githubIssues.issues.map(issue => (
                        <a key={issue.id} href={issue.html_url} target="_blank" rel="noopener noreferrer" className={`list-item status-${issue.priority === 'P0' ? 'bad' : 'warn'}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                          <div className="item-head">
                            <strong>#{issue.number} {issue.title}</strong>
                            <div className="inline-badges">
                              {issue.priority && <span className={`badge ${issue.priority === 'P0' ? 'badge-bad' : 'badge-warn'}`}>{issue.priority}</span>}
                              {issue.is_bug && <span className="badge badge-neutral">bug</span>}
                            </div>
                          </div>
                          <p>{issue.assignees.length > 0 ? `Assigned to ${issue.assignees.join(', ')}` : 'Unassigned'} · Updated {formatFreshness(issue.updated_at)}</p>
                        </a>
                      ))}
                    </div>
                  ) : (
                    <div className="state-message">{githubIssues?.configured === false ? 'GitHub integration not configured.' : 'No P0/P1 issues found'}</div>
                  )}
                </section>

                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Product Issue Clusters</strong>
                    <Link to="/issues" className="analysis-link">Full radar &#x2197;</Link>
                  </div>
                  {productClusters.length > 0 ? (
                    <div className="stack-list compact">
                      {productClusters.slice(0, 6).map((cluster, i) => {
                        const d = cluster.details_json || {}
                        return (
                          <div key={i} className={`list-item status-${cluster.severity === 'critical' ? 'bad' : cluster.severity === 'high' ? 'warn' : 'muted'}`}>
                            <div className="item-head">
                              <strong>{cluster.title}</strong>
                              {severityBadge(cluster.severity)}
                            </div>
                            <p>
                              {d.total_tickets && `${d.total_tickets} tickets`}
                              {d.trend_label && ` · ${d.trend_label}`}
                              {d.affected_products?.length > 0 && ` · ${d.affected_products.join(', ')}`}
                            </p>
                          </div>
                        )
                      })}
                    </div>
                  ) : <div className="state-message">No product-specific issue clusters detected.</div>}
                  {/* Product CX escalations */}
                  {productActions.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div className="venom-breakdown-label">Product Escalations from CX</div>
                      <div className="stack-list compact">
                        {productActions.slice(0, 3).map((action, i) => (
                          <div key={i} className={`list-item status-${action.priority === 'critical' ? 'bad' : 'warn'}`}>
                            <div className="item-head"><strong>{action.title}</strong><span className={`badge ${action.priority === 'critical' ? 'badge-bad' : 'badge-warn'}`}>{action.status}</span></div>
                            <p>{action.required_action}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              </div>

              {/* Drill-down routes */}
              <section className="card">
                <div className="venom-panel-head"><strong>Telemetry Deep-Dives</strong></div>
                <div className="venom-drill-grid">
                  {DRILL_ROUTES.map(route => (
                    <Link key={route.path} to={route.path} className="venom-drill-tile">
                      <span className="venom-drill-icon">{route.icon}</span>
                      <div><strong>{route.label}</strong><small>{route.path}</small></div>
                    </Link>
                  ))}
                </div>
              </section>
            </>
          )}

          {/* ============================================================ */}
          {/*  VIEW 2: VOICE OF CUSTOMER                                   */}
          {/* ============================================================ */}
          {view === 'voice' && (
            <>
              {/* VOC KPI strip */}
              <div className="venom-kpi-strip">
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Product Issue Clusters</div>
                  <div className="venom-kpi-value">{productClusters.length}</div>
                  <div className="venom-kpi-sub">from support tickets + telemetry</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">CX Escalations</div>
                  <div className="venom-kpi-value">{productActions.filter(a => a.status !== 'resolved').length}</div>
                  <div className="venom-kpi-sub">open product-linked actions</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Market Mentions</div>
                  <div className="venom-kpi-value">{fmtInt(marketIntel?.total_mentions || 0)}</div>
                  <div className="venom-kpi-sub">Reddit + YouTube + Amazon (30d)</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Brand Sentiment</div>
                  <div className="venom-kpi-value" style={{ color: sentimentColor(marketIntel?.competitive_landscape?.brand_share_of_voice) }}>
                    {marketIntel?.competitive_landscape?.brand_share_of_voice != null ? `${(marketIntel.competitive_landscape.brand_share_of_voice * 100).toFixed(1)}%` : '\u2014'}
                  </div>
                  <div className="venom-kpi-sub">share of voice</div>
                </div>
              </div>

              {/* Product Issue Deep-Dive */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Product Issue Analysis — What Customers Are Reporting</strong>
                  <Link to="/issues" className="analysis-link">Full radar &#x2197;</Link>
                </div>
                {productClusters.length > 0 ? (
                  <div className="stack-list">
                    {productClusters.map((cluster, i) => {
                      const d = cluster.details_json || {}
                      const trendPct = d.trend_pct ?? 0
                      return (
                        <div key={i} className={`list-item status-${cluster.severity === 'critical' ? 'bad' : cluster.severity === 'high' ? 'warn' : 'muted'}`}>
                          <div className="item-head">
                            <strong>{cluster.title}</strong>
                            <div className="inline-badges">
                              {severityBadge(cluster.severity)}
                              <span className={`badge ${trendPct > 10 ? 'badge-bad' : trendPct < -10 ? 'badge-good' : 'badge-neutral'}`}>
                                {trendPct > 0 ? '+' : ''}{trendPct.toFixed(0)}% trend
                              </span>
                            </div>
                          </div>
                          <p>
                            {d.total_tickets && <><strong>{d.total_tickets}</strong> tickets</>}
                            {d.recent_7d != null && <> · <strong>{d.recent_7d}</strong> this week</>}
                            {d.affected_products?.length > 0 && <> · Affects: {d.affected_products.join(', ')}</>}
                          </p>
                          {d.tickets_per_100_orders && (
                            <p style={{ fontSize: 12, color: 'var(--muted)' }}>
                              Impact: {d.tickets_per_100_orders.toFixed(1)} tickets/100 orders
                              {d.estimated_conversion_impact_pct && ` · est. ${d.estimated_conversion_impact_pct.toFixed(1)}% conversion impact`}
                            </p>
                          )}
                          <p style={{ fontSize: 12 }}>
                            <strong>Action:</strong> {cluster.severity === 'critical' ? 'Requires immediate engineering review' : d.owner_team ? `Owner: ${d.owner_team}` : 'Assign to engineering team'}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                ) : <div className="state-message">No product-specific issue clusters detected from customer data.</div>}
              </section>

              {/* CX Escalations for Product Team */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Product Escalations from Customer Support</strong>
                  <Link to="/division/customer-experience" className="analysis-link">CX dashboard &#x2197;</Link>
                </div>
                {productActions.length > 0 ? (
                  <div className="stack-list compact">
                    {productActions.map((action, i) => (
                      <div key={i} className={`list-item status-${action.status === 'resolved' ? 'good' : action.priority === 'critical' ? 'bad' : 'warn'}`}>
                        <div className="item-head">
                          <strong>{action.title}</strong>
                          <div className="inline-badges">
                            <span className={`badge ${action.priority === 'critical' ? 'badge-bad' : 'badge-warn'}`}>{action.priority}</span>
                            <span className={`badge ${action.status === 'resolved' ? 'badge-good' : 'badge-neutral'}`}>{action.status}</span>
                          </div>
                        </div>
                        <p>{action.required_action}</p>
                        <p style={{ fontSize: 11, color: 'var(--muted)' }}>Trigger: {action.trigger_kpi} {action.trigger_condition} · Owner: {action.owner}{action.co_owner ? ` + ${action.co_owner}` : ''}</p>
                      </div>
                    ))}
                  </div>
                ) : <div className="state-message">No product-linked CX escalations. All support metrics within thresholds.</div>}
              </section>

              {/* Purchase Intent Monitor — what are buyers looking for? */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Purchase Intent Monitor — What Buyers Want</strong>
                  <Link to="/social" className="analysis-link">Social Intel &#x2197;</Link>
                </div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>
                  Conversations where people are actively shopping for charcoal grill controllers. Each signal is a potential customer or feature request.
                </p>
                {purchaseIntents.length > 0 ? (
                  <div className="stack-list compact">
                    {purchaseIntents.slice(0, 8).map((post, i) => (
                      <a key={i} href={post.source_url} target="_blank" rel="noopener noreferrer" className="list-item status-muted" style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div className="item-head">
                          <strong>{post.title || post.body?.slice(0, 80) || 'Untitled'}</strong>
                          <span className="badge badge-neutral">{post.platform}</span>
                        </div>
                        <p style={{ fontSize: 12 }}>
                          {post.engagement_score > 0 && `${fmtInt(post.engagement_score)} engagement`}
                          {post.comment_count > 0 && ` · ${post.comment_count} comments`}
                          {post.competitor_mentioned && ` · Mentions: ${post.competitor_mentioned}`}
                        </p>
                      </a>
                    ))}
                  </div>
                ) : <div className="state-message">No purchase intent signals captured yet.</div>}
              </section>
            </>
          )}

          {/* ============================================================ */}
          {/*  VIEW 3: INNOVATION RADAR                                    */}
          {/* ============================================================ */}
          {view === 'roadmap' && (
            <>
              {/* Innovation KPI strip */}
              <div className="venom-kpi-strip">
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Innovation Signals</div>
                  <div className="venom-kpi-value">{innovations.length}</div>
                  <div className="venom-kpi-sub">product ideas from market conversations</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Competitor Weaknesses</div>
                  <div className="venom-kpi-value">{competitorPains.length}</div>
                  <div className="venom-kpi-sub">pain points to exploit</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Trending Topics</div>
                  <div className="venom-kpi-value">{trendMomentum.length}</div>
                  <div className="venom-kpi-sub">cross-platform industry trends</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Amazon Position</div>
                  <div className="venom-kpi-value">
                    {marketIntel?.amazon_positioning?.bsr?.our_best_bsr ? `#${fmtInt(marketIntel.amazon_positioning.bsr.our_best_bsr)}` : '\u2014'}
                  </div>
                  <div className="venom-kpi-sub">best BSR ranking</div>
                </div>
              </div>

              {/* Industry Trend Momentum */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Industry Trend Momentum — What's Moving in Charcoal Grilling</strong>
                </div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
                  Topics gaining traction across Reddit, YouTube, and Amazon. Cross-platform signals have the highest reliability for identifying real market shifts.
                </p>
                {trendMomentum.length > 0 ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
                    {trendMomentum.map((trend, i) => (
                      <div key={i} style={{ background: 'var(--panel-2)', borderRadius: 8, padding: '12px 16px', border: `1px solid ${trend.cross_platform ? 'var(--blue)' : 'var(--border)'}` }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                          <strong style={{ fontSize: 14 }}>{trend.topic}</strong>
                          {momentumBadge(trend.momentum)}
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                          {fmtInt(trend.mentions)} mentions · {fmtInt(trend.total_engagement)} engagement
                        </div>
                        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                          {trend.platforms.map(p => <span key={p} className="badge badge-neutral" style={{ fontSize: 10 }}>{p}</span>)}
                          {trend.cross_platform && <span className="badge badge-good" style={{ fontSize: 10 }}>cross-platform</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <div className="state-message">No trend momentum data available yet. Social connectors will populate this.</div>}
              </section>

              {/* Product Innovation Signals */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Product Innovation Signals — Ideas From The Market</strong>
                  <Link to="/social" className="analysis-link">Social Intel &#x2197;</Link>
                </div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>
                  Conversations where users discuss product features they wish existed, modifications they've made, or innovations they've seen. Each is a potential product roadmap input.
                </p>
                {innovations.length > 0 ? (
                  <div className="stack-list">
                    {innovations.slice(0, 10).map((post, i) => (
                      <a key={i} href={post.source_url} target="_blank" rel="noopener noreferrer" className="list-item status-muted" style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div className="item-head">
                          <strong>{post.title || post.body?.slice(0, 100) || 'Untitled'}</strong>
                          <div className="inline-badges">
                            <span className="badge badge-neutral">{post.platform}</span>
                            {post.product_mentioned && <span className="badge badge-good">{post.product_mentioned}</span>}
                          </div>
                        </div>
                        {post.body && <p style={{ fontSize: 12, lineHeight: 1.5 }}>{post.body.slice(0, 200)}{post.body.length > 200 ? '...' : ''}</p>}
                        <p style={{ fontSize: 11, color: 'var(--muted)' }}>
                          {post.engagement_score > 0 && `${fmtInt(post.engagement_score)} engagement`}
                          {post.comment_count > 0 && ` · ${post.comment_count} comments`}
                          {post.published_at && ` · ${formatFreshness(post.published_at)}`}
                        </p>
                      </a>
                    ))}
                  </div>
                ) : <div className="state-message">No product innovation signals captured yet.</div>}
              </section>

              {/* Competitor Pain Points — opportunities */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Competitor Pain Points — Differentiation Opportunities</strong>
                </div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>
                  Complaints and frustrations about competitor products. Each pain point is an opportunity for Spider Grills to differentiate with superior design.
                </p>
                {competitorPains.length > 0 ? (
                  <div className="stack-list">
                    {competitorPains.slice(0, 10).map((post, i) => (
                      <a key={i} href={post.source_url} target="_blank" rel="noopener noreferrer" className="list-item status-muted" style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div className="item-head">
                          <strong>{post.title || post.body?.slice(0, 100) || 'Untitled'}</strong>
                          <div className="inline-badges">
                            {post.competitor_mentioned && <span className="badge badge-warn">{post.competitor_mentioned}</span>}
                            <span className="badge badge-neutral">{post.platform}</span>
                          </div>
                        </div>
                        {post.body && <p style={{ fontSize: 12, lineHeight: 1.5 }}>{post.body.slice(0, 200)}{post.body.length > 200 ? '...' : ''}</p>}
                        <p style={{ fontSize: 11, color: 'var(--muted)' }}>
                          {post.engagement_score > 0 && `${fmtInt(post.engagement_score)} engagement`}
                          {post.comment_count > 0 && ` · ${post.comment_count} comments`}
                        </p>
                      </a>
                    ))}
                  </div>
                ) : <div className="state-message">No competitor pain points captured yet.</div>}
              </section>

              {/* Competitive Landscape */}
              {marketIntel?.competitive_landscape && (
                <div className="two-col two-col-equal">
                  <section className="card">
                    <div className="venom-panel-head"><strong>Competitive Share of Voice</strong></div>
                    {marketIntel.competitive_landscape.competitors.length > 0 ? (
                      <>
                        <div className="chart-wrap-short">
                          <ResponsiveContainer width="100%" height={240}>
                            <BarChart data={[
                              { brand: 'Spider Grills', mentions: marketIntel.competitive_landscape.brand_mentions, fill: 'var(--green)' },
                              ...marketIntel.competitive_landscape.competitors.slice(0, 6).map(c => ({ brand: c.competitor, mentions: c.mentions, fill: 'var(--blue)' }))
                            ]} layout="vertical">
                              <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                              <XAxis type="number" stroke="#9fb0d4" />
                              <YAxis type="category" dataKey="brand" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={100} />
                              <Tooltip />
                              <Bar dataKey="mentions" name="Mentions" radius={[0, 4, 4, 0]}>
                                {[
                                  { brand: 'Spider Grills', mentions: marketIntel.competitive_landscape.brand_mentions },
                                  ...marketIntel.competitive_landscape.competitors.slice(0, 6)
                                ].map((_, i) => <Cell key={i} fill={i === 0 ? '#4ade80' : CHART_COLORS[i % CHART_COLORS.length]} />)}
                              </Bar>
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                        <small className="venom-panel-footer">
                          Spider Grills SOV: {(marketIntel.competitive_landscape.brand_share_of_voice * 100).toFixed(1)}% · {marketIntel.competitive_landscape.brand_mentions} mentions
                        </small>
                      </>
                    ) : <div className="state-message">No competitor data available yet.</div>}
                  </section>

                  {/* Amazon Market Position */}
                  <section className="card">
                    <div className="venom-panel-head"><strong>Amazon Market Position</strong></div>
                    {marketIntel.amazon_positioning ? (
                      <div className="venom-breakdown-list">
                        {marketIntel.amazon_positioning.bsr && (
                          <>
                            <div className="venom-breakdown-row">
                              <span>Our Best BSR</span>
                              <span className="venom-breakdown-val">#{fmtInt(marketIntel.amazon_positioning.bsr.our_best_bsr)}</span>
                            </div>
                            <div className="venom-breakdown-row">
                              <span>Competitor Best BSR</span>
                              <span className="venom-breakdown-val">#{fmtInt(marketIntel.amazon_positioning.bsr.competitor_best_bsr)}</span>
                            </div>
                            <div className="venom-breakdown-row">
                              <span>Outranking Competitors</span>
                              <span className="venom-breakdown-val" style={{ color: marketIntel.amazon_positioning.bsr.outranking_competitors ? 'var(--green)' : 'var(--red)' }}>
                                {marketIntel.amazon_positioning.bsr.outranking_competitors ? 'Yes' : 'No'}
                              </span>
                            </div>
                          </>
                        )}
                        {marketIntel.amazon_positioning.price && (
                          <>
                            <div className="venom-breakdown-row">
                              <span>Our Avg Price</span>
                              <span className="venom-breakdown-val">${marketIntel.amazon_positioning.price.our_avg_price.toFixed(2)}</span>
                            </div>
                            <div className="venom-breakdown-row">
                              <span>Competitor Avg Price</span>
                              <span className="venom-breakdown-val">${marketIntel.amazon_positioning.price.competitor_avg_price.toFixed(2)}</span>
                            </div>
                            <div className="venom-breakdown-row">
                              <span>Price Position</span>
                              <span className="venom-breakdown-val">{marketIntel.amazon_positioning.price.position} ({marketIntel.amazon_positioning.price.price_delta_pct > 0 ? '+' : ''}{marketIntel.amazon_positioning.price.price_delta_pct.toFixed(0)}%)</span>
                            </div>
                          </>
                        )}
                        <div className="venom-breakdown-row">
                          <span>Our Products Listed</span>
                          <span className="venom-breakdown-val">{marketIntel.amazon_positioning.our_products}</span>
                        </div>
                        <div className="venom-breakdown-row">
                          <span>Competitor Products Tracked</span>
                          <span className="venom-breakdown-val">{marketIntel.amazon_positioning.competitor_products}</span>
                        </div>
                      </div>
                    ) : <div className="state-message">Amazon positioning data not available yet.</div>}
                  </section>
                </div>
              )}

              {/* Product Roadmap Input Summary */}
              <section className="card">
                <div className="venom-panel-head"><strong>Roadmap Input Summary</strong></div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
                  Aggregated signals that should inform the next product development cycle. Review these inputs when planning sprints or quarterly roadmaps.
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Customer Support</div>
                    <strong style={{ fontSize: 20 }}>{productClusters.length}</strong>
                    <span style={{ fontSize: 13, color: 'var(--muted)' }}> issue clusters</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12, color: 'var(--text)' }}>
                      {productClusters.slice(0, 3).map((c, i) => <li key={i}>{c.title} ({c.severity})</li>)}
                      {productClusters.length === 0 && <li>No clusters</li>}
                    </ul>
                  </div>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Market Research</div>
                    <strong style={{ fontSize: 20 }}>{innovations.length}</strong>
                    <span style={{ fontSize: 13, color: 'var(--muted)' }}> innovation signals</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12, color: 'var(--text)' }}>
                      {innovations.slice(0, 3).map((p, i) => <li key={i}>{(p.title || p.body || '').slice(0, 60)}...</li>)}
                      {innovations.length === 0 && <li>No signals yet</li>}
                    </ul>
                  </div>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Competitors</div>
                    <strong style={{ fontSize: 20 }}>{competitorPains.length}</strong>
                    <span style={{ fontSize: 13, color: 'var(--muted)' }}> pain points to exploit</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12, color: 'var(--text)' }}>
                      {competitorPains.slice(0, 3).map((p, i) => <li key={i}>{p.competitor_mentioned || 'Competitor'}: {(p.title || p.body || '').slice(0, 50)}...</li>)}
                      {competitorPains.length === 0 && <li>No pain points yet</li>}
                    </ul>
                  </div>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Telemetry</div>
                    <strong style={{ fontSize: 20 }}>{issuePatterns.length}</strong>
                    <span style={{ fontSize: 13, color: 'var(--muted)' }}> detected patterns</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12, color: 'var(--text)' }}>
                      {issuePatterns.slice(0, 3).map((p, i) => <li key={i}>{p.pattern.replace(/_/g, ' ')} ({p.severity})</li>)}
                      {issuePatterns.length === 0 && <li>No patterns detected</li>}
                    </ul>
                  </div>
                </div>
              </section>
            </>
          )}
        </>
      ) : null}
    </div>
  )
}
