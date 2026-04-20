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
  type FirmwareOverviewMetrics,
  type FirmwareDeviceSummary,
  type FirmwareDeviceShadow,
  type FirmwareDeviceActiveCook,
  type FirmwareDeviceRecent,
  type FirmwareSession,
} from '../lib/api'
import { BetaProgramPanel } from '../components/BetaProgramPanel'
import { FirmwareDeployPanel, FirmwareDeployLogView } from '../components/FirmwareDeployPanel'
import { useAuth } from '../components/AuthGate'

type TabKey = 'overview' | 'device' | 'alpha' | 'beta' | 'gamma' | 'deploy' | 'log'

const OWNER_EMAIL = 'joseph@spidergrills.com'

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
  const { user } = useAuth()
  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL
  const tabs: Array<{ key: TabKey; label: string }> = [
    { key: 'overview', label: 'Overview' },
    { key: 'alpha', label: 'Alpha (R&D)' },
    { key: 'beta', label: 'Beta' },
    { key: 'gamma', label: 'Gamma' },
    { key: 'device', label: 'Device Drill-down' },
  ]
  if (isOwner) {
    tabs.push({ key: 'deploy', label: 'Deploy' })
    tabs.push({ key: 'log', label: 'Deploy Log' })
  }
  return (
    <div className="page-grid">
      <section className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div className="card-title">Firmware Hub</div>
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            Program health, cohort status, and per-device drill-down. Live shadow polls every 15 s.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4, background: 'var(--panel-2)', borderRadius: 8, padding: 2, flexWrap: 'wrap' }}>
          {tabs.map(t => (
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
      {tab === 'deploy' ? <FirmwareDeployPanel /> : null}
      {tab === 'log' ? <FirmwareDeployLogView /> : null}
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

type RangePreset = '24h' | '7d' | '30d' | '90d'

const PRESETS: Array<{ key: RangePreset; label: string; days: number }> = [
  { key: '24h', label: 'Last 24 h', days: 1 },
  { key: '7d', label: 'Last 7 d', days: 7 },
  { key: '30d', label: 'Last 30 d', days: 30 },
  { key: '90d', label: 'Last 90 d', days: 90 },
]

function toDateInputValue(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function rangeForPreset(preset: RangePreset): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  const p = PRESETS.find(x => x.key === preset)!
  start.setDate(end.getDate() - p.days)
  return { start: toDateInputValue(start), end: toDateInputValue(end) }
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function fmtPctRaw(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  // in_control_pct is 0..1 in the session table.
  const pct = v <= 1 ? v * 100 : v
  return `${pct.toFixed(1)}%`
}

function OverviewTab() {
  const [preset, setPreset] = useState<RangePreset>('7d')
  const initial = rangeForPreset('7d')
  const [start, setStart] = useState(initial.start)
  const [end, setEnd] = useState(initial.end)
  const [firmwareFilter, setFirmwareFilter] = useState<string>('')
  const [metrics, setMetrics] = useState<FirmwareOverviewMetrics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    api.firmwareOverviewMetrics(
      { start, end, firmware_version: firmwareFilter || undefined },
      ctl.signal,
    )
      .then(d => { setMetrics(d); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [start, end, firmwareFilter])

  const applyPreset = (p: RangePreset) => {
    setPreset(p)
    const r = rangeForPreset(p)
    setStart(r.start)
    setEnd(r.end)
  }

  return (
    <>
      <section className="card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div className="card-title">Firmware metrics</div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              Cook success, PID quality, and disconnect rate across the window.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 4, background: 'var(--panel-2)', borderRadius: 8, padding: 2, flexWrap: 'wrap' }}>
            {PRESETS.map(p => (
              <button
                key={p.key}
                className={`range-button${preset === p.key ? ' active' : ''}`}
                onClick={() => applyPreset(p.key)}
              >{p.label}</button>
            ))}
          </div>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', fontSize: 13 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>Start</span>
            <input
              type="date"
              className="deci-input"
              value={start}
              onChange={e => { setStart(e.target.value); setPreset('7d'); }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>End</span>
            <input
              type="date"
              className="deci-input"
              value={end}
              onChange={e => { setEnd(e.target.value); setPreset('7d'); }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: '1 1 200px', minWidth: 180 }}>
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>Firmware (optional)</span>
            <input
              className="deci-input"
              value={firmwareFilter}
              onChange={e => setFirmwareFilter(e.target.value)}
              placeholder="e.g. 1.4.12"
            />
          </label>
        </div>
      </section>

      {loading ? <section className="card"><div className="state-message">Loading metrics…</div></section> : null}
      {error ? <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section> : null}

      {metrics && !loading && !error ? (
        <>
          <section className="card">
            <div className="card-title">Window stats</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10 }}>
              <Stat label="Sessions" value={metrics.sessions.toLocaleString()} />
              <Stat label="Devices with cooks" value={metrics.devices.toLocaleString()} />
              <Stat label="Cook success rate" value={fmtPct(metrics.cook_success_rate)} />
              <Stat label="Avg in-control %" value={fmtPctRaw(metrics.avg_in_control_pct)} />
              <Stat label="Disconnect events" value={metrics.disconnect_events.toLocaleString()} />
              <Stat
                label="Disconnects / session"
                value={metrics.disconnect_rate_per_session != null ? metrics.disconnect_rate_per_session.toFixed(2) : '—'}
              />
            </div>
          </section>

          <section className="card">
            <div className="card-title">Firmware distribution — active in window</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
              {metrics.active_devices_window.toLocaleString()} devices reported at least once in this window.
            </div>
            {metrics.firmware_distribution.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>No stream events in this window.</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}>
                {metrics.firmware_distribution.slice(0, 24).map(d => (
                  <button
                    key={d.firmware_version}
                    className="range-button"
                    style={{
                      flexDirection: 'column',
                      alignItems: 'flex-start',
                      padding: 10,
                      background: firmwareFilter === d.firmware_version ? 'var(--panel-2)' : 'transparent',
                      height: 'auto',
                    }}
                    onClick={() => setFirmwareFilter(firmwareFilter === d.firmware_version ? '' : d.firmware_version)}
                    title={firmwareFilter === d.firmware_version ? 'Clear firmware filter' : 'Filter metrics to this firmware'}
                  >
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>{d.firmware_version}</div>
                    <div style={{ fontSize: 20, fontWeight: 600 }}>{d.devices}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{d.pct}% of active</div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </>
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
  const [recents, setRecents] = useState<FirmwareDeviceRecent[]>([])
  const [recentsError, setRecentsError] = useState<string | null>(null)

  const reloadRecents = useCallback(async () => {
    try {
      const res = await api.firmwareDeviceRecents()
      setRecents(res.recents)
      setRecentsError(null)
    } catch (e: unknown) {
      setRecentsError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => { reloadRecents() }, [reloadRecents])

  // Upsert whenever activeMac becomes set.
  useEffect(() => {
    if (!activeMac) return
    let alive = true
    api.firmwareDeviceRecentUpsert(activeMac)
      .then(() => { if (alive) reloadRecents() })
      .catch(() => { /* non-fatal — recents is a convenience strip */ })
    return () => { alive = false }
  }, [activeMac, reloadRecents])

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

  const onSetNickname = useCallback(async (mac: string, nickname: string | null) => {
    try {
      await api.firmwareDeviceRecentNickname(mac, nickname)
      reloadRecents()
    } catch (e: unknown) {
      setRecentsError(e instanceof Error ? e.message : String(e))
    }
  }, [reloadRecents])

  const onDeleteRecent = useCallback(async (mac: string) => {
    try {
      await api.firmwareDeviceRecentDelete(mac)
      reloadRecents()
    } catch (e: unknown) {
      setRecentsError(e instanceof Error ? e.message : String(e))
    }
  }, [reloadRecents])

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

      <RecentsPanel
        recents={recents}
        activeMac={activeMac}
        error={recentsError}
        onSelect={mac => setActiveMac(mac)}
        onRename={onSetNickname}
        onRemove={onDeleteRecent}
      />

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

function RecentsPanel({ recents, activeMac, error, onSelect, onRename, onRemove }: {
  recents: FirmwareDeviceRecent[]
  activeMac: string | null
  error: string | null
  onSelect: (mac: string) => void
  onRename: (mac: string, nickname: string | null) => void
  onRemove: (mac: string) => void
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  if (!recents.length && !error) {
    return (
      <section className="card">
        <div className="card-title">Recent devices</div>
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>
          Devices you look up here will show up as recents with nickname tags.
        </div>
      </section>
    )
  }

  const startEdit = (r: FirmwareDeviceRecent) => {
    setEditing(r.mac)
    setDraft(r.nickname ?? '')
  }
  const commitEdit = (mac: string) => {
    onRename(mac, draft.trim() || null)
    setEditing(null)
    setDraft('')
  }

  return (
    <section className="card">
      <div className="card-title">Recent devices</div>
      {error ? <div style={{ color: 'var(--red)', fontSize: 12, marginBottom: 8 }}>{error}</div> : null}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {recents.map(r => {
          const isActive = activeMac === r.mac
          const isEditing = editing === r.mac
          return (
            <div
              key={r.mac}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 8px',
                background: isActive ? 'var(--panel-2)' : 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 6,
                flexWrap: 'wrap',
              }}
            >
              <button
                className="range-button"
                style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace', flex: '0 0 auto' }}
                onClick={() => onSelect(r.mac)}
              >{r.mac}</button>
              {isEditing ? (
                <>
                  <input
                    className="deci-input"
                    value={draft}
                    autoFocus
                    placeholder="nickname (e.g. office grill)"
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') { e.preventDefault(); commitEdit(r.mac) }
                      if (e.key === 'Escape') { setEditing(null); setDraft('') }
                    }}
                    style={{ flex: '1 1 220px', minWidth: 160 }}
                  />
                  <button className="range-button active" type="button" onClick={() => commitEdit(r.mac)}>Save</button>
                  <button className="range-button" type="button" onClick={() => { setEditing(null); setDraft('') }}>Cancel</button>
                </>
              ) : (
                <>
                  <span style={{ flex: '1 1 auto', fontSize: 13, color: r.nickname ? 'var(--fg)' : 'var(--muted)' }}>
                    {r.nickname ?? 'no nickname'}
                  </span>
                  <button className="range-button" type="button" onClick={() => startEdit(r)}>
                    {r.nickname ? 'Rename' : 'Tag'}
                  </button>
                  <button
                    className="range-button"
                    type="button"
                    onClick={() => onRemove(r.mac)}
                    title="Remove from recents"
                  >✕</button>
                </>
              )}
            </div>
          )
        })}
      </div>
    </section>
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
