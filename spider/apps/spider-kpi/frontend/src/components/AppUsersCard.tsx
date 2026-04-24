import { useEffect, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'
import { api } from '../lib/api'
import type { KlaviyoAppEngagement, KlaviyoAppProfileSummary, KlaviyoSyncStatus } from '../lib/api'

/**
 * App & Users — Klaviyo-backed view of actual mobile app usage.
 *
 * Distinct from the Venom telemetry fleet ("devices phoning home via
 * AWS"); this tracks users who have installed and opened the Spider
 * Grills native app. Agustin's app fires Klaviyo "Opened App" events
 * on every launch and writes device ownership + phone platform to
 * the profile, so we get DAU/MAU/stickiness plus an iOS vs Android
 * split on the fly.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

function fmtFreshness(iso: string | null | undefined): string {
  if (!iso) return '—'
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function AppUsersCard() {
  const [engagement, setEngagement] = useState<KlaviyoAppEngagement | null>(null)
  const [summary, setSummary] = useState<KlaviyoAppProfileSummary | null>(null)
  const [syncStatus, setSyncStatus] = useState<KlaviyoSyncStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    Promise.all([
      api.klaviyoAppEngagement(30, ctl.signal),
      api.klaviyoAppProfileSummary(ctl.signal),
      api.klaviyoSyncStatus(ctl.signal),
    ])
      .then(([e, s, st]) => { setEngagement(e); setSummary(s); setSyncStatus(st) })
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>App & Users</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>
          {error.includes('404') || error.includes('500')
            ? 'App engagement data not yet available — Klaviyo connector may still be indexing. Retry in a few minutes.'
            : `Error: ${error}`}
        </div>
      </section>
    )
  }
  if (!engagement || !summary || !syncStatus) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>App & Users</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  const stickinessPct = engagement.stickiness_pct
  const iosPct = summary.phone_os.find(r => r.label === 'ios')?.pct ?? 0
  const androidPct = summary.phone_os.find(r => r.label === 'android')?.pct ?? 0
  const topAppVersion = summary.app_version[0]
  const versionFragmentation = summary.app_version.length

  const series = engagement.daily_unique_openers.map(r => ({
    date: r.date.slice(5),
    users: r.unique_profiles,
  }))

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>App & Users</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Klaviyo-backed native-app engagement · {fmtInt(summary.app_profiles)} installed profiles · Updated {fmtFreshness(syncStatus.latest_event_at)}
          </div>
        </div>
      </div>

      {/* KPI tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10, marginTop: 12 }}>
        <div className="kpi-tile">
          <div className="kpi-tile-label">DAU</div>
          <div className="kpi-tile-value">{fmtInt(engagement.dau)}</div>
          <div className="kpi-tile-sub">last 24h</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">MAU</div>
          <div className="kpi-tile-value">{fmtInt(engagement.mau)}</div>
          <div className="kpi-tile-sub">last 30d</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Stickiness</div>
          <div className="kpi-tile-value" style={{ color: stickinessPct >= 20 ? 'var(--green)' : stickinessPct >= 10 ? 'var(--orange)' : 'var(--red)' }}>
            {stickinessPct.toFixed(1)}%
          </div>
          <div className="kpi-tile-sub">DAU/MAU</div>
        </div>
        <div className="kpi-tile">
          <div className="kpi-tile-label">Active 30d</div>
          <div className="kpi-tile-value">{fmtInt(summary.active_30d)}</div>
          <div className="kpi-tile-sub">of {fmtInt(summary.app_profiles)} profiles</div>
        </div>
      </div>

      {/* Daily openers line */}
      {series.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
            Daily unique openers — last 30 days
          </div>
          <div className="chart-wrap-short">
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={series}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 10 }} interval={2} />
                <YAxis stroke="#9fb0d4" tick={{ fontSize: 10 }} />
                <Tooltip />
                <Line type="monotone" dataKey="users" stroke="var(--blue)" strokeWidth={2} dot={false} name="Unique openers" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Platform + version splits */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10, marginTop: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Phone OS</div>
          {summary.phone_os.length === 0 ? (
            <div style={{ fontSize: 12 }}>—</div>
          ) : (
            <div style={{ fontSize: 12 }}>
              {summary.phone_os.slice(0, 2).map(r => (
                <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span>{r.label === 'ios' ? 'iOS' : r.label === 'android' ? 'Android' : r.label}</span>
                  <span style={{ color: 'var(--muted)' }}>{fmtInt(r.count)} · {r.pct}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>App versions ({versionFragmentation})</div>
          <div style={{ fontSize: 12 }}>
            {summary.app_version.slice(0, 4).map(r => (
              <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span>{r.label}</span>
                <span style={{ color: 'var(--muted)' }}>{fmtInt(r.count)} · {r.pct}%</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Device types (app-reported)</div>
          <div style={{ fontSize: 12 }}>
            {summary.device_types.length === 0 ? (
              <span>—</span>
            ) : (
              summary.device_types.slice(0, 4).map(r => (
                <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                  <span>{r.label}</span>
                  <span style={{ color: 'var(--muted)' }}>{fmtInt(r.count)} · {r.pct}%</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 10 }}>
        iOS {iosPct.toFixed(0)}% · Android {androidPct.toFixed(0)}% · Latest app version <strong>{topAppVersion?.label ?? '—'}</strong> on {topAppVersion?.pct.toFixed(0) ?? 0}% of installed base.
        Sync: {fmtInt(syncStatus.profiles_total)} profiles · {fmtInt(syncStatus.events_total)} events · latest event {fmtFreshness(syncStatus.latest_event_at)}.
      </div>
    </section>
  )
}
