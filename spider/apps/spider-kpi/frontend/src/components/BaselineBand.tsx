import { useEffect, useRef, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { api } from '../lib/api'
import type { SeasonalBaselineRow } from '../lib/types'

/**
 * BaselineBand — trend chart that overlays the seasonal p10–p90 + p25–p75
 * bands and median line for a metric, with the caller's current-period
 * series drawn on top.
 *
 * Answers "is this value normal for this time of year?" at a glance.
 *
 * Usage:
 *   <BaselineBand metric="revenue" start="2026-04-01" end="2026-04-19"
 *                 currentSeries={rangeRows.map(r => ({ date: r.business_date, value: r.revenue }))}
 *                 currentLabel="Revenue"
 *                 color="#6ea8ff" />
 */

type CurrentPoint = { date: string; value: number | null }

type Props = {
  metric: string
  start: string
  end: string
  /** Current-period observed values, one per date. Dates should match the
   *  baseline range day-for-day; mismatched dates are rendered by date-join. */
  currentSeries?: CurrentPoint[]
  currentLabel?: string
  color?: string
  height?: number
  /** Y-axis label formatter (e.g. currency, percent). */
  valueFormatter?: (v: number) => string
}

type MergedRow = SeasonalBaselineRow & {
  current: number | null
}

export function BaselineBand({
  metric,
  start,
  end,
  currentSeries,
  currentLabel = 'Current',
  color = '#6ea8ff',
  height = 280,
  valueFormatter,
}: Props) {
  const [rows, setRows] = useState<SeasonalBaselineRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setError(null)
    api.loreSeasonalBaseline(metric, start, end, ctrl.signal)
      .then((res) => {
        setRows(res.baseline)
        setLoading(false)
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return
        setError(e?.message || 'Failed to load baseline')
        setLoading(false)
      })
    return () => ctrl.abort()
  }, [metric, start, end])

  if (loading) return <div className="state-message">Loading seasonal baseline…</div>
  if (error) return <div className="state-message error">{error}</div>
  if (!rows || rows.length === 0) return <div className="state-message">No baseline data.</div>

  const byDate = new Map<string, number | null>()
  for (const p of currentSeries || []) byDate.set(p.date, p.value)

  const merged: MergedRow[] = rows.map((r) => ({
    ...r,
    current: byDate.has(r.date) ? byDate.get(r.date) ?? null : null,
  }))

  const yearCountMax = Math.max(0, ...rows.map((r) => r.year_count))
  const fmt = valueFormatter || ((v: number) => v.toLocaleString())

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={merged}>
          <CartesianGrid stroke="rgba(255,255,255,0.08)" />
          <XAxis dataKey="date" stroke="#9fb0d4" />
          <YAxis stroke="#9fb0d4" tickFormatter={(v) => fmt(Number(v))} />
          <Tooltip
            contentStyle={{ background: '#0f1624', border: '1px solid #1f2a3d', fontSize: 12 }}
            formatter={(val: any, name: string) => {
              if (Array.isArray(val)) {
                const [lo, hi] = val
                return [`${fmt(Number(lo))} – ${fmt(Number(hi))}`, name]
              }
              return [val == null ? '—' : fmt(Number(val)), name]
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />

          <Area
            type="monotone"
            name="p10–p90 band"
            dataKey={(d: MergedRow) => [d.p10 ?? null, d.p90 ?? null]}
            stroke="none"
            fill={color}
            fillOpacity={0.10}
            isAnimationActive={false}
            connectNulls
          />
          <Area
            type="monotone"
            name="p25–p75 band"
            dataKey={(d: MergedRow) => [d.p25 ?? null, d.p75 ?? null]}
            stroke="none"
            fill={color}
            fillOpacity={0.22}
            isAnimationActive={false}
            connectNulls
          />
          <Line
            type="monotone"
            name="Median (p50)"
            dataKey="p50"
            stroke={color}
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
          />
          {currentSeries && currentSeries.length > 0 && (
            <Line
              type="monotone"
              name={currentLabel}
              dataKey="current"
              stroke="#ffffff"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6, display: 'flex', justifyContent: 'space-between' }}>
        <span>Baseline: p10/p25/p50/p75/p90 by day-of-year from prior years ({yearCountMax}y max).</span>
        <span>Current year excluded.</span>
      </div>
    </div>
  )
}
