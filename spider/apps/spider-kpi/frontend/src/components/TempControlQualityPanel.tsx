import { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, ReferenceLine } from 'recharts'
import { api } from '../lib/api'
import { fmtInt, fmtPct } from '../lib/format'
import { GaugeTile, MetricTile, TileGrid } from './tiles'
import type { CookOutcomesSummary } from '../lib/types'

/**
 * Visual dashboard of PID control quality, replacing the old text-heavy
 * "Temperature Control Quality" bar list. Everything here reads from
 * the new intent/outcome/PID-quality model:
 *
 *   * PID quality (in-control %) — post-reach samples within ±15°F
 *     of target, excluding disturbance windows. The real PID metric.
 *   * Avg disturbances per cook — lid-open proxy. Higher = user
 *     interacting with grill more.
 *   * Avg recovery — seconds for the PID to return to target after
 *     a disturbance. This is where firmware quality shows up most
 *     directly (faster = better PID).
 *   * Max overshoot — post-reach positive deviation outside
 *     disturbance windows. Captures PID bias.
 *
 * Cook outcome distribution shown as a horizontal severity bar so it's
 * obvious at a glance whether most cooks are "reached_and_held"
 * (good) vs "reached_not_held" (PID failing to sustain).
 *
 * Graceful degradation: when totals.held_target_rate is null the panel
 * shows a "pending re-derivation" banner instead of empty gauges.
 */

const OUTCOME_LABELS: Record<string, string> = {
  reached_and_held: 'Reached & held',
  reached_not_held: 'Reached but not held',
  did_not_reach: 'Did not reach',
  disconnect: 'Disconnect',
  error: 'Device error',
  unknown: 'Unknown',
}

const OUTCOME_COLORS: Record<string, string> = {
  reached_and_held: '#22c55e',
  reached_not_held: '#f59e0b',
  did_not_reach: '#ef4444',
  disconnect: '#6b7280',
  error: '#a78bfa',
  unknown: '#9ca3af',
}

const INTENT_LABELS: Record<string, string> = {
  startup_assist: 'Startup assist (≤15m)',
  short_cook: 'Short (15-60m)',
  medium_cook: 'Medium (1-3h)',
  long_cook: 'Long (3h+)',
  unclassified: 'Unclassified',
}

const INTENT_COLORS: Record<string, string> = {
  startup_assist: '#6b7280',
  short_cook: '#6ea8ff',
  medium_cook: '#f59e0b',
  long_cook: '#22c55e',
  unclassified: '#374151',
}

export function TempControlQualityPanel({ days = 90 }: { days?: number }) {
  const [resp, setResp] = useState<CookOutcomesSummary | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.cookOutcomesSummary(days)
      .then(r => { if (!cancelled) setResp(r) })
      .catch(() => { /* silent */ })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [days])

  const totals = resp?.totals
  const hasNewModel = !!(totals?.held_target_rate != null || totals?.avg_in_control_pct != null)

  const outcomeBar = useMemo(() => {
    if (!resp?.outcome_distribution) return { data: [], total: 0 }
    const total = resp.outcome_distribution.reduce((s, o) => s + o.count, 0) || 1
    return {
      data: resp.outcome_distribution.map(o => ({
        outcome: o.outcome,
        count: o.count,
        pct: (o.count / total) * 100,
        label: OUTCOME_LABELS[o.outcome] || o.outcome,
      })),
      total,
    }
  }, [resp])

  const intentBar = useMemo(() => {
    if (!resp?.intent_distribution) return { data: [], total: 0 }
    const total = resp.intent_distribution.reduce((s, i) => s + i.count, 0) || 1
    return {
      data: resp.intent_distribution.map(i => ({
        intent: i.intent,
        count: i.count,
        pct: (i.count / total) * 100,
        label: INTENT_LABELS[i.intent] || i.intent,
      })),
      total,
    }
  }, [resp])

  if (loading) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Temperature control quality</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  if (!resp?.ok || !hasNewModel) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--orange)' }}>
        <div className="venom-panel-head">
          <strong>Temperature control quality</strong>
          <span className="venom-panel-hint">pending re-derivation</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Intent / outcome / PID-quality columns on <code>telemetry_sessions</code> haven't been populated yet.
          Once the S3 backfill completes and the <code>rederive_session_quality</code> script runs, this panel will
          light up with the new PID metrics: <strong>in-control %</strong> (PID performance during non-disturbance
          windows), <strong>avg disturbances per cook</strong> (lid-open proxy), <strong>avg recovery seconds</strong> (firmware
          responsiveness), and <strong>overshoot distribution</strong>.
        </p>
      </section>
    )
  }

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Temperature control quality</strong>
          <p className="venom-chart-sub">
            PID performance measured only during <em>post-reach, non-disturbance</em> windows.
            Lid-opens don't count against the score — user interaction is its own dimension, shown below.
          </p>
        </div>
        <span className="venom-panel-hint">
          {fmtInt(totals?.sessions_scored || 0)} sessions · last {resp.window_days}d
        </span>
      </div>

      {/* Gauge row — headline PID metrics. */}
      <TileGrid cols={4}>
        <GaugeTile
          label="PID quality (in-control %)"
          value={totals?.avg_in_control_pct ?? 0}
          display={totals?.avg_in_control_pct != null ? fmtPct(totals.avg_in_control_pct) : '—'}
          sublabel="post-reach samples within ±15°F · lid-open windows excluded"
          bandsAsc={{ bad: 0.65, warn: 0.80 }}
        />
        <GaugeTile
          label="Held-target rate"
          value={totals?.held_target_rate ?? 0}
          display={totals?.held_target_rate != null ? fmtPct(totals.held_target_rate) : '—'}
          sublabel={`${fmtInt(totals?.held_count || 0)} / ${fmtInt(totals?.target_seeking_count || 0)} target-seeking cooks`}
          bandsAsc={{ bad: 0.60, warn: 0.75 }}
        />
        <MetricTile
          label="Avg disturbances/cook"
          value={totals?.avg_disturbances_per_cook != null ? totals.avg_disturbances_per_cook.toFixed(1) : '—'}
          sublabel="lid-open proxy · >3 is heavy interaction"
          state={
            totals?.avg_disturbances_per_cook == null ? 'neutral'
            : totals.avg_disturbances_per_cook <= 2 ? 'good'
            : totals.avg_disturbances_per_cook <= 4 ? 'warn'
            : 'bad'
          }
          icon="🔥"
        />
        <MetricTile
          label="Avg recovery"
          value={totals?.avg_recovery_seconds != null ? `${Math.round(totals.avg_recovery_seconds)}s` : '—'}
          sublabel="seconds to return to ±15°F after disturbance · firmware PID speed"
          state={
            totals?.avg_recovery_seconds == null ? 'neutral'
            : totals.avg_recovery_seconds <= 180 ? 'good'
            : totals.avg_recovery_seconds <= 300 ? 'warn'
            : 'bad'
          }
          icon="⏱"
        />
      </TileGrid>

      {/* Outcome distribution — horizontal stacked bar. */}
      {outcomeBar.data.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>
            Cook outcome distribution
          </div>
          <div style={{ display: 'flex', height: 28, borderRadius: 6, overflow: 'hidden' }}>
            {outcomeBar.data.map(b => (
              <div
                key={b.outcome}
                title={`${b.label}: ${fmtInt(b.count)} (${b.pct.toFixed(1)}%)`}
                style={{
                  flex: b.pct,
                  background: OUTCOME_COLORS[b.outcome] || '#555',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#fff',
                  fontSize: 10,
                  fontWeight: 600,
                  minWidth: b.pct > 2 ? undefined : 2,
                }}
              >
                {b.pct >= 6 ? `${b.pct.toFixed(0)}%` : ''}
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 8, fontSize: 11 }}>
            {outcomeBar.data.map(b => (
              <div key={b.outcome} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, background: OUTCOME_COLORS[b.outcome] || '#555', borderRadius: 2 }} />
                <span>{b.label}</span>
                <span style={{ color: 'var(--muted)' }}>{fmtInt(b.count)} ({b.pct.toFixed(1)}%)</span>
              </div>
            ))}
          </div>
          <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8, lineHeight: 1.45 }}>
            <strong style={{ color: OUTCOME_COLORS.reached_not_held }}>Reached but not held</strong> is the concerning
            bucket — the device hit target once but couldn't sustain it. Ratio of <em>reached_not_held ÷ (reached_and_held + reached_not_held)</em> is the
            PID-hold failure rate. <strong style={{ color: OUTCOME_COLORS.did_not_reach }}>Did not reach</strong> is typically
            user intent (pulled off early, short session, bad fire-start) rather than firmware.
          </p>
        </div>
      )}

      {/* Intent distribution — context for how users use the device. */}
      {intentBar.data.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6 }}>
            Cook intent mix
          </div>
          <div style={{ display: 'flex', height: 22, borderRadius: 6, overflow: 'hidden' }}>
            {intentBar.data.map(b => (
              <div
                key={b.intent}
                title={`${b.label}: ${fmtInt(b.count)} (${b.pct.toFixed(1)}%)`}
                style={{
                  flex: b.pct,
                  background: INTENT_COLORS[b.intent] || '#555',
                  minWidth: b.pct > 1 ? undefined : 1,
                }}
              />
            ))}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 6, fontSize: 11 }}>
            {intentBar.data.map(b => (
              <div key={b.intent} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, background: INTENT_COLORS[b.intent] || '#555', borderRadius: 2 }} />
                <span>{b.label}</span>
                <span style={{ color: 'var(--muted)' }}>{b.pct.toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
