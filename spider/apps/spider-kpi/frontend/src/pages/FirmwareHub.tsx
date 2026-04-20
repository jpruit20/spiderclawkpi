/**
 * Firmware Hub — central surface for firmware work: program overview,
 * beta/alpha/gamma cohorts, and per-device drill-down with live shadow
 * polling (15s — matches AWS cadence).
 *
 * Deploy controls are intentionally absent from Phase 1. The page is
 * view-only so anyone with a dashboard session can look up a device.
 * When deploy lands it will be owner-gated the same way the ECR tracker
 * route guards are.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from 'recharts'
import {
  api,
  type FirmwareOverview,
  type FirmwareDeviceSummary,
  type FirmwareDeviceShadow,
  type FirmwareDeviceActiveCook,
  type FirmwareSession,
} from '../lib/api'
import { BetaProgramPanel } from '../components/BetaProgramPanel'

type TabKey = 'overview' | 'device' | 'alpha' | 'beta' | 'gamma'

const SHADOW_POLL_MS = 15_000

function fmtTemp(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `${Math.round(v)}°F`
}

function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null) return 'never'
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s ago`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m ago`
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

export function FirmwareHub() {
  const [tab, setTab] = useState<TabKey>('overview')
  return (
    <div className="page-grid">
      <section className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div className="card-title">Firmware Hub</div>
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            Program health, cohort status, and per-device drill-down. Live shadow polls every 15 s.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4, background: 'var(--panel-2)', borderRadius: 8, padding: 2 }}>
          {([
            { key: 'overview', label: 'Overview' },
            { key: 'alpha', label: 'Alpha (R&D)' },
            { key: 'beta', label: 'Beta' },
            { key: 'gamma', label: 'Gamma' },
            { key: 'device', label: 'Device Drill-down' },
          ] as Array<{ key: TabKey; label: string }>).map(t => (
            <button
              key={t.key}
              className={`range-button${tab === t.key ? ' active' : ''}`}
              onClick={() => setTab(t.key)}
            >{t.label}</button>
          ))}
        </div>
      </section>

      {tab === 'overview' ? <OverviewTab /> : null}
      {tab === 'alpha' ? <PlaceholderTab title="Alpha (R&D) cohort" copy="Spider Grills-internal grills only (< 10 devices). Shares the BetaCohortMember schema — separation coming in Phase 2 when the stage enum is wired in. For now, add devices to a beta release and treat employees as the alpha cohort." /> : null}
      {tab === 'beta' ? <BetaProgramPanel /> : null}
      {tab === 'gamma' ? <PlaceholderTab title="Gamma rollout" copy="Production-wide 10%/day progression once a beta clears its verdict. Surfaces the IoT job IDs + per-wave device counts in Phase 2." /> : null}
      {tab === 'device' ? <DeviceDrillDown /> : null}
    </div>
  )
}

function PlaceholderTab({ title, copy }: { title: string; copy: string }) {
  return (
    <section className="card">
      <div className="card-title">{title}</div>
      <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.5, maxWidth: 720 }}>{copy}</div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

function OverviewTab() {
  const [data, setData] = useState<FirmwareOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    api.firmwareOverview(ctl.signal)
      .then(d => { setData(d); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [])

  if (loading) return <section className="card"><div className="state-message">Loading overview…</div></section>
  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!data) return null

  return (
    <section className="card">
      <div className="card-title">Fleet firmware — last 24 h</div>
      <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
        {data.active_devices} devices reporting. Devices that haven't reported in the last 24 h aren't included.
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}>
        {data.firmware_distribution.slice(0, 24).map(d => (
          <div key={d.firmware_version} style={{ padding: 10, background: 'var(--panel-2)', borderRadius: 8 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>{d.firmware_version}</div>
            <div style={{ fontSize: 20, fontWeight: 600 }}>{d.devices}</div>
            <div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.pct}% of active</div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Device drill-down
// ---------------------------------------------------------------------------

function DeviceDrillDown() {
  const [query, setQuery] = useState('')
  const [activeMac, setActiveMac] = useState<string | null>(null)
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [lookupLoading, setLookupLoading] = useState(false)
  const [lookupCandidates, setLookupCandidates] = useState<string[]>([])

  const onLookup = useCallback(async (raw: string) => {
    const q = raw.trim()
    if (!q) return
    setLookupLoading(true)
    setLookupError(null)
    try {
      const res = await api.firmwareDeviceLookup(q)
      if (!res.devices.length) {
        setLookupError(`No devices found for "${q}".`)
        setLookupCandidates([])
        return
      }
      if (res.devices.length === 1) {
        setActiveMac(res.devices[0].mac)
        setLookupCandidates([])
      } else {
        setLookupCandidates(res.devices.map(d => d.mac))
      }
    } catch (e: unknown) {
      setLookupError(e instanceof Error ? e.message : String(e))
    } finally {
      setLookupLoading(false)
    }
  }, [])

  return (
    <>
      <section className="card">
        <div className="card-title">Look up a device</div>
        <form
          onSubmit={e => { e.preventDefault(); onLookup(query) }}
          style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}
        >
          <input
            className="deci-input"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="MAC (fcb467f9b456 or fc:b4:67:f9:b4:56) or email/user_key"
            style={{ flex: '1 1 320px', minWidth: 240 }}
          />
          <button className="range-button active" type="submit" disabled={lookupLoading}>
            {lookupLoading ? 'Looking up…' : 'Look up'}
          </button>
          {activeMac ? (
            <button
              type="button"
              className="range-button"
              onClick={() => { setActiveMac(null); setLookupCandidates([]); setQuery('') }}
            >Clear</button>
          ) : null}
        </form>
        {lookupError ? <div style={{ marginTop: 10, color: 'var(--red)', fontSize: 13 }}>{lookupError}</div> : null}
        {lookupCandidates.length > 1 ? (
          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>Multiple devices matched. Pick one:</div>
            {lookupCandidates.map(m => (
              <button key={m} className="range-button" style={{ justifyContent: 'flex-start' }} onClick={() => { setActiveMac(m); setLookupCandidates([]) }}>
                {m}
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {activeMac ? <DevicePanel mac={activeMac} /> : (
        <section className="card">
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            Tip: the office grill is MAC <code>fcb467f9b456</code>. Paste any format — separators and case don't matter.
          </div>
        </section>
      )}
    </>
  )
}

function DevicePanel({ mac }: { mac: string }) {
  const [summary, setSummary] = useState<FirmwareDeviceSummary | null>(null)
  const [shadow, setShadow] = useState<FirmwareDeviceShadow | null>(null)
  const [cook, setCook] = useState<FirmwareDeviceActiveCook | null>(null)
  const [sessions, setSessions] = useState<FirmwareSession[]>([])
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  // Load the heavy stuff once per mac.
  useEffect(() => {
    mountedRef.current = true
    const ctl = new AbortController()
    setSummary(null); setSessions([]); setShadow(null); setCook(null); setError(null)
    Promise.all([
      api.firmwareDeviceSummary(mac, ctl.signal),
      api.firmwareDeviceSessions(mac, 20, ctl.signal),
    ])
      .then(([s, sess]) => {
        if (!mountedRef.current) return
        setSummary(s)
        setSessions(sess.sessions)
      })
      .catch(e => { if (e.name !== 'AbortError' && mountedRef.current) setError(String(e.message || e)) })
    return () => { mountedRef.current = false; ctl.abort() }
  }, [mac])

  // Poll shadow + active cook every 15s.
  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const [sh, ck] = await Promise.all([
          api.firmwareDeviceShadow(mac),
          api.firmwareDeviceActiveCook(mac),
        ])
        if (!alive) return
        setShadow(sh)
        setCook(ck)
      } catch {
        // swallow transient poll errors
      }
    }
    pull()
    const t = window.setInterval(pull, SHADOW_POLL_MS)
    return () => { alive = false; window.clearInterval(t) }
  }, [mac])

  const trailData = useMemo(() => {
    if (!cook?.trail?.length) return []
    return cook.trail.map(e => ({
      t: e.sample_timestamp ? new Date(e.sample_timestamp).getTime() : 0,
      label: e.sample_timestamp ? new Date(e.sample_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '',
      current: e.current_temp ?? null,
      target: e.target_temp ?? null,
    }))
  }, [cook])

  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!summary) return <section className="card"><div className="state-message">Loading device…</div></section>

  const live = shadow?.event
  return (
    <>
      {/* Identity + status header */}
      <section className="card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div className="card-title" style={{ marginBottom: 4 }}>{summary.mac}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              {summary.app_side.controller_model ?? '—'} · app {summary.app_side.app_version ?? '—'} · {summary.app_side.phone_brand ?? '—'} {summary.app_side.phone_model ?? ''} ({summary.app_side.phone_os ?? '—'} {summary.app_side.phone_os_version ?? ''})
            </div>
          </div>
          <div style={{ textAlign: 'right', fontSize: 12, color: 'var(--muted)' }}>
            <div>Last shadow: <strong style={{ color: 'var(--fg)' }}>{fmtAge(shadow?.age_seconds)}</strong></div>
            <div>{cook?.active ? <span style={{ color: 'var(--green)' }}>● LIVE COOK</span> : 'Idle'}</div>
          </div>
        </div>
      </section>

      {/* Live shadow strip */}
      <section className="card">
        <div className="card-title">Live shadow</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10 }}>
          <Stat label="Current temp" value={fmtTemp(live?.current_temp)} />
          <Stat label="Target temp" value={fmtTemp(live?.target_temp)} />
          <Stat label="Heating" value={live?.heating ? 'Yes' : live?.heating === false ? 'No' : '—'} />
          <Stat label="Intensity" value={live?.intensity != null ? `${Math.round(live.intensity)}%` : '—'} />
          <Stat label="RSSI" value={live?.rssi != null ? `${Math.round(live.rssi)} dBm` : '—'} />
          <Stat label="Firmware" value={live?.firmware_version ?? '—'} />
          <Stat label="Grill" value={live?.grill_type ?? '—'} />
          <Stat label="Engaged" value={live?.engaged ? 'Yes' : 'No'} />
        </div>
        {live?.error_codes && live.error_codes.length > 0 ? (
          <div style={{ marginTop: 10, fontSize: 12 }}>
            <span style={{ color: 'var(--muted)' }}>Error codes: </span>
            {live.error_codes.map((c, i) => (
              <span key={i} style={{ marginRight: 6, padding: '2px 6px', borderRadius: 4, background: 'rgba(239,68,68,0.15)', color: 'var(--red)' }}>{String(c)}</span>
            ))}
          </div>
        ) : null}
      </section>

      {/* Active cook chart */}
      {cook?.active && trailData.length > 1 ? (
        <section className="card">
          <div className="card-title">Active cook — live trail</div>
          <div style={{ width: '100%', height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={trailData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--muted)' }} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--muted)' }} domain={['auto', 'auto']} />
                <Tooltip contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', fontSize: 12 }} />
                <Line type="monotone" dataKey="current" name="Current" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="target" name="Target" stroke="#6ea8ff" strokeWidth={2} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      ) : null}

      {/* Cohort memberships */}
      <section className="card">
        <div className="card-title">Program memberships</div>
        {summary.cohorts.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>Not in any alpha / beta / gamma cohort.</div>
        ) : (
          <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 0' }}>Release</th>
                <th>State</th>
                <th>Invited</th>
                <th>Opted in</th>
                <th>OTA pushed</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {summary.cohorts.map(c => (
                <tr key={c.release_id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 0' }}>{c.release_version}{c.release_title ? ` · ${c.release_title}` : ''}</td>
                  <td>{c.state}</td>
                  <td>{fmtDateTime(c.invited_at)}</td>
                  <td>{fmtDateTime(c.opted_in_at)}</td>
                  <td>{fmtDateTime(c.ota_pushed_at)}</td>
                  <td>{c.verdict ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Session history */}
      <section className="card">
        <div className="card-title">Recent cooks ({sessions.length})</div>
        {sessions.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>No sessions recorded for this device.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 720 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px' }}>Start</th>
                  <th>Duration</th>
                  <th>Target</th>
                  <th>Firmware</th>
                  <th>Intent → Outcome</th>
                  <th>In control</th>
                  <th>Disconnects</th>
                  <th>Errors</th>
                  <th>Success</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map(s => (
                  <tr key={s.source_event_id} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 8px' }}>{fmtDateTime(s.session_start)}</td>
                    <td>{s.session_duration_seconds != null ? `${Math.round(s.session_duration_seconds / 60)}m` : '—'}</td>
                    <td>{fmtTemp(s.target_temp)}</td>
                    <td>{s.firmware_version ?? '—'}</td>
                    <td>{(s.cook_intent ?? '—')} → {(s.cook_outcome ?? '—')}</td>
                    <td>{s.in_control_pct != null ? `${Math.round(s.in_control_pct * 100)}%` : '—'}</td>
                    <td>{s.disconnect_events}</td>
                    <td>{s.error_count}</td>
                    <td style={{ color: s.cook_success ? 'var(--green)' : 'var(--muted)' }}>{s.cook_success ? 'Yes' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card" style={{ fontSize: 12, color: 'var(--muted)' }}>
        Phase 1 is view-only. OTA push, cohort assignment, and alpha promotion land in Phase 2 — gated to <Link to="/lore" style={{ color: 'inherit', textDecoration: 'underline' }}>owner access</Link> only.
      </section>
    </>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: 10, background: 'var(--panel-2)', borderRadius: 8 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
    </div>
  )
}
