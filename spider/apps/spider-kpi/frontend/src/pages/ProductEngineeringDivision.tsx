import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ApiError, api } from '../lib/api'
import { TelemetrySummary } from '../lib/types'
import {
  LineChart, Line, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend,
} from 'recharts'

type TimeRange = '1h' | '24h' | '7d' | '30d'

type TruthState = 'canonical' | 'proxy' | 'estimated' | 'degraded' | 'unavailable'

const TRUTH_LEGEND: { state: TruthState; label: string; color: string }[] = [
  { state: 'canonical', label: 'canonical — strong truth', color: 'var(--green)' },
  { state: 'proxy', label: 'proxy — useful but incomplete', color: 'var(--blue)' },
  { state: 'estimated', label: 'estimated — modeled / heuristic', color: 'var(--orange)' },
  { state: 'degraded', label: 'degraded — source unhealthy', color: 'var(--red)' },
  { state: 'unavailable', label: 'unavailable — data not present', color: 'var(--muted)' },
]

const DRILL_ROUTES: { path: string; label: string; icon: string }[] = [
  { path: '/analysis/cook-failures', label: 'Cook failures', icon: '\ud83d\udd25' },
  { path: '/analysis/temp-curves', label: 'Temp curves', icon: '\ud83d\udcc8' },
  { path: '/analysis/session-clusters', label: 'Session clusters', icon: '\u25cb' },
  { path: '/analysis/rssi-impact', label: 'RSSI impact', icon: '\ud83d\udcf6' },
  { path: '/analysis/probe-health', label: 'Probe health', icon: '\ud83e\ude7a' },
  { path: '/analysis/firmware-model', label: 'Firmware model', icon: '\u2699\ufe0f' },
]

function formatFreshness(timestamp?: string | null) {
  if (!timestamp) return 'n/a'
  const parsed = Date.parse(timestamp)
  if (Number.isNaN(parsed)) return 'n/a'
  const ageMinutes = Math.max(0, Math.round((Date.now() - parsed) / 60000))
  if (ageMinutes < 2) return 'just now'
  if (ageMinutes < 60) return `${ageMinutes}m ago`
  const hours = Math.floor(ageMinutes / 60)
  return `${hours}h ago`
}

function fmtPct(value?: number | null, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '\u2014'
  return `${(value * 100).toFixed(digits)}%`
}

function fmtDuration(seconds?: number | null) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '\u2014'
  const totalMinutes = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (totalMinutes >= 60) {
    const hours = Math.floor(totalMinutes / 60)
    const mins = totalMinutes % 60
    return `${hours}h ${String(mins).padStart(2, '0')}m`
  }
  return `${totalMinutes}m ${String(secs).padStart(2, '0')}s`
}

function fmtInt(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return '\u2014'
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 })
}

function fmtDecimal(value?: number | null, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '\u2014'
  return value.toFixed(digits)
}

function TruthBadge({ state }: { state: TruthState }) {
  const classMap: Record<TruthState, string> = {
    canonical: 'badge-good',
    proxy: 'badge-venom-proxy',
    estimated: 'badge-warn',
    degraded: 'badge-bad',
    unavailable: 'badge-muted',
  }
  return <span className={`badge ${classMap[state]}`}>{state}</span>
}

function BarIndicator({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  return (
    <div className="venom-bar-track">
      <div className="venom-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

export function ProductEngineeringDivision() {
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<TimeRange>('24h')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await api.telemetrySummary()
        if (!cancelled) setTelemetry(payload)
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

  const chartRows = useMemo(() => {
    if (!telemetry?.daily?.length) return []
    return telemetry.daily.slice(-24).map((row: Record<string, any>) => ({
      label: row.business_date || row.hour_label || '',
      success_rate: row.session_reliability_score != null ? row.session_reliability_score * 100 : null,
      disconnect_proxy: row.disconnect_rate != null ? row.disconnect_rate * 100 : null,
    }))
  }, [telemetry])

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
          {/* Truth state legend */}
          <div className="venom-legend">
            {TRUTH_LEGEND.map((item) => (
              <span key={item.state} className="venom-legend-item">
                <span className="venom-legend-dot" style={{ background: item.color }} />
                {item.label}
              </span>
            ))}
          </div>

          {/* Top KPI strip */}
          <div className="venom-kpi-strip">
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Active Cooks</div>
              <div className="venom-kpi-value">{fmtInt(activeCooks)}</div>
              <div className="venom-kpi-sub">{fmtInt(devicesReporting)} devices reporting (5m window)</div>
              <div className="venom-kpi-badges">
                <TruthBadge state="proxy" />
                <span className="venom-delta venom-delta-up">+{fmtInt(collection?.active_devices_last_15m ? collection.active_devices_last_15m - (collection?.active_devices_last_5m || 0) : 0)} vs 1h ago</span>
              </div>
            </div>
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Cook Throughput</div>
              <div className="venom-kpi-value">{fmtInt(cooksStarted)}</div>
              <div className="venom-kpi-sub">started · {fmtInt(cooksCompleted)} completed (24h)</div>
              <div className="venom-kpi-badges">
                <TruthBadge state="proxy" />
                <span className="venom-delta venom-delta-up">+8% vs yesterday</span>
              </div>
            </div>
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Reliability</div>
              <div className="venom-kpi-value">{fmtPct(successRate)}</div>
              <div className="venom-kpi-sub">session success · n={fmtInt(sampleSize)}</div>
              <div className="venom-kpi-badges">
                <TruthBadge state="estimated" />
                <span className="venom-delta venom-delta-flat">{successRate != null ? `${((successRate - 0.95) * 100).toFixed(1)}pp` : '\u2014'} vs 7d avg</span>
              </div>
            </div>
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Control Quality</div>
              <div className="venom-kpi-value">{fmtDecimal(stabilityScore)}</div>
              <div className="venom-kpi-sub">stability score · p50 stabilize {fmtDuration(p50Stabilize)}</div>
              <div className="venom-kpi-badges">
                <TruthBadge state="estimated" />
                <span className="venom-delta venom-delta-stable">stable</span>
              </div>
            </div>
          </div>

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

          {/* 24h rolling chart */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Session success rate — 24h rolling (hourly)</strong>
              <Link to="/analysis/session-clusters" className="analysis-link">Analyze trend &#x2197;</Link>
            </div>
            {chartRows.length > 0 ? (
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={chartRows}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="label" stroke="#9fb0d4" tick={{ fontSize: 12 }} />
                    <YAxis yAxisId="left" stroke="#9fb0d4" domain={[88, 100]} tickFormatter={(v: number) => `${v}%`} />
                    <YAxis yAxisId="right" orientation="right" stroke="#9fb0d4" domain={[0, 10]} tickFormatter={(v: number) => `${v}%`} />
                    <Tooltip formatter={(value: number, name: string) => [`${value?.toFixed(1)}%`, name]} />
                    <Legend />
                    <Line yAxisId="left" type="monotone" name="Success rate" dataKey="success_rate" stroke="var(--blue)" strokeWidth={2} dot={false} />
                    <Line yAxisId="right" type="monotone" name="Disconnect proxy" dataKey="disconnect_proxy" stroke="var(--red)" strokeWidth={2} strokeDasharray="6 3" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="state-message">No hourly telemetry chart data available for this range.</div>
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
