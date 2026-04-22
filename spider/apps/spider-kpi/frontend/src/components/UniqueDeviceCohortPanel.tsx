import { useMemo } from 'react'
import { fmtInt, fmtPct } from '../lib/format'
import type { CookDurationStats } from '../lib/types'

/**
 * Device-cohort analytics — "of our active-fleet Venoms, how broad is
 * the user base this window?"
 *
 * Primary metric:
 *   * Unique active devices — count of distinct device_ids that
 *     produced a session in the window
 *   * Sessions-per-device histogram — reveals heavy-tail shape
 *     (few power users) vs broad engagement
 *   * Avg / median sessions per device
 *
 * `installedBase` should come from /api/fleet/size.active_24mo.total.
 * Passing 0 (or omitting) makes the % row render "—" instead of lying
 * against a stale placeholder — which is what the old 13k default did.
 */

type Props = {
  stats: CookDurationStats
  installedBase?: number
}

export function UniqueDeviceCohortPanel({ stats, installedBase = 0 }: Props) {
  const hasSessions = stats.source === 'telemetry_sessions'
  const uniqueDevices = stats.unique_devices || 0
  const partial = !!stats.unique_devices_is_partial

  // Compute pct of installed base that's active (or partial).
  const pctActive = installedBase > 0 ? uniqueDevices / installedBase : null

  const buckets = useMemo(() => {
    const h = stats.sessions_per_device_histogram
    if (!h) return [] as Array<{ bucket: string; count: number; pct: number }>
    const order = ['1', '2-3', '4-6', '7-14', '15-29', '30+']
    const total = Object.values(h).reduce((s, n) => s + (n || 0), 0) || 1
    return order
      .filter(k => k in h)
      .map(k => ({
        bucket: k,
        count: h[k] || 0,
        pct: ((h[k] || 0) / total) * 100,
      }))
  }, [stats.sessions_per_device_histogram])

  // Visual density — max bar width for the histogram.
  const maxBarPct = Math.max(...buckets.map(b => b.pct), 1)

  return (
    <section
      style={{
        marginTop: 12,
        padding: '14px 16px',
        background: 'rgba(255,255,255,0.03)',
        borderLeft: `3px solid ${hasSessions ? '#4a7aff' : '#f59e0b'}`,
        borderRadius: 6,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <strong style={{ fontSize: 13 }}>Active-device cohort</strong>
          <p style={{ fontSize: 11, color: 'var(--muted)', margin: '2px 0 0', lineHeight: 1.4 }}>
            How many distinct Venoms actually cooked in this window — and how concentrated is usage?
            {!hasSessions && <span style={{ color: 'var(--orange)' }}> Sessions backfill in progress; histogram + per-device stats pending.</span>}
          </p>
        </div>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          {hasSessions
            ? `source: telemetry_sessions`
            : `source: last ${stats.unique_devices_source_days || 9}d of stream events (partial)`}
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 10,
          marginBottom: buckets.length > 0 ? 14 : 0,
        }}
      >
        <div style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
            Unique active devices
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, color: hasSessions ? 'var(--blue)' : 'var(--orange)' }}>
            {fmtInt(uniqueDevices)}
            {partial && <span style={{ fontSize: 11, color: 'var(--orange)', marginLeft: 6 }}>partial</span>}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            in the selected window
          </div>
        </div>

        <div style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
            % of installed base
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, color: 'var(--text)' }}>
            {pctActive != null ? fmtPct(pctActive, 1) : '—'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            {installedBase > 0
              ? `of ${fmtInt(installedBase)} active-fleet Venoms (24mo)`
              : 'fleet-size endpoint pending'}
          </div>
        </div>

        <div style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
            Avg sessions/device
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, color: 'var(--text)' }}>
            {stats.avg_sessions_per_device != null ? stats.avg_sessions_per_device.toFixed(1) : '—'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            mean across active cohort
          </div>
        </div>

        <div style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
            Median sessions/device
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, color: 'var(--text)' }}>
            {stats.median_sessions_per_device != null ? stats.median_sessions_per_device : '—'}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            typical user — resists long-tail skew
          </div>
        </div>
      </div>

      {buckets.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 8 }}>
            Sessions-per-device distribution
            <span style={{ color: 'var(--muted)', textTransform: 'none', letterSpacing: 0, fontWeight: 400, marginLeft: 8 }}>
              — heavy-tailed = small power-user cohort · flat = broad engagement
            </span>
          </div>
          <div style={{ display: 'grid', gap: 4 }}>
            {buckets.map(b => (
              <div key={b.bucket} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
                <span style={{ width: 60, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
                  {b.bucket}
                </span>
                <div style={{ flex: 1, height: 16, background: 'rgba(255,255,255,0.04)', borderRadius: 3, position: 'relative' }}>
                  <div
                    style={{
                      width: `${(b.pct / maxBarPct) * 100}%`,
                      height: '100%',
                      background: b.bucket === '30+' ? '#ef4444' : b.bucket === '15-29' ? '#f59e0b' : b.bucket === '1' ? '#6b7280' : '#4a7aff',
                      borderRadius: 3,
                      transition: 'width 120ms ease',
                    }}
                  />
                </div>
                <span style={{ minWidth: 110, fontVariantNumeric: 'tabular-nums', color: 'var(--text)' }}>
                  <strong>{fmtInt(b.count)}</strong>
                  <span style={{ color: 'var(--muted)', marginLeft: 6 }}>({b.pct.toFixed(1)}%)</span>
                </span>
              </div>
            ))}
          </div>
          <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8, lineHeight: 1.5 }}>
            Devices in the <strong style={{ color: '#6b7280' }}>"1"</strong> bucket cooked only once in the window — possible tryout, returning user, or occasional cook.
            <strong style={{ color: '#4a7aff' }}> 4-14</strong> sessions is a regular user (≈weekly cadence over 30d).
            <strong style={{ color: '#ef4444' }}> 30+</strong> is a power user; a heavy concentration here means the active cohort is narrow.
          </p>
        </div>
      )}

      {stats.top_device_sessions && stats.top_device_sessions.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--muted)' }}>
            Top 10 power-user devices ({stats.top_device_sessions.length})
          </summary>
          <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6 }}>
            {stats.top_device_sessions.map((d, i) => (
              <div key={i} style={{ padding: '4px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: 4, fontSize: 11 }}>
                <code style={{ color: 'var(--muted)', fontSize: 10 }}>{d.device_id_short}…</code>
                <div style={{ fontWeight: 600 }}>{fmtInt(d.sessions)} sessions</div>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  )
}
