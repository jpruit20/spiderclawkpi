import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { KlaviyoPairingLifecycle } from '../lib/api'

/**
 * Device pairing lifecycle.
 *
 * Surfaces three signals that telemetry alone can't tell us:
 *
 *   1. Active-on-app device count (paired - unpaired). Telemetry tells
 *      us how many controllers are reporting; this tells us how many
 *      have a phone associated with them. The gap is "owners who
 *      cook but don't open the app" — a real customer segment.
 *
 *   2. Pair-success rate against the telemetry-active baseline.
 *      Persistent low rate = devices reaching the field that nobody
 *      pairs (returns? buyers without smartphones? bad onboarding?).
 *
 *   3. Per-firmware pair counts. If 01.01.99 (Beta) shows a surprising
 *      pair drop relative to 01.01.33 (production), the firmware is
 *      breaking the pairing flow.
 *
 * `device_type` only carries Kettle / Huntsman per Agustín
 * (2026-04-28) — Giant Huntsman lives in the casing, the firmware
 * doesn't know. Until Matías's QR-code provisioning firmware ships,
 * the existing KlaviyoOwnershipBreakdownCard (Klaviyo Placed Order
 * line items) remains the source of truth for the Giant Huntsman
 * cohort.
 */

function _fmtRelative(iso: string | null): string {
  if (!iso) return '—'
  const ts = new Date(iso).getTime()
  if (!ts) return '—'
  const seconds = Math.floor((Date.now() - ts) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function PairingLifecycleCard({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<KlaviyoPairingLifecycle | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoPairingLifecycle(days, ctl.signal)
      .then(setData)
      .catch(err => { if (!ctl.signal.aborted) setError(err instanceof Error ? err.message : String(err)) })
    return () => ctl.abort()
  }, [days])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Device pairing lifecycle</strong></div>
        <div className="state-message error">{error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Device pairing lifecycle</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  const t = data.totals
  const successPctState =
    t.pair_success_rate_pct == null ? 'neutral'
    : t.pair_success_rate_pct >= 90 ? 'good'
    : t.pair_success_rate_pct >= 60 ? 'warn'
    : 'bad'
  const successColor =
    successPctState === 'good' ? 'var(--green)'
    : successPctState === 'warn' ? 'var(--orange)'
    : successPctState === 'bad' ? 'var(--red)'
    : 'var(--muted)'

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>Device pairing lifecycle</strong>
        <span className="venom-panel-hint">{data.window_days}-day window</span>
      </div>

      {/* Headline KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Pair events</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--green)' }}>{t.pair_events.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Unpair events</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: t.unpair_events > 0 ? 'var(--orange)' : 'var(--muted)' }}>{t.unpair_events.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Net active on app</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{t.net_app_active.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Pair-success rate</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: successColor }}>
            {t.pair_success_rate_pct != null ? `${t.pair_success_rate_pct}%` : '—'}
          </div>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>
            vs {t.telemetry_active_devices_recent} telemetry-active
          </div>
        </div>
      </div>

      {/* By device type */}
      <div className="venom-panel-head" style={{ marginTop: 8, marginBottom: 6 }}>
        <strong style={{ fontSize: 12 }}>By device type</strong>
        <span className="venom-panel-hint" style={{ fontSize: 10 }}>Giant Huntsman split: see ownership breakdown card</span>
      </div>
      {data.by_device_type.length > 0 ? (
        <div className="venom-breakdown-list">
          {data.by_device_type.map(r => (
            <div key={r.device_type} className="venom-breakdown-row">
              <span style={{ fontWeight: 500 }}>{r.device_type}</span>
              <span style={{ fontSize: 11, color: 'var(--green)' }}>+{r.paired} paired</span>
              <span style={{ fontSize: 11, color: r.unpaired > 0 ? 'var(--orange)' : 'var(--muted)' }}>−{r.unpaired} unpaired</span>
              <span className="venom-breakdown-val">{r.paired - r.unpaired} net</span>
            </div>
          ))}
        </div>
      ) : <div className="state-message">No device-type breakdowns yet.</div>}

      {/* By firmware */}
      <div className="venom-panel-head" style={{ marginTop: 12, marginBottom: 6 }}>
        <strong style={{ fontSize: 12 }}>By firmware version</strong>
        <span className="venom-panel-hint" style={{ fontSize: 10 }}>Top 8 most-active</span>
      </div>
      {data.by_firmware.length > 0 ? (
        <div className="venom-breakdown-list">
          {data.by_firmware.map(r => (
            <div key={r.firmware_version} className="venom-breakdown-row">
              <span style={{ fontWeight: 500, fontFamily: 'monospace', fontSize: 12 }}>{r.firmware_version}</span>
              <span style={{ fontSize: 11, color: 'var(--green)' }}>+{r.paired}</span>
              <span style={{ fontSize: 11, color: r.unpaired > 0 ? 'var(--orange)' : 'var(--muted)' }}>−{r.unpaired}</span>
              <span className="venom-breakdown-val">{r.paired - r.unpaired} net</span>
            </div>
          ))}
        </div>
      ) : <div className="state-message">No firmware breakdowns yet.</div>}

      {/* Recent unpairs */}
      {data.recent_unpairs.length > 0 ? (
        <>
          <div className="venom-panel-head" style={{ marginTop: 12, marginBottom: 6 }}>
            <strong style={{ fontSize: 12 }}>Recent unpairs</strong>
            <span className="venom-panel-hint" style={{ fontSize: 10 }}>Spot-check who's leaving</span>
          </div>
          <div className="stack-list compact">
            {data.recent_unpairs.map((u, i) => (
              <div key={i} className="list-item status-warn" style={{ padding: '6px 10px' }}>
                <div className="item-head">
                  <strong style={{ fontFamily: 'monospace', fontSize: 12 }}>{u.mac_normalized || '?'}</strong>
                  <div className="inline-badges">
                    <span className="badge badge-neutral">{u.device_type}</span>
                    <span className="badge badge-muted" style={{ fontFamily: 'monospace' }}>{u.firmware_version}</span>
                    <span className="badge badge-muted">{_fmtRelative(u.event_datetime)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : null}

      <small style={{ color: 'var(--muted)', fontSize: 11, marginTop: 8, display: 'block' }}>
        Pair-success rate uses the latest telemetry-active device count as the denominator.
        At small N, this can exceed 100% — settles as more devices pair over the window.
      </small>
    </section>
  )
}
