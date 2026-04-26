import { useEffect, useState } from 'react'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'
import { api } from '../lib/api'
import type { KlaviyoInstallFunnel } from '../lib/api'

/**
 * Install → First Cook conversion funnel.
 *
 * Two questions this card answers at a glance:
 *
 * 1. What share of profiles that installed the app actually completed
 *    a first cook? (single % gauge)
 * 2. How long did it take? (histogram bucketed Same-day / 1-3d / 3-7d
 *    / 1-2w / 2-4w / 30d+)
 *
 * Source: Klaviyo "Opened App" anchored to "First Cooking Session" per
 * profile. Until the app fires a more granular onboarding-step event,
 * this is the closest signal the dashboard has to a real onboarding
 * funnel.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

export function AppFunnelCard() {
  const [data, setData] = useState<KlaviyoInstallFunnel | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoInstallToFirstCook(ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Install → First Cook</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Install → First Cook</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  const conversionColor = data.conversion_pct >= 60
    ? 'var(--green)'
    : data.conversion_pct >= 35
      ? 'var(--orange)'
      : 'var(--red)'

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Install → First Cook</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            How many profiles that installed the app actually completed a first cook, and how fast.
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10, marginTop: 12 }}>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Installed</div>
          <div className="kpi-tile-value">{fmtInt(data.installed)}</div>
          <div className="kpi-tile-sub">profiles with Opened App</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Converted</div>
          <div className="kpi-tile-value">{fmtInt(data.converted_to_first_cook)}</div>
          <div className="kpi-tile-sub">first cook completed</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Conversion</div>
          <div className="kpi-tile-value" style={{ color: conversionColor }}>
            {data.conversion_pct.toFixed(1)}%
          </div>
          <div className="kpi-tile-sub">install → first cook</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Median time</div>
          <div className="kpi-tile-value">
            {data.median_days_to_first_cook != null
              ? `${data.median_days_to_first_cook}d`
              : '—'}
          </div>
          <div className="kpi-tile-sub">install → first cook</div>
        </div>
      </div>

      {/* Histogram */}
      <div style={{ marginTop: 14 }}>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
          Time-to-first-cook distribution
        </div>
        <div className="chart-wrap-short">
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={data.histogram}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="bucket" stroke="#9fb0d4" tick={{ fontSize: 10 }} />
              <YAxis stroke="#9fb0d4" tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="count" name="Profiles" fill="var(--blue)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  )
}
