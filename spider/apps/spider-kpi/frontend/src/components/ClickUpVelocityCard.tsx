import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { ClickUpVelocityResponse } from '../lib/types'
import { fmtInt } from '../lib/format'

/**
 * Team velocity for a ClickUp space — throughput sparkline, week-over-week
 * change, cycle-time median, and top closers. Reads from the
 * /api/clickup/velocity endpoint (backed by clickup_tasks_daily +
 * clickup_tasks).
 *
 * Drops alongside <ClickUpTasksCard> on any division page.
 */
type Props = {
  title?: string
  subtitle?: string
  /** Filter to a specific space; omit for workspace-wide view. */
  spaceId?: string
  days?: number
}

function sparklineBlocks(values: number[]): string {
  if (!values.length) return ''
  const max = Math.max(...values, 1)
  const blocks = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█']
  return values.map(v => blocks[Math.min(blocks.length - 1, Math.floor((v / max) * (blocks.length - 1)))]).join('')
}

function formatDuration(days: number | null | undefined): string {
  if (days == null) return '—'
  if (days < 1) return `${Math.round(days * 24)}h`
  if (days < 14) return `${days.toFixed(1)}d`
  return `${(days / 7).toFixed(1)}w`
}

function wowColor(pct: number | null): string {
  if (pct == null) return 'var(--muted)'
  if (pct > 5) return 'var(--green)'
  if (pct < -5) return 'var(--red)'
  return 'var(--muted)'
}

export function ClickUpVelocityCard({
  title = 'ClickUp velocity',
  subtitle,
  spaceId,
  days = 30,
}: Props) {
  const [data, setData] = useState<ClickUpVelocityResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.clickupVelocity(spaceId, days)
      .then(r => { if (!cancelled) setData(r) })
      .catch(err => { if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load velocity') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [spaceId, days])

  const openSpark = useMemo(() => sparklineBlocks((data?.throughput || []).map(r => r.open_pit)), [data])
  const closedSpark = useMemo(() => sparklineBlocks((data?.throughput || []).map(r => r.completed)), [data])

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>{title}</strong>
        <span className="venom-panel-hint">
          {data ? `${data.window.days}-day window` : ''}
        </span>
      </div>
      {subtitle && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>{subtitle}</p>
      )}

      {loading && <div className="state-message">Loading velocity…</div>}
      {error && <div className="state-message error">{error}</div>}

      {!loading && !error && data && (
        <>
          <div className="venom-bar-list" style={{ marginBottom: 10 }}>
            <div className="venom-breakdown-row">
              <span className="venom-bar-label">Closed last 7 days</span>
              <span className="venom-breakdown-val">{fmtInt(data.totals.closed_last_7)}</span>
              <span style={{ color: wowColor(data.totals.wow_pct), fontSize: 11 }}>
                {data.totals.wow_delta > 0 ? '+' : ''}{data.totals.wow_delta} vs prior 7
                {data.totals.wow_pct != null && ` (${data.totals.wow_pct > 0 ? '+' : ''}${data.totals.wow_pct.toFixed(0)}%)`}
              </span>
            </div>
            <div className="venom-breakdown-row">
              <span className="venom-bar-label">Open right now</span>
              <span className="venom-breakdown-val">{fmtInt(data.totals.open_now)}</span>
              {data.totals.overdue_now > 0 && (
                <span style={{ color: 'var(--red)', fontSize: 11 }}>{fmtInt(data.totals.overdue_now)} overdue</span>
              )}
            </div>
            <div className="venom-breakdown-row">
              <span className="venom-bar-label">Median cycle time</span>
              <span className="venom-breakdown-val">{formatDuration(data.cycle_time.median_days)}</span>
              <span style={{ color: 'var(--muted)', fontSize: 11 }}>
                p90 {formatDuration(data.cycle_time.p90_days)} · n={data.cycle_time.sample_size}
              </span>
            </div>
          </div>

          {(openSpark || closedSpark) && (
            <div style={{ fontFamily: 'monospace', fontSize: 16, letterSpacing: 1, lineHeight: 1 }}>
              {openSpark && (
                <div>
                  <span style={{ color: 'var(--blue)' }}>{openSpark}</span>
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>open tasks per day</div>
                </div>
              )}
              {closedSpark && (
                <div style={{ marginTop: 6 }}>
                  <span style={{ color: 'var(--green)' }}>{closedSpark}</span>
                  <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>closed per day</div>
                </div>
              )}
            </div>
          )}

          {data.top_closers.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Top closers</div>
              <div className="venom-breakdown-list">
                {data.top_closers.map((c) => (
                  <div key={c.user} className="venom-breakdown-row">
                    <span>{c.user}</span>
                    <span className="venom-breakdown-val">{fmtInt(c.completed)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.totals.closed_last_7 === 0 && data.totals.open_now === 0 && (
            <div className="state-message">No activity in this window yet.</div>
          )}
        </>
      )}
    </section>
  )
}
