import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KlaviyoRecentEvents } from '../lib/api'

/**
 * Scrolling feed of the most recent Klaviyo app events.
 *
 * Useful as an ops-floor "is the app alive right now?" signal —
 * if the feed stops updating for 10+ minutes during business
 * hours, something's wrong. Each row carries enough identity
 * (email, ownership, phone OS) to triage from the feed itself.
 *
 * Refreshes every 60 s.
 */

function relative(iso: string | null): string {
  if (!iso) return '—'
  const secs = (Date.now() - new Date(iso).getTime()) / 1000
  if (secs < 60) return `${Math.floor(secs)}s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

function metricColor(metric: string): string {
  if (metric.includes('Cooking')) return 'var(--green)'
  if (metric.includes('Order')) return '#a855f7'
  return 'var(--blue)'
}

export function AppLiveFeedCard() {
  const [data, setData] = useState<KlaviyoRecentEvents | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    const fetchOnce = async () => {
      try {
        const r = await api.klaviyoRecentEvents(40)
        if (!cancelled) {
          setData(r)
          setError(null)
        }
      } catch (err: any) {
        if (!cancelled && err.name !== 'AbortError') setError(String(err.message || err))
      }
    }
    fetchOnce()
    const fetchInterval = setInterval(fetchOnce, 60_000)
    // Re-render every 5s to update the relative timestamps without a fresh fetch.
    const tickInterval = setInterval(() => setTick(t => t + 1), 5_000)
    return () => {
      cancelled = true
      clearInterval(fetchInterval)
      clearInterval(tickInterval)
    }
  }, [])

  if (error && !data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>App live feed</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>App live feed</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>App live feed</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Last {data.events.length} app events from Klaviyo. Auto-refreshes every 60s.
          </div>
        </div>
      </div>

      <div
        style={{
          marginTop: 10,
          maxHeight: 360,
          overflowY: 'auto',
          fontSize: 12,
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 6,
        }}
      >
        {data.events.length === 0 ? (
          <div style={{ padding: 12, color: 'var(--muted)' }}>No events yet.</div>
        ) : (
          data.events.map(e => (
            <div
              key={e.event_id}
              style={{
                display: 'grid',
                gridTemplateColumns: '54px 1fr auto',
                gap: 10,
                padding: '6px 10px',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                alignItems: 'baseline',
              }}
            >
              <span
                style={{
                  fontVariantNumeric: 'tabular-nums',
                  color: 'var(--muted)',
                  fontSize: 11,
                }}
              >
                {relative(e.when)} ago
              </span>
              <span>
                <span style={{ color: metricColor(e.metric), fontWeight: 600 }}>
                  {e.metric}
                </span>{' '}
                <span style={{ color: 'var(--muted)' }}>
                  · {e.email ?? e.external_id ?? '(anon)'}
                  {e.product_ownership ? ` · ${e.product_ownership}` : ''}
                </span>
              </span>
              <span style={{ color: 'var(--muted)', fontSize: 11 }}>
                {e.phone_os === 'ios' ? 'iOS' : e.phone_os === 'android' ? 'Android' : ''}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  )
}
