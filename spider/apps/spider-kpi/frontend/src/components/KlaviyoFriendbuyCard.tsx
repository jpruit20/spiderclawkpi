import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KlaviyoFriendbuyAttribution } from '../lib/api'

/**
 * Friendbuy referral attribution from Klaviyo profile properties.
 *
 * Surfaces what % of recent customer signups came in through the
 * Friendbuy program, broken out by referral campaign. Shows up on
 * the Marketing page next to the funnel and campaign cards.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

export function KlaviyoFriendbuyCard() {
  const [data, setData] = useState<KlaviyoFriendbuyAttribution | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [windowDays, setWindowDays] = useState(30)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoFriendbuyAttribution(windowDays, ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [windowDays])

  if (error) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Friendbuy referrals</strong></div>
      <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
    </section>
  )
  if (!data) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Friendbuy referrals</strong></div>
      <div className="state-message">Loading…</div>
    </section>
  )

  const shareColor = data.friendbuy_share_of_new_pct >= 15
    ? 'var(--green)'
    : data.friendbuy_share_of_new_pct >= 5
      ? 'var(--orange)'
      : 'var(--muted)'

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Friendbuy referrals</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Share of recent profiles that arrived via the Friendbuy program, plus the top referral campaigns by profile volume.
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

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginTop: 12 }}>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Friendbuy-tagged</div>
          <div className="kpi-tile-value">{fmtInt(data.profiles_with_friendbuy_tag)}</div>
          <div className="kpi-tile-sub">{data.tag_rate_pct}% of base</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">New profiles ({windowDays}d)</div>
          <div className="kpi-tile-value">{fmtInt(data.new_in_window)}</div>
          <div className="kpi-tile-sub">all signup sources</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">From referrals ({windowDays}d)</div>
          <div className="kpi-tile-value">{fmtInt(data.new_friendbuy_in_window)}</div>
          <div className="kpi-tile-sub">Friendbuy-tagged</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Referral share</div>
          <div className="kpi-tile-value" style={{ color: shareColor }}>
            {data.friendbuy_share_of_new_pct.toFixed(1)}%
          </div>
          <div className="kpi-tile-sub">of new signups</div>
        </div>
      </div>

      {data.top_campaigns.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            Top campaigns (all-time)
          </div>
          <div style={{ fontSize: 12 }}>
            {data.top_campaigns.map(c => (
              <div key={c.campaign} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span>{c.campaign}</span>
                <span style={{ color: 'var(--muted)' }}>{fmtInt(c.profiles)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
