import { useEffect, useState } from 'react'

/**
 * "Whole-business pulse" card for the Command Center morning view.
 *
 * Renders all 9 registered trend metrics as a compact 7d-vs-prior-7d
 * grid with arrow + % + tiny anomaly chip. Pulls /api/trends/all in
 * one round-trip so this is cheap to drop above the morning briefing.
 *
 * Color rule matches TrendPill: ↑ on an up_is_good metric is green;
 * ↑ on tickets_created / first_response_time / telemetry_errors is red.
 */

interface Trend7d {
  current: number
  prior: number
  delta_abs: number
  delta_pct: number | null
  direction: 'up' | 'down' | 'flat'
}

interface Anomaly {
  z_score: number
  severity: 'normal' | 'mild' | 'moderate' | 'critical'
  direction: 'above' | 'below' | 'flat'
  baseline_mean: number
}

interface MetricEntry {
  label?: string
  available?: boolean
  up_is_good?: boolean
  trend_7d?: Trend7d
  anomaly?: Anomaly
  error?: string
}

interface AllTrendsResponse {
  generated_at: string
  metrics: Record<string, MetricEntry>
}

const ARROW: Record<Trend7d['direction'], string> = {
  up: '↑',
  down: '↓',
  flat: '·',
}

// Render order — most-watched metrics first.
const ORDER = [
  'revenue',
  'orders',
  'cook_success_rate',
  'active_devices',
  'telemetry_sessions',
  'telemetry_errors',
  'tickets_created',
  'csat',
  'first_response_time',
]

function arrowColor(metric: MetricEntry): string {
  if (!metric.trend_7d || !metric.available) return 'var(--muted)'
  const up = metric.trend_7d.direction === 'up'
  const down = metric.trend_7d.direction === 'down'
  if (up) return metric.up_is_good ? 'var(--green)' : 'var(--red)'
  if (down) return metric.up_is_good ? 'var(--red)' : 'var(--green)'
  return 'var(--muted)'
}

function formatValue(metric_key: string, raw: number): string {
  if (metric_key === 'revenue') return `$${raw.toFixed(0)}`
  if (metric_key === 'cook_success_rate') return `${(raw * 100).toFixed(0)}%`
  if (metric_key === 'first_response_time') return raw.toFixed(1)
  if (metric_key === 'csat') return raw.toFixed(2)
  return Math.round(raw).toString()
}

export function TrendSnapshotCard() {
  const [data, setData] = useState<AllTrendsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    fetch('/api/trends/all', { signal: ctl.signal, credentials: 'include' })
      .then(r => r.json())
      .then(d => setData(d as AllTrendsResponse))
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--muted)' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>Trend snapshot unavailable: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--muted)' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>Loading 7-day trend snapshot…</div>
      </section>
    )
  }

  // Anomaly summary — count moderate+ across all metrics
  const anomalies = ORDER
    .map(k => ({ key: k, m: data.metrics[k] }))
    .filter(({ m }) => m?.anomaly && (m.anomaly.severity === 'moderate' || m.anomaly.severity === 'critical'))

  return (
    <section
      className="card"
      style={{
        borderLeft: anomalies.length > 0 ? '3px solid var(--orange)' : '3px solid var(--blue)',
      }}
    >
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>7-day trend snapshot</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            All registered KPIs vs the prior 7 days.
            {anomalies.length > 0
              ? <> · <span style={{ color: 'var(--orange)', fontWeight: 600 }}>{anomalies.length} moderate+ anomal{anomalies.length === 1 ? 'y' : 'ies'}</span> vs 28-day baseline</>
              : ' · No anomalies above 2.5σ.'}
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))',
          gap: 8,
          marginTop: 12,
        }}
      >
        {ORDER.map(k => {
          const m = data.metrics[k]
          if (!m) return null
          if (m.error || !m.available || !m.trend_7d) {
            return (
              <div key={k} style={{ padding: 10, background: 'var(--panel-2)', borderRadius: 6, opacity: 0.6 }}>
                <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--muted)', letterSpacing: 0.5 }}>{m.label || k}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  {m.error ? 'error' : 'no data'}
                </div>
              </div>
            )
          }
          const ac = arrowColor(m)
          const isAnom = m.anomaly && (m.anomaly.severity === 'moderate' || m.anomaly.severity === 'critical')
          return (
            <div
              key={k}
              style={{
                padding: 10,
                background: 'var(--panel-2)',
                borderRadius: 6,
                borderLeft: isAnom ? '2px solid var(--orange)' : '2px solid transparent',
              }}
              title={
                `Current 7d avg: ${m.trend_7d.current.toFixed(2)}\n`
                + `Prior 7d avg: ${m.trend_7d.prior.toFixed(2)}\n`
                + `28d baseline: ${m.anomaly?.baseline_mean.toFixed(2)} (z=${m.anomaly?.z_score.toFixed(2)}, ${m.anomaly?.severity})`
              }
            >
              <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--muted)', letterSpacing: 0.5 }}>{m.label || k}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 4 }}>
                <span style={{ fontSize: 16, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                  {formatValue(k, m.trend_7d.current)}
                </span>
                <span style={{ fontSize: 12, fontWeight: 600, color: ac, fontVariantNumeric: 'tabular-nums' }}>
                  {ARROW[m.trend_7d.direction]} {m.trend_7d.delta_pct == null ? '—' : `${m.trend_7d.delta_pct > 0 ? '+' : ''}${m.trend_7d.delta_pct.toFixed(1)}%`}
                </span>
              </div>
              {isAnom && (
                <div style={{ fontSize: 10, color: 'var(--orange)', marginTop: 2, fontWeight: 600, letterSpacing: 0.3 }}>
                  ⚠ {m.anomaly!.severity.toUpperCase()} z={m.anomaly!.z_score.toFixed(1)}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
