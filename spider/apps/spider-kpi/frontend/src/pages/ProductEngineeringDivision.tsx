import { useEffect, useMemo, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge, type TruthState } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ProvenanceBanner } from '../components/ProvenanceBanner'
import { ClickUpComplianceCard } from '../components/ClickUpComplianceCard'
import { ClickUpOverlayChart } from '../components/ClickUpOverlayChart'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { ClickUpVelocityCard } from '../components/ClickUpVelocityCard'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { FirmwareCohortPanel } from '../components/FirmwareCohortPanel'
import { FirmwareImpactTimeline } from '../components/FirmwareImpactTimeline'
import { SlackPulseCard } from '../components/SlackPulseCard'
import { TempControlQualityPanel } from '../components/TempControlQualityPanel'
import { UniqueDeviceCohortPanel } from '../components/UniqueDeviceCohortPanel'
import { TelemetryReportCard } from '../components/TelemetryReportCard'
import { GaugeTile, MetricTile, StatusLight, TileGrid, openSectionById } from '../components/tiles'
import { ApiError, api } from '../lib/api'
import { addDays, fmtPct, fmtInt, fmtDecimal, fmtDuration, formatDateTimeET, formatFreshness, todayET } from '../lib/format'
import type { AppSideFleetResponse, ClusterTicketDetail, CookAnalysis, GithubIssuesResponse, IssueRadarResponse, MarketIntelligence, MarketPost, TelemetryHistoryDailyRow, TelemetrySummary, TrendMomentum, CXSnapshotResponse } from '../lib/types'
import {
  BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Line, Area, ComposedChart, PieChart, Pie, Cell, ReferenceLine,
} from 'recharts'

/* ------------------------------------------------------------------ */
/*  Analysis-derived benchmarks (from first comprehensive report)     */
/* ------------------------------------------------------------------ */
const BENCHMARKS = {
  COOK_SUCCESS_MEDIAN_PCT: 69,           // 68-70% across 26 months
  ERROR_RATE_HEALTHY_PCT: 1.3,           // ≤1.3% = healthy; 1.4-1.7% investigate; ≥1.8% incident
  ERROR_RATE_INCIDENT_PCT: 1.8,
  LOW_N_SESSION_FLOOR: 50,               // suppress daily cook_success when n < this
} as const

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

/** UTC offset for America/New_York on a representative "now" date.
 *  DST-correct: -4 during EDT (spring-summer), -5 during EST (fall-winter).
 *  We rebase peak_hour_distribution (which is keyed by UTC hour) into
 *  ET so "0:00" late-night cooks don't show up in the morning bucket. */
function _etOffsetHours(): number {
  // Compute current ET offset by taking a UTC midnight and asking what
  // hour it is in NY. The difference is the offset.
  const nowUtc = new Date()
  const etFormatter = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour12: false, hour: '2-digit', year: 'numeric', month: '2-digit', day: '2-digit' })
  const parts = etFormatter.formatToParts(nowUtc)
  const etHour = Number(parts.find(p => p.type === 'hour')?.value ?? '0')
  const utcHour = nowUtc.getUTCHours()
  let delta = etHour - utcHour
  if (delta > 12) delta -= 24
  if (delta < -12) delta += 24
  return delta
}

function buildPeakHours(historyRows: TelemetryHistoryDailyRow[]) {
  const offset = _etOffsetHours()  // e.g. -4 during EDT
  const etTotals: Record<number, number> = {}
  for (const row of historyRows) {
    for (const [hour, count] of Object.entries(row.peak_hour_distribution || {})) {
      const utcH = Number(hour)
      if (!Number.isFinite(utcH)) continue
      const etH = (utcH + offset + 24) % 24
      etTotals[etH] = (etTotals[etH] || 0) + (count as number)
    }
  }
  return Array.from({ length: 24 }, (_, i) => ({ hour: `${String(i).padStart(2, '0')}:00 ET`, events: etTotals[i] || 0 }))
}

function buildModelBreakdown(historyRows: TelemetryHistoryDailyRow[]) {
  const totals: Record<string, number> = {}
  for (const row of historyRows) {
    for (const [model, count] of Object.entries(row.model_distribution || {})) {
      totals[model] = (totals[model] || 0) + (count as number)
    }
  }
  const raw = Object.entries(totals).sort(([, a], [, b]) => b - a).slice(0, 8).map(([model, events]) => ({ model, events }))
  return mergeModelData(raw)
}

/** Daily per-model event counts, shaped for a Recharts stacked Area.
 *  Each row has {date, total, <displayModelName>: N, ...}. Only keeps
 *  the top-6 models by total events across the window. */
function buildModelStackedSeries(historyRows: TelemetryHistoryDailyRow[]): { rows: Array<Record<string, number | string>>; keys: string[] } {
  if (!historyRows.length) return { rows: [], keys: [] }
  const totals: Record<string, number> = {}
  for (const row of historyRows) {
    for (const [raw, count] of Object.entries(row.model_distribution || {})) {
      const name = displayModelName(raw)
      totals[name] = (totals[name] || 0) + (count as number)
    }
  }
  const keys = Object.entries(totals)
    .filter(([, v]) => v > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6)
    .map(([k]) => k)
  const rows = historyRows.map(row => {
    const perModel: Record<string, number> = {}
    for (const [raw, count] of Object.entries(row.model_distribution || {})) {
      const name = displayModelName(raw)
      if (!keys.includes(name)) continue
      perModel[name] = (perModel[name] || 0) + (count as number)
    }
    return {
      date: row.business_date.slice(5),
      business_date: row.business_date,
      total: row.total_events,
      ...Object.fromEntries(keys.map(k => [k, perModel[k] || 0])),
    }
  })
  return { rows, keys }
}

function buildFirmwareBreakdown(historyRows: TelemetryHistoryDailyRow[]) {
  const totals: Record<string, number> = {}
  for (const row of historyRows) {
    for (const [fw, count] of Object.entries(row.firmware_distribution || {})) {
      totals[fw] = (totals[fw] || 0) + (count as number)
    }
  }
  return Object.entries(totals).sort(([, a], [, b]) => b - a).slice(0, 8).map(([firmware, events]) => ({ firmware, events }))
}

function avgWeighted(historyRows: TelemetryHistoryDailyRow[], valueKey: 'avg_rssi' | 'avg_cook_temp', weightKey: 'total_events' = 'total_events'): number | null {
  let weightedSum = 0
  let weightTotal = 0
  for (const row of historyRows) {
    const v = row[valueKey] as number | null | undefined
    const w = (row[weightKey] as number | undefined) || 0
    if (v != null && w > 0) {
      weightedSum += v * w
      weightTotal += w
    }
  }
  return weightTotal > 0 ? weightedSum / weightTotal : null
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
  const [appSide, setAppSide] = useState<AppSideFleetResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Date range — defaults to last 30 days
  const [dateStart, setDateStart] = useState(() => {
    return addDays(todayET(), -30)
  })
  const [dateEnd, setDateEnd] = useState(() => todayET())
  const [showDatePicker, setShowDatePicker] = useState(false)

  // Cluster drill-down state
  const [clusterDetail, setClusterDetail] = useState<ClusterTicketDetail | null>(null)
  const [clusterDetailLoading, setClusterDetailLoading] = useState(false)

  const daysDiff = useMemo(() => {
    const start = new Date(dateStart).getTime()
    const end = new Date(dateEnd).getTime()
    return Math.max(1, Math.ceil((end - start) / (1000 * 60 * 60 * 24)))
  }, [dateStart, dateEnd])

  // Pre-materialized cook analysis (separate fetch — instant from daily table)
  const [cookData, setCookData] = useState<Record<string, any> | null>(null)

  useEffect(() => {
    let cancelled = false
    api.cookAnalysis(dateStart, dateEnd)
      .then(data => { if (!cancelled) setCookData(data) })
      .catch(() => { if (!cancelled) setCookData(null) })
    return () => { cancelled = true }
  }, [dateStart, dateEnd])

  // Cook outcomes summary (the 2026-04-18 intent/outcome/PID-quality
  // model). Held-target rate + in-control % drive the new hero gauges.
  // Falls back to legacy metrics when the re-derivation hasn't populated
  // yet (totals.held_target_rate === null).
  const [cookOutcomes, setCookOutcomes] = useState<Record<string, any> | null>(null)
  useEffect(() => {
    let cancelled = false
    api.cookOutcomesSummary(daysDiff)
      .then(data => { if (!cancelled) setCookOutcomes(data) })
      .catch(() => { if (!cancelled) setCookOutcomes(null) })
    return () => { cancelled = true }
  }, [daysDiff])

  // Cook duration + unique-device cohort stats. Drives:
  //   - Avg/Median cook time tiles (replaces old Avg Cook Temp)
  //   - Unique devices in range + sessions-per-device histogram panel
  //     (the '13k Venoms in the world, are we seeing 100 users or a
  //     broad cohort?' question)
  const [cookDuration, setCookDuration] = useState<Record<string, any> | null>(null)
  useEffect(() => {
    let cancelled = false
    api.cookDurationStats(daysDiff)
      .then(data => { if (!cancelled) setCookDuration(data) })
      .catch(() => { if (!cancelled) setCookDuration(null) })
    return () => { cancelled = true }
  }, [daysDiff])

  // CX-derived probe-failure rate. Replaces the misleading
  // telemetry-shadow "probe error" signal: the shadow fires whenever
  // a probe reading is missing (user never installed a meat probe =
  // valid use case, no pit probe = setup issue), while CX tickets
  // capture actual hardware failures ("my probe stopped working,
  // need a replacement").
  const [probeFailure, setProbeFailure] = useState<Record<string, any> | null>(null)
  useEffect(() => {
    let cancelled = false
    api.probeFailureRate(Math.max(daysDiff, 30))
      .then(data => { if (!cancelled) setProbeFailure(data) })
      .catch(() => { if (!cancelled) setProbeFailure(null) })
    return () => { cancelled = true }
  }, [daysDiff])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [telData, issuesData, radarData, miData, cxData, appSideData] = await Promise.all([
          api.telemetrySummary(daysDiff, undefined, dateStart, dateEnd),
          api.engineeringIssues().catch(() => null),
          api.issues().catch(() => null),
          api.marketIntelligence(30).catch(() => null),
          api.cxSnapshot().catch(() => null),
          api.appSideFleet(daysDiff, undefined, dateStart, dateEnd).catch(() => null),
        ])
        if (!cancelled) {
          setTelemetry(telData)
          setGithubIssues(issuesData)
          setIssueRadar(radarData)
          setMarketIntel(miData)
          setCxSnapshot(cxData)
          setAppSide(appSideData)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load product data')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [daysDiff, dateStart, dateEnd])

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
  const cookAnalysis = cookData as { total_sessions: number; cook_styles: Record<string, number>; style_details: Record<string, any>; temp_ranges: Record<string, number>; duration_ranges: Record<string, number>; monthly_breakdown?: { month: string; sessions: number; active_devices: number }[]; fleet_total_unique_devices?: number } | null
  const confidence = telemetry?.confidence || null

  const streamBacked = collection?.sample_source === 'dynamodb_stream'
  const isHistoricalOnly = collection?.data_scope === 'historical_daily'

  // Staleness: warn if newest sample is > 1 hour old
  const newestSample = collection?.newest_sample_timestamp_seen
  const staleMins = newestSample ? Math.floor((Date.now() - new Date(newestSample).getTime()) / 60000) : null
  const isStale = staleMins !== null && staleMins > 60

  // Truncation: warn if DynamoDB scan was bounded
  const scanTruncated = collection?.scan_truncated === true
  const capHit = collection?.max_record_cap_hit === true

  // Compute a cookAnalysis-derived stability score (weighted by style session count)
  const cookStabilityScore = useMemo(() => {
    const details = cookAnalysis?.style_details
    if (!details) return null
    let weightSum = 0, weightN = 0
    for (const d of Object.values(details) as any[]) {
      const c = d?.count || 0
      const s = d?.avg_stability_score
      if (c > 0 && s != null) { weightSum += s * c; weightN += c }
    }
    return weightN > 0 ? weightSum / weightN : null
  }, [cookAnalysis])

  // NOTE: rangedHistory + historyStats are declared *before* the derived
  // metrics below because the derived metrics read historyStats?.*. Using a
  // `const` before its declaration triggers a temporal-dead-zone ReferenceError
  // at render time (surfaces in prod minified builds as "Cannot access 't'
  // before initialization").
  const rangedHistory = useMemo(() => {
    if (!historyDaily.length) return []
    const start = new Date(dateStart).getTime()
    const end = new Date(dateEnd).getTime()
    return historyDaily.filter(row => {
      const t = new Date(row.business_date).getTime()
      return t >= start && t <= end
    })
  }, [historyDaily, dateStart, dateEnd])

  // Exclude today's partial-rollup row from the fleet chart. Today's
  // row in telemetry_history_daily is populated once at 4am ET by the
  // nightly materializer using only the ~4 hours accumulated since
  // midnight ET — it never updates during the day, so it always looks
  // like a massive cliff (e.g. 172 yesterday → 21 today at 1pm). The
  // banner below exposes the real "today" number from the live stream.
  const fleetChartRows = useMemo(() => rangedHistory
    .filter(row => row.business_date !== todayET())
    .map((row) => ({
      date: row.business_date.slice(5),
      active_devices: row.active_devices,
      engaged_devices: row.engaged_devices,
      error_rate: row.total_events > 0 ? Math.round((row.error_events / row.total_events) * 10000) / 100 : 0,
    })), [rangedHistory])

  const peakHourData = useMemo(() => buildPeakHours(rangedHistory), [rangedHistory])
  const modelData = useMemo(() => buildModelBreakdown(rangedHistory), [rangedHistory])
  const firmwareData = useMemo(() => buildFirmwareBreakdown(rangedHistory), [rangedHistory])
  const modelStacked = useMemo(() => buildModelStackedSeries(rangedHistory), [rangedHistory])

  // Partial-day detection: the last row in the window is "partial" if its
  // business_date equals today in ET. We don't yet have all of today's
  // telemetry, so it can mislead trends (e.g. showing 11 active devices
  // at noon when yesterday saw 458).
  const partialLatest = useMemo(() => {
    if (!rangedHistory.length) return null
    const last = rangedHistory[rangedHistory.length - 1]
    return last.business_date === todayET() ? last : null
  }, [rangedHistory])

  const historyStats = useMemo(() => {
    if (!rangedHistory.length) return null
    const avgDevices = rangedHistory.reduce((s, r) => s + r.active_devices, 0) / rangedHistory.length
    const avgEngaged = rangedHistory.reduce((s, r) => s + r.engaged_devices, 0) / rangedHistory.length
    const totalErrors = rangedHistory.reduce((s, r) => s + r.error_events, 0)
    const totalEvents = rangedHistory.reduce((s, r) => s + r.total_events, 0)
    const totalSessions = rangedHistory.reduce((s, r) => s + (r.session_count || 0), 0)
    const totalSuccessful = rangedHistory.reduce((s, r) => s + (r.successful_sessions || 0), 0)
    const peakDay = rangedHistory.reduce((best, r) => r.active_devices > (best?.active_devices || 0) ? r : best, rangedHistory[0])
    const historicalRssi = avgWeighted(rangedHistory, 'avg_rssi')
    const historicalCookTemp = avgWeighted(rangedHistory, 'avg_cook_temp')
    return {
      avgDevices, avgEngaged, totalErrors, totalEvents, totalSessions, totalSuccessful,
      errorRate: totalEvents > 0 ? totalErrors / totalEvents : 0,
      sessionSuccessRate: totalSessions > 0 ? totalSuccessful / totalSessions : null,
      peakDay, historicalRssi, historicalCookTemp,
      daysWithSessions: rangedHistory.filter(r => (r.session_count || 0) > 0).length,
    }
  }, [rangedHistory])

  // Range-first metrics: prefer values derived from the user's selected range
  // (historyStats + cookAnalysis), falling back to stream-backed values only
  // when the daily rollups don't have the field.
  const sampleSize = historyStats?.totalSessions || Math.max(telemetry?.slice_snapshot?.sessions_derived || 0, collection?.distinct_devices_observed || 0)

  const activeCooks = isHistoricalOnly
    ? Math.round(historyStats?.avgEngaged ?? 0)
    : (derived?.active_cooks_now ?? collection?.active_devices_last_15m ?? 0)
  const devicesReporting = isHistoricalOnly
    ? Math.round(historyStats?.avgDevices ?? 0)
    : (derived?.devices_reporting_last_5m ?? collection?.active_devices_last_5m ?? 0)
  const successRate = historyStats?.sessionSuccessRate ?? derived?.session_success_rate ?? null
  const disconnectRate = derived?.disconnect_proxy_rate ?? null
  const stabilityScore = cookStabilityScore ?? derived?.stability_score ?? null
  const overshootRate = derived?.overshoot_rate ?? null
  const p50Stabilize = derived?.time_to_stabilize_p50_seconds ?? null
  const p95Stabilize = derived?.time_to_stabilize_p95_seconds ?? null
  const medianCookDuration = derived?.median_cook_duration_seconds ?? null
  const p95CookDuration = derived?.p95_cook_duration_seconds ?? null
  const medianRssi = historyStats?.historicalRssi ?? derived?.median_rssi_now ?? null
  // CX-derived probe failure rate (real hardware failures from tickets).
  // The legacy `analytics.probe_failure_rate` was misleading — it counted
  // any session where a probe reading was missing, including users who
  // intentionally don't install meat probes. Kept only as a comparison
  // reference, not as the headline number.
  const probeFailureCount = probeFailure?.probe_failure_count ?? null
  const probeActiveDevices = probeFailure?.active_devices_in_window ?? 0
  const probeInstalledBase = probeFailure?.installed_base_venoms ?? 13000
  const probeWindowDays = probeFailure?.window_days ?? 0
  const probeRatePer1kActive = probeFailure?.rate_per_1000_active_30d ?? null
  const probeAnnualizedProjected = probeFailure?.annualized_failures_projected ?? null
  const probeAnnualizedRateOfBase = probeFailure?.annualized_rate_per_installed_base ?? null
  const legacyShadowProbeRate = analytics?.probe_failure_rate ?? null
  const devices24h = isHistoricalOnly
    ? Math.round(historyStats?.avgDevices ?? 0)
    : (collection?.active_devices_last_24h ?? 0)
  const devices60m = isHistoricalOnly ? 0 : (collection?.active_devices_last_60m ?? 0)

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

      {/* AI-written telemetry analysis — comprehensive baseline + future monthly reports */}
      <TelemetryReportCard reportType="comprehensive" />

      {loading ? <Card title="Product Hub"><div className="state-message">Loading product data...</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <ProvenanceBanner
            compact
            truthState={streamBacked ? 'canonical' : (rangedHistory.length > 0 ? 'estimated' : 'degraded')}
            lastUpdated={collection?.newest_sample_timestamp_seen}
            scope={`${dateStart} to ${dateEnd} (${daysDiff}d) · ${fmtInt(rangedHistory.length)} daily rows · ${fmtInt(historyStats?.totalSessions || sampleSize)} sessions`}
            caveat={isHistoricalOnly ? 'Historical view — metrics derived from daily rollups. Event-level details (disconnect rate, probe errors, stabilization percentiles) require the live stream window.' : undefined}
          />

          {collection?.data_scope === 'historical_daily' && (
            <div className="scope-note" style={{ fontSize: 12, color: 'var(--blue)', padding: '8px 12px', background: 'rgba(110,168,255,0.08)', border: '1px solid rgba(110,168,255,0.2)', borderRadius: 6, marginBottom: 8 }}>
              Historical view ({dateStart} to {dateEnd}) — fleet activity, cook styles, firmware / model mix, RSSI, and cook temperatures are rebuilt from daily rollups. Event-level detail (top error codes, issue patterns, per-session stability percentiles) only exists for the live 7-day stream retention window.
            </div>
          )}

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

          {/* Intelligence Briefing — signal-per-row chips, icon-prefixed,
              severity-colored left border. More scannable than text bullets. */}
          <section className="card" style={{ padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <strong style={{ fontSize: 13 }}>Product intelligence briefing</strong>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                {productInsights.length} signal{productInsights.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              {productInsights.map((insight, i) => {
                const sevColor =
                  insight.severity === 'good' ? '#22c55e'
                  : insight.severity === 'warn' ? '#f59e0b'
                  : insight.severity === 'bad' ? '#ef4444'
                  : '#9ca3af'
                const sevBg =
                  insight.severity === 'good' ? 'rgba(34,197,94,0.08)'
                  : insight.severity === 'warn' ? 'rgba(245,158,11,0.08)'
                  : insight.severity === 'bad' ? 'rgba(239,68,68,0.08)'
                  : 'rgba(255,255,255,0.03)'
                return (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      gap: 12,
                      padding: '8px 12px',
                      background: sevBg,
                      borderLeft: `3px solid ${sevColor}`,
                      borderRadius: 6,
                      alignItems: 'flex-start',
                    }}
                  >
                    <span style={{ fontSize: 18, lineHeight: 1.2, flexShrink: 0 }}>{insight.icon}</span>
                    <span style={{ fontSize: 12.5, lineHeight: 1.45, flex: 1 }}>{insight.text}</span>
                  </div>
                )
              })}
            </div>
          </section>

          {/* ============================================================ */}
          {/*  VIEW 1: FLEET HEALTH                                        */}
          {/* ============================================================ */}
          {view === 'fleet' && (
            <>
              <TruthLegend />

              {/* Visual gauge dashboard — glanceable fleet health.
                  Benchmarks: cook success 69% median (28-month baseline),
                  error rate ≤1.3% healthy / ≥1.8% incident. */}
              <section className="card" style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
                  <strong style={{ fontSize: 13 }}>Fleet gauges</strong>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                    {isHistoricalOnly ? `historical window · ${rangedHistory.length} days` : 'live telemetry window'}
                  </span>
                </div>
                <TileGrid cols={4}>
                  <MetricTile
                    label={isHistoricalOnly ? 'Avg engaged devices' : 'Active cooks'}
                    value={fmtInt(activeCooks)}
                    sublabel={isHistoricalOnly
                      ? `avg/day across ${rangedHistory.length}d`
                      : `${fmtInt(devicesReporting)} devices reporting (5m)`}
                    state={activeCooks > 0 ? 'info' : 'neutral'}
                    icon="🍖"
                    sparkline={rangedHistory.map(r => r.engaged_devices).slice(-30)}
                    onClick={() => openSectionById('pe-fleet-cook-patterns')}
                  />
                  {/* Held-target rate — excludes startup_assist sessions
                      from the denominator so the metric doesn't penalize
                      the device for doing what the user asked (quick
                      fire-start then manual). Falls back to legacy
                      cook_success_rate when the re-derivation hasn't
                      populated the new columns yet. */}
                  {(() => {
                    const newRate = cookOutcomes?.totals?.held_target_rate as number | null | undefined
                    const seeking = cookOutcomes?.totals?.target_seeking_count as number | undefined
                    const usingNew = newRate != null
                    const val = usingNew ? newRate : (successRate ?? 0)
                    return (
                      <GaugeTile
                        label={usingNew ? 'Held-target rate' : 'Cook success rate (legacy)'}
                        value={val}
                        display={val != null ? fmtPct(val) : '—'}
                        sublabel={
                          usingNew
                            ? `${fmtInt(cookOutcomes?.totals?.held_count || 0)} / ${fmtInt(seeking || 0)} target-seeking cooks · startup-assist excluded`
                            : historyStats?.daysWithSessions
                              ? `${fmtInt(historyStats.totalSessions)} sessions · ${historyStats.daysWithSessions}d · pending new-model re-derivation`
                              : `n=${fmtInt(sampleSize)} · pending new-model re-derivation`
                        }
                        bandsAsc={{ bad: 0.60, warn: 0.75 }}
                        onClick={() => openSectionById('pe-fleet-cook-patterns')}
                      />
                    )
                  })()}
                  {/* PID quality — in-control % during post-reach,
                      non-disturbance windows only. Lid-opens don't
                      penalize the device. */}
                  {(() => {
                    const inControl = cookOutcomes?.totals?.avg_in_control_pct as number | null | undefined
                    const usingNew = inControl != null
                    const val = usingNew ? inControl : (stabilityScore ?? 0)
                    return (
                      <GaugeTile
                        label={usingNew ? 'PID quality (in-control %)' : 'Temp stability (legacy)'}
                        value={val}
                        display={usingNew ? fmtPct(val) : fmtDecimal(val)}
                        sublabel={
                          usingNew
                            ? 'post-reach samples within ±15°F · lid-open windows excluded'
                            : 'legacy 0-1 score · pending new-model re-derivation'
                        }
                        bandsAsc={{ bad: 0.50, warn: 0.70 }}
                        onClick={() => openSectionById('pe-fleet-cook-patterns')}
                      />
                    )
                  })()}
                  <MetricTile
                    label="Error rate"
                    value={historyStats ? fmtPct(historyStats.errorRate) : '—'}
                    sublabel={historyStats
                      ? `${fmtInt(historyStats.totalErrors)} / ${fmtInt(historyStats.totalEvents)} events`
                      : 'no data in range'}
                    state={
                      !historyStats ? 'neutral'
                      : historyStats.errorRate >= 0.018 ? 'bad'
                      : historyStats.errorRate >= 0.013 ? 'warn'
                      : 'good'
                    }
                    icon="⚠"
                    onClick={() => openSectionById('pe-fleet-cook-patterns')}
                  />
                </TileGrid>
              </section>

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
                        {/* Benchmark lines derived from the 28-month analysis. */}
                        <ReferenceLine yAxisId="right" y={BENCHMARKS.ERROR_RATE_HEALTHY_PCT} stroke="rgba(239,68,68,0.35)" strokeDasharray="2 4" label={{ value: `≤${BENCHMARKS.ERROR_RATE_HEALTHY_PCT}% healthy`, position: 'insideTopRight', fill: 'rgba(239,68,68,0.7)', fontSize: 10 }} />
                        <ReferenceLine yAxisId="right" y={BENCHMARKS.ERROR_RATE_INCIDENT_PCT} stroke="rgba(239,68,68,0.55)" strokeDasharray="2 4" label={{ value: `≥${BENCHMARKS.ERROR_RATE_INCIDENT_PCT}% incident`, position: 'insideBottomRight', fill: 'rgba(239,68,68,0.8)', fontSize: 10 }} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : <div className="state-message">No historical daily data available for this date range. Run the S3 import to populate fleet history.</div>}
                {partialLatest && (
                  <div style={{ marginTop: 6, padding: '6px 10px', fontSize: 11, color: 'var(--muted)', background: 'rgba(245,158,11,0.08)', borderLeft: '3px solid var(--orange)', borderRadius: 4 }}>
                    <strong style={{ color: 'var(--orange)' }}>Today ({partialLatest.business_date}) excluded from chart.</strong>{' '}
                    The daily rollup materializes once at 4am ET, so today's row reflects only the overnight hours ({fmtInt(partialLatest.active_devices)} device{partialLatest.active_devices === 1 ? '' : 's'} rolled up). Live stream shows <strong>{fmtInt(collection?.active_devices_last_24h ?? 0)}</strong> active in the last 24h and <strong>{fmtInt(collection?.active_devices_last_15m ?? 0)}</strong> cooking right now — today's bar will fill in tomorrow morning.
                  </div>
                )}
                {historyStats ? (
                  <div className="venom-kpi-strip" style={{ marginTop: 12 }}>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Unique Devices (avg/day)</div>
                      <div className="venom-kpi-value">{fmtInt(Math.round(historyStats.avgDevices))}</div>
                      <div className="venom-kpi-sub">
                        peak: {historyStats.peakDay ? fmtInt(historyStats.peakDay.active_devices) : '\u2014'} on {historyStats.peakDay?.business_date ?? '\u2014'}
                      </div>
                      <div className="venom-kpi-badges"><TruthBadge state="canonical" /></div>
                    </div>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Total Device-Days</div>
                      <div className="venom-kpi-value">{fmtInt(rangedHistory.reduce((s, r) => s + r.active_devices, 0))}</div>
                      <div className="venom-kpi-sub">
                        {fmtInt(rangedHistory.reduce((s, r) => s + r.engaged_devices, 0))} engaged device-days ({rangedHistory.length}d)
                      </div>
                      <div className="venom-kpi-badges"><TruthBadge state="canonical" /></div>
                    </div>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Avg WiFi Signal</div>
                      <div className="venom-kpi-value">
                        {historyStats.historicalRssi != null ? `${historyStats.historicalRssi.toFixed(1)} dBm` : '\u2014'}
                      </div>
                      <div className="venom-kpi-sub">
                        {historyStats.historicalRssi != null && historyStats.historicalRssi < -75
                          ? 'Weak \u2014 outdoor placement far from router'
                          : historyStats.historicalRssi != null && historyStats.historicalRssi < -65
                            ? 'Fair signal'
                            : historyStats.historicalRssi != null ? 'Strong signal' : 'no RSSI data in range'}
                      </div>
                      <div className="venom-kpi-badges"><TruthBadge state="canonical" /></div>
                    </div>
                    {/* Avg Cook Time — replaces Avg Cook Temp. Pulls from
                        /cook-duration-stats which prefers telemetry_sessions
                        but falls back to weighted per-style aggregates from
                        the daily rollups when sessions haven't been
                        backfilled yet. */}
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Avg Cook Time</div>
                      <div className="venom-kpi-value">
                        {cookDuration?.avg_duration_seconds != null
                          ? fmtDuration(cookDuration.avg_duration_seconds)
                          : '\u2014'}
                      </div>
                      <div className="venom-kpi-sub">
                        {cookDuration?.source === 'telemetry_sessions'
                          ? `${fmtInt(cookDuration.total_sessions || 0)} sessions`
                          : cookDuration
                            ? 'weighted from daily rollups · sessions pending backfill'
                            : 'loading…'}
                      </div>
                      <div className="venom-kpi-badges">
                        <TruthBadge state={cookDuration?.source === 'telemetry_sessions' ? 'canonical' : 'estimated'} />
                      </div>
                    </div>
                    {/* Median Cook Time — new tile alongside Avg. */}
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Median Cook Time</div>
                      <div className="venom-kpi-value">
                        {cookDuration?.median_duration_seconds != null
                          ? fmtDuration(cookDuration.median_duration_seconds)
                          : '\u2014'}
                      </div>
                      <div className="venom-kpi-sub">
                        {cookDuration?.source === 'telemetry_sessions'
                          ? `p50 · ${cookDuration.p90_duration_seconds != null ? `p90 ${fmtDuration(cookDuration.p90_duration_seconds)}` : ''}`
                          : cookDuration?.median_is_estimate
                            ? 'bucket-interpolated estimate · refines after backfill'
                            : ''}
                      </div>
                      <div className="venom-kpi-badges">
                        <TruthBadge state={cookDuration?.source === 'telemetry_sessions' ? 'canonical' : 'estimated'} />
                      </div>
                    </div>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Total Events</div>
                      <div className="venom-kpi-value">{fmtInt(historyStats.totalEvents)}</div>
                      <div className="venom-kpi-sub">{fmtInt(historyStats.totalErrors)} errors \u00b7 {fmtPct(historyStats.errorRate)} rate</div>
                      <div className="venom-kpi-badges"><TruthBadge state="canonical" /></div>
                    </div>
                  </div>
                ) : null}

                {/* Unique-device cohort panel — 'are we seeing the same
                    100 people cook over and over, or is the active user
                    base broad?' Answers: count of distinct Venoms active
                    in the selected window + histogram of sessions-per-
                    device. Lights up fully once telemetry_sessions
                    populates; falls back to a 9-day stream-events count
                    in the meantime. */}
                {cookDuration && (
                  <UniqueDeviceCohortPanel stats={cookDuration} />
                )}
              </section>

              {/* Model Mix Over Time — surfaces the Huntsman ramp that was
                  invisible on the active-devices chart (report finding #3).
                  NOT stacked: each model is its own translucent area so
                  smaller lines are still visible when they overlap the
                  bigger ones. Render order: largest model first (in the
                  back), smaller models on top so they never get hidden. */}
              {modelStacked.rows.length > 0 && modelStacked.keys.length > 1 && (
                <section className="card">
                  <div className="venom-panel-head">
                    <div>
                      <strong>Fleet Composition — Daily Events by Model</strong>
                      <p className="venom-chart-sub">Per-model event volume across the selected range. Overlayed (not stacked) so small-share models stay visible — smaller models render on top with translucent fill.</p>
                    </div>
                    <span className="venom-panel-hint">{modelStacked.keys.length} models shown</span>
                  </div>
                  <div className="chart-wrap">
                    <ResponsiveContainer width="100%" height={300}>
                      <ComposedChart data={modelStacked.rows}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                        <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 11 }} />
                        <YAxis stroke="#9fb0d4" tickFormatter={(v: number) => v >= 1_000_000 ? `${(v/1_000_000).toFixed(1)}M` : v >= 1_000 ? `${(v/1_000).toFixed(0)}k` : String(v)} />
                        <Tooltip formatter={(v: number) => v.toLocaleString()} />
                        <Legend />
                        {/* Render largest-total first so small models paint on top
                            and remain visible through the big model's translucent
                            fill. `modelStacked.keys` is already sorted descending
                            by cumulative event volume (from buildModelStackedSeries). */}
                        {modelStacked.keys.map((name, i) => (
                          <Area
                            key={name}
                            type="monotone"
                            dataKey={name}
                            name={name}
                            fill={CHART_COLORS[i % CHART_COLORS.length]}
                            stroke={CHART_COLORS[i % CHART_COLORS.length]}
                            fillOpacity={0.30}
                            strokeWidth={2}
                            dot={false}
                            activeDot={{ r: 3 }}
                          />
                        ))}
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                  <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>
                    Derived from <code>telemetry_history_daily.model_distribution</code>. Kettle22 / W:K:22:1:V / kettle_22 are merged under one display name.
                    Areas are overlayed with 30% fill — legend toggle lets you isolate a single model.
                  </p>
                </section>
              )}

              {/* Firmware cohort performance — uses held-target rate +
                  in-control % once the re-derivation populates the new
                  columns; falls back to legacy success rate in the
                  meantime. */}
              <FirmwareCohortPanel minSessions={20} />

              {/* Firmware-over-time impact — did shipping 01.01.97 actually
                  improve PID quality vs 01.01.94? Segmented line chart
                  colored by dominant firmware each week, with ClickUp
                  firmware-release markers overlaid. */}
              <FirmwareImpactTimeline weeks={26} />

              {/* ========================================================= */}
              {/* BELOW-THE-FOLD DETAIL — progressive disclosure.           */}
              {/* Everything from here through the voice/roadmap sections   */}
              {/* lives behind a single click. Expandable collapsible       */}
              {/* sections so the top of the page stays digestible while    */}
              {/* every card remains one keystroke away.                    */}
              {/* ========================================================= */}

              <CollapsibleSection
                id="pe-fleet-cook-patterns"
                title="Cook patterns & device behavior"
                subtitle="How customers actually use Venom: cook styles, temperature control, connectivity, peak hours, model mix, firmware, error codes"
                accentColor="#6ea8ff"
              >
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

              {/* NEW (2026-04-18): Temp Control Quality redesigned around
                  the intent/outcome/PID-quality model. Falls back to a
                  'pending re-derivation' banner until the new columns
                  are populated. */}
              <TempControlQualityPanel days={Math.max(daysDiff, 7)} />

              {/* Connectivity & Reliability — kept compact; these are
                  infrastructure-level (WiFi signal, disconnects, probe
                  health) rather than PID-level, so it stays as a separate
                  card. Legacy session_success shown as 'legacy metric' for
                  compat. Grill-type health retained as a sub-table. */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Connectivity &amp; reliability</strong>
                  <Link to="/issues" className="analysis-link">View issues &#x2197;</Link>
                </div>
                <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                  Infrastructure-level reliability — WiFi signal, disconnects, probe hardware. Orthogonal to PID-quality
                  (above); a session can be connectively healthy but have poor PID-quality, and vice versa.
                </p>
                <div className="venom-breakdown-list">
                  <div className="venom-breakdown-row"><span>Session success (legacy)</span><span className="venom-breakdown-val">{fmtPct(successRate)}</span><TruthBadge state={(confidence?.cook_success as TruthState) || 'estimated'} /></div>
                  <div className="venom-breakdown-row"><span>Disconnect rate</span><span className="venom-breakdown-val">{fmtPct(disconnectRate)}</span><TruthBadge state={(confidence?.disconnect_detection as TruthState) || 'proxy'} /></div>
                  <div className="venom-breakdown-row">
                    <span>Probe failures (CX tickets, {probeWindowDays || '—'}d)</span>
                    <span className="venom-breakdown-val">{probeFailureCount != null ? fmtInt(probeFailureCount) : '—'}</span>
                    <TruthBadge state="canonical" />
                  </div>
                  <div className="venom-breakdown-row">
                    <span>Failure rate /1k active (30d)</span>
                    <span className="venom-breakdown-val">{probeRatePer1kActive != null ? probeRatePer1kActive.toFixed(2) : '—'}</span>
                  </div>
                  <div className="venom-breakdown-row">
                    <span>Annualized /installed base</span>
                    <span className="venom-breakdown-val">{probeAnnualizedRateOfBase != null ? `${(probeAnnualizedRateOfBase * 100).toFixed(2)}%` : '—'}</span>
                  </div>
                  <div className="venom-breakdown-row"><span>Avg RSSI</span><span className="venom-breakdown-val">{medianRssi != null ? `${typeof medianRssi === 'number' ? medianRssi.toFixed(1) : medianRssi} dBm` : '\u2014'}</span></div>
                  {historyStats && (
                    <div className="venom-breakdown-row"><span>Event error rate</span><span className="venom-breakdown-val">{fmtPct(historyStats.errorRate)}</span><TruthBadge state="canonical" /></div>
                  )}
                </div>
                <small className="venom-panel-footer">
                  Probe failure rate is CX-derived — tickets where a customer reported their probe broke or needs replacement, classified via keyword/tag match. Normalized against {fmtInt(probeActiveDevices)} active devices seen this window (installed base ≈ {fmtInt(probeInstalledBase)}).
                  {probeAnnualizedProjected != null && ` At the current rate, ~${fmtInt(probeAnnualizedProjected)} probe-failure tickets/yr would be expected.`}
                  {legacyShadowProbeRate != null && ` Legacy telemetry-shadow signal was ${fmtPct(legacyShadowProbeRate)} — retained only for reference; it conflates hardware failures with users who never installed a meat probe.`}
                  {historyStats?.daysWithSessions
                    ? ` Based on ${fmtInt(historyStats.totalSessions)} sessions over ${historyStats.daysWithSessions} days in the selected range.`
                    : ` Disconnect rate = sessions where a >45-minute gap was detected. n=${fmtInt(sampleSize)} sessions.`}
                </small>
                {grillTypeHealth.length > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div className="venom-breakdown-label">By grill type</div>
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

              </CollapsibleSection>

              <CollapsibleSection
                id="pe-app-side-fleet"
                title="App-side fleet"
                subtitle="Freshdesk-derived app user + device stats; app backend integration pending"
                accentColor="#4ade80"
              >
              {/* App-side fleet — Freshdesk-derived today, app backend pending */}
              <section className="card">
                <div className="venom-panel-head">
                  <strong>App-side fleet</strong>
                  <span className="venom-panel-hint">
                    {appSide?.latest_observed_at
                      ? `Latest observation · ${formatFreshness(appSide.latest_observed_at)}`
                      : 'No observations yet'}
                  </span>
                </div>
                <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
                  Complements the device-side DynamoDB/S3 telemetry with data reported directly from
                  the Spider Grills mobile app (React Native). Every metric is explicitly tagged
                  by source so Freshdesk-derived rows and direct app-backend rows stay separable
                  and never double-count.
                </p>

                <div className="two-col two-col-equal" style={{ marginBottom: 12 }}>
                  {/* Freshdesk source column */}
                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 6 }}>
                      <strong style={{ fontSize: 13 }}>Freshdesk (diagnostics-only)</strong>
                      <span className="badge badge-neutral" style={{ fontSize: 10 }}>
                        {appSide?.sources?.freshdesk?.connected ? 'connected' : 'not connected'}
                      </span>
                    </div>
                    <p style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
                      Only users who submitted an in-app diagnostic ticket — a floor, not the full population.
                    </p>
                    <div className="venom-bar-list">
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">Unique users (window)</span>
                        <span className="venom-breakdown-val">{fmtInt(appSide?.sources?.freshdesk?.unique_users_window ?? 0)}</span>
                      </div>
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">Unique devices by MAC</span>
                        <span className="venom-breakdown-val">{fmtInt(appSide?.sources?.freshdesk?.unique_devices_window ?? 0)}</span>
                      </div>
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">Observations</span>
                        <span className="venom-breakdown-val">{fmtInt(appSide?.sources?.freshdesk?.observations ?? 0)}</span>
                      </div>
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">No MAC reported</span>
                        <span className="venom-breakdown-val" style={{ color: 'var(--muted)' }}>
                          {fmtInt(appSide?.sources?.freshdesk?.device_observations_without_mac ?? 0)}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* App backend source column */}
                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 6 }}>
                      <strong style={{ fontSize: 13 }}>App backend (spidergrills.app)</strong>
                      <span
                        className={`badge ${appSide?.sources?.app_backend?.connected ? 'badge-neutral' : 'badge-warn'}`}
                        style={{ fontSize: 10 }}
                      >
                        {appSide?.sources?.app_backend?.connected ? 'connected' : 'pending credentials'}
                      </span>
                    </div>
                    <p style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
                      Full DAU/MAU, every paired device, signup funnel. Live once the direct DB pull is wired in.
                    </p>
                    <div className="venom-bar-list">
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">Unique users (window)</span>
                        <span className="venom-breakdown-val">{fmtInt(appSide?.sources?.app_backend?.unique_users_window ?? 0)}</span>
                      </div>
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">Unique devices by MAC</span>
                        <span className="venom-breakdown-val">{fmtInt(appSide?.sources?.app_backend?.unique_devices_window ?? 0)}</span>
                      </div>
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">Observations</span>
                        <span className="venom-breakdown-val">{fmtInt(appSide?.sources?.app_backend?.observations ?? 0)}</span>
                      </div>
                      <div className="venom-breakdown-row">
                        <span className="venom-bar-label">Overlap with Freshdesk (users)</span>
                        <span className="venom-breakdown-val" style={{ color: 'var(--muted)' }}>
                          {appSide?.overlap?.users_in_both != null ? fmtInt(appSide.overlap.users_in_both) : '—'}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Combined / deduped totals */}
                <div className="venom-panel-head" style={{ marginTop: 6, marginBottom: 6 }}>
                  <strong style={{ fontSize: 13 }}>Combined (deduped by MAC + user_key)</strong>
                  <span className="venom-panel-hint">safe to read as a union</span>
                </div>
                <div className="venom-bar-list" style={{ marginBottom: 12 }}>
                  <div className="venom-breakdown-row">
                    <span className="venom-bar-label">Unique users across sources</span>
                    <span className="venom-breakdown-val">{fmtInt(appSide?.combined?.unique_users_window ?? 0)}</span>
                  </div>
                  <div className="venom-breakdown-row">
                    <span className="venom-bar-label">Unique devices across sources</span>
                    <span className="venom-breakdown-val">{fmtInt(appSide?.combined?.unique_devices_window ?? 0)}</span>
                  </div>
                </div>

                {/* Distribution breakdowns — each shows combined + per-source split */}
                <div className="two-col two-col-equal">
                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 4 }}>
                      <strong style={{ fontSize: 12 }}>App version (top)</strong>
                    </div>
                    {(appSide?.combined?.app_version_top || []).length > 0 ? (
                      <div className="venom-breakdown-list">
                        {(appSide?.combined?.app_version_top || []).slice(0, 8).map((row) => (
                          <div key={row.value} className="venom-breakdown-row">
                            <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{row.value}</span>
                            <span className="venom-breakdown-val">{fmtInt(row.count)}</span>
                            <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtPct(row.pct)}</span>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">No app-version signal yet.</div>}
                  </div>

                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 4 }}>
                      <strong style={{ fontSize: 12 }}>Firmware (as reported by app)</strong>
                    </div>
                    {(appSide?.combined?.firmware_version_top || []).length > 0 ? (
                      <div className="venom-breakdown-list">
                        {(appSide?.combined?.firmware_version_top || []).slice(0, 8).map((row) => (
                          <div key={row.value} className="venom-breakdown-row">
                            <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{row.value}</span>
                            <span className="venom-breakdown-val">{fmtInt(row.count)}</span>
                            <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtPct(row.pct)}</span>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">No firmware signal yet.</div>}
                  </div>
                </div>

                <div className="two-col two-col-equal" style={{ marginTop: 10 }}>
                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 4 }}>
                      <strong style={{ fontSize: 12 }}>Phone OS</strong>
                    </div>
                    {(appSide?.combined?.phone_os_top || []).length > 0 ? (
                      <div className="venom-breakdown-list">
                        {(appSide?.combined?.phone_os_top || []).map((row) => (
                          <div key={row.value} className="venom-breakdown-row">
                            <span>{row.value}</span>
                            <span className="venom-breakdown-val">{fmtInt(row.count)}</span>
                            <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtPct(row.pct)}</span>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">No OS signal yet.</div>}
                  </div>

                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 4 }}>
                      <strong style={{ fontSize: 12 }}>Controller model (as reported by app)</strong>
                    </div>
                    {(appSide?.combined?.controller_model_top || []).length > 0 ? (
                      <div className="venom-breakdown-list">
                        {(appSide?.combined?.controller_model_top || []).map((row) => (
                          <div key={row.value} className="venom-breakdown-row">
                            <span>{row.value}</span>
                            <span className="venom-breakdown-val">{fmtInt(row.count)}</span>
                            <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtPct(row.pct)}</span>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">No controller-model signal yet.</div>}
                  </div>
                </div>

                <div className="two-col two-col-equal" style={{ marginTop: 10 }}>
                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 4 }}>
                      <strong style={{ fontSize: 12 }}>Phone brand</strong>
                    </div>
                    {(appSide?.combined?.phone_brand_top || []).length > 0 ? (
                      <div className="venom-breakdown-list">
                        {(appSide?.combined?.phone_brand_top || []).slice(0, 8).map((row) => (
                          <div key={row.value} className="venom-breakdown-row">
                            <span>{row.value}</span>
                            <span className="venom-breakdown-val">{fmtInt(row.count)}</span>
                            <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtPct(row.pct)}</span>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">No phone-brand signal yet.</div>}
                  </div>

                  <div>
                    <div className="venom-panel-head" style={{ marginBottom: 4 }}>
                      <strong style={{ fontSize: 12 }}>Top phone models</strong>
                    </div>
                    {(appSide?.combined?.phone_model_top || []).length > 0 ? (
                      <div className="venom-breakdown-list">
                        {(appSide?.combined?.phone_model_top || []).slice(0, 10).map((row) => (
                          <div key={row.value} className="venom-breakdown-row">
                            <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{row.value}</span>
                            <span className="venom-breakdown-val">{fmtInt(row.count)}</span>
                            <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtPct(row.pct)}</span>
                          </div>
                        ))}
                      </div>
                    ) : <div className="state-message">No phone-model signal yet.</div>}
                  </div>
                </div>

                <p style={{ fontSize: 10, color: 'var(--muted)', marginTop: 12, lineHeight: 1.5 }}>
                  <strong>Source note:</strong> Freshdesk rows are mined from [AUTOMATED] diagnostic-ticket
                  custom fields (MAC, firmware, app version, phone). App-backend rows will come from a
                  direct pull of the spidergrills.app database once credentials are in place. Devices
                  are deduped by normalized MAC; users by sha256(email) — so a user who appears in both
                  sources is counted once in the combined totals.
                </p>
              </section>

              </CollapsibleSection>

              <CollapsibleSection
                id="pe-team-activity"
                title="Team activity & coordination"
                subtitle="ClickUp product-dev tasks, velocity, compliance; firmware overlay; #product-dev Slack"
                accentColor="#a78bfa"
              >
              {/* ClickUp tasks + velocity — Product Development space */}
              <ClickUpTasksCard
                title="ClickUp tasks — Product / Engineering"
                subtitle="Product Development space: continuous improvement, firmware, NPD. Non-GitHub engineering work lives here."
                defaultFilter={{ space_id: '901313726772', limit: 30 }}
              />
              <ClickUpVelocityCard
                title="Team velocity — Product Development space"
                subtitle="Throughput, cycle time, and who's closing what this week."
                spaceId="901313726772"
              />
              <ClickUpComplianceCard
                title="Tagging compliance — Product Development space"
                subtitle="Closed firmware / hardware / NPD tasks carrying Division + Category. Precision here makes the firmware-overlay chart credible."
                spaceId="901313726772"
              />

              {/* Firmware releases / engineering closes overlaid on cook-success-rate.
                  Vertical markers = Category=Firmware ClickUp task completions. */}
              <ClickUpOverlayChart
                title="Firmware releases ↔ Cook success rate"
                subtitle={`Daily cook-success rate with Category=Firmware ClickUp task completions as vertical markers. Days with fewer than ${BENCHMARKS.LOW_N_SESSION_FLOOR} sessions are suppressed (noise, not signal). Baseline = 69% median.`}
                primarySeries={rangedHistory.map(r => ({
                  date: r.business_date,
                  // Suppress low-n days: a daily cook-success of 43% on 39
                  // sessions is noise; null renders as a gap in the line.
                  value: (r.session_count || 0) >= BENCHMARKS.LOW_N_SESSION_FLOOR
                    ? Math.round(((r.successful_sessions || 0) / (r.session_count || 1)) * 10000) / 100
                    : (null as unknown as number),
                }))}
                primaryLabel="Cook success %"
                primaryColor="var(--green)"
                clickupFilter={{
                  category: 'Firmware',
                  event_types: 'completed',
                  days: 90,
                }}
                benchmarkValue={BENCHMARKS.COOK_SUCCESS_MEDIAN_PCT}
                benchmarkLabel={`${BENCHMARKS.COOK_SUCCESS_MEDIAN_PCT}% — 28-month median`}
              />

              {/* Slack pulse — product-dev channel */}
              <SlackPulseCard
                title="Slack pulse — Product / Engineering"
                subtitle="Engineering conversation in #product-dev. Issue-shaped messages auto-surface on Issue Radar."
                defaultChannelName="product-dev"
              />

              </CollapsibleSection>

              <CollapsibleSection
                id="pe-engineering-issues"
                title="Engineering issues & deep-dive navigation"
                subtitle="Open GitHub issues, product issue clusters from support, cluster drill-down, telemetry analysis routes"
                accentColor="#f59e0b"
              >
              {/* GitHub Issues + Product Clusters */}
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Engineering Issues</strong>
                    <span className="venom-panel-hint">
                      {githubIssues?.total_count ? `${githubIssues.total_count} open` : ''}
                      {githubIssues?.repo && <>{' · '}<a href={`https://github.com/${githubIssues.repo}/issues`} target="_blank" rel="noopener noreferrer" className="analysis-link">GitHub &#x2197;</a></>}
                    </span>
                  </div>
                  {githubIssues?.error ? (
                    <div className="state-message warn">{githubIssues.error}</div>
                  ) : githubIssues?.issues && githubIssues.issues.length > 0 ? (
                    <div className="stack-list compact">
                      {githubIssues.issues.map(issue => {
                        const severity = issue.priority === 'P0' ? 'bad' : issue.priority === 'P1' ? 'warn' : issue.is_bug ? 'muted' : 'muted'
                        return (
                          <a key={issue.id} href={issue.html_url} target="_blank" rel="noopener noreferrer" className={`list-item status-${severity}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                            <div className="item-head">
                              <strong style={{ fontSize: 12 }}>#{issue.number} {issue.title}</strong>
                              <div className="inline-badges">
                                {issue.priority && <span className={`badge ${issue.priority === 'P0' ? 'badge-bad' : issue.priority === 'P1' ? 'badge-warn' : 'badge-neutral'}`}>{issue.priority}</span>}
                                {issue.is_bug && <span className="badge badge-bad" style={{ fontSize: 10 }}>bug</span>}
                              </div>
                            </div>
                            <p style={{ fontSize: 11 }}>
                              {issue.assignees.length > 0 ? issue.assignees.join(', ') : 'Unassigned'}
                              {' · '}{formatFreshness(issue.updated_at)}
                              {issue.labels.filter(l => !['bug', 'p0', 'p1', 'p2', 'p3', 'critical', 'high', 'medium', 'low'].includes(l.toLowerCase())).slice(0, 2).map(l => (
                                <span key={l} className="badge badge-neutral" style={{ marginLeft: 4, fontSize: 10 }}>{l}</span>
                              ))}
                            </p>
                          </a>
                        )
                      })}
                    </div>
                  ) : <div className="state-message">{githubIssues?.configured === false ? 'GitHub not configured. Set GITHUB_TOKEN in the backend.' : 'No open issues'}</div>}
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
              </CollapsibleSection>
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

              <CollapsibleSection
                id="pe-voice-escalations-intent"
                title="Escalations & purchase-intent signals"
                subtitle="Product-related escalations from Customer Experience + purchase-intent conversations from social"
                accentColor="#4a7aff"
              >
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
              </CollapsibleSection>
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

              <CollapsibleSection
                id="pe-roadmap-signals-and-competition"
                title="Innovation, competitor pain points & market position"
                subtitle="Roll-ups of social signals tagged as innovation ideas, competitor complaints, share-of-voice, and Amazon position"
                accentColor="#f472b6"
              >
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
              </CollapsibleSection>
            </>
          )}
        </>
      ) : null}
    </div>
  )
}
