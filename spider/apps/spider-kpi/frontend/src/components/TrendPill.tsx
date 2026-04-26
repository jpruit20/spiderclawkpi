import { useEffect, useState } from 'react'

/**
 * Compact 7d-vs-prior-7d trend chip with arrow + % change, plus an
 * optional anomaly badge. Renders inline (e.g. next to a KPI number)
 * to give the dashboard "is this normal" context everywhere.
 *
 *   <TrendPill metricKey="cook_success_rate" />
 *
 * Pulls /api/trends/{metricKey} on mount. Anomaly severity ≥ moderate
 * gets a colored ⚠ badge; mild/normal anomalies render plain.
 */

interface TrendData {
  label: string
  available: boolean
  up_is_good: boolean
  trend_7d: {
    current: number
    prior: number
    delta_abs: number
    delta_pct: number | null
    direction: 'up' | 'down' | 'flat'
  }
  anomaly: {
    current: number
    baseline_mean: number
    baseline_std: number
    z_score: number
    severity: 'normal' | 'mild' | 'moderate' | 'critical'
    direction: 'above' | 'below' | 'flat'
    n_observations: number
  }
}

const ARROW: Record<TrendData['trend_7d']['direction'], string> = {
  up: '↑',
  down: '↓',
  flat: '·',
}

interface Props {
  metricKey: string
  showLabel?: boolean
  size?: 'sm' | 'md'
}

export function TrendPill({ metricKey, showLabel = false, size = 'sm' }: Props) {
  const [data, setData] = useState<TrendData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    fetch(`/api/trends/${metricKey}`, { signal: ctl.signal, credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.error || !d.available) {
          setError(d.error || 'no data')
          return
        }
        setData(d as TrendData)
      })
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [metricKey])

  if (error || !data) return null

  const { trend_7d, anomaly, up_is_good, label } = data
  // Color the trend arrow based on whether it's directionally good/bad
  // for this metric. Up isn't always green — tickets going up is bad.
  let trendColor = 'var(--muted)'
  if (trend_7d.direction === 'up') trendColor = up_is_good ? 'var(--green)' : 'var(--red)'
  else if (trend_7d.direction === 'down') trendColor = up_is_good ? 'var(--red)' : 'var(--green)'

  // Anomaly badge — only show on moderate/critical
  const showAnomaly = anomaly.severity === 'moderate' || anomaly.severity === 'critical'
  // Anomaly direction is only "bad" if it's above-baseline for an
  // up-is-bad metric, or below-baseline for an up-is-good metric.
  const anomalyIsBad = (
    (anomaly.direction === 'above' && !up_is_good)
    || (anomaly.direction === 'below' && up_is_good)
  )
  const anomalyColor = anomalyIsBad
    ? (anomaly.severity === 'critical' ? 'var(--red)' : 'var(--orange)')
    : 'var(--muted)'

  const fontSize = size === 'sm' ? 11 : 13
  const pad = size === 'sm' ? '2px 6px' : '3px 8px'

  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 4 }}>
      {showLabel && <span style={{ fontSize, color: 'var(--muted)' }}>{label}</span>}
      <span
        title={
          `7-day avg ${trend_7d.current.toFixed(2)} vs prior ${trend_7d.prior.toFixed(2)} `
          + `(Δ${trend_7d.delta_abs >= 0 ? '+' : ''}${trend_7d.delta_abs.toFixed(2)})`
        }
        style={{
          fontSize,
          padding: pad,
          borderRadius: 4,
          background: 'var(--panel-2)',
          color: trendColor,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {ARROW[trend_7d.direction]} {trend_7d.delta_pct == null ? '—' : `${trend_7d.delta_pct > 0 ? '+' : ''}${trend_7d.delta_pct.toFixed(1)}%`}
      </span>
      {showAnomaly && (
        <span
          title={
            `${anomaly.severity} anomaly: z=${anomaly.z_score.toFixed(1)} `
            + `(current ${anomaly.current.toFixed(2)} vs baseline ${anomaly.baseline_mean.toFixed(2)} ± ${anomaly.baseline_std.toFixed(2)})`
          }
          style={{
            fontSize: fontSize - 1,
            padding: '1px 5px',
            borderRadius: 3,
            background: 'var(--panel-2)',
            color: anomalyColor,
            fontWeight: 700,
            letterSpacing: 0.5,
          }}
        >
          ⚠ {anomaly.severity.toUpperCase()}
        </span>
      )}
    </span>
  )
}
