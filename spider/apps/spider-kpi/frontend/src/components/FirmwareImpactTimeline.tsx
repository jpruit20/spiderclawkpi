import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis, Scatter,
} from 'recharts'
import { api } from '../lib/api'
import type { FirmwareImpactTimelineResponse, FirmwareImpactWeek } from '../lib/types'

/**
 * Weekly PID-quality trend, colored by the dominant firmware active
 * each week, with firmware release markers overlaid from ClickUp.
 *
 * The question this chart answers: "When we shipped firmware X.Y.Z, did
 * in-control % actually improve?" Vertical lines mark release dates;
 * line-segment color changes when the dominant firmware version flips.
 *
 * Two overlay series available on the same chart:
 *   - in_control_pct (%) — PID performance
 *   - held_target_rate (%) — headline success metric
 *
 * Caller can toggle between them via the metric selector.
 */

// Stable palette for firmware-color segments. We deterministically map
// each firmware version to one of these; the same firmware gets the
// same color across every render.
const FW_COLORS = [
  '#6ea8ff', '#22c55e', '#f59e0b', '#ef4444',
  '#a78bfa', '#f472b6', '#38bdf8', '#fb923c', '#eab308', '#14b8a6',
]

function hashFirmwareColor(fw: string | null): string {
  if (!fw) return '#9ca3af'
  let h = 0
  for (let i = 0; i < fw.length; i++) h = (h * 31 + fw.charCodeAt(i)) >>> 0
  return FW_COLORS[h % FW_COLORS.length]
}

type Metric = 'in_control' | 'held_target'

export function FirmwareImpactTimeline({ weeks = 26 }: { weeks?: number }) {
  const [resp, setResp] = useState<FirmwareImpactTimelineResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [metric, setMetric] = useState<Metric>('in_control')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.firmwareImpactTimeline(weeks)
      .then(r => { if (!cancelled) setResp(r) })
      .catch(() => { /* silent — null handled below */ })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [weeks])

  const { chartData, firmwareSegments, validWeeks, scatterData, domain } = useMemo(() => {
    const series = resp?.series || []
    const chart = series.map(w => ({
      week_start: w.week_start,
      in_control: w.in_control_pct != null ? Number((w.in_control_pct * 100).toFixed(1)) : null,
      held_target: w.held_target_rate != null ? Number((w.held_target_rate * 100).toFixed(1)) : null,
      dominant: w.dominant_firmware,
      sessions: w.sessions,
      avg_recovery: w.avg_recovery_seconds,
      avg_disturbances: w.avg_disturbances_per_cook,
    }))

    // Group contiguous weeks sharing the same dominant firmware into
    // colored segments so the line visually changes color at version
    // boundaries. We implement this by generating per-firmware duplicate
    // keys with null values outside the segment — Recharts then renders
    // each as a distinct colored line.
    const firmwareSet = Array.from(new Set(series.map(w => w.dominant_firmware).filter((v): v is string => !!v)))
    const segmented: Record<string, number | null | string>[] = chart.map(row => {
      const copy: Record<string, number | null | string> = {
        week_start: row.week_start as string,
        sessions: row.sessions,
        avg_recovery: row.avg_recovery == null ? null : row.avg_recovery,
        avg_disturbances: row.avg_disturbances == null ? null : row.avg_disturbances,
        dominant: row.dominant as string,
      }
      for (const fw of firmwareSet) {
        const isMatch = row.dominant === fw
        copy[`fw_${fw}_${metric}`] = isMatch ? (metric === 'in_control' ? row.in_control : row.held_target) : null
      }
      return copy
    })

    // Build scatter for legit (non-sparse) weeks to highlight firmware
    // version on dots (helps the color-shift pop).
    const scatter = chart
      .filter(r => metric === 'in_control' ? r.in_control != null : r.held_target != null)
      .map(r => ({
        week_start: r.week_start,
        value: metric === 'in_control' ? r.in_control : r.held_target,
        dominant: r.dominant,
      }))

    // Y-axis domain for both metrics: ~50-100% covers typical PID quality;
    // pin to [0, 100] so the axis is intuitively comparable.
    const domain: [number, number] = [40, 100]

    return {
      chartData: segmented,
      firmwareSegments: firmwareSet,
      validWeeks: chart.filter(r => (metric === 'in_control' ? r.in_control != null : r.held_target != null)).length,
      scatterData: scatter,
      domain,
    }
  }, [resp, metric])

  if (loading) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Firmware impact on PID quality</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }
  if (!resp || !resp.ok) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Firmware impact on PID quality</strong></div>
        <div className="state-message">No timeline data yet.</div>
      </section>
    )
  }
  if (validWeeks === 0) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--orange)' }}>
        <div className="venom-panel-head">
          <strong>Firmware impact on PID quality</strong>
          <span className="venom-panel-hint">pending data</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          No weeks meet the minimum session threshold for in-control % yet. Once the backfill completes and the
          rederive_session_quality script populates the new-model columns, this chart will plot weekly PID quality
          colored by dominant firmware, with release markers from ClickUp.
        </p>
      </section>
    )
  }

  const firmwareReleases = resp.firmware_releases || []

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Firmware impact on PID quality</strong>
          <p className="venom-chart-sub">
            Weekly {metric === 'in_control' ? 'in-control % (PID performance during non-disturbance windows)' : 'held-target rate (of target-seeking cooks)'},
            line segments colored by the firmware version most active that week.
            Dashed verticals are firmware-release dates from ClickUp.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <button
            className={`range-button${metric === 'in_control' ? ' active' : ''}`}
            style={{ fontSize: 11 }}
            onClick={() => setMetric('in_control')}
          >
            In-control %
          </button>
          <button
            className={`range-button${metric === 'held_target' ? ' active' : ''}`}
            style={{ fontSize: 11 }}
            onClick={() => setMetric('held_target')}
          >
            Held-target
          </button>
        </div>
      </div>

      <div className="chart-wrap" style={{ marginTop: 8 }}>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={chartData} margin={{ top: 14, right: 22, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
            <XAxis
              dataKey="week_start"
              tick={{ fontSize: 10 }}
              stroke="var(--muted)"
              tickFormatter={(d: string) => (d || '').slice(5)}
            />
            <YAxis
              tick={{ fontSize: 10 }}
              stroke="var(--muted)"
              domain={domain}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }}
              formatter={(value: number | null | undefined, name: string) =>
                value == null ? null : [`${value}%`, name.replace(/^fw_/, '').replace(/_in_control$/, '').replace(/_held_target$/, '')]
              }
              labelFormatter={(label: string) => `Week of ${label}`}
            />
            {/* One line per firmware segment; only the matching week's value
                is non-null so Recharts draws each version in its own color. */}
            {firmwareSegments.map((fw) => (
              <Line
                key={fw}
                type="monotone"
                dataKey={`fw_${fw}_${metric}`}
                stroke={hashFirmwareColor(fw)}
                strokeWidth={2.5}
                connectNulls={false}
                dot={{ r: 3, strokeWidth: 0, fill: hashFirmwareColor(fw) }}
                activeDot={{ r: 5 }}
                name={fw}
              />
            ))}
            {/* Firmware release markers */}
            {firmwareReleases.map((release, i) => (
              <ReferenceLine
                key={i}
                x={release.date}
                stroke="rgba(248, 113, 113, 0.55)"
                strokeDasharray="3 3"
                label={{
                  value: `release`,
                  position: 'top',
                  fill: 'rgba(248, 113, 113, 0.75)',
                  fontSize: 9,
                }}
              />
            ))}
            {/* Benchmark line for context */}
            <ReferenceLine
              y={metric === 'in_control' ? 80 : 75}
              stroke="rgba(34, 197, 94, 0.35)"
              strokeDasharray="2 4"
              label={{
                value: metric === 'in_control' ? 'target 80%' : 'target 75%',
                position: 'insideBottomRight',
                fill: 'rgba(34, 197, 94, 0.7)',
                fontSize: 10,
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Firmware color legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10, fontSize: 11 }}>
        {firmwareSegments.map(fw => (
          <div key={fw} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 10, height: 10, background: hashFirmwareColor(fw), borderRadius: 2 }} />
            <code style={{ fontSize: 11 }}>{fw}</code>
          </div>
        ))}
      </div>

      {/* Release list — click-through to ClickUp task where available */}
      {firmwareReleases.length > 0 && (
        <div style={{ marginTop: 14, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>
            Firmware releases in window ({firmwareReleases.length})
          </div>
          <div style={{ display: 'grid', gap: 4 }}>
            {firmwareReleases.slice(0, 6).map((r, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, gap: 8 }}>
                <span style={{ color: 'var(--muted)', minWidth: 90 }}>{r.date}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
                {r.url && (
                  <a href={r.url} target="_blank" rel="noopener noreferrer" className="analysis-link" style={{ fontSize: 11 }}>
                    ClickUp ↗
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
