import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ApiError, api } from '../lib/api'
import { fmtPct, fmtInt, fmtDecimal, fmtDuration, formatFreshness } from '../lib/format'
import { ClarityPageMetric, TelemetryHistoryDailyRow, TelemetrySummary } from '../lib/types'
import {
  BarChart, Bar, ResponsiveContainer, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Line, Area, ComposedChart,
} from 'recharts'

type TimeRange = '1h' | '24h' | '7d' | '30d'

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

export function ProductEngineeringDivision() {
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [productPageHealth, setProductPageHealth] = useState<ClarityPageMetric[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<TimeRange>('24h')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [payload, pageHealth] = await Promise.all([
          api.telemetrySummary(),
          api.clarityPageHealth().catch(() => [] as ClarityPageMetric[]),
        ])
        if (!cancelled) {
          setTelemetry(payload)
          setProductPageHealth(pageHealth)
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

          {/* Top KPI strip */}
          <div className="venom-kpi-strip">
            <div className="venom-kpi-card">
              <div className="venom-kpi-label">Active Cooks</div>
              <div className="venom-kpi-value">{fmtInt(activeCooks)}</div>
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
              <div className="venom-kpi-value">{fmtPct(successRate)}</div>
              <div className="venom-kpi-sub">session success · n={fmtInt(sampleSize)}</div>
              <div className="venom-kpi-badges">
                <TruthBadge state="estimated" />
                {historyStats ? <span className="venom-delta venom-delta-flat">30d error rate: {fmtPct(historyStats.errorRate30)}</span> : null}
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

          {/* Fleet Activity + Error Trend (main chart) */}
          <section className="card">
            <div className="venom-panel-head">
              <div>
                <strong>Fleet Activity — Daily Active Devices</strong>
                <p className="venom-chart-sub">Unique Venom controllers reporting each day across Huntsman, Giant Huntsman, and Weber Kettle grills</p>
              </div>
              {historyStats?.peakDay ? <span className="venom-panel-hint">Peak: {historyStats.peakDay.active_devices} devices on {historyStats.peakDay.business_date}</span> : null}
            </div>
            {fleetChartRows.length > 0 ? (
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height={320}>
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
