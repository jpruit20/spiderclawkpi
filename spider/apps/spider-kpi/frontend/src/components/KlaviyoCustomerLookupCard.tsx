import { useState, FormEvent } from 'react'
import { api } from '../lib/api'
import type { KlaviyoCustomerLookup } from '../lib/api'

/**
 * Klaviyo customer lookup for CX triage.
 *
 * Paste a customer email (from a Freshdesk ticket, etc.) and get the
 * one-glance context a support agent needs:
 *
 * - what grill/firmware they own
 * - when they last opened the app (and from which device)
 * - recent "First Cooking Session" / "Opened App" / "Placed Order"
 *   events
 *
 * Replaces the copy/paste between Freshdesk, Klaviyo, and Shopify
 * with a single field.
 */

function relative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const secs = (Date.now() - new Date(iso).getTime()) / 1000
  if (secs < 60) return 'just now'
  const m = Math.floor(secs / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function stateColor(seconds: number): string {
  if (seconds < 7 * 86400) return 'var(--green)'
  if (seconds < 30 * 86400) return 'var(--orange)'
  return 'var(--muted)'
}

export function KlaviyoCustomerLookupCard() {
  const [email, setEmail] = useState('')
  const [result, setResult] = useState<KlaviyoCustomerLookup | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const cleaned = email.trim().toLowerCase()
    if (!cleaned) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await api.klaviyoCustomerLookup({ email: cleaned, limit_events: 20 })
      setResult(r)
    } catch (err: any) {
      setError(String(err?.message || err))
    } finally {
      setLoading(false)
    }
  }

  const profile = result?.profile
  const lastEventSeconds = profile?.last_event_at
    ? (Date.now() - new Date(profile.last_event_at).getTime()) / 1000
    : Infinity

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Customer Lookup (Klaviyo)</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Paste a customer email to see their grill ownership, firmware, and recent app activity.
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
          {loading ? 'Looking up…' : 'Look up'}
        </button>
      </form>

      {error && (
        <div style={{ marginTop: 10, color: 'var(--red)', fontSize: 12 }}>Error: {error}</div>
      )}

      {result && !result.found && (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>
          No Klaviyo profile found for <code>{result.email || email}</code>. They may not be on the app or in Shopify yet.
        </div>
      )}

      {profile && (
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Profile header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>
                {profile.first_name || profile.last_name
                  ? `${profile.first_name ?? ''} ${profile.last_name ?? ''}`.trim()
                  : (profile.email || profile.klaviyo_id)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                {profile.email} · {profile.external_id ?? 'no external_id'}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Last event</div>
              <div style={{
                fontWeight: 600,
                color: stateColor(lastEventSeconds),
                fontSize: 13,
              }}>
                {relative(profile.last_event_at)}
              </div>
            </div>
          </div>

          {/* Grill + firmware */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Product Ownership</div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{profile.product_ownership ?? '—'}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Device types</div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>
                {profile.device_types.length ? profile.device_types.join(', ') : '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Firmware</div>
              <div style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>
                {profile.device_firmware_versions.length
                  ? profile.device_firmware_versions.join(', ')
                  : '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Phone</div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>
                {profile.phone_os ? `${profile.phone_os === 'ios' ? 'iOS' : profile.phone_os} ${profile.phone_os_version ?? ''}` : '—'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>{profile.phone_model ?? ''}</div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>App version</div>
              <div style={{ fontWeight: 600, fontSize: 13, fontFamily: 'monospace' }}>
                {profile.app_version ?? '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Expected next order</div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{profile.expected_next_order_date ?? '—'}</div>
            </div>
          </div>

          {/* Recent events */}
          {result!.recent_events && result!.recent_events.length > 0 && (
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                Recent events ({result!.recent_events.length})
              </div>
              <div style={{
                maxHeight: 200,
                overflowY: 'auto',
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 6,
                padding: 6,
                fontSize: 12,
              }}>
                {result!.recent_events.map((e, i) => (
                  <div key={i} style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    padding: '4px 6px',
                    borderBottom: i < result!.recent_events!.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                  }}>
                    <span style={{ fontWeight: 500 }}>{e.metric}</span>
                    <span style={{ color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                      {relative(e.when)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
