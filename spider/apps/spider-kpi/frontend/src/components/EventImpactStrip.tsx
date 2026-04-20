import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { LoreEventImpactResponse, LoreEventImpactMetric } from '../lib/types'

interface Props {
  eventId: number
  beforeDays?: number
  afterDays?: number
  // Cap how many metrics we show — keeps the strip compact on narrow cards.
  maxMetrics?: number
}

function badgeClass(m: LoreEventImpactMetric): string {
  if (m.delta_pct == null || m.is_improvement == null) return 'badge-neutral'
  if (Math.abs(m.delta_pct) < 2) return 'badge-neutral'
  return m.is_improvement ? 'badge-good' : 'badge-bad'
}

function fmtDelta(d: number | null): string {
  if (d == null) return '—'
  const sign = d > 0 ? '+' : ''
  return `${sign}${d.toFixed(1)}%`
}

export function EventImpactStrip({ eventId, beforeDays = 14, afterDays = 14, maxMetrics = 4 }: Props) {
  const [data, setData] = useState<LoreEventImpactResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    api.loreEventImpact(eventId, { before_days: beforeDays, after_days: afterDays }, controller.signal)
      .then(r => setData(r))
      .catch(err => {
        if (err?.name === 'AbortError') return
        setError(err?.message || 'impact load failed')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [eventId, beforeDays, afterDays])

  if (loading) return <small className="state-message" style={{ fontSize: 11 }}>Loading impact…</small>
  if (error) return null
  if (!data) return null

  // Keep metrics with a measured delta — empty ones are noise on a narrow strip.
  const measured = data.metrics
    .filter(m => m.delta_pct != null)
    .sort((a, b) => Math.abs(b.delta_pct ?? 0) - Math.abs(a.delta_pct ?? 0))
    .slice(0, maxMetrics)

  if (!measured.length) return null

  return (
    <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
      <small style={{ fontSize: 10, color: 'var(--muted)' }}>
        {beforeDays}d before → {afterDays}d after:
      </small>
      {measured.map(m => (
        <span
          key={`${m.table}.${m.column}`}
          className={`badge ${badgeClass(m)}`}
          title={`${m.label}: ${m.before_avg ?? '—'} → ${m.after_avg ?? '—'}`}
          style={{ fontSize: 10 }}
        >
          {m.label} {fmtDelta(m.delta_pct)}
        </span>
      ))}
    </div>
  )
}
