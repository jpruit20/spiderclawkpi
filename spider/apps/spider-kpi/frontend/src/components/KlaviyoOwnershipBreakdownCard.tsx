import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KlaviyoProductOwnership } from '../lib/api'

/**
 * Giant Huntsman signal surfaced from Klaviyo Placed Order line-items.
 *
 * The AWS telemetry side can't tell Giant Huntsman from regular
 * Huntsman — they share a shadow signature and (on V2) the same
 * grill_type string. But Klaviyo mirrors Shopify's Placed Order
 * events, whose ``Items`` property contains the exact product name
 * ("Giant Huntsman™", "The Huntsman®", etc.). This card counts
 * unique profiles who have bought each variant, giving the dashboard
 * the Giant Huntsman breakdown it's been missing.
 *
 * Once Agustin wires the ``Device Paired`` event with an explicit
 * ``device_type`` property, we can flip the telemetry-side
 * classifier on. Until then, this card is the authoritative view.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

export function KlaviyoOwnershipBreakdownCard() {
  const [data, setData] = useState<KlaviyoProductOwnership | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoProductOwnership(ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Ownership (from Klaviyo orders)</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Ownership (from Klaviyo orders)</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  const total = data.from_orders.reduce((a, r) => a + r.unique_profiles, 0)

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Ownership — from Shopify orders (via Klaviyo)</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Unique customers per product family, derived from Placed Order line-items.
            The authoritative Giant Huntsman vs Huntsman split until the app reports device type directly.
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginTop: 12 }}>
        {data.from_orders.map(r => {
          const pct = total > 0 ? (r.unique_profiles / total) * 100 : 0
          return (
            <div key={r.family} className="kpi-tile">
              <div className="kpi-tile-label">{r.family}</div>
              <div className="kpi-tile-value">{fmtInt(r.unique_profiles)}</div>
              <div className="kpi-tile-sub">{pct.toFixed(1)}% of orders</div>
            </div>
          )
        })}
      </div>

      {data.tagged_ownership.breakdown.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            Klaviyo ``Product Ownership`` tags (coarser bucket, for reconciliation)
          </div>
          <div style={{ fontSize: 12 }}>
            {data.tagged_ownership.breakdown.map(r => (
              <div key={r.ownership} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span>{r.ownership}</span>
                <span style={{ color: 'var(--muted)' }}>{fmtInt(r.count)} · {r.pct}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
