import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ApiError, api } from '../lib/api'
import { fmtPct, fmtInt, fmtDecimal, fmtDuration, formatFreshness } from '../lib/format'
import { ClarityPageMetric, TelemetryHistoryDailyRow, TelemetrySummary, IssueRadarResponse } from '../lib/types'
import {
  BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Line, Area, ComposedChart, ReferenceLine,
} from 'recharts'

type TimeRange = '1h' | '24h' | '7d' | '30d'

// Engineering SLA targets
const SLA_TARGETS = {
  reliability: 0.95,     // 95% session success rate
  stabilization_p50: 180, // 3 minutes to stabilize (seconds)
  errorRate: 0.03,       // 3% max error rate
  overshoot: 0.10,       // 10% max overshoot rate
  disconnectRate: 0.05,  // 5% max disconnect rate
}

// Firmware release dates for overlay annotations
const FIRMWARE_RELEASES: { version: string; date: string; label: string }[] = [
  { version: '2.4.0', date: '2026-03-15', label: 'v2.4 - PID tuning' },
  { version: '2.4.1', date: '2026-03-28', label: 'v2.4.1 - WiFi fix' },
  { version: '2.5.0', date: '2026-04-05', label: 'v2.5 - New probe support' },
]

// Target firmware version for rollout tracker
const TARGET_FIRMWARE = '2.5.0'

interface AnomalyAlert {
  id: string
  severity: 'critical' | 'warning' | 'info'
  title: string
  description: string
  metric: string
  currentValue: string
  suggestedAction: string
}

interface CohortRow {
  cohort: string
  type: 'model' | 'firmware' | 'rssi'
  devices: number
  successRate: number | null
  errorRate: number | null
  disconnectRate: number | null
  stabilityScore: number | null
}

// Error category types based on telemetry patterns
interface ErrorCategory {
  category: string
  count: number
  rate: number
  trend: 'up' | 'down' | 'flat'
  color: string
}

interface GitHubIssue {
  number: number
  title: string
  priority: 'P0' | 'P1' | 'P2'
  labels: string[]
  createdAt: string
  url: string
}

const DRILL_ROUTES: { path: string; label: string; icon: string }[] = [
  { path: '/analysis/cook-failures', label: 'Cook failures', icon: '\ud83d\udd25' },
  { path: '/analysis/temp-curves', label: 'Temp curves', icon: '\ud83d\udcc8' },
  { path: '/analysis/session-clusters', label: 'Session clusters', icon: '\u25cb' },
  { path: '/analysis/rssi-impact', label: 'RSSI impact', icon: '\ud83d\udcf6' },
  { path: '/analysis/probe-health', label: 'Probe health', icon: '\ud83e\ude7a' },
  { path: '/analysis/firmware-model', label: 'Firmware model', icon: '\u2699\ufe0f' },
]


function buildPeakHours(historyRows: TelemetryHistoryDailyRow[]) {
  const hourTotals: Record<string, number> = {}
  for (const row of historyRows) {
    for (const [hour, count] of Object.entries(row.peak_hour_distribution || {})) {
      hourTotals[hour] = (hourTotals[hour] || 0) + (count as number)
    }
  }
  return Array.from({ length: 24 }, (_, i) => {
    const h = String(i)
    return { hour: `${String(i).padStart(2, '0')}:00`, events: hourTotals[h] || 0 }
  })
}

function buildModelBreakdown(historyRows: TelemetryHistoryDailyRow[]) {
  const totals: Record<string, number> = {}
  for (const row of historyRows.slice(-30)) {
    for (const [model, count] of Object.entries(row.model_distribution || {})) {
      totals[model] = (totals[model] || 0) + (count as number)
    }
  }
  return Object.entries(totals)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8)
    .map(([model, events]) => ({ model, events }))
}

function buildFirmwareBreakdown(historyRows: TelemetryHistoryDailyRow[]) {
  const totals: Record<string, number> = {}
  for (const row of historyRows.slice(-30)) {
    for (const [fw, count] of Object.entries(row.firmware_distribution || {})) {
      totals[fw] = (totals[fw] || 0) + (count as number)
    }
  }
  return Object.entries(totals)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8)
    .map(([firmware, events]) => ({ firmware, events }))
}

// Calculate WoW delta for a metric
function calcWoWDelta(current: number | null, historyRows: TelemetryHistoryDailyRow[], metricFn: (row: TelemetryHistoryDailyRow) => number | null): { delta: number; direction: 'up' | 'down' | 'flat' } | null {
  if (current === null || historyRows.length < 8) return null
  const priorWeekRows = historyRows.slice(-14, -7)
  if (priorWeekRows.length === 0) return null
  const priorValues = priorWeekRows.map(metricFn).filter((v): v is number => v !== null)
  if (priorValues.length === 0) return null
  const priorAvg = priorValues.reduce((s, v) => s + v, 0) / priorValues.length
  if (priorAvg === 0) return null
  const delta = ((current - priorAvg) / priorAvg) * 100
  const direction = delta > 2 ? 'up' : delta < -2 ? 'down' : 'flat'
  return { delta, direction }
}

// Detect anomalies based on current metrics
function detectAnomalies(
  successRate: number | null,
  disconnectRate: number | null,
  overshootRate: number | null,
  errorRate30: number | null,
  historyRows: TelemetryHistoryDailyRow[],
  firmwareHealth: Array<{ key: string; health_score: number; failure_rate: number }>
): AnomalyAlert[] {
  const alerts: AnomalyAlert[] = []

  // Check reliability drop
  if (successRate !== null && successRate < SLA_TARGETS.reliability) {
    const drop = (SLA_TARGETS.reliability - successRate) * 100
    alerts.push({
      id: 'reliability-drop',
      severity: drop > 10 ? 'critical' : 'warning',
      title: 'Reliability Below Target',
      description: `Session success rate is ${fmtPct(successRate)} (target: ${fmtPct(SLA_TARGETS.reliability)})`,
      metric: 'session_success_rate',
      currentValue: fmtPct(successRate),
      suggestedAction: 'Review recent firmware changes and connectivity patterns'
    })
  }

  // Check for sudden reliability change (WoW)
  if (historyRows.length >= 8) {
    const recentRows = historyRows.slice(-7)
    const priorRows = historyRows.slice(-14, -7)
    const recentErrorRate = recentRows.reduce((s, r) => s + r.error_events, 0) / Math.max(1, recentRows.reduce((s, r) => s + r.total_events, 0))
    const priorErrorRate = priorRows.reduce((s, r) => s + r.error_events, 0) / Math.max(1, priorRows.reduce((s, r) => s + r.total_events, 0))
    const change = recentErrorRate - priorErrorRate
    if (change > 0.05) {
      alerts.push({
        id: 'error-spike',
        severity: change > 0.10 ? 'critical' : 'warning',
        title: 'Error Rate Spike Detected',
        description: `Error rate increased ${fmtPct(change)} week-over-week`,
        metric: 'error_rate',
        currentValue: fmtPct(recentErrorRate),
        suggestedAction: 'Check firmware version distribution for outliers'
      })
    }
  }

  // Check firmware versions with high failure rates
  const badFirmware = firmwareHealth.filter(fw => fw.failure_rate > 0.10)
  if (badFirmware.length > 0) {
    alerts.push({
      id: 'firmware-outlier',
      severity: badFirmware.some(fw => fw.failure_rate > 0.20) ? 'critical' : 'warning',
      title: `Firmware Outliers Detected`,
      description: `${badFirmware.length} firmware version(s) have >10% failure rate`,
      metric: 'firmware_health',
      currentValue: badFirmware.map(fw => `${fw.key}: ${fmtPct(fw.failure_rate)}`).join(', '),
      suggestedAction: 'Prioritize hotfix or force-update for affected versions'
    })
  }

  // Check overshoot rate
  if (overshootRate !== null && overshootRate > SLA_TARGETS.overshoot) {
    alerts.push({
      id: 'overshoot-high',
      severity: overshootRate > 0.20 ? 'critical' : 'warning',
      title: 'Temperature Overshoot Elevated',
      description: `Overshoot rate ${fmtPct(overshootRate)} exceeds ${fmtPct(SLA_TARGETS.overshoot)} target`,
      metric: 'overshoot_rate',
      currentValue: fmtPct(overshootRate),
      suggestedAction: 'Review PID tuning parameters on affected models'
    })
  }

  // Check disconnect rate
  if (disconnectRate !== null && disconnectRate > SLA_TARGETS.disconnectRate) {
    alerts.push({
      id: 'disconnect-high',
      severity: disconnectRate > 0.10 ? 'critical' : 'warning',
      title: 'High Disconnect Rate',
      description: `Disconnect rate ${fmtPct(disconnectRate)} exceeds ${fmtPct(SLA_TARGETS.disconnectRate)} target`,
      metric: 'disconnect_rate',
      currentValue: fmtPct(disconnectRate),
      suggestedAction: 'Check WiFi signal distribution and network stability'
    })
  }

  return alerts
}

// Build error classification breakdown
function buildErrorClassification(
  probeErrorRate: number | null,
  disconnectRate: number | null,
  timeoutRate: number | null,
  overshootRate: number | null,
  historyRows: TelemetryHistoryDailyRow[]
): ErrorCategory[] {
  const categories: ErrorCategory[] = []

  // Calculate trend for each error type
  const getTrend = (currentRate: number, category: string): 'up' | 'down' | 'flat' => {
    // Simplified trend calculation based on history
    if (historyRows.length < 14) return 'flat'
    return 'flat' // Would need per-category history for real trends
  }

  if (disconnectRate !== null) {
    categories.push({
      category: 'WiFi / Connectivity',
      count: Math.round((disconnectRate || 0) * 1000), // estimated from rate
      rate: disconnectRate,
      trend: getTrend(disconnectRate, 'wifi'),
      color: 'var(--blue)'
    })
  }

  if (probeErrorRate !== null) {
    categories.push({
      category: 'Probe Errors',
      count: Math.round((probeErrorRate || 0) * 1000),
      rate: probeErrorRate,
      trend: getTrend(probeErrorRate, 'probe'),
      color: 'var(--orange)'
    })
  }

  if (overshootRate !== null) {
    categories.push({
      category: 'Temp Control',
      count: Math.round((overshootRate || 0) * 1000),
      rate: overshootRate,
      trend: getTrend(overshootRate, 'temp'),
      color: 'var(--red)'
    })
  }

  if (timeoutRate !== null) {
    categories.push({
      category: 'Timeout / Firmware',
      count: Math.round((timeoutRate || 0) * 1000),
      rate: timeoutRate,
      trend: getTrend(timeoutRate, 'timeout'),
      color: 'var(--purple, #9b7bff)'
    })
  }

  // Sort by rate descending
  return categories.sort((a, b) => (b.rate || 0) - (a.rate || 0))
}

// Build firmware rollout progress
function buildFirmwareRollout(firmwareData: Array<{ firmware: string; events: number }>) {
  const total = firmwareData.reduce((s, f) => s + f.events, 0)
  const targetEvents = firmwareData.find(f => f.firmware === TARGET_FIRMWARE)?.events || 0
  const targetPct = total > 0 ? targetEvents / total : 0
  const deprecated = firmwareData.filter(f => {
    const [major, minor] = f.firmware.split('.').map(Number)
    const [targetMajor, targetMinor] = TARGET_FIRMWARE.split('.').map(Number)
    return major < targetMajor || (major === targetMajor && minor < targetMinor - 1)
  })
  const deprecatedPct = total > 0 ? deprecated.reduce((s, f) => s + f.events, 0) / total : 0

  return {
    targetVersion: TARGET_FIRMWARE,
    targetAdoption: targetPct,
    totalDevices: total,
    deprecatedPct,
    deprecatedVersions: deprecated.map(d => d.firmware),
    breakdown: firmwareData.map(f => ({
      ...f,
      pct: total > 0 ? f.events / total : 0,
      isTarget: f.firmware === TARGET_FIRMWARE,
      isDeprecated: deprecated.some(d => d.firmware === f.firmware)
    }))
  }
}

// Build cohort comparison data
function buildCohortComparison(
  historyRows: TelemetryHistoryDailyRow[],
  firmwareHealth: Array<{ key: string; health_score: number; failure_rate: number; disconnect_rate: number; sessions: number }>,
  grillTypeHealth: Array<{ key: string; health_score: number; failure_rate: number; disconnect_rate: number; sessions: number }>,
  connectivityBuckets: Array<{ bucket: string; sessions: number; failure_rate: number; stability_score: number | null; disconnect_rate?: number | null }>
): CohortRow[] {
  const rows: CohortRow[] = []

  // Model cohorts
  for (const model of grillTypeHealth.slice(0, 5)) {
    rows.push({
      cohort: model.key,
      type: 'model',
      devices: model.sessions,
      successRate: model.health_score ? 1 - model.failure_rate : null,
      errorRate: model.failure_rate,
      disconnectRate: model.disconnect_rate,
      stabilityScore: null
    })
  }

  // Firmware cohorts
  for (const fw of firmwareHealth.slice(0, 5)) {
    rows.push({
      cohort: `FW ${fw.key}`,
      type: 'firmware',
      devices: fw.sessions,
      successRate: fw.health_score ? 1 - fw.failure_rate : null,
      errorRate: fw.failure_rate,
      disconnectRate: fw.disconnect_rate,
      stabilityScore: null
    })
  }

  // WiFi signal cohorts
  for (const bucket of connectivityBuckets) {
    rows.push({
      cohort: bucket.bucket,
      type: 'rssi',
      devices: bucket.sessions,
      successRate: 1 - bucket.failure_rate,
      errorRate: bucket.failure_rate,
      disconnectRate: bucket.disconnect_rate ?? null,
      stabilityScore: bucket.stability_score
    })
  }

  return rows
}

// Mock P0/P1 issues (would be fetched from GitHub API in production)
function getMockEngIssues(): GitHubIssue[] {
  return [
    { number: 142, title: 'WiFi reconnect fails on v2.4.0 after sleep', priority: 'P0', labels: ['bug', 'firmware', 'critical'], createdAt: '2026-04-09', url: '#' },
    { number: 138, title: 'Probe 2 temp reading drift >5F over 2hr cooks', priority: 'P0', labels: ['bug', 'hardware', 'critical'], createdAt: '2026-04-08', url: '#' },
    { number: 135, title: 'PID overshoot on Giant Huntsman cold start', priority: 'P1', labels: ['bug', 'firmware'], createdAt: '2026-04-07', url: '#' },
    { number: 131, title: 'Session timeout not triggering reconnect', priority: 'P1', labels: ['bug', 'connectivity'], createdAt: '2026-04-05', url: '#' },
  ]
}

export function ProductEngineeringDivision() {
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [productPageHealth, setProductPageHealth] = useState<ClarityPageMetric[]>([])
  const [issueRadar, setIssueRadar] = useState<IssueRadarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<TimeRange>('24h')
  const [cohortFilter, setCohortFilter] = useState<'all' | 'model' | 'firmware' | 'rssi'>('all')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [payload, pageHealth, issues] = await Promise.all([
          api.telemetrySummary(),
          api.clarityPageHealth().catch(() => [] as ClarityPageMetric[]),
          api.issues().catch(() => null),
        ])
        if (!cancelled) {
          setTelemetry(payload)
          setProductPageHealth(pageHealth)
          setIssueRadar(issues)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load telemetry summary')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const collection = telemetry?.collection_metadata || null
  const slice = telemetry?.slice_snapshot || null
  const derived = telemetry?.analytics?.derived_metrics || null
  const latest = telemetry?.latest || null
  const analytics = telemetry?.analytics || null
  const historyDaily = telemetry?.history_daily || []

  const streamBacked = collection?.sample_source === 'dynamodb_stream'
  const sampleSize = Math.max(slice?.sessions_derived || 0, collection?.distinct_devices_observed || 0)
  const sampleReliability = !streamBacked ? 'low' : sampleSize < 5 ? 'low' : sampleSize < 20 ? 'medium' : 'high'

  const activeCooks = derived?.active_cooks_now ?? collection?.active_devices_last_15m ?? 0
  const devicesReporting = derived?.devices_reporting_last_5m ?? collection?.active_devices_last_5m ?? 0
  const cooksStarted = derived?.cooks_started_24h ?? slice?.sessions_derived ?? 0
  const cooksCompleted = derived?.cooks_completed_24h ?? 0
  const successRate = derived?.session_success_rate ?? latest?.session_reliability_score ?? null
  const disconnectRate = derived?.disconnect_proxy_rate ?? latest?.disconnect_rate ?? null
  const timeoutRate = derived?.timeout_rate ?? null
  const probeErrorRate = analytics?.probe_failure_rate ?? null
  const medianRssi = derived?.median_rssi_now ?? null
  const stabilityScore = derived?.stability_score ?? latest?.temp_stability_score ?? null
  const overshootRate = derived?.overshoot_rate ?? null
  const p50Stabilize = derived?.time_to_stabilize_p50_seconds ?? null
  const p95Stabilize = derived?.time_to_stabilize_p95_seconds ?? null
  const medianCookDuration = derived?.median_cook_duration_seconds ?? null
  const p95CookDuration = derived?.p95_cook_duration_seconds ?? null
  const devices24h = collection?.active_devices_last_24h ?? 0
  const devices60m = collection?.active_devices_last_60m ?? 0

  const rangedHistory = useMemo(() => {
    if (!historyDaily.length) return []
    const rangeDays: Record<TimeRange, number> = { '1h': 1, '24h': 1, '7d': 7, '30d': 30 }
    const days = rangeDays[range] || 30
    return historyDaily.slice(-days)
  }, [historyDaily, range])

  const fleetChartRows = useMemo(() => {
    if (!rangedHistory.length) return []
    return rangedHistory.map((row) => ({
      date: row.business_date.slice(5),
      active_devices: row.active_devices,
      engaged_devices: row.engaged_devices,
      error_rate: row.total_events > 0 ? Math.round((row.error_events / row.total_events) * 10000) / 100 : 0,
    }))
  }, [rangedHistory])

  const peakHourData = useMemo(() => buildPeakHours(rangedHistory), [rangedHistory])
  const modelData = useMemo(() => buildModelBreakdown(rangedHistory), [rangedHistory])
  const firmwareData = useMemo(() => buildFirmwareBreakdown(rangedHistory), [rangedHistory])

  const historyStats = useMemo(() => {
    if (!rangedHistory.length) return null
    const avgDevices = rangedHistory.reduce((s, r) => s + r.active_devices, 0) / rangedHistory.length
    const totalErrors = rangedHistory.reduce((s, r) => s + r.error_events, 0)
    const totalEvents = rangedHistory.reduce((s, r) => s + r.total_events, 0)
    const peakDay = rangedHistory.reduce((best, r) => r.active_devices > (best?.active_devices || 0) ? r : best, rangedHistory[0])
    return { avgDevices30: avgDevices, avgDevices7: avgDevices, totalErrors30: totalErrors, totalEvents30: totalEvents, errorRate30: totalEvents > 0 ? totalErrors / totalEvents : 0, peakDay }
  }, [rangedHistory])

  // Feature 1: Week-over-Week Delta calculations
  const wowDeltas = useMemo(() => {
    const activeDevicesWoW = calcWoWDelta(devices24h, historyDaily, r => r.active_devices)
    const errorRateWoW = historyStats ? calcWoWDelta(historyStats.errorRate30, historyDaily, r => r.total_events > 0 ? r.error_events / r.total_events : null) : null
    const reliabilityWoW = successRate !== null ? calcWoWDelta(successRate, historyDaily, () => successRate) : null
    return { activeDevicesWoW, errorRateWoW, reliabilityWoW }
  }, [devices24h, historyDaily, historyStats, successRate])

  // Feature 2: Anomaly detection
  const anomalyAlerts = useMemo(() => {
    return detectAnomalies(
      successRate,
      disconnectRate,
      overshootRate,
      historyStats?.errorRate30 ?? null,
      historyDaily,
      telemetry?.firmware_health || []
    )
  }, [successRate, disconnectRate, overshootRate, historyStats, historyDaily, telemetry?.firmware_health])

  // Feature 3: Error classification breakdown
  const errorClassification = useMemo(() => {
    return buildErrorClassification(probeErrorRate, disconnectRate, timeoutRate, overshootRate, historyDaily)
  }, [probeErrorRate, disconnectRate, timeoutRate, overshootRate, historyDaily])

  // Feature 4: Firmware rollout progress
  const firmwareRollout = useMemo(() => {
    return buildFirmwareRollout(firmwareData)
  }, [firmwareData])

  // Feature 6: Release impact overlay data for chart
  const releaseAnnotations = useMemo(() => {
    if (!fleetChartRows.length) return []
    return FIRMWARE_RELEASES.filter(release => {
      const releaseDate = release.date.slice(5) // MM-DD format
      return fleetChartRows.some(r => r.date === releaseDate)
    }).map(release => ({
      ...release,
      chartDate: release.date.slice(5)
    }))
  }, [fleetChartRows])

  // Feature 7: Device cohort comparison
  const cohortData = useMemo(() => {
    const allCohorts = buildCohortComparison(
      historyDaily,
      telemetry?.firmware_health || [],
      telemetry?.grill_type_health || [],
      telemetry?.analytics?.connectivity_buckets || []
    )
    if (cohortFilter === 'all') return allCohorts
    return allCohorts.filter(c => c.type === cohortFilter)
  }, [historyDaily, telemetry, cohortFilter])

  // Feature 8: P0/P1 Engineering Issues
  const engIssues = useMemo(() => getMockEngIssues(), [])

  return (
    <div className="page-grid venom-page">
      {/* Header */}
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Venom Telemetry — Product OS</h2>
          <p className="venom-subtitle">
            {streamBacked ? 'Live' : 'Degraded'} · Updated {formatFreshness(collection?.newest_sample_timestamp_seen)} · {fmtInt(devicesReporting || activeCooks)} devices reporting
          </p>
        </div>
        <div className="venom-range-group">
          {(['1h', '24h', '7d', '30d'] as TimeRange[]).map((r) => (
            <button key={r} className={`range-button${range === r ? ' active' : ''}`} onClick={() => setRange(r)}>{r}</button>
          ))}
        </div>
      </div>

      {loading ? <Card title="Venom Telemetry"><div className="state-message">Loading telemetry…</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <TruthLegend />

          {/* Feature 2: Anomaly Alerts Panel - "Needs Attention" */}
          {anomalyAlerts.length > 0 && (
            <section className="card anomaly-alerts-panel">
              <div className="venom-panel-head">
                <strong style={{ color: 'var(--red)' }}>Needs Attention</strong>
                <span className="badge badge-bad">{anomalyAlerts.length} alert{anomalyAlerts.length !== 1 ? 's' : ''}</span>
              </div>
              <div className="anomaly-alerts-grid">
                {anomalyAlerts.map(alert => (
                  <div key={alert.id} className={`anomaly-alert anomaly-${alert.severity}`}>
                    <div className="anomaly-header">
                      <span className={`anomaly-severity badge badge-${alert.severity === 'critical' ? 'bad' : 'warn'}`}>
                        {alert.severity.toUpperCase()}
                      </span>
                      <strong>{alert.title}</strong>
                    </div>
                    <p className="anomaly-description">{alert.description}</p>
                    <div className="anomaly-action">
                      <span className="anomaly-action-label">Suggested:</span> {alert.suggestedAction}
                    </div>
                    <Link to="/issues" className="anomaly-link">View in Issue Radar &#x2197;</Link>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Top KPI strip - Feature 1: WoW Delta Indicators */}
          <div className="venom-kpi-strip">
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Active Cooks</div>
              <div className="venom-kpi-value-row">
                <span className="venom-kpi-value">{fmtInt(activeCooks)}</span>
                {wowDeltas.activeDevicesWoW && (
                  <span className={`wow-delta wow-delta-${wowDeltas.activeDevicesWoW.direction}`}>
                    {wowDeltas.activeDevicesWoW.direction === 'up' ? '↑' : wowDeltas.activeDevicesWoW.direction === 'down' ? '↓' : '→'}
                    {Math.abs(wowDeltas.activeDevicesWoW.delta).toFixed(1)}% WoW
                  </span>
                )}
              </div>
              <div className="venom-kpi-sub">{fmtInt(devicesReporting)} devices reporting (5m window)</div>
              <div className="venom-kpi-badges">
                <TruthBadge state="proxy" />
                {devices60m > 0 ? <span className="venom-delta venom-delta-up">{fmtInt(devices60m)} in 60m · {fmtInt(devices24h)} in 24h</span> : null}
              </div>
            </div>
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Cook Throughput</div>
              <div className="venom-kpi-value">{fmtInt(cooksStarted)}</div>
              <div className="venom-kpi-sub">started · {fmtInt(cooksCompleted)} completed (24h)</div>
              <div className="venom-kpi-badges">
                <TruthBadge state="proxy" />
                {historyStats ? <span className="venom-delta venom-delta-flat">30d avg: {Math.round(historyStats.avgDevices30)} devices/day</span> : null}
              </div>
            </div>
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Reliability</div>
              <div className="venom-kpi-value-row">
                <span className={`venom-kpi-value ${successRate !== null && successRate < SLA_TARGETS.reliability ? 'below-target' : ''}`}>
                  {fmtPct(successRate)}
                </span>
                {wowDeltas.reliabilityWoW && (
                  <span className={`wow-delta wow-delta-${wowDeltas.reliabilityWoW.direction === 'up' ? 'up' : wowDeltas.reliabilityWoW.direction === 'down' ? 'down' : 'flat'}`}>
                    {wowDeltas.reliabilityWoW.direction === 'up' ? '↑' : wowDeltas.reliabilityWoW.direction === 'down' ? '↓' : '→'}
                    {Math.abs(wowDeltas.reliabilityWoW.delta).toFixed(1)}% WoW
                  </span>
                )}
              </div>
              <div className="venom-kpi-sub">
                session success · n={fmtInt(sampleSize)}
                <span className="sla-target-hint">target: {fmtPct(SLA_TARGETS.reliability)}</span>
              </div>
              <div className="venom-kpi-badges">
                <TruthBadge state="estimated" />
                {historyStats ? <span className={`venom-delta ${historyStats.errorRate30 > SLA_TARGETS.errorRate ? 'venom-delta-down' : 'venom-delta-flat'}`}>
                  30d error rate: {fmtPct(historyStats.errorRate30)}
                </span> : null}
              </div>
            </div>
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Control Quality</div>
              <div className="venom-kpi-value-row">
                <span className="venom-kpi-value">{fmtDecimal(stabilityScore)}</span>
                {p50Stabilize !== null && p50Stabilize > SLA_TARGETS.stabilization_p50 && (
                  <span className="wow-delta wow-delta-down">slow</span>
                )}
              </div>
              <div className="venom-kpi-sub">
                stability score · p50 stabilize {fmtDuration(p50Stabilize)}
                <span className="sla-target-hint">target: {fmtDuration(SLA_TARGETS.stabilization_p50)}</span>
              </div>
              <div className="venom-kpi-badges">
                <TruthBadge state="estimated" />
                <span className="venom-delta venom-delta-stable">stable</span>
              </div>
            </div>
          </div>

          {/* Fleet Activity + Error Trend (main chart) - Features 5 & 6: SLA targets + Release overlay */}
          <section className="card">
            <div className="venom-panel-head">
              <div>
                <strong>Fleet Activity — Daily Active Devices</strong>
                <p className="venom-chart-sub">Unique Venom controllers reporting each day across Huntsman, Giant Huntsman, and Weber Kettle grills</p>
              </div>
              <div className="chart-legend-extras">
                {releaseAnnotations.length > 0 && (
                  <span className="release-legend">
                    <span className="release-marker"></span> Firmware releases
                  </span>
                )}
                {historyStats?.peakDay ? <span className="venom-panel-hint">Peak: {historyStats.peakDay.active_devices} devices on {historyStats.peakDay.business_date}</span> : null}
              </div>
            </div>
            {fleetChartRows.length > 0 ? (
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height={320}>
                  <ComposedChart data={fleetChartRows}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 11 }} />
                    <YAxis yAxisId="left" stroke="#9fb0d4" />
                    <YAxis yAxisId="right" orientation="right" stroke="#9fb0d4" tickFormatter={(v: number) => `${v}%`} domain={[0, 10]} />
                    <Tooltip />
                    <Legend />
                    {/* Feature 5: SLA target line for error rate */}
                    <ReferenceLine yAxisId="right" y={SLA_TARGETS.errorRate * 100} stroke="var(--orange)" strokeDasharray="8 4" label={{ value: `Target: ${SLA_TARGETS.errorRate * 100}%`, fill: 'var(--orange)', fontSize: 10, position: 'right' }} />
                    {/* Feature 6: Release impact overlay annotations */}
                    {releaseAnnotations.map(release => (
                      <ReferenceLine
                        key={release.version}
                        x={release.chartDate}
                        yAxisId="left"
                        stroke="var(--purple, #9b7bff)"
                        strokeDasharray="4 2"
                        label={{ value: release.label, fill: 'var(--purple, #9b7bff)', fontSize: 9, position: 'top', angle: -45 }}
                      />
                    ))}
                    <Area yAxisId="left" type="monotone" name="Active devices" dataKey="active_devices" fill="rgba(110,168,255,0.15)" stroke="var(--blue)" strokeWidth={2} />
                    <Line yAxisId="left" type="monotone" name="Engaged (cooking)" dataKey="engaged_devices" stroke="var(--green)" strokeWidth={2} dot={false} />
                    <Line yAxisId="right" type="monotone" name="Error rate %" dataKey="error_rate" stroke="var(--red)" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="state-message">No historical daily data available yet. Run the S3 import to populate fleet history.</div>
            )}
          </section>

          {/* Breakdown panels */}
          <div className="two-col two-col-equal">
            {/* Reliability breakdown */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Reliability breakdown</strong>
                <Link to="/issues" className="analysis-link">View issues &#x2197;</Link>
              </div>
              <div className="venom-breakdown-list">
                <div className="venom-breakdown-row">
                  <span>Session success rate</span>
                  <span className="venom-breakdown-val">{fmtPct(successRate)}</span>
                  <TruthBadge state="estimated" />
                </div>
                <div className="venom-breakdown-row">
                  <span>Disconnect (proxy)</span>
                  <span className="venom-breakdown-val">{fmtPct(disconnectRate)}</span>
                  <TruthBadge state="proxy" />
                </div>
                <div className="venom-breakdown-row">
                  <span>Timeout rate</span>
                  <span className="venom-breakdown-val">{fmtPct(timeoutRate)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span>Probe error rate</span>
                  <span className="venom-breakdown-val">{fmtPct(probeErrorRate)}</span>
                </div>
                <div className="venom-breakdown-row">
                  <span>Median RSSI</span>
                  <span className="venom-breakdown-val">{medianRssi != null ? `${medianRssi} dBm` : '\u2014'}</span>
                </div>
              </div>
              <small className="venom-panel-footer">n={fmtInt(sampleSize)} sessions · {sampleReliability} sample reliability · directional only</small>
            </section>

            {/* Control quality breakdown */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Control quality breakdown</strong>
                <Link to="/analysis/temp-curves" className="analysis-link">View curves &#x2197;</Link>
              </div>
              <div className="venom-breakdown-label">Time to stabilize distribution</div>
              <div className="venom-bar-list">
                <div className="venom-bar-row">
                  <span className="venom-bar-label">p50 stabilize</span>
                  <BarIndicator value={p50Stabilize || 0} max={p95Stabilize || 1200} color="var(--blue)" />
                  <span className="venom-bar-value">{fmtDuration(p50Stabilize)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">p95 stabilize</span>
                  <BarIndicator value={p95Stabilize || 0} max={p95Stabilize || 1200} color="var(--red)" />
                  <span className="venom-bar-value">{fmtDuration(p95Stabilize)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">Overshoot rate</span>
                  <BarIndicator value={(overshootRate || 0) * 100} max={100} color="var(--orange)" />
                  <span className="venom-bar-value">{fmtPct(overshootRate, 0)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">Stability score</span>
                  <BarIndicator value={(stabilityScore || 0) * 100} max={100} color="var(--green)" />
                  <span className="venom-bar-value">{fmtDecimal(stabilityScore)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">Median cook (p50)</span>
                  <BarIndicator value={medianCookDuration || 0} max={p95CookDuration || 14400} color="#9b7bff" />
                  <span className="venom-bar-value">{fmtDuration(medianCookDuration)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">Cook duration (p95)</span>
                  <BarIndicator value={p95CookDuration || 0} max={p95CookDuration || 14400} color="var(--red)" />
                  <span className="venom-bar-value">{fmtDuration(p95CookDuration)}</span>
                </div>
              </div>
              <small className="venom-panel-footer">n={fmtInt(sampleSize)} sessions · estimated · {sampleReliability} reliability</small>
            </section>
          </div>

          {/* Feature 3: Error Classification Breakdown + Feature 4: Firmware Rollout Tracker */}
          <div className="two-col two-col-equal">
            {/* Error Classification */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Error Classification</strong>
                <Link to="/issues?filter=errors" className="analysis-link">View details &#x2197;</Link>
              </div>
              <div className="error-classification-list">
                {errorClassification.length > 0 ? (
                  errorClassification.map(cat => (
                    <div key={cat.category} className="error-category-row">
                      <div className="error-category-info">
                        <span className="error-category-dot" style={{ background: cat.color }}></span>
                        <span className="error-category-name">{cat.category}</span>
                        <span className={`error-trend error-trend-${cat.trend}`}>
                          {cat.trend === 'up' ? '↑' : cat.trend === 'down' ? '↓' : '→'}
                        </span>
                      </div>
                      <div className="error-category-stats">
                        <BarIndicator value={(cat.rate || 0) * 100} max={15} color={cat.color} />
                        <span className="error-category-rate">{fmtPct(cat.rate)}</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="state-message">Error classification data not available</div>
                )}
              </div>
              <small className="venom-panel-footer">Categories based on telemetry error patterns</small>
            </section>

            {/* Firmware Rollout Progress */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Firmware Rollout</strong>
                <span className="venom-panel-hint">Target: {firmwareRollout.targetVersion}</span>
              </div>
              <div className="firmware-rollout-summary">
                <div className="rollout-stat rollout-stat-primary">
                  <span className="rollout-value">{fmtPct(firmwareRollout.targetAdoption)}</span>
                  <span className="rollout-label">on target version</span>
                </div>
                <div className="rollout-stat rollout-stat-warning">
                  <span className="rollout-value">{fmtPct(firmwareRollout.deprecatedPct)}</span>
                  <span className="rollout-label">on deprecated</span>
                </div>
              </div>
              <div className="firmware-rollout-breakdown">
                {firmwareRollout.breakdown.slice(0, 5).map(fw => (
                  <div key={fw.firmware} className={`firmware-row ${fw.isTarget ? 'firmware-target' : ''} ${fw.isDeprecated ? 'firmware-deprecated' : ''}`}>
                    <span className="firmware-version">
                      {fw.isTarget && <span className="fw-badge fw-badge-target">target</span>}
                      {fw.isDeprecated && <span className="fw-badge fw-badge-deprecated">old</span>}
                      {fw.firmware}
                    </span>
                    <BarIndicator value={fw.pct * 100} max={100} color={fw.isTarget ? 'var(--green)' : fw.isDeprecated ? 'var(--orange)' : 'var(--blue)'} />
                    <span className="firmware-pct">{fmtPct(fw.pct)}</span>
                  </div>
                ))}
              </div>
              {firmwareRollout.deprecatedVersions.length > 0 && (
                <small className="venom-panel-footer" style={{ color: 'var(--orange)' }}>
                  Deprecated: {firmwareRollout.deprecatedVersions.join(', ')}
                </small>
              )}
            </section>
          </div>

          {/* Feature 7: Device Cohort Comparison Table */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Device Cohort Comparison</strong>
              <div className="cohort-filters">
                {(['all', 'model', 'firmware', 'rssi'] as const).map(f => (
                  <button
                    key={f}
                    className={`cohort-filter-btn ${cohortFilter === f ? 'active' : ''}`}
                    onClick={() => setCohortFilter(f)}
                  >
                    {f === 'all' ? 'All' : f === 'rssi' ? 'WiFi Signal' : f.charAt(0).toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            <div className="cohort-table-wrap">
              <table className="cohort-table">
                <thead>
                  <tr>
                    <th>Cohort</th>
                    <th>Type</th>
                    <th>Devices</th>
                    <th>Success Rate</th>
                    <th>Error Rate</th>
                    <th>Disconnect</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {cohortData.length > 0 ? cohortData.map((row, idx) => {
                    const status = (row.errorRate || 0) > 0.10 ? 'bad' : (row.errorRate || 0) > 0.05 ? 'warn' : 'good'
                    return (
                      <tr key={idx} className={`cohort-row cohort-${status}`}>
                        <td className="cohort-name">{row.cohort}</td>
                        <td><span className={`cohort-type-badge cohort-type-${row.type}`}>{row.type}</span></td>
                        <td>{fmtInt(row.devices)}</td>
                        <td className={row.successRate !== null && row.successRate < SLA_TARGETS.reliability ? 'below-sla' : ''}>
                          {fmtPct(row.successRate)}
                        </td>
                        <td className={(row.errorRate || 0) > SLA_TARGETS.errorRate ? 'below-sla' : ''}>
                          {fmtPct(row.errorRate)}
                        </td>
                        <td className={(row.disconnectRate || 0) > SLA_TARGETS.disconnectRate ? 'below-sla' : ''}>
                          {fmtPct(row.disconnectRate)}
                        </td>
                        <td>
                          <span className={`cohort-status-badge badge-${status}`}>
                            {status === 'bad' ? 'Degraded' : status === 'warn' ? 'Warning' : 'Healthy'}
                          </span>
                        </td>
                      </tr>
                    )
                  }) : (
                    <tr><td colSpan={7} className="state-message">No cohort data available</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <small className="venom-panel-footer">
              Compare metrics across device models, firmware versions, and WiFi signal strength bands
            </small>
          </section>

          {/* Feature 8: P0/P1 Open Issues Widget */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>P0/P1 Open Issues</strong>
              <a href="https://github.com/jpruit20/spiderclawkpi/issues?q=is%3Aopen+label%3Abug" target="_blank" rel="noopener noreferrer" className="analysis-link">
                View all issues &#x2197;
              </a>
            </div>
            <div className="issues-list">
              {engIssues.length > 0 ? engIssues.map(issue => (
                <div key={issue.number} className={`issue-row issue-${issue.priority.toLowerCase()}`}>
                  <span className={`issue-priority badge badge-${issue.priority === 'P0' ? 'bad' : 'warn'}`}>
                    {issue.priority}
                  </span>
                  <div className="issue-info">
                    <a href={issue.url} target="_blank" rel="noopener noreferrer" className="issue-title">
                      #{issue.number}: {issue.title}
                    </a>
                    <div className="issue-meta">
                      {issue.labels.map(label => (
                        <span key={label} className="issue-label">{label}</span>
                      ))}
                      <span className="issue-date">opened {issue.createdAt}</span>
                    </div>
                  </div>
                </div>
              )) : (
                <div className="state-message" style={{ color: 'var(--green)' }}>No P0/P1 issues open</div>
              )}
            </div>
            <small className="venom-panel-footer">
              Critical engineering issues impacting reliability or customer experience
            </small>
          </section>

          {/* Usage patterns: peak hours + model/firmware breakdown */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Peak cooking hours</strong>
                <span className="venom-panel-hint">When users cook most (all-time)</span>
              </div>
              {peakHourData.some((r) => r.events > 0) ? (
                <div className="chart-wrap-short">
                  <ResponsiveContainer width="100%" height={240}>
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
              <div className="venom-panel-head">
                <strong>Grill model mix</strong>
                <span className="venom-panel-hint">Last 30 days</span>
              </div>
              {modelData.length > 0 ? (
                <div className="chart-wrap-short">
                  <ResponsiveContainer width="100%" height={240}>
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

          {/* Firmware breakdown + live issues */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Firmware versions in field</strong>
                <Link to="/analysis/firmware-model" className="analysis-link">Details &#x2197;</Link>
              </div>
              {firmwareData.length > 0 ? (
                <div className="chart-wrap-short">
                  <ResponsiveContainer width="100%" height={240}>
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
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>Live fleet signals</strong>
              </div>
              <div className="stack-list compact">
                <div className={`list-item status-${(successRate || 0) >= 0.9 ? 'good' : (successRate || 0) >= 0.8 ? 'warn' : 'bad'}`}>
                  <div className="item-head"><strong>Session reliability</strong><span className="badge badge-{(successRate || 0) >= 0.9 ? 'good' : 'warn'}">{fmtPct(successRate)}</span></div>
                  <p>{sampleSize} sessions observed · disconnect proxy {fmtPct(disconnectRate)}</p>
                </div>
                {(overshootRate || 0) > 0.15 ? (
                  <div className="list-item status-warn">
                    <div className="item-head"><strong>Overshoot elevated</strong><span className="badge badge-warn">{fmtPct(overshootRate)}</span></div>
                    <p>Temperature overshoot above 15% threshold — may indicate PID tuning issue on certain models</p>
                  </div>
                ) : null}
                {(medianRssi || 0) < -75 ? (
                  <div className="list-item status-warn">
                    <div className="item-head"><strong>Weak WiFi signal</strong><span className="badge badge-warn">{medianRssi} dBm</span></div>
                    <p>Median RSSI below -75 dBm across active fleet — connectivity-related disconnects likely</p>
                  </div>
                ) : null}
                {historyStats && historyStats.errorRate30 > 0.05 ? (
                  <div className="list-item status-bad">
                    <div className="item-head"><strong>30-day error rate elevated</strong><span className="badge badge-bad">{fmtPct(historyStats.errorRate30)}</span></div>
                    <p>{fmtInt(historyStats.totalErrors30)} error events out of {fmtInt(historyStats.totalEvents30)} total in last 30 days</p>
                  </div>
                ) : null}
                <div className="list-item status-muted">
                  <div className="item-head"><strong>Fleet coverage</strong></div>
                  <p>{fmtInt(devices24h)} devices seen in 24h · {fmtInt(devices60m)} in last hour · {fmtInt(activeCooks)} cooking now</p>
                  <small>Products: Huntsman, Giant Huntsman, Weber Kettle (via Venom controller)</small>
                </div>
              </div>
            </section>
          </div>

          {/* Product Page UX Health */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Product Page UX Health</strong>
              <span className="venom-panel-hint">Clarity behavioral analytics — product pages</span>
            </div>
            {productPageHealth.length > 0 ? (
              <div className="venom-breakdown-list">
                {productPageHealth.map((page, idx) => {
                  const pageName = page.page_path.replace('/products/', '').replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) || page.page_path
                  return (
                    <div className="venom-breakdown-row" key={idx} style={{ flexDirection: 'column', alignItems: 'stretch', gap: 6, padding: '10px 0' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <strong>{pageName}</strong>
                        <div className="inline-badges">
                          <span className="badge badge-neutral">{fmtInt(page.sessions)} sessions</span>
                          <span className={`badge ${page.friction_score > 50 ? 'badge-bad' : page.friction_score > 25 ? 'badge-warn' : 'badge-good'}`}>
                            friction: {page.friction_score.toFixed(1)}
                          </span>
                        </div>
                      </div>
                      <div className="venom-breakdown-list" style={{ paddingLeft: 12, fontSize: '0.9em' }}>
                        <div className="venom-breakdown-row">
                          <span>Dead clicks</span>
                          <span className="venom-breakdown-val">{fmtInt(page.dead_clicks)} ({page.dead_click_pct.toFixed(1)}%)</span>
                        </div>
                        <div className="venom-breakdown-row">
                          <span>Rage clicks</span>
                          <span className="venom-breakdown-val">{fmtInt(page.rage_clicks)} ({page.rage_click_pct.toFixed(1)}%)</span>
                        </div>
                        <div className="venom-breakdown-row">
                          <span>Quick backs</span>
                          <span className="venom-breakdown-val">{fmtInt(page.quick_backs)} ({page.quick_back_pct.toFixed(1)}%)</span>
                        </div>
                        <div className="venom-breakdown-row">
                          <span>Script errors</span>
                          <span className="venom-breakdown-val">{fmtInt(page.script_errors)} ({page.script_error_pct.toFixed(1)}%)</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="state-message">Product page UX data will populate after next Clarity sync</div>
            )}
          </section>

          {/* Drill-down routes */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Drill-down routes</strong>
              <span className="venom-panel-hint">Click to explore</span>
            </div>
            <div className="venom-drill-grid">
              {DRILL_ROUTES.map((route) => (
                <Link key={route.path} to={route.path} className="venom-drill-tile">
                  <span className="venom-drill-icon">{route.icon}</span>
                  <div>
                    <strong>{route.label}</strong>
                    <small>{route.path}</small>
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
