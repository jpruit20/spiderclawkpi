import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KlaviyoEngagementByOwnership } from '../lib/api'

/**
 * App engagement broken out by Klaviyo's Product Ownership tag.
 *
 * Lets product see whether Huntsman owners are stickier than Kettle
 * owners — if one segment shows much higher DAU/MAU stickiness, it
 * informs which user group's app needs are being served best (or
 * worst). Scoped to profiles that have actually installed the app
 * so untagged buyers don't dominate the table.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

function stickinessColor(pct: number): string {
  if (pct >= 25) return 'var(--green)'
  if (pct >= 12) return 'var(--orange)'
  return 'var(--red)'
}

export function AppEngagementByOwnershipCard() {
  const [data, setData] = useState<KlaviyoEngagementByOwnership | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoEngagementByOwnership(ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>App engagement by ownership</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>App engagement by ownership</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  const rows = data.by_ownership.filter(r => r.profiles >= 5)

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>App engagement by ownership</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            DAU / MAU / stickiness segmented by Klaviyo's Product Ownership tag.
            Buckets with fewer than 5 profiles are hidden.
          </div>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="state-message" style={{ marginTop: 10 }}>
          No ownership-tagged profiles with app activity yet.
        </div>
      ) : (
        <div style={{ marginTop: 12, overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                <th style={{ padding: '6px 8px' }}>Ownership</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Profiles</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>DAU</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>MAU</th>
                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Stickiness</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.ownership} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '6px 8px', fontWeight: 500 }}>{r.ownership}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmtInt(r.profiles)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmtInt(r.dau)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmtInt(r.mau)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: stickinessColor(r.stickiness_pct), fontWeight: 600 }}>
                    {r.stickiness_pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
