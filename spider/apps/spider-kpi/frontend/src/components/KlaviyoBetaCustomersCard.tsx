import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KlaviyoBetaCustomers } from '../lib/api'

/**
 * Members of Klaviyo's "Beta Customers" list, surfaced on the Firmware
 * Beta Program. The marketing team curates the list inside Klaviyo
 * (matched by exact name "Beta Customers"), and the dashboard reads
 * it here so firmware can see the cohort's actual hardware spread
 * before pushing an OTA.
 *
 * Three rollups across the cohort:
 *   - Firmware version distribution — what's actually running today
 *   - Device type distribution — who has Huntsman vs Venom-on-Kettle
 *   - Phone OS distribution — iOS/Android skew (matters for OTA UX)
 *
 * Plus a paginated member table for ground-truth.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

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

export function KlaviyoBetaCustomersCard() {
  const [data, setData] = useState<KlaviyoBetaCustomers | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showTable, setShowTable] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoBetaCustomers(500, ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Beta Customers (Klaviyo)</strong></div>
      <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
    </section>
  )
  if (!data) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Beta Customers (Klaviyo)</strong></div>
      <div className="state-message">Loading…</div>
    </section>
  )

  if (data.error) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Beta Customers (Klaviyo)</strong></div>
      <div className="state-message">
        {data.error} — create a list named exactly <code>Beta Customers</code> in Klaviyo to populate this view.
      </div>
    </section>
  )

  const fwDist = data.firmware_distribution ?? []
  const dtDist = data.device_type_distribution ?? []
  const osDist = data.phone_os_distribution ?? []

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Beta Customers — Klaviyo cohort</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Members of the <code>Beta Customers</code> list in Klaviyo, joined to per-profile firmware/device state.
            This is the canonical opt-in cohort; curate it inside Klaviyo and it shows up here.
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Total members</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{fmtInt(data.total_members)}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 16, marginTop: 14 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Firmware mix in cohort</div>
          {fwDist.length === 0 ? <span style={{ fontSize: 12 }}>—</span> : (
            <div style={{ fontSize: 12 }}>
              {fwDist.slice(0, 6).map(r => (
                <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span style={{ fontFamily: 'monospace' }}>{r.label}</span>
                  <span style={{ color: 'var(--muted)' }}>{fmtInt(r.count)} · {r.pct}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Device types in cohort</div>
          {dtDist.length === 0 ? <span style={{ fontSize: 12 }}>—</span> : (
            <div style={{ fontSize: 12 }}>
              {dtDist.slice(0, 6).map(r => (
                <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span>{r.label}</span>
                  <span style={{ color: 'var(--muted)' }}>{fmtInt(r.count)} · {r.pct}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Phone OS in cohort</div>
          {osDist.length === 0 ? <span style={{ fontSize: 12 }}>—</span> : (
            <div style={{ fontSize: 12 }}>
              {osDist.map(r => (
                <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span>{r.label === 'ios' ? 'iOS' : r.label === 'android' ? 'Android' : r.label}</span>
                  <span style={{ color: 'var(--muted)' }}>{fmtInt(r.count)} · {r.pct}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <button
        onClick={() => setShowTable(s => !s)}
        style={{
          marginTop: 12,
          padding: '4px 10px',
          background: 'var(--panel-2)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 6,
          color: 'var(--muted)',
          fontSize: 11,
          cursor: 'pointer',
        }}
      >
        {showTable ? 'Hide' : 'Show'} member roster
      </button>

      {showTable && (
        <div style={{ marginTop: 8, maxHeight: 360, overflowY: 'auto' }}>
          <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                <th style={{ padding: '4px 6px' }}>Email</th>
                <th style={{ padding: '4px 6px' }}>Device</th>
                <th style={{ padding: '4px 6px' }}>Firmware</th>
                <th style={{ padding: '4px 6px' }}>OS</th>
                <th style={{ padding: '4px 6px' }}>Last event</th>
              </tr>
            </thead>
            <tbody>
              {data.members.map(m => (
                <tr key={m.klaviyo_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '4px 6px' }}>{m.email ?? <code>{m.external_id ?? m.klaviyo_id}</code>}</td>
                  <td style={{ padding: '4px 6px' }}>{(m.device_types || []).join(', ') || '—'}</td>
                  <td style={{ padding: '4px 6px', fontFamily: 'monospace' }}>{(m.device_firmware_versions || []).join(', ') || '—'}</td>
                  <td style={{ padding: '4px 6px' }}>{m.phone_os ?? '—'}</td>
                  <td style={{ padding: '4px 6px', color: 'var(--muted)' }}>{relative(m.last_event_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
