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
  type AlphaCohortResponse,
  type FirmwareOverviewMetrics,
  type FirmwareDeviceSummary,
  type FirmwareDeviceShadow,
  type FirmwareDeviceActiveCook,
  type FirmwareDeviceControlSignals,
  type FirmwareDeviceRecent,
  type FirmwareFleetControlHealth,
  type FirmwareSession,
  type GammaStatusResponse,
  type CookBehaviorBaseline,
  type CookBehaviorBaselinesResponse,
  type CookBehaviorBacktestResponse,
} from '../lib/api'
import { BetaProgramPanel } from '../components/BetaProgramPanel'
import { FirmwareDeployPanel, FirmwareDeployLogView } from '../components/FirmwareDeployPanel'
import { useAuth } from '../components/AuthGate'
import { CacheFreshnessBadge } from '../components/CacheFreshnessBadge'
import { CookTimelineChart } from '../components/CookTimelineChart'

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
      {tab === 'alpha' ? <AlphaCohortPanel /> : null}
      {tab === 'beta' ? <BetaProgramPanel /> : null}
      {tab === 'gamma' ? <GammaWavesPanel /> : null}
      {tab === 'device' ? <DeviceDrillDown /> : null}
      {tab === 'deploy' ? <FirmwareDeployPanel /> : null}
      {tab === 'log' ? <FirmwareDeployLogView /> : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Alpha cohort panel (R&D grills, opt_in_source='alpha')
// ---------------------------------------------------------------------------

function AlphaCohortPanel() {
  const [data, setData] = useState<AlphaCohortResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [focusedDeviceId, setFocusedDeviceId] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    api.betaAlphaCohort(ctl.signal)
      .then(d => { setData(d); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [])

  if (loading) return <section className="card"><div className="state-message">Loading alpha cohort…</div></section>
  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!data) return null

  return (
    <>
      <section className="card">
        <div className="card-title">Alpha (R&D) cohort</div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 10 }}>
          Spider Grills-internal grills — cohort members with <code>opt_in_source = 'alpha'</code>.
          Shares the BetaCohortMember schema with beta but is kept separate here so customer devices
          don't show up in the R&D view.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10 }}>
          <Stat label="Alpha members" value={data.count.toLocaleString()} />
          {Object.entries(data.state_distribution).map(([state, n]) => (
            <Stat key={state} label={state} value={String(n)} />
          ))}
        </div>
      </section>

      <section className="card">
        <div className="card-title">Members ({data.count})</div>
        {data.members.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            No alpha members yet. Add one by inviting an internal device to a release and recording
            the opt-in with <code>source=alpha</code>.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 720 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px' }}>Release</th>
                  <th>Device</th>
                  <th>User</th>
                  <th>State</th>
                  <th>Score</th>
                  <th>Invited</th>
                  <th>Opted in</th>
                  <th>OTA pushed</th>
                </tr>
              </thead>
              <tbody>
                {data.members.map(m => (
                  <tr
                    key={`${m.release_id}:${m.device_id}`}
                    onClick={() => setFocusedDeviceId(m.device_id)}
                    style={{ borderTop: '1px solid var(--border)', cursor: 'pointer' }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                    title="Click for cook timeline"
                  >
                    <td style={{ padding: '6px 8px' }}>{m.release_version}{m.release_title ? ` · ${m.release_title}` : ''}</td>
                    <td style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{m.device_id.slice(0, 10)}…</td>
                    <td>{m.user_id ?? '—'}</td>
                    <td>{m.state}</td>
                    <td>{m.candidate_score != null ? m.candidate_score.toFixed(2) : '—'}</td>
                    <td>{fmtDateTime(m.invited_at)}</td>
                    <td>{fmtDateTime(m.opted_in_at)}</td>
                    <td>{fmtDateTime(m.ota_pushed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {focusedDeviceId ? (
        <CookTimelineChart
          deviceId={focusedDeviceId}
          lookbackHours={24}
          modal
          onClose={() => setFocusedDeviceId(null)}
        />
      ) : null}
    </>
  )
}

// ---------------------------------------------------------------------------
// Gamma waves panel (production rollout)
// ---------------------------------------------------------------------------

function GammaWavesPanel() {
  const [data, setData] = useState<GammaStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const ctl = new AbortController()
    setLoading(true)
    api.betaGammaStatus(ctl.signal)
      .then(d => { setData(d); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
      .finally(() => setLoading(false))
    return () => ctl.abort()
  }, [])

  if (loading) return <section className="card"><div className="state-message">Loading gamma status…</div></section>
  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!data) return null

  if (data.releases.length === 0) {
    return (
      <section className="card">
        <div className="card-title">Gamma rollout</div>
        <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.5, maxWidth: 720 }}>
          No releases currently approved for gamma. Gamma waves progress a release across
          production at ~10%/day once its beta verdict clears. Flip <code>approved_for_gamma</code> on
          a release to start staging waves here.
        </div>
      </section>
    )
  }

  return (
    <>
      {data.releases.map(r => (
        <section key={r.release_id} className="card">
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div>
              <div className="card-title" style={{ marginBottom: 2 }}>{r.version}{r.title ? ` · ${r.title}` : ''}</div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                {r.target_controller_model ?? 'any controller'} · approved {fmtDateTime(r.approved_at)}
                {r.released_at ? ` · released ${fmtDateTime(r.released_at)}` : ''}
              </div>
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              {r.waves.length} wave{r.waves.length === 1 ? '' : 's'} planned · {r.total_planned.toLocaleString()} devices total
            </div>
          </div>
          {r.waves.length === 0 ? (
            <div style={{ marginTop: 10, fontSize: 13, color: 'var(--muted)' }}>
              Approved for gamma but no wave plan set yet. Populate <code>gamma_plan_json</code> on
              the release to stage waves.
            </div>
          ) : (
            <div style={{ marginTop: 12, overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 680 }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                    <th style={{ padding: '6px 8px' }}>Wave</th>
                    <th>Target %</th>
                    <th>Devices</th>
                    <th>Scheduled</th>
                    <th>Started</th>
                    <th>Completed</th>
                    <th>IoT job</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {r.waves.map(w => (
                    <tr key={w.wave_index} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px' }}>Wave {w.wave_index}</td>
                      <td>{w.target_pct != null ? `${w.target_pct}%` : '—'}</td>
                      <td>{w.target_devices?.toLocaleString() ?? '—'}</td>
                      <td>{fmtDateTime(w.scheduled_at)}</td>
                      <td>{fmtDateTime(w.started_at)}</td>
                      <td>{fmtDateTime(w.completed_at)}</td>
                      <td style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>
                        {w.aws_job_id ? w.aws_job_id.slice(0, 16) + '…' : '—'}
                      </td>
                      <td>{w.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// Fleet control health (Agustin app-control review)
// ---------------------------------------------------------------------------

const STATE_BADGE: Record<string, { bg: string; fg: string; label: string }> = {
  ramping_up:     { bg: '#fef3c7', fg: '#92400e', label: 'Ramping up' },
  in_control:     { bg: '#d1fae5', fg: '#065f46', label: 'In control' },
  out_of_control: { bg: '#fee2e2', fg: '#991b1b', label: 'Out of control' },
  cooling_down:   { bg: '#dbeafe', fg: '#1e40af', label: 'Cooling down' },
  manual_mode:    { bg: '#ede9fe', fg: '#5b21b6', label: 'Manual mode' },
  error:          { bg: '#fecaca', fg: '#7f1d1d', label: 'Error' },
  idle:           { bg: '#f3f4f6', fg: '#6b7280', label: 'Idle' },
  unknown:        { bg: '#f3f4f6', fg: '#6b7280', label: 'Unknown' },
}

type ControlSortKey = 'gap_abs' | 'gap' | 'target' | 'intensity' | 'firmware' | 'sample_ts' | 'state' | 'cook_elapsed' | 'product'

function FleetControlHealthCard() {
  const [data, setData] = useState<FirmwareFleetControlHealth | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [sort, setSort] = useState<ControlSortKey>('gap_abs')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [stateFilter, setStateFilter] = useState<string>('')
  const [productFilter, setProductFilter] = useState<string>('')
  const [page, setPage] = useState<number>(1)
  const [focusedMac, setFocusedMac] = useState<string | null>(null)

  // Reset to page 1 whenever filters/sort change — otherwise the user
  // lands on page 4 of a smaller filtered list and sees "no devices."
  useEffect(() => { setPage(1) }, [sort, sortDir, stateFilter, productFilter])

  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const d = await api.firmwareFleetControlHealth({
          sort, sort_dir: sortDir,
          state: stateFilter || undefined,
          product: productFilter || undefined,
          page, per_page: 25,
        })
        if (!alive) return
        setData(d)
        setError(null)
      } catch (e: unknown) {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (alive) setLoading(false)
      }
    }
    pull()
    const t = window.setInterval(pull, 30_000)
    return () => { alive = false; window.clearInterval(t) }
  }, [sort, sortDir, stateFilter, productFilter, page])

  const toggleSort = (k: ControlSortKey) => {
    if (sort === k) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSort(k)
      setSortDir('desc')
    }
  }
  const sortIndicator = (k: ControlSortKey) =>
    sort === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''

  if (loading && !data) return <section className="card"><div className="state-message">Loading fleet control health…</div></section>
  if (error && !data) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!data) return null

  const t = data.tallies || {}
  const ramping = t.ramping_up ?? 0
  const inControl = t.in_control ?? 0
  const oocBadge = t.out_of_control ?? 0
  const cooling = t.cooling_down ?? 0
  const manual = t.manual_mode ?? 0
  const errs = t.error ?? 0

  return (
    <section className="card">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="card-title" style={{ marginBottom: 2 }}>Fleet control health — live</div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Last {Math.round(data.window_seconds / 60)} min · time-aware classifier {data.baseline_driven ? '(baseline-driven)' : '(heuristic)'} · refreshes every 30 s
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>
          fetched {new Date(data.fetched_at).toLocaleTimeString()}
        </div>
      </div>
      <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(130px,1fr))', gap: 10 }}>
        <Stat label="Reporting" value={data.total_reporting_devices.toLocaleString()} />
        <Stat label="Active cooks" value={data.active_cooks.toLocaleString()} />
        <Stat label="In control" value={inControl.toLocaleString()} />
        <Stat label="Ramping up" value={ramping.toLocaleString()} />
        <Stat label="Out of control" value={oocBadge.toLocaleString()} />
        <Stat label="Errors" value={errs.toLocaleString()} />
        <Stat label="Manual" value={manual.toLocaleString()} />
        <Stat label="Cooling" value={cooling.toLocaleString()} />
      </div>

      <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>Filter state:</span>
        <select
          value={stateFilter}
          onChange={(e) => setStateFilter(e.target.value)}
          style={{ fontSize: 12, padding: '3px 6px' }}
        >
          <option value="">All</option>
          <option value="out_of_control">Out of control only</option>
          <option value="error">Errors only</option>
          <option value="ramping_up">Ramping up</option>
          <option value="in_control">In control</option>
          <option value="cooling_down">Cooling down</option>
          <option value="manual_mode">Manual mode</option>
          <option value="idle">Idle</option>
        </select>
        <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 8 }}>Product:</span>
        <select
          value={productFilter}
          onChange={(e) => setProductFilter(e.target.value)}
          style={{ fontSize: 12, padding: '3px 6px' }}
        >
          <option value="">All products</option>
          {Object.entries(data.product_tallies || {})
            .sort((a, b) => (b[1] as number) - (a[1] as number))
            .map(([product, count]) => (
              <option key={product} value={product}>{product} ({count})</option>
            ))}
        </select>
      </div>

      {data.devices.length > 0 ? (
        <div style={{ marginTop: 10 }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 820 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '6px 8px' }}>MAC</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('product')}>Product{sortIndicator('product')}</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('state')}>State{sortIndicator('state')}</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('target')}>Target{sortIndicator('target')}</th>
                  <th>Current</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('gap_abs')}>Gap{sortIndicator('gap_abs')}</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('intensity')}>Fan{sortIndicator('intensity')}</th>
                  <th>Ramp</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('cook_elapsed')} title="Live fire detected: first sample with pit ≥140°F in this engagement">Cook started{sortIndicator('cook_elapsed')}</th>
                  <th title="When the user last set a target temperature on the controller.">Target set</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('firmware')}>Firmware{sortIndicator('firmware')}</th>
                  <th style={{ cursor: 'pointer' }} onClick={() => toggleSort('sample_ts')}>Last sample{sortIndicator('sample_ts')}</th>
                </tr>
              </thead>
              <tbody>
                {data.devices.map(d => {
                  const badge = STATE_BADGE[d.state] ?? STATE_BADGE.unknown
                  const clickable = !!d.mac
                  return (
                    <tr
                      key={d.device_id}
                      onClick={clickable ? () => setFocusedMac(d.mac!) : undefined}
                      style={{
                        borderTop: '1px solid var(--border)',
                        cursor: clickable ? 'pointer' : 'default',
                      }}
                      onMouseEnter={e => { if (clickable) (e.currentTarget.style.background = 'rgba(255,255,255,0.03)') }}
                      onMouseLeave={e => { if (clickable) (e.currentTarget.style.background = 'transparent') }}
                      title={clickable ? `${d.reason} · Click for cook timeline` : d.reason}
                    >
                      <td style={{ padding: '6px 8px', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{d.mac ?? '—'}</td>
                      <td title={d.grill_type ?? undefined}>{d.product ?? '—'}</td>
                      <td>
                        <span style={{ background: badge.bg, color: badge.fg, padding: '2px 6px', borderRadius: 4, fontSize: 11, fontWeight: 500 }}>
                          {badge.label}
                        </span>
                      </td>
                      <td>{fmtTemp(d.target_temp)}</td>
                      <td>{fmtTemp(d.current_temp)}</td>
                      <td style={{ color: d.is_anomalous ? 'var(--red)' : 'inherit' }}>
                        {d.gap_f != null ? `${d.gap_f > 0 ? '+' : ''}${Math.round(d.gap_f)}°F` : '—'}
                      </td>
                      <td>{d.intensity != null ? `${Math.round(d.intensity)}%` : '—'}</td>
                      <td>
                        {d.ramp_elapsed_seconds != null && d.ramp_budget_seconds != null
                          ? `${Math.round(d.ramp_elapsed_seconds / 60)}m / ${Math.round(d.ramp_budget_seconds / 60)}m`
                          : '—'}
                      </td>
                      <td title={d.cook_start_ts ?? undefined}>
                        {d.cook_start_ts
                          ? new Date(d.cook_start_ts).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
                          : (d.state === 'ramping_up' ? 'no fire yet' : '—')}
                        {d.cook_elapsed_seconds != null ? (
                          <span style={{ color: 'var(--muted)', fontSize: 10, marginLeft: 4 }}>
                            ({Math.round(d.cook_elapsed_seconds / 60)}m)
                          </span>
                        ) : null}
                      </td>
                      <td title={d.target_set_at ?? undefined}>
                        {d.target_set_at
                          ? new Date(d.target_set_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
                          : '—'}
                      </td>
                      <td>{d.firmware_version ?? '—'}</td>
                      <td>{fmtDateTime(d.sample_timestamp)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {data.total_pages > 1 ? (
            <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 12 }}>
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={data.page <= 1}
                style={{ padding: '4px 10px', opacity: data.page <= 1 ? 0.4 : 1 }}
              >
                ← Prev
              </button>
              <span style={{ color: 'var(--muted)' }}>
                Page {data.page} of {data.total_pages} · {data.total_filtered.toLocaleString()} devices · showing {((data.page - 1) * data.per_page) + 1}–{Math.min(data.page * data.per_page, data.total_filtered)}
              </span>
              <button
                onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                disabled={data.page >= data.total_pages}
                style={{ padding: '4px 10px', opacity: data.page >= data.total_pages ? 0.4 : 1 }}
              >
                Next →
              </button>
              <input
                type="number"
                min={1}
                max={data.total_pages}
                value={page}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  if (v >= 1 && v <= data.total_pages) setPage(v)
                }}
                style={{ width: 60, fontSize: 12, padding: '3px 6px', marginLeft: 'auto' }}
              />
            </div>
          ) : (
            <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
              {data.total_filtered.toLocaleString()} devices match filter.
            </div>
          )}
        </div>
      ) : (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)' }}>No devices matching filter.</div>
      )}

      {focusedMac ? (
        <CookTimelineChart
          mac={focusedMac}
          lookbackHours={24}
          modal
          onClose={() => setFocusedMac(null)}
        />
      ) : null}
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

// ---------------------------------------------------------------------------
// Cook Behavior Encyclopedia
// ---------------------------------------------------------------------------

function fmtSeconds(v: number | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  if (v < 60) return `${Math.round(v)}s`
  const m = Math.floor(v / 60)
  const s = Math.round(v - m * 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

function fmtNum(v: number | null, suffix = ''): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `${Math.round(v * 10) / 10}${suffix}`
}

function CookBehaviorEncyclopediaCard() {
  const [data, setData] = useState<CookBehaviorBaselinesResponse | null>(null)
  const [drift, setDrift] = useState<CookBehaviorBacktestResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildMsg, setRebuildMsg] = useState<string | null>(null)
  const { user } = useAuth()
  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL

  const load = async () => {
    try {
      const [b, bt] = await Promise.all([
        api.firmwareCookBehaviorBaselines(),
        api.firmwareCookBehaviorBacktest(),
      ])
      setData(b)
      setDrift(bt)
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const onRebuild = async () => {
    setRebuilding(true)
    setRebuildMsg(null)
    try {
      const r = await api.firmwareCookBehaviorRebuild()
      setRebuildMsg('Rebuild complete.')
      await load()
      void r
    } catch (e: unknown) {
      setRebuildMsg(`Rebuild failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setRebuilding(false)
    }
  }

  if (loading) return <section className="card"><div className="state-message">Loading cook-behavior encyclopedia…</div></section>
  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div></section>
  if (!data) return null

  const driftByKey = new Map<string, { coverage: number | null; err: number | null; n: number }>()
  drift?.rows.forEach(r => {
    driftByKey.set(`${r.target_temp_band}:${r.metric}`, {
      coverage: r.coverage_pct,
      err: r.median_error_pct,
      n: r.sample_size,
    })
  })

  return (
    <section className="card">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="card-title" style={{ marginBottom: 2 }}>Cook Behavior Encyclopedia</div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Learned baselines per target-temp band. Rebuilt nightly 08:30 UTC from every cook session.
          </div>
        </div>
        {isOwner ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {rebuildMsg ? <span style={{ fontSize: 11, color: 'var(--muted)' }}>{rebuildMsg}</span> : null}
            <button
              onClick={onRebuild}
              disabled={rebuilding}
              style={{ fontSize: 12, padding: '4px 10px' }}
            >
              {rebuilding ? 'Rebuilding…' : 'Rebuild now'}
            </button>
          </div>
        ) : null}
      </div>

      {data.baselines.length === 0 ? (
        <div style={{ marginTop: 12, fontSize: 13, color: 'var(--muted)' }}>
          No baselines computed yet. Click "Rebuild now" or wait for the 08:30 UTC nightly run.
        </div>
      ) : (() => {
        // Hide Fan + coverage columns when no baseline row has populated
        // steady_fan_p* — the DynamoDB session source doesn't carry fan
        // data, so these are structurally empty until the stream-based
        // session rebuild lands. Showing empty columns looked like a bug.
        const anyFan = data.baselines.some(b => b.steady_fan_p50 != null)
        return (
        <div style={{ marginTop: 12, overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 820 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px' }}>Target band</th>
                <th>Sessions</th>
                <th>Ramp p10 / p50 / p90</th>
                {anyFan ? <th>Fan p10 / p50 / p90</th> : null}
                <th>Stddev p50 / p90</th>
                <th>Cool p50</th>
                <th>Duration p50</th>
                <th>Ramp coverage</th>
                {anyFan ? <th>Fan coverage</th> : null}
              </tr>
            </thead>
            <tbody>
              {data.baselines.map(b => {
                const rd = driftByKey.get(`${b.target_temp_band}:ramp_time`)
                const fd = driftByKey.get(`${b.target_temp_band}:steady_fan`)
                return (
                  <tr key={`${b.target_temp_band}:${b.baseline_version}`} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 500 }}>{b.target_temp_band}–{Number(b.target_temp_band) + 49}°F</td>
                    <td>{b.sample_size}</td>
                    <td>{fmtSeconds(b.ramp_time_p10)} / {fmtSeconds(b.ramp_time_p50)} / {fmtSeconds(b.ramp_time_p90)}</td>
                    {anyFan ? <td>{fmtNum(b.steady_fan_p10, '%')} / {fmtNum(b.steady_fan_p50, '%')} / {fmtNum(b.steady_fan_p90, '%')}</td> : null}
                    <td>{fmtNum(b.steady_temp_stddev_p50, '°F')} / {fmtNum(b.steady_temp_stddev_p90, '°F')}</td>
                    <td>{fmtNum(b.cool_down_rate_p50, '°/m')}</td>
                    <td>{fmtSeconds(b.typical_duration_p50)}</td>
                    <td style={{ color: rd && rd.coverage != null && rd.coverage < 0.5 ? 'var(--red)' : 'inherit' }}>
                      {rd && rd.coverage != null ? `${Math.round(rd.coverage * 100)}% (n=${rd.n})` : '—'}
                    </td>
                    {anyFan ? (
                      <td style={{ color: fd && fd.coverage != null && fd.coverage < 0.5 ? 'var(--red)' : 'inherit' }}>
                        {fd && fd.coverage != null ? `${Math.round(fd.coverage * 100)}% (n=${fd.n})` : '—'}
                      </td>
                    ) : null}
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)' }}>
            Coverage = % of last 48h sessions whose actual values fell inside the p10–p90 band. Drops below 50% flag drift.
            {!anyFan ? ' Fan columns hidden — source data is empty until the stream-based session rebuild lands.' : ''}
          </div>
        </div>
        )
      })()}
    </section>
  )
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
      <FleetControlHealthCard />
      <CookBehaviorEncyclopediaCard />
      <section className="card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div className="card-title">Firmware metrics</div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              Cook success, PID quality, and disconnect rate across the window.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            {metrics?.cache_info ? (
              <CacheFreshnessBadge
                info={metrics.cache_info}
                onRefreshed={() => {
                  const ctl = new AbortController()
                  api.firmwareOverviewMetrics({ start, end, firmware_version: firmwareFilter || undefined }, ctl.signal)
                    .then(d => setMetrics(d))
                    .catch(() => {})
                }}
              />
            ) : null}
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
          {metrics.sessions_stale ? (
            <section
              className="card"
              style={{ borderLeft: '4px solid var(--orange)', background: 'rgba(245,158,11,0.08)' }}
            >
              <div style={{ fontSize: 13 }}>
                <strong>⚠ Session data is stale.</strong>{' '}
                TelemetrySession last updated{' '}
                <strong>{metrics.sessions_latest_ts ? new Date(metrics.sessions_latest_ts).toLocaleString() : 'unknown'}</strong>.
                The raw stream pipeline is healthy ({metrics.active_devices_window.toLocaleString()} devices
                reporting in this window) — only the DynamoDB-backed session builder is behind, so the
                session-derived KPIs below show zero. Firmware + product distribution are fresh.
              </div>
            </section>
          ) : null}

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
            <div className="card-title">Product family — active in window</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
              AWS ``grill_type`` + firmware version rolled up into the three field lines. Weber Kettle covers Kettle 22 / Kettle 26 / Webcraft (JOEHY ``W:K:22:1:V`` defaults here). Huntsman covers JOEHY on firmware 01.01.33 plus ADN V2 Huntsman builds. Giant Huntsman is reserved.
            </div>
            {metrics.product_distribution && metrics.product_distribution.length > 0 ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 10 }}>
                {metrics.product_distribution.map(p => (
                  <div
                    key={p.product}
                    style={{
                      padding: 10,
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      background: 'var(--panel-2)',
                    }}
                  >
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>{p.product}</div>
                    <div style={{ fontSize: 18, fontWeight: 600 }}>{p.devices.toLocaleString()}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{p.pct}% of fleet</div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: 'var(--muted)' }}>No stream events in this window.</div>
            )}
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

      {activeMac ? (
        <>
          <CookTimelineChart mac={activeMac} lookbackHours={24} />
          <DevicePanel mac={activeMac} />
        </>
      ) : (
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
  const [control, setControl] = useState<FirmwareDeviceControlSignals | null>(null)
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

  // Poll shadow + active cook + control signals every 15s.
  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const [sh, ck, cs] = await Promise.all([
          api.firmwareDeviceShadow(mac),
          api.firmwareDeviceActiveCook(mac),
          api.firmwareDeviceControlSignals(mac),
        ])
        if (!alive) return
        setShadow(sh)
        setCook(ck)
        setControl(cs)
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

      {/* Commanded vs reported — app-control review */}
      {control?.signals ? (
        <section className="card">
          <div className="card-title">Commanded vs reported</div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
            What the grill is honoring (target) vs. what it's doing now (actual). Gap is what the
            PID loop is chasing.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 10 }}>
            <Stat label="Commanded target" value={fmtTemp(control.signals.target_temp)} />
            <Stat label="Reported current" value={fmtTemp(control.signals.current_temp)} />
            <Stat
              label="Gap"
              value={
                control.signals.gap_f != null
                  ? `${control.signals.gap_f > 0 ? '+' : ''}${Math.round(control.signals.gap_f)}°F`
                  : '—'
              }
            />
            <Stat label="Intensity" value={control.signals.intensity != null ? `${Math.round(control.signals.intensity)}%` : '—'} />
            <Stat label="Heating" value={control.signals.heating == null ? '—' : control.signals.heating ? 'Yes' : 'No'} />
            <Stat label="Engaged" value={control.signals.engaged == null ? '—' : control.signals.engaged ? 'Yes' : 'No'} />
            <Stat label="Paused" value={control.signals.paused == null ? '—' : control.signals.paused ? 'Yes' : 'No'} />
            <Stat label="Door open" value={control.signals.door_open == null ? '—' : control.signals.door_open ? 'Yes' : 'No'} />
            <Stat label="Power on" value={control.signals.power_on == null ? '—' : control.signals.power_on ? 'Yes' : 'No'} />
          </div>
          {control.signals.probes.length > 0 ? (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>Probes</div>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                    <th style={{ padding: '4px 8px' }}>Probe</th>
                    <th>Target</th>
                    <th>Current</th>
                    <th>Gap</th>
                  </tr>
                </thead>
                <tbody>
                  {control.signals.probes.map(p => {
                    const gap = (p.current_temp != null && p.target_temp != null)
                      ? p.current_temp - p.target_temp : null
                    return (
                      <tr key={p.probe} style={{ borderTop: '1px solid var(--border)' }}>
                        <td style={{ padding: '4px 8px' }}>{p.probe}</td>
                        <td>{fmtTemp(p.target_temp)}</td>
                        <td>{fmtTemp(p.current_temp)}</td>
                        <td style={{ color: gap != null && Math.abs(gap) > 15 ? '#f59e0b' : 'inherit' }}>
                          {gap != null ? `${gap > 0 ? '+' : ''}${Math.round(gap)}°F` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
          {control.event_at ? (
            <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
              Sample at {fmtDateTime(control.event_at)}
            </div>
          ) : null}
        </section>
      ) : null}

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
