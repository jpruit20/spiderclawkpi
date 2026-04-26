import { useState, FormEvent } from 'react'
import { api } from '../lib/api'
import type { KlaviyoCustomerJourney } from '../lib/api'

/**
 * Full chronological event timeline for one customer.
 *
 * Sister card to the existing Customer Lookup, but oriented around
 * "what's the whole story" instead of "what's their current state".
 * Returns events oldest-first so the CX agent can read the journey
 * top-to-bottom: signup → install → first cook → orders → support.
 *
 * Used in escalations where we need the whole thread to brief
 * engineering or marketing.
 */

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: '2-digit',
      hour: 'numeric', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function metricColor(metric: string): string {
  if (metric.includes('Cooking')) return 'var(--green)'
  if (metric.includes('Order')) return '#a855f7'
  if (metric.toLowerCase().includes('opened app')) return 'var(--blue)'
  if (metric.toLowerCase().includes('email')) return '#9fb0d4'
  if (metric.toLowerCase().includes('sms')) return '#f59e0b'
  return 'var(--muted)'
}

export function KlaviyoCustomerJourneyCard() {
  const [email, setEmail] = useState('')
  const [data, setData] = useState<KlaviyoCustomerJourney | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const cleaned = email.trim().toLowerCase()
    if (!cleaned) return
    setLoading(true)
    setError(null)
    setData(null)
    try {
      const r = await api.klaviyoCustomerJourney({ email: cleaned, limit: 100 })
      setData(r)
    } catch (err: any) {
      setError(String(err?.message || err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Customer journey</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Full chronological event history for one customer. Use during escalations to brief engineering or marketing on what happened before the ticket.
          </div>
        </div>
      </div>

      <form onSubmit={onSubmit} style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <input
          type="email"
          placeholder="customer@example.com"
          value={email}
          onChange={e => setEmail(e.target.value)}
          style={{
            flex: 1,
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid rgba(255,255,255,0.1)',
            background: 'var(--panel-2)',
            color: 'var(--text)',
            fontSize: 13,
          }}
        />
        <button
          type="submit"
          disabled={loading || !email.trim()}
          style={{
            padding: '6px 14px',
            borderRadius: 6,
            border: 'none',
            background: 'var(--blue)',
            color: '#fff',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            opacity: loading || !email.trim() ? 0.5 : 1,
          }}
        >
          {loading ? 'Loading…' : 'Show journey'}
        </button>
      </form>

      {error && <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 8 }}>Error: {error}</div>}

      {data && data.found === false && (
        <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 10 }}>
          No Klaviyo profile found for that email.
        </div>
      )}

      {data && data.profile && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>
            {(data.profile.first_name || data.profile.last_name)
              ? `${data.profile.first_name ?? ''} ${data.profile.last_name ?? ''}`.trim()
              : data.profile.email}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>
            {data.profile.email} · {data.profile.product_ownership ?? '—'} · {(data.profile.device_types || []).join(', ') || 'no device'} · {data.profile.phone_os ?? '—'}
            {data.profile.klaviyo_created_at ? ` · joined ${fmtTime(data.profile.klaviyo_created_at)}` : ''}
          </div>

          {data.events && data.events.length > 0 ? (
            <div style={{
              marginTop: 12,
              maxHeight: 400,
              overflowY: 'auto',
              borderLeft: '2px solid rgba(255,255,255,0.08)',
              paddingLeft: 12,
            }}>
              {data.events.map((e, i) => (
                <div key={i} style={{
                  position: 'relative',
                  padding: '4px 0',
                  fontSize: 12,
                }}>
                  <span style={{
                    position: 'absolute',
                    left: -17,
                    top: 9,
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: metricColor(e.metric),
                  }} />
                  <span style={{ color: metricColor(e.metric), fontWeight: 600 }}>
                    {e.metric}
                  </span>
                  <span style={{ marginLeft: 8, color: 'var(--muted)' }}>
                    {fmtTime(e.when)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 10 }}>
              {data.event_count === 0 ? 'No events recorded yet.' : ''}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
