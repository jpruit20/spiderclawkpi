import { useEffect, useMemo, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge, type TruthState } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ProvenanceBanner } from '../components/ProvenanceBanner'
import { ApiError, api } from '../lib/api'
import { fmtPct, fmtInt, fmtDecimal, fmtDuration, formatFreshness } from '../lib/format'
import type { ClusterTicketDetail, CookAnalysis, GithubIssuesResponse, IssueRadarResponse, MarketIntelligence, MarketPost, TelemetryHistoryDailyRow, TelemetrySummary, TrendMomentum, CXSnapshotResponse } from '../lib/types'
import {
  BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Line, Area, ComposedChart, PieChart, Pie, Cell,
} from 'recharts'

/* ------------------------------------------------------------------ */
/*  Sub-view navigation                                               */
/* ------------------------------------------------------------------ */
type SubView = 'fleet' | 'voice' | 'roadmap'

/* ------------------------------------------------------------------ */
/*  Model name mapping                                                */
/* ------------------------------------------------------------------ */
const MODEL_NAME_MAP: Record<string, string> = {
  'W:K:22:1:V': '22" Weber Kettle (Venom)',
  'Kettle 22': '22" Weber Kettle (Venom)',
  'kettle_22': '22" Weber Kettle (Venom)',
  'Kettle22': '22" Weber Kettle (Venom)',
  'W:K:22': '22" Weber Kettle',
  'Huntsman': 'Huntsman',
  'Giant Huntsman': 'Giant Huntsman',
}

function displayModelName(raw: string): string {
  return MODEL_NAME_MAP[raw] || raw
}

/** Merge model keys that map to the same display name */
function mergeModelData(data: { model: string; events: number }[]): { model: string; events: number }[] {
  const merged: Record<string, number> = {}
  for (const d of data) {
    const name = displayModelName(d.model)
    merged[name] = (merged[name] || 0) + d.events
  }
  return Object.entries(merged).sort(([, a], [, b]) => b - a).map(([model, events]) => ({ model, events }))
}

/* ------------------------------------------------------------------ */
/*  Cook style labels + colors                                        */
/* ------------------------------------------------------------------ */
const COOK_STYLE_LABELS: Record<string, string> = {
  startup_only: 'Startup Only',
  hot_and_fast: 'Hot & Fast (400F+)',
  low_and_slow: 'Low & Slow (< 275F)',
  medium_heat: 'Medium Heat (275-400F)',
  unclassified: 'Unclassified',
}
const COOK_STYLE_COLORS: Record<string, string> = {
  startup_only: '#9b7bff',
  hot_and_fast: '#ef4444',
  low_and_slow: '#6ea8ff',
  medium_heat: '#f59e0b',
  unclassified: '#555',
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

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
  const raw = Object.entries(totals).sort(([, a], [, b]) => b - a).slice(0, 8).map(([model, events]) => ({ model, events }))
  return mergeModelData(raw)
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
/*  Cluster Detail Modal                                              */
/* ------------------------------------------------------------------ */
function ClusterDetailPanel({ detail, onClose }: { detail: ClusterTicketDetail; onClose: () => void }) {
  const [showAll, setShowAll] = useState(false)
  const visibleTickets = showAll ? detail.tickets : detail.tickets.slice(0, 15)

  return (
    <div className="card" style={{ border: '1px solid var(--accent)', marginTop: 12 }}>
      <div className="venom-panel-head">
        <strong>{detail.theme_title} — Ticket Deep-Dive</strong>
        <button className="range-button" onClick={onClose}>Close</button>
      </div>

      {/* Key metrics */}
      <div className="venom-kpi-strip" style={{ marginBottom: 12 }}>
        <div className="venom-kpi-card">
          <div className="venom-kpi-label">Total Tickets</div>
          <div className="venom-kpi-value">{detail.total_tickets}</div>
        </div>
        <div className="venom-kpi-card">
          <div className="venom-kpi-label">Unique Customers</div>
          <div className="venom-kpi-value">{detail.unique_customers}</div>
          <div className="venom-kpi-sub">{(detail.customer_ratio * 100).toFixed(0)}% unique ratio</div>
        </div>
        <div className="venom-kpi-card">
          <div className="venom-kpi-label">Severity Assessment</div>
          <div className="venom-kpi-value" style={{ fontSize: 16, color: detail.severity_adjustment === 'downgraded' ? 'var(--green)' : detail.severity_adjustment === 'upgraded' ? 'var(--red)' : 'var(--text)' }}>
            {detail.severity_adjustment === 'downgraded' ? 'Lower Risk' : detail.severity_adjustment === 'upgraded' ? 'Higher Risk' : 'Normal'}
          </div>
          <div className="venom-kpi-sub">{detail.severity_reason}</div>
        </div>
        <div className="venom-kpi-card">
          <div className="venom-kpi-label">Owner</div>
          <div className="venom-kpi-value" style={{ fontSize: 16 }}>{detail.owner_team}</div>
        </div>
      </div>

      {/* Sub-topics */}
      {detail.sub_topics.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="venom-breakdown-label">Common Sub-Topics Within This Cluster</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
            {detail.sub_topics.map((t, i) => (
              <span key={i} className="badge badge-neutral" style={{ fontSize: 11 }}>{t.keyword} ({t.count})</span>
            ))}
          </div>
        </div>
      )}

      {/* Breakdowns */}
      <div className="two-col two-col-equal" style={{ marginBottom: 12 }}>
        <div>
          <div className="venom-breakdown-label">Status Breakdown</div>
          <div className="venom-breakdown-list">
            {Object.entries(detail.status_breakdown).map(([k, v]) => (
              <div key={k} className="venom-breakdown-row"><span>{k}</span><span className="venom-breakdown-val">{v}</span></div>
            ))}
          </div>
        </div>
        <div>
          <div className="venom-breakdown-label">Top Reporters</div>
          <div className="venom-breakdown-list">
            {detail.top_requesters.slice(0, 5).map((r, i) => (
              <div key={i} className="venom-breakdown-row">
                <span>Customer #{r.requester_id.slice(-6)}</span>
                <span className="venom-breakdown-val">{r.ticket_count} ticket{r.ticket_count !== 1 ? 's' : ''}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Ticket list */}
      <div className="venom-breakdown-label">Individual Tickets ({detail.total_tickets})</div>
      <div className="stack-list compact" style={{ maxHeight: 400, overflowY: 'auto' }}>
        {visibleTickets.map((t, i) => (
          <div key={i} className={`list-item status-${t.status === 'Resolved' || t.status === 'Closed' ? 'good' : 'muted'}`}>
            <div className="item-head">
              <strong>#{t.ticket_id} {t.subject}</strong>
              <div className="inline-badges">
                <span className="badge badge-neutral">{t.status || 'open'}</span>
                {t.channel && <span className="badge badge-neutral" style={{ fontSize: 10 }}>{t.channel}</span>}
              </div>
            </div>
            <p style={{ fontSize: 11, color: 'var(--muted)' }}>
              Customer #{t.requester_id.slice(-6)}
              {t.created_at && ` · Created ${formatFreshness(t.created_at)}`}
              {t.resolution_hours != null && ` · Resolved in ${t.resolution_hours.toFixed(1)}h`}
              {t.tags.length > 0 && ` · Tags: ${t.tags.join(', ')}`}
            </p>
          </div>
        ))}
      </div>
      {!showAll && detail.tickets.length > 15 && (
        <button className="range-button" style={{ marginTop: 8 }} onClick={() => setShowAll(true)}>Show all {detail.tickets.length} tickets</button>
      )}
    </div>
  )
}

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

  // Date range — defaults to last 30 days
  const [dateStart, setDateStart] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 30); return d.toISOString().split('T')[0]
  })
  const [dateEnd, setDateEnd] = useState(() => new Date().toISOString().split('T')[0])
  const [showDatePicker, setShowDatePicker] = useState(false)

  // Cluster drill-down state
  const [clusterDetail, setClusterDetail] = useState<ClusterTicketDetail | null>(null)
  const [clusterDetailLoading, setClusterDetailLoading] = useState(false)

  const daysDiff = useMemo(() => {
    const start = new Date(dateStart).getTime()
    const end = new Date(dateEnd).getTime()
    return Math.max(1, Math.ceil((end - start) / (1000 * 60 * 60 * 24)))
  }, [dateStart, dateEnd])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [telData, issuesData, radarData, miData, cxData] = await Promise.all([
          api.telemetrySummary(daysDiff),
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
  }, [daysDiff])

  const loadClusterDetail = useCallback(async (theme: string) => {
    setClusterDetailLoading(true)
    try {
      const detail = await api.clusterDetail(theme)
      setClusterDetail(detail)
    } catch {
      setClusterDetail(null)
    } finally {
      setClusterDetailLoading(false)
    }
  }, [])

  /* Telemetry derived values */
  const collection = telemetry?.collection_metadata || null
  const derived = telemetry?.analytics?.derived_metrics || null
  const latest = telemetry?.latest || null
  const analytics = telemetry?.analytics || null
  const historyDaily = telemetry?.history_daily || []
  const cookAnalysis = telemetry?.cook_analysis || null
  const confidence = telemetry?.confidence || null

  const streamBacked = collection?.sample_source === 'dynamodb_stream'

  // Staleness: warn if newest sample is > 1 hour old
  const newestSample = collection?.newest_sample_timestamp_seen
  const staleMins = newestSample ? Math.floor((Date.now() - new Date(newestSample).getTime()) / 60000) : null
  const isStale = staleMins !== null && staleMins > 60

  // Truncation: warn if DynamoDB scan was bounded
  const scanTruncated = collection?.scan_truncated === true
  const capHit = collection?.max_record_cap_hit === true
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
    const start = new Date(dateStart).getTime()
    const end = new Date(dateEnd).getTime()
    return historyDaily.filter(row => {
      const t = new Date(row.business_date).getTime()
      return t >= start && t <= end
    })
  }, [historyDaily, dateStart, dateEnd])

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

  /* Issue Radar: product-related clusters — filter out "unknown" */
  const productClusters = useMemo(() => {
    if (!issueRadar?.clusters) return []
    return issueRadar.clusters
      .filter(c => {
        const d = c.details_json || {}
        if (d.theme === 'unknown') return false
        const themes: string[] = [d.theme, ...(d.secondary_themes || [])]
        const productThemes = ['temperature_control_venom', 'ignition_startup', 'app_connectivity', 'assembly', 'parts_replacement', 'probe_issues', 'wifi_connectivity']
        return themes.some(t => productThemes.includes(t)) || (d.affected_products && d.affected_products.length > 0)
      })
      .sort((a, b) => (b.details_json?.priority_score || 0) - (a.details_json?.priority_score || 0))
  }, [issueRadar])

  /* All clusters except "unknown" for VOC view */
  const allClusters = useMemo(() => {
    if (!issueRadar?.clusters) return []
    return issueRadar.clusters
      .filter(c => (c.details_json?.theme || '') !== 'unknown')
      .sort((a, b) => (b.details_json?.priority_score || 0) - (a.details_json?.priority_score || 0))
  }, [issueRadar])

  /* CX actions that are product-related */
  const productActions = useMemo(() => {
    if (!cxSnapshot?.actions) return []
    const productKpis = ['reopen_rate', 'escalation_rate', 'avg_close_time']
    return cxSnapshot.actions.filter(a => productKpis.includes(a.trigger_kpi) || a.co_owner === 'Kyle')
  }, [cxSnapshot])

  /* Market intel */
  const innovations = marketIntel?.product_innovation?.posts || []
  const competitorPains = marketIntel?.competitor_pain_points?.posts || []
  const purchaseIntents = marketIntel?.purchase_intent?.posts || []
  const trendMomentum = marketIntel?.trend_momentum || []

  /* Firmware/grill health from telemetry */
  const firmwareHealth = telemetry?.firmware_health || []
  const grillTypeHealth = useMemo(() =>
    (telemetry?.grill_type_health || []).map(g => ({ ...g, key: displayModelName(g.key) })),
    [telemetry]
  )
  const topErrors = telemetry?.top_error_codes || []
  const issuePatterns = telemetry?.top_issue_patterns || []

  /* Cook style pie data */
  const cookStylePie = useMemo(() => {
    if (!cookAnalysis?.cook_styles) return []
    return Object.entries(cookAnalysis.cook_styles)
      .filter(([, v]) => v > 0)
      .map(([key, value]) => ({ name: COOK_STYLE_LABELS[key] || key, value, key }))
  }, [cookAnalysis])

  /* ------------------------------------------------------------------
   * Auto-insights for product team
   * ------------------------------------------------------------------ */
  const productInsights = useMemo(() => {
    const items: { icon: string; text: string; severity: 'good' | 'warn' | 'bad' | 'info' }[] = []

    if (successRate != null) {
      if (successRate >= 0.95) items.push({ icon: '\u2705', text: `Session reliability is ${fmtPct(successRate)} — strong performance.`, severity: 'good' })
      else if (successRate >= 0.85) items.push({ icon: '\u26a0\ufe0f', text: `Session reliability at ${fmtPct(successRate)}. Note: short startup-only sessions that end before reaching target count as "incomplete" and lower this number. Check cook type mix below for context.`, severity: 'warn' })
      else items.push({ icon: '\ud83d\udea8', text: `Session reliability at ${fmtPct(successRate)}. Review cook type breakdown — startup-only sessions pulling down the average may not indicate a real product issue.`, severity: 'bad' })
    }

    // Cook mix insight
    if (cookAnalysis?.cook_styles) {
      const total = cookAnalysis.total_sessions
      const startup = cookAnalysis.cook_styles.startup_only || 0
      const lowSlow = cookAnalysis.cook_styles.low_and_slow || 0
      if (total > 0 && startup / total > 0.3) {
        items.push({ icon: '\ud83d\udd25', text: `${fmtPct(startup / total)} of sessions are startup-only (< 15 min) — users lighting the grill and switching to manual. This is a normal use case, not an error.`, severity: 'info' })
      }
      if (total > 0 && lowSlow / total > 0.2) {
        items.push({ icon: '\ud83c\udf56', text: `${fmtPct(lowSlow / total)} of sessions are low-and-slow cooks. Temperature stability is critical for these users — monitor the stability score closely.`, severity: 'info' })
      }
    }

    if (overshootRate != null && overshootRate > 0.15) {
      items.push({ icon: '\ud83c\udf21\ufe0f', text: `Overshoot rate at ${fmtPct(overshootRate)} — may indicate PID tuning needed. Check if specific grill types or firmware versions are disproportionately affected.`, severity: 'warn' })
    }

    if (medianRssi != null && medianRssi < -75) {
      items.push({ icon: '\ud83d\udcf6', text: `Median WiFi signal at ${medianRssi} dBm (weak). Outdoor grill placement far from routers is common — consider documentation guidance or antenna improvements.`, severity: 'warn' })
    }

    if (productClusters.length > 0) {
      const topCluster = productClusters[0]
      const d = topCluster.details_json || {}
      items.push({ icon: '\ud83d\udce6', text: `Top product issue cluster: "${topCluster.title}" (${d.total_tickets || '?'} tickets, ${topCluster.severity} severity).`, severity: topCluster.severity === 'critical' ? 'bad' : 'warn' })
    }

    if (innovations.length > 0) items.push({ icon: '\ud83d\udca1', text: `${innovations.length} product innovation signals from market conversations.`, severity: 'info' })
    if (competitorPains.length > 0) items.push({ icon: '\ud83c\udfaf', text: `${competitorPains.length} competitor pain points captured — differentiation opportunities.`, severity: 'info' })
    if (items.length === 0) items.push({ icon: '\u2705', text: 'All product health metrics within normal ranges.', severity: 'good' })
    return items
  }, [successRate, overshootRate, medianRssi, productClusters, innovations, competitorPains, cookAnalysis])


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
              <button key={tab.key} className={`range-button${view === tab.key ? ' active' : ''}`} onClick={() => { setView(tab.key); setClusterDetail(null) }}>{tab.label}</button>
            ))}
          </div>
          {/* Date Range Picker */}
          <div style={{ position: 'relative' }}>
            <button className="range-button active" onClick={() => setShowDatePicker(!showDatePicker)}>
              {dateStart.slice(5)} to {dateEnd.slice(5)} ({daysDiff}d)
            </button>
            {showDatePicker && (
              <div style={{ position: 'absolute', top: '100%', right: 0, zIndex: 20, background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginTop: 4, display: 'flex', gap: 8, alignItems: 'center' }}>
                <label style={{ fontSize: 12, color: 'var(--muted)' }}>From <input type="date" value={dateStart} onChange={e => setDateStart(e.target.value)} className="deci-input" /></label>
                <label style={{ fontSize: 12, color: 'var(--muted)' }}>To <input type="date" value={dateEnd} onChange={e => setDateEnd(e.target.value)} className="deci-input" /></label>
                <button className="range-button" onClick={() => setShowDatePicker(false)}>Apply</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {loading ? <Card title="Product Hub"><div className="state-message">Loading product data...</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <ProvenanceBanner
            compact
            truthState={streamBacked ? 'canonical' : 'degraded'}
            lastUpdated={collection?.newest_sample_timestamp_seen}
            scope={`${daysDiff}-day window · ${fmtInt(sampleSize)} device samples`}
            caveat={!streamBacked ? 'Running on daily aggregates — live stream unavailable. Some metrics may be delayed up to 24h.' : undefined}
          />

          {/* Data quality warnings */}
          {isStale && (
            <div className="scope-note" style={{ fontSize: 12, color: 'var(--orange)', padding: '6px 12px', background: 'var(--warning-bg)', borderRadius: 6, marginBottom: 8 }}>
              ⚠️ Telemetry data is stale — newest sample is {staleMins! > 1440 ? `${Math.floor(staleMins! / 1440)}d` : staleMins! > 60 ? `${Math.floor(staleMins! / 60)}h` : `${staleMins}m`} old. Device metrics may not reflect current fleet state.
            </div>
          )}
          {(scanTruncated || capHit) && (
            <div className="scope-note" style={{ fontSize: 12, color: 'var(--orange)', padding: '6px 12px', background: 'var(--warning-bg)', borderRadius: 6, marginBottom: 8 }}>
              ⚠️ Telemetry scan was bounded{scanTruncated ? ' (pagination limit)' : ''}{capHit ? ' (record cap hit)' : ''} — fleet metrics are based on a sample, not the full device population. Confidence badges reflect this.
            </div>
          )}
          {sampleSize > 0 && sampleSize < 10 && (
            <div className="scope-note" style={{ fontSize: 12, color: 'var(--muted)', padding: '6px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, marginBottom: 8 }}>
              Sample size is low (n={fmtInt(sampleSize)}) — reliability and stability metrics are directional, not statistically significant.
            </div>
          )}

          {/* Intelligence Briefing */}
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
                    <TruthBadge state={(confidence?.global_completeness as TruthState) || 'proxy'} />
                    {devices60m > 0 && <span className="venom-delta venom-delta-up">{fmtInt(devices60m)} in 60m · {fmtInt(devices24h)} in 24h</span>}
                  </div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Reliability</div>
                  <div className="venom-kpi-value">{fmtPct(successRate)}</div>
                  <div className="venom-kpi-sub">session success · n={fmtInt(sampleSize)}</div>
                  <div className="venom-kpi-badges"><TruthBadge state={(confidence?.cook_success as TruthState) || 'estimated'} /></div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Temp Stability</div>
                  <div className="venom-kpi-value">{fmtDecimal(stabilityScore)}</div>
                  <div className="venom-kpi-sub">score (0-1, higher = steadier)</div>
                  <div className="venom-kpi-badges"><TruthBadge state={(confidence?.session_derivation as TruthState) || 'estimated'} /></div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Product Issues</div>
                  <div className="venom-kpi-value">{productClusters.length}</div>
                  <div className="venom-kpi-sub">active clusters from support + telemetry</div>
                </div>
              </div>

              {/* Fleet Activity Chart */}
              <section className="card">
                <div className="venom-panel-head">
                  <div>
                    <strong>Fleet Activity — Daily Active Devices</strong>
                    <p className="venom-chart-sub">Showing {rangedHistory.length} day{rangedHistory.length !== 1 ? 's' : ''} ({dateStart} to {dateEnd})</p>
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
                ) : <div className="state-message">No historical daily data available for this date range. Run the S3 import to populate fleet history.</div>}
              </section>

              {/* Cook Type Analysis */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>How Customers Use the Venom</strong>
                  <span className="venom-panel-hint">{cookAnalysis?.total_sessions || 0} sessions analyzed</span>
                </div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
                  Understanding cook types helps interpret all other metrics. A "Startup Only" session (&lt;15 min) means the user lit the grill with Venom, reached temp, then switched to manual — that's a normal use case, not a failure. Low-and-slow cooks (brisket, pulled pork) demand tight temperature stability. Hot-and-fast cooks (burgers, searing) are brief and less stability-sensitive.
                </p>
                {cookStylePie.length > 0 ? (
                  <div className="two-col two-col-equal">
                    <div>
                      <div className="chart-wrap-short">
                        <ResponsiveContainer width="100%" height={240}>
                          <PieChart>
                            <Pie data={cookStylePie} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                              {cookStylePie.map((entry) => <Cell key={entry.key} fill={COOK_STYLE_COLORS[entry.key] || '#555'} />)}
                            </Pie>
                            <Tooltip />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                    <div>
                      <div className="venom-breakdown-label">Per-Style Performance</div>
                      <div className="venom-breakdown-list">
                        {Object.entries(cookAnalysis?.style_details || {}).filter(([, d]) => d.count > 0).map(([style, d]) => (
                          <div key={style} className="venom-breakdown-row" style={{ flexWrap: 'wrap' }}>
                            <span style={{ color: COOK_STYLE_COLORS[style], fontWeight: 600, minWidth: 160 }}>{COOK_STYLE_LABELS[style] || style}</span>
                            <span className="venom-breakdown-val" style={{ minWidth: 200 }}>
                              {d.count} sessions · avg {fmtDuration(d.avg_duration_seconds)}
                              {d.avg_stability_score != null ? ` · stability ${fmtDecimal(d.avg_stability_score)}` : ''}
                              {d.success_rate != null ? ` · success ${fmtPct(d.success_rate)}` : ''}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : <div className="state-message">Cook type data populates from telemetry sessions. Data will appear after sufficient device activity.</div>}
              </section>

              {/* Control Quality + Reliability */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Temperature Control Quality</strong>
                    <Link to="/analysis/temp-curves" className="analysis-link">View curves &#x2197;</Link>
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                    Post-target stability: only measures temperature hold <em>after</em> reaching the target zone. Preheat ramp-up is excluded. Stabilization time depends on charcoal type, ambient conditions, and fire-start method — treat as directional, not absolute.
                  </p>
                  <div className="venom-bar-list">
                    <div className="venom-bar-row"><span className="venom-bar-label">Stability (post-target)</span><BarIndicator value={(stabilityScore || 0) * 100} max={100} color="var(--green)" /><span className="venom-bar-value">{fmtDecimal(stabilityScore)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Overshoot rate</span><BarIndicator value={(overshootRate || 0) * 100} max={100} color="var(--orange)" /><span className="venom-bar-value">{fmtPct(overshootRate, 0)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Stabilize (p50)</span><BarIndicator value={p50Stabilize || 0} max={p95Stabilize || 1200} color="var(--blue)" /><span className="venom-bar-value">{fmtDuration(p50Stabilize)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Stabilize (p95)</span><BarIndicator value={p95Stabilize || 0} max={p95Stabilize || 1200} color="var(--red)" /><span className="venom-bar-value">{fmtDuration(p95Stabilize)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Median cook</span><BarIndicator value={medianCookDuration || 0} max={p95CookDuration || 14400} color="#9b7bff" /><span className="venom-bar-value">{fmtDuration(medianCookDuration)}</span></div>
                    <div className="venom-bar-row"><span className="venom-bar-label">Cook p95</span><BarIndicator value={p95CookDuration || 0} max={p95CookDuration || 14400} color="var(--red)" /><span className="venom-bar-value">{fmtDuration(p95CookDuration)}</span></div>
                  </div>
                  <small className="venom-panel-footer">
                    Stability = how tightly temp stays within target band <strong>after reaching setpoint</strong> (preheat excluded). Stabilize time = seconds from grill-lit detection (&gt;150°F) to 3 consecutive readings within ±15°F of target. Varies by charcoal, ambient temp, fire-start method.
                  </small>
                </section>

                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Connectivity & Reliability</strong>
                    <Link to="/issues" className="analysis-link">View issues &#x2197;</Link>
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                    Session success requires: reaching target temp, stabilizing, no disconnects, and zero errors. Startup-only sessions (&lt;15 min) that end before target may count as incomplete.
                  </p>
                  <div className="venom-breakdown-list">
                    <div className="venom-breakdown-row"><span>Session success rate</span><span className="venom-breakdown-val">{fmtPct(successRate)}</span><TruthBadge state={(confidence?.cook_success as TruthState) || 'estimated'} /></div>
                    <div className="venom-breakdown-row"><span>Disconnect rate</span><span className="venom-breakdown-val">{fmtPct(disconnectRate)}</span><TruthBadge state={(confidence?.disconnect_detection as TruthState) || 'proxy'} /></div>
                    <div className="venom-breakdown-row"><span>Probe error rate</span><span className="venom-breakdown-val">{fmtPct(probeErrorRate)}</span></div>
                    <div className="venom-breakdown-row"><span>Median RSSI</span><span className="venom-breakdown-val">{medianRssi != null ? `${medianRssi} dBm` : '\u2014'}</span></div>
                  </div>
                  <small className="venom-panel-footer">
                    Disconnect rate = sessions where a &gt;45-minute gap was detected between telemetry events (proxy for WiFi dropout). Probe error = sessions where food probe readings were expected but missing. RSSI = WiFi signal strength (below -75 dBm = weak). n={fmtInt(sampleSize)} sessions.
                  </small>
                  {grillTypeHealth.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div className="venom-breakdown-label">By Grill Type</div>
                      <div className="venom-breakdown-list">
                        {grillTypeHealth.map((g, i) => (
                          <div key={i} className="venom-breakdown-row">
                            <span>{g.key}</span>
                            <span className="venom-breakdown-val" style={{ color: g.severity === 'critical' ? 'var(--red)' : g.severity === 'warning' ? 'var(--orange)' : 'var(--green)' }}>{fmtDecimal(g.health_score)} health</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              </div>

              {/* Model + Peak Hours */}
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
                          <YAxis type="category" dataKey="model" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={160} />
                          <Tooltip />
                          <Bar dataKey="events" name="Events" fill="var(--green)" radius={[0, 4, 4, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : <div className="state-message">Model distribution populates after S3 history import.</div>}
                </section>
              </div>

              {/* Firmware + Errors */}
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
                  {firmwareHealth.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div className="venom-breakdown-label">Firmware Health</div>
                      <div className="venom-breakdown-list">
                        {firmwareHealth.map((f, i) => (
                          <div key={i} className="venom-breakdown-row">
                            <span>{f.key}</span>
                            <span className="venom-breakdown-val">{f.sessions} sessions</span>
                            <span style={{ color: f.severity === 'critical' ? 'var(--red)' : f.severity === 'warning' ? 'var(--orange)' : 'var(--green)', fontWeight: 600, fontSize: 12 }}>{fmtDecimal(f.health_score)}</span>
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
                          <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{e.error_code || e.code}</span>
                          <span className="venom-breakdown-val">{fmtInt(e.count)} events</span>
                          <span style={{ color: 'var(--muted)', fontSize: 11 }}>{e.pct_of_errors ? fmtPct(e.pct_of_errors) : ''}</span>
                        </div>
                      ))}
                    </div>
                  ) : <div className="state-message">No error codes captured yet.</div>}
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

              {/* GitHub Issues + Product Clusters */}
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
                            </div>
                          </div>
                          <p>{issue.assignees.length > 0 ? `Assigned: ${issue.assignees.join(', ')}` : 'Unassigned'} · Updated {formatFreshness(issue.updated_at)}</p>
                        </a>
                      ))}
                    </div>
                  ) : <div className="state-message">{githubIssues?.configured === false ? 'GitHub not configured.' : 'No P0/P1 issues'}</div>}
                </section>
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Product Issue Clusters</strong>
                    <Link to="/issues" className="analysis-link">Full radar &#x2197;</Link>
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Click any cluster for ticket-level detail.</p>
                  {productClusters.length > 0 ? (
                    <div className="stack-list compact">
                      {productClusters.slice(0, 6).map((cluster, i) => {
                        const d = cluster.details_json || {}
                        return (
                          <div key={i} className={`list-item status-${cluster.severity === 'critical' ? 'bad' : cluster.severity === 'high' ? 'warn' : 'muted'}`}
                            style={{ cursor: 'pointer' }}
                            onClick={() => loadClusterDetail(d.theme)}>
                            <div className="item-head">
                              <strong>{cluster.title}</strong>
                              {severityBadge(cluster.severity)}
                            </div>
                            <p>{d.total_tickets && `${d.total_tickets} tickets`}{d.trend_label && ` · ${d.trend_label}`}{d.affected_products?.length > 0 && ` · ${d.affected_products.join(', ')}`}</p>
                          </div>
                        )
                      })}
                    </div>
                  ) : <div className="state-message">No product issue clusters detected.</div>}
                </section>
              </div>

              {/* Cluster detail panel (expanded) */}
              {clusterDetailLoading && <Card title="Loading"><div className="state-message">Loading ticket detail...</div></Card>}
              {clusterDetail && !clusterDetailLoading && <ClusterDetailPanel detail={clusterDetail} onClose={() => setClusterDetail(null)} />}

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
              <div className="venom-kpi-strip">
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Issue Clusters</div>
                  <div className="venom-kpi-value">{allClusters.length}</div>
                  <div className="venom-kpi-sub">categorized from support tickets</div>
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
                  <div className="venom-kpi-label">Share of Voice</div>
                  <div className="venom-kpi-value" style={{ color: sentimentColor(marketIntel?.competitive_landscape?.brand_share_of_voice) }}>
                    {marketIntel?.competitive_landscape?.brand_share_of_voice != null ? `${(marketIntel.competitive_landscape.brand_share_of_voice * 100).toFixed(1)}%` : '\u2014'}
                  </div>
                  <div className="venom-kpi-sub">Spider Grills vs competitors</div>
                </div>
              </div>

              {/* Issue clusters with drill-down */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Customer Issue Analysis</strong>
                  <Link to="/issues" className="analysis-link">Full radar &#x2197;</Link>
                </div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>
                  Tickets are classified by topic, ranked by business impact. Click any cluster to see individual tickets, unique customer count, and sub-topics within the category.
                </p>
                {allClusters.length > 0 ? (
                  <div className="stack-list">
                    {allClusters.map((cluster, i) => {
                      const d = cluster.details_json || {}
                      const trendPct = d.trend_pct ?? 0
                      const isExpanded = clusterDetail?.theme === d.theme
                      return (
                        <div key={i}>
                          <div className={`list-item status-${cluster.severity === 'critical' ? 'bad' : cluster.severity === 'high' ? 'warn' : 'muted'}`}
                            style={{ cursor: 'pointer' }}
                            onClick={() => isExpanded ? setClusterDetail(null) : loadClusterDetail(d.theme)}>
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
                              <strong>{d.total_tickets}</strong> tickets · <strong>{d.recent_7d}</strong> this week
                              {d.affected_products?.length > 0 && <> · Affects: {d.affected_products.join(', ')}</>}
                              {d.owner_team && <> · Owner: {d.owner_team}</>}
                            </p>
                            {d.tickets_per_100_orders_by_theme && (
                              <p style={{ fontSize: 12, color: 'var(--muted)' }}>
                                Impact: {d.tickets_per_100_orders_by_theme.toFixed(1)} tickets/100 orders
                                {d.estimated_conversion_impact_pct && ` · est. ${d.estimated_conversion_impact_pct.toFixed(1)}% conversion impact`}
                              </p>
                            )}
                            <p style={{ fontSize: 11, color: 'var(--accent)' }}>
                              {isExpanded ? 'Click to collapse' : 'Click for ticket detail'}
                            </p>
                          </div>
                          {isExpanded && clusterDetail && <ClusterDetailPanel detail={clusterDetail} onClose={() => setClusterDetail(null)} />}
                        </div>
                      )
                    })}
                  </div>
                ) : <div className="state-message">No issue clusters detected from customer data.</div>}
                {clusterDetailLoading && <div className="state-message">Loading ticket detail...</div>}
              </section>

              {/* CX Escalations */}
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
                      </div>
                    ))}
                  </div>
                ) : <div className="state-message">No product-linked CX escalations.</div>}
              </section>

              {/* Purchase intent */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Purchase Intent Monitor</strong>
                  <Link to="/social" className="analysis-link">Social Intel &#x2197;</Link>
                </div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>People actively shopping for charcoal grill controllers — each signal is a potential customer or feature request.</p>
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
              <div className="venom-kpi-strip">
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Innovation Signals</div>
                  <div className="venom-kpi-value">{innovations.length}</div>
                  <div className="venom-kpi-sub">from market conversations</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Competitor Weaknesses</div>
                  <div className="venom-kpi-value">{competitorPains.length}</div>
                  <div className="venom-kpi-sub">pain points to exploit</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Trending Topics</div>
                  <div className="venom-kpi-value">{trendMomentum.length}</div>
                  <div className="venom-kpi-sub">cross-platform trends</div>
                </div>
                <div className="venom-kpi-card">
                  <div className="venom-kpi-label">Amazon BSR</div>
                  <div className="venom-kpi-value">
                    {marketIntel?.amazon_positioning?.bsr?.our_best_bsr ? `#${fmtInt(marketIntel.amazon_positioning.bsr.our_best_bsr)}` : '\u2014'}
                  </div>
                  <div className="venom-kpi-sub">best ranking</div>
                </div>
              </div>

              {/* Trend Momentum */}
              <section className="card">
                <div className="venom-panel-head"><strong>Industry Trend Momentum</strong></div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>Topics gaining traction across Reddit, YouTube, and Amazon. Cross-platform signals indicate real market shifts.</p>
                {trendMomentum.length > 0 ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
                    {trendMomentum.map((trend, i) => (
                      <div key={i} style={{ background: 'var(--panel-2)', borderRadius: 8, padding: '12px 16px', border: `1px solid ${trend.cross_platform ? 'var(--blue)' : 'var(--border)'}` }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                          <strong style={{ fontSize: 14 }}>{trend.topic}</strong>
                          {momentumBadge(trend.momentum)}
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--muted)' }}>{fmtInt(trend.mentions)} mentions · {fmtInt(trend.total_engagement)} engagement</div>
                        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                          {trend.platforms.map(p => <span key={p} className="badge badge-neutral" style={{ fontSize: 10 }}>{p}</span>)}
                          {trend.cross_platform && <span className="badge badge-good" style={{ fontSize: 10 }}>cross-platform</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <div className="state-message">No trend data yet. Social connectors will populate this.</div>}
              </section>

              {/* Innovation Signals */}
              <section className="card">
                <div className="venom-panel-head"><strong>Product Innovation Signals</strong><Link to="/social" className="analysis-link">Social Intel &#x2197;</Link></div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>Feature requests, DIY mods, and wishlist items from real users.</p>
                {innovations.length > 0 ? (
                  <div className="stack-list">
                    {innovations.slice(0, 10).map((post, i) => (
                      <a key={i} href={post.source_url} target="_blank" rel="noopener noreferrer" className="list-item status-muted" style={{ textDecoration: 'none', color: 'inherit' }}>
                        <div className="item-head">
                          <strong>{post.title || post.body?.slice(0, 100) || 'Untitled'}</strong>
                          <span className="badge badge-neutral">{post.platform}</span>
                        </div>
                        {post.body && <p style={{ fontSize: 12 }}>{post.body.slice(0, 200)}{post.body.length > 200 ? '...' : ''}</p>}
                      </a>
                    ))}
                  </div>
                ) : <div className="state-message">No innovation signals yet.</div>}
              </section>

              {/* Competitor Pain Points */}
              <section className="card">
                <div className="venom-panel-head"><strong>Competitor Pain Points</strong></div>
                <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>Complaints about competitor products — each is a differentiation opportunity.</p>
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
                        {post.body && <p style={{ fontSize: 12 }}>{post.body.slice(0, 200)}{post.body.length > 200 ? '...' : ''}</p>}
                      </a>
                    ))}
                  </div>
                ) : <div className="state-message">No competitor pain points yet.</div>}
              </section>

              {/* Competitive Landscape + Amazon */}
              {marketIntel?.competitive_landscape && (
                <div className="two-col two-col-equal">
                  <section className="card">
                    <div className="venom-panel-head"><strong>Competitive Share of Voice</strong></div>
                    {marketIntel.competitive_landscape.competitors.length > 0 ? (
                      <div className="chart-wrap-short">
                        <ResponsiveContainer width="100%" height={240}>
                          <BarChart data={[
                            { brand: 'Spider Grills', mentions: marketIntel.competitive_landscape.brand_mentions },
                            ...marketIntel.competitive_landscape.competitors.slice(0, 6).map(c => ({ brand: c.competitor, mentions: c.mentions }))
                          ]} layout="vertical">
                            <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                            <XAxis type="number" stroke="#9fb0d4" />
                            <YAxis type="category" dataKey="brand" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={100} />
                            <Tooltip />
                            <Bar dataKey="mentions" name="Mentions" radius={[0, 4, 4, 0]}>
                              {[marketIntel.competitive_landscape, ...marketIntel.competitive_landscape.competitors.slice(0, 6)].map((_, i) => <Cell key={i} fill={i === 0 ? '#4ade80' : CHART_COLORS[i % CHART_COLORS.length]} />)}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    ) : <div className="state-message">No competitor data yet.</div>}
                  </section>
                  <section className="card">
                    <div className="venom-panel-head"><strong>Amazon Market Position</strong></div>
                    {marketIntel.amazon_positioning ? (
                      <div className="venom-breakdown-list">
                        {marketIntel.amazon_positioning.bsr && (
                          <>
                            <div className="venom-breakdown-row"><span>Our Best BSR</span><span className="venom-breakdown-val">#{fmtInt(marketIntel.amazon_positioning.bsr.our_best_bsr)}</span></div>
                            <div className="venom-breakdown-row"><span>Competitor Best BSR</span><span className="venom-breakdown-val">#{fmtInt(marketIntel.amazon_positioning.bsr.competitor_best_bsr)}</span></div>
                            <div className="venom-breakdown-row"><span>Outranking</span><span className="venom-breakdown-val" style={{ color: marketIntel.amazon_positioning.bsr.outranking_competitors ? 'var(--green)' : 'var(--red)' }}>{marketIntel.amazon_positioning.bsr.outranking_competitors ? 'Yes' : 'No'}</span></div>
                          </>
                        )}
                        {marketIntel.amazon_positioning.price && (
                          <>
                            <div className="venom-breakdown-row"><span>Our Avg Price</span><span className="venom-breakdown-val">${marketIntel.amazon_positioning.price.our_avg_price.toFixed(2)}</span></div>
                            <div className="venom-breakdown-row"><span>Competitor Avg</span><span className="venom-breakdown-val">${marketIntel.amazon_positioning.price.competitor_avg_price.toFixed(2)}</span></div>
                            <div className="venom-breakdown-row"><span>Position</span><span className="venom-breakdown-val">{marketIntel.amazon_positioning.price.position}</span></div>
                          </>
                        )}
                      </div>
                    ) : <div className="state-message">Amazon data not available yet.</div>}
                  </section>
                </div>
              )}

              {/* Roadmap Input Summary */}
              <section className="card">
                <div className="venom-panel-head"><strong>Roadmap Input Summary</strong></div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Customer Support</div>
                    <strong style={{ fontSize: 20 }}>{productClusters.length}</strong><span style={{ fontSize: 13, color: 'var(--muted)' }}> issue clusters</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12 }}>
                      {productClusters.slice(0, 3).map((c, i) => <li key={i}>{c.title} ({c.severity})</li>)}
                      {productClusters.length === 0 && <li>No clusters</li>}
                    </ul>
                  </div>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Market Research</div>
                    <strong style={{ fontSize: 20 }}>{innovations.length}</strong><span style={{ fontSize: 13, color: 'var(--muted)' }}> innovation signals</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12 }}>
                      {innovations.slice(0, 3).map((p, i) => <li key={i}>{(p.title || p.body || '').slice(0, 60)}...</li>)}
                      {innovations.length === 0 && <li>No signals yet</li>}
                    </ul>
                  </div>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Competitors</div>
                    <strong style={{ fontSize: 20 }}>{competitorPains.length}</strong><span style={{ fontSize: 13, color: 'var(--muted)' }}> pain points</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12 }}>
                      {competitorPains.slice(0, 3).map((p, i) => <li key={i}>{p.competitor_mentioned || 'Competitor'}: {(p.title || p.body || '').slice(0, 50)}...</li>)}
                      {competitorPains.length === 0 && <li>No data yet</li>}
                    </ul>
                  </div>
                  <div style={{ background: 'var(--panel-2)', borderRadius: 8, padding: 16 }}>
                    <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>From Telemetry</div>
                    <strong style={{ fontSize: 20 }}>{issuePatterns.length}</strong><span style={{ fontSize: 13, color: 'var(--muted)' }}> detected patterns</span>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 12 }}>
                      {issuePatterns.slice(0, 3).map((p, i) => <li key={i}>{p.pattern.replace(/_/g, ' ')} ({p.severity})</li>)}
                      {issuePatterns.length === 0 && <li>No patterns</li>}
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
