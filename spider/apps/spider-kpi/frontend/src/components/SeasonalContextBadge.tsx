import { useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import type { MetricContextResponse, SeasonalVerdict } from '../lib/types'

/**
 * SeasonalContextBadge — tiny chip that tells you whether a metric is
 * running hot, cold, or normal for this time of year. Reads
 * /api/lore/metric-context and renders a color-coded pill with an
 * on-hover tooltip showing the full baseline distribution.
 *
 * Usage:
 *   <SeasonalContextBadge metric="revenue" onDate="2026-04-19" value={12400} />
 *
 * If `value` is omitted, the backend fetches the current value from the
 * source table itself.
 */

type Props = {
  metric: string
  onDate: string
  value?: number | null
  /** Compact: just a dot + 2-word label. Default shows delta % too. */
  compact?: boolean
}

const VERDICT_STYLE: Record<SeasonalVerdict, { color: string; bg: string; label: string }> = {
  running_very_hot: { color: '#22c55e', bg: 'rgba(34,197,94,0.16)',  label: 'Very hot' },
  running_hot:      { color: '#22c55e', bg: 'rgba(34,197,94,0.10)',  label: 'Hot' },
  normal:           { color: '#9ca3af', bg: 'rgba(255,255,255,0.05)', label: 'Normal' },
  running_cold:     { color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', label: 'Cold' },
  running_very_cold:{ color: '#ef4444', bg: 'rgba(239,68,68,0.12)',  label: 'Very cold' },
  no_baseline:      { color: '#9ca3af', bg: 'rgba(255,255,255,0.04)', label: 'No baseline' },
}

function fmtPct(n: number | null | undefined, opts: { sign?: boolean } = {}) {
  if (n == null) return '—'
  const sign = opts.sign && n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}%`
}

function fmtPctRank(r: number | null | undefined) {
  if (r == null) return '—'
  return `${Math.round(r * 100)}th pct`
}

export function SeasonalContextBadge({ metric, onDate, value, compact = false }: Props) {
  const [ctx, setCtx] = useState<MetricContextResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setError(null)
    api.loreMetricContext(metric, onDate, value ?? undefined, ctrl.signal)
      .then((res) => setCtx(res))
      .catch((e) => {
        if (ctrl.signal.aborted) return
        setError(e?.message || 'Failed to load context')
      })
    return () => ctrl.abort()
  }, [metric, onDate, value])

  if (error) return null
  if (!ctx) {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        padding: '2px 6px', borderRadius: 4, fontSize: 10,
        color: 'var(--muted)', background: 'rgba(255,255,255,0.04)',
      }}>
        …
      </span>
    )
  }

  const style = VERDICT_STYLE[ctx.verdict] || VERDICT_STYLE.no_baseline
  const tooltip = buildTooltip(ctx)

  return (
    <span
      title={tooltip}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '2px 8px',
        borderRadius: 10,
        fontSize: 10.5,
        fontWeight: 600,
        color: style.color,
        background: style.bg,
        border: `1px solid ${style.color}33`,
        lineHeight: 1.4,
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          width: 6, height: 6, borderRadius: '50%',
          background: style.color,
          boxShadow: (ctx.verdict === 'running_very_hot' || ctx.verdict === 'running_very_cold') ? `0 0 6px ${style.color}` : 'none',
        }}
      />
      <span>{style.label}</span>
      {!compact && ctx.delta_vs_median_pct != null && ctx.verdict !== 'no_baseline' && (
        <span style={{ color: 'var(--muted)', fontWeight: 500 }}>
          {fmtPct(ctx.delta_vs_median_pct, { sign: true })}
        </span>
      )}
    </span>
  )
}

function buildTooltip(ctx: MetricContextResponse): string {
  const b = ctx.baseline
  const cv = ctx.current_value
  const lines = [
    `${ctx.metric} on ${ctx.on_date} (day ${ctx.day_of_year})`,
    cv != null ? `Current: ${cv.toLocaleString()}` : 'Current: —',
    `Rank: ${fmtPctRank(ctx.percentile_rank)} vs ${ctx.year_count} prior years`,
    `vs median: ${fmtPct(ctx.delta_vs_median_pct, { sign: true })}`,
    '',
    `Baseline (prior years, same day-of-year):`,
    `  p10 ${b.p10?.toLocaleString() ?? '—'}  ·  p25 ${b.p25?.toLocaleString() ?? '—'}`,
    `  p50 ${b.p50?.toLocaleString() ?? '—'}  ·  p75 ${b.p75?.toLocaleString() ?? '—'}`,
    `  p90 ${b.p90?.toLocaleString() ?? '—'}`,
  ]
  return lines.join('\n')
}
