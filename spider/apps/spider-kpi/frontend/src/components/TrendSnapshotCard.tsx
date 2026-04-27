import { useEffect, useState } from 'react'
import { KpiTargetsPanel } from './KpiTargetsPanel'
import type { KpiTargetRow } from '../lib/api'

/**
 * Whole-business pulse card for the Command Center morning view.
 *
 * For each registered metric:
 *   • current  = mean of the 7 most-recent daily values
 *   • prior    = mean of the 7 daily values immediately before
 *   • delta    = (current − prior) / |prior| × 100
 *   • anomaly  = z-score of current vs the prior 28-day daily-mean baseline
 *   • target   = operator-set value (resolves seasonally) — when present,
 *                tile shows "X% of target" and tints by hit/miss.
 *
 * Click "Set targets" to open the KpiTargetsPanel where Joseph configures
 * seasonal target windows (Spring grilling vs winter off-season, etc).
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
  target?: KpiTargetRow | null
  target_progress_pct?: number | null
  target_hit?: boolean | null
  error?: string
}

interface AllTrendsResponse {
  generated_at: string
  methodology?: Record<string, string>
  metrics: Record<string, MetricEntry>
}

const ARROW: Record<Trend7d['direction'], string> = { up: '↑', down: '↓', flat: '·' }

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

// Default direction for the targets panel when creating a new target.
// 'min' = at-or-above is good (revenue, orders). 'max' = at-or-below
// is good (tickets, errors, first-response-time).
export const METRIC_DIRECTION_DEFAULT: Record<string, 'min' | 'max'> = {
  revenue: 'min',
  orders: 'min',
  cook_success_rate: 'min',
  active_devices: 'min',
  telemetry_sessions: 'min',
  csat: 'min',
  telemetry_errors: 'max',
  tickets_created: 'max',
  first_response_time: 'max',
}

export const METRIC_LABELS: Record<string, string> = {
  revenue: 'Revenue',
  orders: 'Orders',
  cook_success_rate: 'Cook success rate',
  active_devices: 'Active devices',
  telemetry_sessions: 'Cook sessions',
  telemetry_errors: 'Telemetry errors',
  tickets_created: 'Tickets created',
  csat: 'CSAT',
  first_response_time: 'First-response time',
}

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

function formatTarget(metric_key: string, raw: number): string {
  return formatValue(metric_key, raw)
}

export function TrendSnapshotCard() {
  const [data, setData] = useState<AllTrendsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [showTargets, setShowTargets] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    fetch('/api/trends/all', { signal: ctl.signal, credentials: 'include' })
      .then(r => r.json())
      .then(d => setData(d as AllTrendsResponse))
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [refresh])

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
      <div className="venom-panel-head" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <strong>7-day pulse</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, lineHeight: 1.5 }}>
            Each tile shows the <strong>mean of the last 7 daily values</strong>, with the % delta
            comparing it to the <strong>mean of the 7 daily values before that</strong>. The orange ⚠
            flags moderate-or-greater anomalies vs the prior 28-day daily-mean baseline.
            {anomalies.length > 0
              ? <> · <span style={{ color: 'var(--orange)', fontWeight: 600 }}>{anomalies.length} active anomal{anomalies.length === 1 ? 'y' : 'ies'}</span></>
              : ' · No active anomalies.'}
          </div>
        </div>
        <button
          onClick={() => setShowTargets(true)}
          title="Set or edit operator targets per metric, with seasonal windows"
          style={{
            background: 'var(--panel-2)',
            border: '1px solid rgba(255,255,255,0.1)',
            color: 'var(--text)',
            padding: '4px 10px',
            borderRadius: 4,
            fontSize: 11,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          🎯 Set targets
        </button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))',
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
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{m.error ? 'error' : 'no data'}</div>
              </div>
            )
          }
          const ac = arrowColor(m)
          const isAnom = m.anomaly && (m.anomaly.severity === 'moderate' || m.anomaly.severity === 'critical')

          // Target border color (overrides anomaly border when present)
          let leftBorder = '2px solid transparent'
          if (m.target_hit === true) leftBorder = '2px solid var(--green)'
          else if (m.target_hit === false) leftBorder = '2px solid var(--red)'
          else if (isAnom) leftBorder = '2px solid var(--orange)'

          return (
            <div
              key={k}
              style={{
                padding: 10,
                background: 'var(--panel-2)',
                borderRadius: 6,
                borderLeft: leftBorder,
              }}
              title={
                `Current (mean of last 7 daily values): ${m.trend_7d.current.toFixed(2)}\n`
                + `Prior (mean of 7 days before that):    ${m.trend_7d.prior.toFixed(2)}\n`
                + `Δ: ${m.trend_7d.delta_pct != null ? m.trend_7d.delta_pct.toFixed(1) + '%' : '—'}\n`
                + `28-day baseline mean: ${m.anomaly?.baseline_mean.toFixed(2)}\n`
                + `Anomaly: z=${m.anomaly?.z_score.toFixed(2)} (${m.anomaly?.severity})`
                + (m.target ? `\n\nTarget: ${formatTarget(k, m.target.target_value)} (${m.target.direction === 'max' ? 'cap' : 'floor'}${m.target.season_label ? ', ' + m.target.season_label : ''})` : '\n\nNo target set — click "Set targets" to add one.')
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
              {m.target ? (
                <div style={{ fontSize: 10, marginTop: 3, color: m.target_hit === true ? 'var(--green)' : m.target_hit === false ? 'var(--red)' : 'var(--muted)', fontWeight: 600, letterSpacing: 0.3 }}>
                  {m.target_progress_pct != null ? `${m.target_progress_pct.toFixed(0)}% of target` : '—'}
                  <span style={{ color: 'var(--muted)', fontWeight: 400, marginLeft: 4 }}>
                    ({m.target.direction === 'max' ? '≤' : '≥'} {formatTarget(k, m.target.target_value)})
                  </span>
                </div>
              ) : (
                <div style={{ fontSize: 10, marginTop: 3, color: 'var(--muted)', fontStyle: 'italic' }}>
                  no target set
                </div>
              )}
              {isAnom && (
                <div style={{ fontSize: 10, color: 'var(--orange)', marginTop: 2, fontWeight: 600, letterSpacing: 0.3 }}>
                  ⚠ {m.anomaly!.severity.toUpperCase()} z={m.anomaly!.z_score.toFixed(1)}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {showTargets && (
        <KpiTargetsPanel
          metrics={ORDER}
          onClose={() => { setShowTargets(false); setRefresh(r => r + 1) }}
        />
      )}
    </section>
  )
}
