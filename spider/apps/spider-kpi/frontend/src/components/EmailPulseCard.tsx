import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { fmtInt } from '../lib/format'
import type { EmailPulseResponse } from '../lib/types'
import { TruthBadge } from './TruthBadge'

interface EmailPulseCardProps {
  range: { startDate: string; endDate: string }
  // Optional per-division archetype highlight. When provided, the card
  // leads with the matching row instead of the raw count-sorted list.
  highlightArchetype?: string
}

function deltaClass(d: number | null): string {
  if (d == null) return 'badge-neutral'
  if (d > 10) return 'badge-bad'   // rising escalations are bad
  if (d < -10) return 'badge-good' // falling escalations are good
  return 'badge-neutral'
}

function formatDelta(d: number | null): string {
  if (d == null) return '—'
  const sign = d > 0 ? '+' : ''
  return `${sign}${d.toFixed(1)}%`
}

export function EmailPulseCard({ range, highlightArchetype }: EmailPulseCardProps) {
  const [data, setData] = useState<EmailPulseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!range.startDate || !range.endDate) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    api.emailPulse({ start: range.startDate, end: range.endDate, compare_prior: true }, controller.signal)
      .then(r => setData(r))
      .catch(err => {
        if (err?.name === 'AbortError') return
        setError(err?.message || 'failed to load email pulse')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [range.startDate, range.endDate])

  const highlighted = data?.archetypes.find(a => a.archetype === highlightArchetype) || null
  const top = (data?.archetypes || []).slice(0, 6)

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>Email archive pulse</strong>
        <TruthBadge state="canonical" />
        <span className="venom-panel-hint">
          {data?.window ? `${data.window.start} → ${data.window.end} (${data.window.days}d)` : '\u2014'}
        </span>
      </div>

      {loading && <div className="state-message">Loading…</div>}
      {error && <div className="state-message error">{error}</div>}

      {!loading && !error && data && (
        <>
          <div className="venom-breakdown-list" style={{ marginBottom: 8 }}>
            <div className="venom-breakdown-row">
              <span>Total emails received</span>
              <span className="venom-breakdown-val">{fmtInt(data.totals.count)}</span>
              <span className={`badge ${deltaClass(data.totals.delta_pct)}`}>{formatDelta(data.totals.delta_pct)}</span>
            </div>
            <div className="venom-breakdown-row">
              <span>Customer escalations</span>
              <span className="venom-breakdown-val">{fmtInt(data.escalations.count)}</span>
              <span className={`badge ${deltaClass(data.escalations.delta_pct)}`}>{formatDelta(data.escalations.delta_pct)}</span>
            </div>
            {highlighted && highlighted.archetype !== 'customer_escalation' && (
              <div className="venom-breakdown-row">
                <span>{highlighted.label}</span>
                <span className="venom-breakdown-val">{fmtInt(highlighted.count)}</span>
                <span className={`badge ${deltaClass(highlighted.delta_pct)}`}>{formatDelta(highlighted.delta_pct)}</span>
              </div>
            )}
          </div>

          <div className="venom-panel-head" style={{ marginTop: 12 }}>
            <strong style={{ fontSize: 12 }}>Archetype mix</strong>
          </div>
          <div className="venom-breakdown-list">
            {top.map(a => (
              <div className="venom-breakdown-row" key={a.archetype}>
                <span>{a.label}</span>
                <span className="venom-breakdown-val">{fmtInt(a.count)}</span>
                <span className={`badge ${deltaClass(a.delta_pct)}`}>{formatDelta(a.delta_pct)}</span>
              </div>
            ))}
          </div>

          {data.escalations.top_domains.length > 0 && (
            <>
              <div className="venom-panel-head" style={{ marginTop: 12 }}>
                <strong style={{ fontSize: 12 }}>Top escalation domains</strong>
              </div>
              <div className="venom-breakdown-list">
                {data.escalations.top_domains.slice(0, 6).map(d => (
                  <div className="venom-breakdown-row" key={d.domain}>
                    <span>{d.domain}</span>
                    <span className="venom-breakdown-val">{fmtInt(d.count)}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          <small className="venom-panel-footer">
            Archetype classifier: 40k+ emails from info@spidergrills.com, deterministic
            rule pass at ingest. Deltas compare to the prior {data.window.days}-day window.
          </small>
        </>
      )}
    </section>
  )
}
