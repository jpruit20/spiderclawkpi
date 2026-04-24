import { useEffect, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts'
import { api } from '../lib/api'
import type { KlaviyoMarketingOverview } from '../lib/api'

/**
 * Klaviyo funnel view for the Marketing division.
 *
 * The funnel we care about: **sign up → install app → first cook → repurchase**.
 * Klaviyo mirrors every step (Shopify Placed Order events land in it
 * too), so this single card shows the whole path without pulling from
 * Shopify separately.
 *
 * Deliberately not a campaign/flow performance card — those live in
 * the Klaviyo UI where the marketing team already edits them. This
 * card's job is to show how many people are moving through the funnel
 * and what grill they end up with.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

export function KlaviyoMarketingCard() {
  const [data, setData] = useState<KlaviyoMarketingOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [windowDays, setWindowDays] = useState(30)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoMarketingOverview(windowDays, ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [windowDays])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Klaviyo funnel</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Klaviyo funnel</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  // Merge the three dated series into a single row set keyed by date.
  const dateKey = (d: string) => d.slice(5) // MM-DD
  const byDate = new Map<string, { date: string; signups: number; firstCooks: number; orders: number }>()
  const ensure = (iso: string) => {
    const k = dateKey(iso)
    const existing = byDate.get(k)
    if (existing) return existing
    const row = { date: k, signups: 0, firstCooks: 0, orders: 0 }
    byDate.set(k, row)
    return row
  }
  for (const r of data.signups) ensure(r.date).signups = r.count
  for (const r of data.first_cooks) ensure(r.date).firstCooks = r.unique_profiles
  for (const r of data.orders) ensure(r.date).orders = r.unique_profiles
  const chartData = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date))

  const totalSignups = data.signups.reduce((a, r) => a + r.count, 0)
  const totalFirstCooks = data.first_cooks.reduce((a, r) => a + r.unique_profiles, 0)
  const totalOrders = data.orders.reduce((a, r) => a + r.unique_profiles, 0)

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Klaviyo funnel — sign up → install → cook → repurchase</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Mirrored from the Klaviyo profile + event tables. Includes Shopify Placed Order and the app's First Cooking Session event.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[7, 30, 90].map(d => (
            <button
              key={d}
              onClick={() => setWindowDays(d)}
              style={{
                padding: '4px 10px',
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.1)',
                background: windowDays === d ? 'var(--blue)' : 'var(--panel-2)',
                color: windowDays === d ? '#fff' : 'var(--muted)',
                fontSize: 11,
                cursor: 'pointer',
              }}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Funnel totals */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginTop: 12 }}>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Total profiles</div>
          <div className="kpi-tile-value">{fmtInt(data.total_profiles)}</div>
          <div className="kpi-tile-sub">all time</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">App installed</div>
          <div className="kpi-tile-value">{fmtInt(data.app_profiles)}</div>
          <div className="kpi-tile-sub">{data.app_install_rate_pct}% of base</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Signups ({windowDays}d)</div>
          <div className="kpi-tile-value">{fmtInt(totalSignups)}</div>
          <div className="kpi-tile-sub">new profiles</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">First cooks ({windowDays}d)</div>
          <div className="kpi-tile-value">{fmtInt(totalFirstCooks)}</div>
          <div className="kpi-tile-sub">unique users</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Orders ({windowDays}d)</div>
          <div className="kpi-tile-value">{fmtInt(totalOrders)}</div>
          <div className="kpi-tile-sub">unique customers</div>
        </div>
      </div>

      {/* Timeseries */}
      {chartData.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="chart-wrap-short">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 10 }} interval={2} />
                <YAxis stroke="#9fb0d4" tick={{ fontSize: 10 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="signups" name="Signups" stroke="#6ea8ff" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="firstCooks" name="First cooks" stroke="#ffb257" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="orders" name="Orders" stroke="#22c55e" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Product ownership */}
      {data.product_ownership.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            Product ownership (tagged in Klaviyo)
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 8 }}>
            {data.product_ownership.map(r => (
              <div key={r.ownership} style={{
                padding: 8,
                borderRadius: 6,
                background: 'var(--panel-2)',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
              }}>
                <div style={{ fontSize: 12, fontWeight: 500 }}>{r.ownership}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {fmtInt(r.count)} · {r.pct}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
