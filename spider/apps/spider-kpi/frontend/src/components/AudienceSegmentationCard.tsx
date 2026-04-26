import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KlaviyoAudienceSegmentation } from '../lib/api'

/**
 * Single-glance reconciliation between the four populations the
 * dashboard cares about. Sits at the top of Marketing and PE pages
 * so cards lower down are read in the right context.
 *
 *   Total audience       = every Klaviyo profile (newsletter, giveaways, etc.)
 *   Owners               = bought a Spider product (3-signal union)
 *   App users (lifetime) = ever fired Opened App
 *   Connected devices    = unique device_ids in AWS telemetry
 *
 * Plus a callout for the non-owner share — Joseph's 2026-04-26 note
 * was that we were treating the whole audience as owners. Surfacing
 * the actual non-owner share (probably ~95%) makes that explicit.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

export function AudienceSegmentationCard() {
  const [data, setData] = useState<KlaviyoAudienceSegmentation | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoAudienceSegmentation(ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) {
    return (
      <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Audience segmentation error: {error}</div></section>
    )
  }
  if (!data) {
    return (
      <section className="card"><div className="state-message">Loading audience segmentation…</div></section>
    )
  }

  const o = data.owners
  const a = data.app_users
  const d = data.connected_devices

  return (
    <section className="card" style={{ borderLeft: '3px solid var(--blue)' }}>
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Audience segmentation — what these numbers actually mean</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Klaviyo's <strong>{fmtInt(data.total_audience)} total profiles</strong> include newsletter signups, giveaway entrants, and abandoned-cart visitors who don't own a Spider product.
            Cards below use the right population for each metric — owners for retention, audience for acquisition, app users for engagement, devices for fleet.
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 10, marginTop: 12 }}>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Total audience</div>
          <div className="kpi-tile-value">{fmtInt(data.total_audience)}</div>
          <div className="kpi-tile-sub">all Klaviyo profiles</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Owners</div>
          <div className="kpi-tile-value" style={{ color: 'var(--green)' }}>{fmtInt(o.total)}</div>
          <div className="kpi-tile-sub">{o.pct_of_audience}% of audience · 3-signal union</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">App users (lifetime)</div>
          <div className="kpi-tile-value" style={{ color: 'var(--blue)' }}>{fmtInt(a.lifetime)}</div>
          <div className="kpi-tile-sub">{a.active_30d.toLocaleString()} active in last 30d</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Connected devices</div>
          <div className="kpi-tile-value" style={{ color: 'var(--orange)' }}>{fmtInt(d.lifetime)}</div>
          <div className="kpi-tile-sub">{fmtInt(d.last_24mo)} active in last 24mo</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Non-owner audience</div>
          <div className="kpi-tile-value">{fmtInt(data.non_owner_audience)}</div>
          <div className="kpi-tile-sub">{data.non_owner_pct}% — marketing-only</div>
        </div>
      </div>

      {/* How owners are derived */}
      <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
        <strong style={{ color: 'var(--text)' }}>Owner signals (any one qualifies; counted once in the union):</strong>{' '}
        <span>{fmtInt(o.by_order)} bought a Spider product</span> ·{' '}
        <span>{fmtInt(o.by_klaviyo_tag)} tagged with Product Ownership in Klaviyo</span> ·{' '}
        <span>{fmtInt(o.by_device_types)} have a device paired in the app</span>
        {data.device_to_app_user_ratio != null && (
          <>
            <br />
            <strong style={{ color: 'var(--text)' }}>Device-to-app-user ratio:</strong> {data.device_to_app_user_ratio} —
            {' '}each app user has on average this many connected devices, OR many users installed before the Klaviyo SDK landed (mid-2025) so don't have an Opened App event.
          </>
        )}
      </div>
    </section>
  )
}
