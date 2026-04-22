import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type {
  AlphaBulkImportResult,
  AlphaCohortAnalytics,
  AlphaCohortErrorPatterns,
  AlphaCohortInsight,
  AlphaCohortTrend,
  AlphaFirmwareTimeline,
} from '../lib/api'
import { fmtInt } from '../lib/format'
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { useAuth } from './AuthGate'

const OWNER_EMAIL = 'joseph@spidergrills.com'

/* ─── helpers ─────────────────────────────────────────────────────── */

function parseMacLines(raw: string): Array<{ mac: string; user_id?: string }> {
  // Accept any of:
  //   fc:b4:67:f9:b4:56
  //   fcb467f9b456
  //   fcb467f9b456  joe@example.com
  //   fcb467f9b456, user_id
  // Comment lines starting with # are skipped.
  const out: Array<{ mac: string; user_id?: string }> = []
  for (const line of raw.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const parts = trimmed.split(/[\s,]+/)
    const mac = parts[0]
    if (!mac) continue
    const user = parts.slice(1).join(' ').trim()
    out.push({ mac, user_id: user || undefined })
  }
  return out
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' })
}

function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

function fmtNum(n: number | null | undefined, digits = 1): string {
  if (n == null) return '—'
  return n.toFixed(digits)
}

/* ─── Bulk-register card ──────────────────────────────────────────── */

export function AlphaBulkRegisterCard({ onComplete }: { onComplete: () => void }) {
  const [text, setText] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [dryRun, setDryRun] = useState<AlphaBulkImportResult | null>(null)
  const [applied, setApplied] = useState<AlphaBulkImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const entries = useMemo(() => parseMacLines(text), [text])

  const callImport = async (dry: boolean) => {
    if (entries.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.betaAlphaBulkImport({ entries, dry_run: dry })
      if (dry) {
        setDryRun(result)
      } else {
        setApplied(result)
        setDryRun(null)
        onComplete()
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const renderResult = (r: AlphaBulkImportResult, titleSuffix: string) => (
    <div style={{
      marginTop: 12,
      padding: 12,
      border: '1px solid var(--border)',
      borderRadius: 8,
      background: r.dry_run ? 'rgba(245, 158, 11, 0.06)' : 'rgba(57, 208, 143, 0.06)',
    }}>
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>
        {r.dry_run ? 'Dry-run plan' : 'Import complete'} · {titleSuffix}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8, fontSize: 12 }}>
        <div><strong>{r.successful}</strong> / {r.total_requested} {r.dry_run ? 'would register' : 'registered'}</div>
        <div><strong>{r.already_registered}</strong> already registered</div>
        <div><strong>{r.invalid_macs.length}</strong> invalid MAC{r.invalid_macs.length === 1 ? '' : 's'}</div>
        <div><strong>{r.unknown_firmware.length}</strong> unknown firmware</div>
        <div title="MAC resolved via app-side observations only (no recent stream telemetry — registered under a synthetic device_id; re-keys to the real device_id when the grill comes online)">
          <strong>{r.app_side_only?.length ?? 0}</strong> app-side only
        </div>
      </div>
      {Object.keys(r.by_firmware_version).length > 0 ? (
        <div style={{ marginTop: 10, fontSize: 12 }}>
          <div style={{ color: 'var(--muted)', marginBottom: 4 }}>By firmware version:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {Object.entries(r.by_firmware_version).map(([v, n]) => (
              <span key={v} className="badge badge-neutral">{v}: {n}</span>
            ))}
          </div>
        </div>
      ) : null}
      {r.releases_created.length > 0 ? (
        <div style={{ marginTop: 10, fontSize: 12 }}>
          <span style={{ color: 'var(--muted)' }}>Auto-created release rows: </span>
          {r.releases_created.map(v => <span key={v} className="badge badge-good" style={{ marginRight: 4 }}>{v}</span>)}
        </div>
      ) : null}
      {r.invalid_macs.length > 0 ? (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--red)' }}>
          Invalid MACs: {r.invalid_macs.join(', ')}
        </div>
      ) : null}
      {r.unknown_firmware.length > 0 ? (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--orange)' }}>
          <strong>Unknown firmware</strong> — no stream events AND no app-side observations for these MACs.
          Likely offline or never reported. Supply a <code>firmware_version_override</code> per MAC to force, or wait until they come online.
          <div style={{ marginTop: 4, fontFamily: 'ui-monospace, SFMono-Regular, monospace', color: 'var(--muted)' }}>
            {r.unknown_firmware.slice(0, 20).join(', ')}
            {r.unknown_firmware.length > 20 ? ` · +${r.unknown_firmware.length - 20} more` : ''}
          </div>
        </div>
      ) : null}
      {r.app_side_only && r.app_side_only.length > 0 ? (
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--blue)' }}>
          <strong>Registered via app-side fallback</strong> ({r.app_side_only.length} device{r.app_side_only.length === 1 ? '' : 's'}) —
          no recent stream events, but firmware version found in app-side device observations
          (Freshdesk + app sync). Registered under a synthetic <code>mac:xxxx</code> device_id so
          the member is tracked; it auto-re-keys to the real device_id when the grill next reports.
        </div>
      ) : null}
      {r.dry_run && r.successful > 0 ? (
        <div style={{ marginTop: 10 }}>
          <button
            className="range-button active"
            onClick={() => void callImport(false)}
            disabled={busy}
          >
            Confirm import → write {r.successful} cohort row{r.successful === 1 ? '' : 's'}
          </button>
        </div>
      ) : null}
    </div>
  )

  return (
    <section className="card" style={{ borderLeft: '3px solid var(--orange)' }}>
      <div className="card-title">Register alpha testers · bulk MAC import</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10, lineHeight: 1.5 }}>
        Paste the list of alpha tester MAC addresses (one per line, any format).
        Optional: append a user identifier after the MAC, separated by a space or comma.
        Lines starting with <code>#</code> are skipped.
        <br />
        The system auto-detects each device's current firmware from telemetry
        and registers it under that version's release. Releases for
        <strong> 01.01.90 → 01.01.99</strong> (or any version we haven't yet recorded)
        are auto-created as historical (status=ga, no binary, no deploy capability).
        <strong> No new firmware is pushed.</strong>
      </div>
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={[
          '# One MAC per line. Examples:',
          'fc:b4:67:f9:b4:56',
          'fc-b4-67-f9-b4-57  tester@example.com',
          'fcb467f9b458, another-user',
        ].join('\n')}
        rows={10}
        style={{
          width: '100%',
          fontFamily: 'ui-monospace, SFMono-Regular, monospace',
          fontSize: 12,
          padding: 10,
          background: 'var(--panel-2)',
          color: 'var(--text)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          resize: 'vertical',
        }}
      />
      <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <button
          className="range-button"
          onClick={() => void callImport(true)}
          disabled={busy || entries.length === 0}
        >
          {busy && !applied ? 'Evaluating…' : `Dry-run preview (${entries.length})`}
        </button>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>
          Always preview first — dry-run shows which MACs would resolve, which have unknown firmware, and how many cohort rows would be created.
        </span>
      </div>
      {error ? <div style={{ marginTop: 8, fontSize: 12, color: 'var(--red)' }}>{error}</div> : null}
      {dryRun ? renderResult(dryRun, `${entries.length} MAC${entries.length === 1 ? '' : 's'} submitted`) : null}
      {applied ? renderResult(applied, `${entries.length} MAC${entries.length === 1 ? '' : 's'} submitted`) : null}
    </section>
  )
}

/* ─── Per-device firmware timeline ────────────────────────────────── */

export function AlphaFirmwareTimelineCard({ mac, onClose }: { mac: string; onClose: () => void }) {
  const [data, setData] = useState<AlphaFirmwareTimeline | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.betaAlphaFirmwareTimeline(mac, ctl.signal)
      .then(r => setData(r))
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctl.abort()
  }, [mac])

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 100, padding: 20,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          maxWidth: 720, width: '100%',
          background: 'var(--panel)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: 20,
          color: 'var(--text)',
          maxHeight: '85vh', overflowY: 'auto',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1 }}>
              Alpha tester · firmware journey
            </div>
            <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace', fontSize: 15, fontWeight: 600 }}>
              {mac}
            </div>
          </div>
          <button className="range-button" onClick={onClose}>Close</button>
        </div>
        {error ? <div style={{ color: 'var(--red)', fontSize: 13 }}>{error}</div> : null}
        {!data && !error ? <div className="state-message">Loading firmware history…</div> : null}
        {data && data.versions.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            No firmware-version history found — the device has not reported recent stream events.
            Historical sessions on the TelemetrySession table may still exist below.
          </div>
        ) : null}
        {data && data.versions.length > 0 ? (
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px' }}>Firmware</th>
                <th>First seen</th>
                <th>Last seen</th>
                <th>Active days</th>
                <th>Sessions</th>
              </tr>
            </thead>
            <tbody>
              {data.versions.map(v => (
                <tr key={v.firmware_version} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px', fontWeight: 600 }}>{v.firmware_version}</td>
                  <td>{fmtDate(v.stream_first_seen)}</td>
                  <td>{fmtDate(v.stream_last_seen)}</td>
                  <td>{fmtInt(v.stream_active_days)}</td>
                  <td>{fmtInt(v.session_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </div>
  )
}

/* ─── Version-over-version trend chart ───────────────────────────── */

type MetricKey =
  | 'cook_success_rate'
  | 'avg_in_control_pct'
  | 'avg_stability_score'
  | 'avg_disconnects_per_session'
  | 'avg_max_overshoot_f'
  | 'avg_time_to_stabilize_seconds'
  | 'avg_error_events_per_session'

type MetricDef = {
  key: MetricKey
  label: string
  unit: string
  higherIsBetter: boolean
  transform?: (v: number) => number
  formatter: (v: number) => string
}

const METRIC_DEFS: MetricDef[] = [
  {
    key: 'cook_success_rate',
    label: 'Cook success',
    unit: '%',
    higherIsBetter: true,
    transform: v => v * 100,
    formatter: v => `${v.toFixed(1)}%`,
  },
  {
    key: 'avg_in_control_pct',
    label: 'In-control %',
    unit: '%',
    higherIsBetter: true,
    transform: v => v * 100,
    formatter: v => `${v.toFixed(1)}%`,
  },
  {
    key: 'avg_stability_score',
    label: 'Stability',
    unit: '%',
    higherIsBetter: true,
    transform: v => v * 100,
    formatter: v => `${v.toFixed(1)}%`,
  },
  {
    key: 'avg_disconnects_per_session',
    label: 'Disconnects / cook',
    unit: '',
    higherIsBetter: false,
    formatter: v => v.toFixed(2),
  },
  {
    key: 'avg_max_overshoot_f',
    label: 'Max overshoot',
    unit: '°F',
    higherIsBetter: false,
    formatter: v => `${v.toFixed(1)}°F`,
  },
  {
    key: 'avg_time_to_stabilize_seconds',
    label: 'Time to stabilize',
    unit: 'min',
    higherIsBetter: false,
    transform: v => v / 60,
    formatter: v => `${v.toFixed(1)}m`,
  },
  {
    key: 'avg_error_events_per_session',
    label: 'Errors / cook',
    unit: '',
    higherIsBetter: false,
    formatter: v => v.toFixed(2),
  },
]

export function AlphaTrendChart() {
  const [data, setData] = useState<AlphaCohortTrend | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [metric, setMetric] = useState<MetricKey>('cook_success_rate')

  useEffect(() => {
    const ctl = new AbortController()
    api.betaAlphaTrend(ctl.signal)
      .then(r => { setData(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctl.abort()
  }, [])

  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Trend error: {error}</div></section>
  if (!data) return <section className="card"><div className="state-message">Loading alpha trend…</div></section>

  const def = METRIC_DEFS.find(d => d.key === metric)!
  const transform = def.transform ?? ((v: number) => v)

  const chartData = data.points.map(p => {
    const raw = p[metric]
    return {
      firmware: p.firmware_version,
      value: raw != null ? transform(raw) : null,
      sessions: p.sessions,
      devices: p.devices,
      small_sample: p.small_sample,
    }
  })

  const baselineRaw = data.production_baseline[metric]
  const baseline = baselineRaw != null ? transform(baselineRaw) : null

  const alphaAvgOfLastThree = (() => {
    const last = data.points.slice(-3).map(p => p[metric]).filter((v): v is number => v != null)
    if (!last.length) return null
    return transform(last.reduce((a, b) => a + b, 0) / last.length)
  })()

  const deltaVsBaseline = (baseline != null && alphaAvgOfLastThree != null)
    ? alphaAvgOfLastThree - baseline
    : null

  const deltaGood = deltaVsBaseline != null
    ? (def.higherIsBetter ? deltaVsBaseline > 0 : deltaVsBaseline < 0)
    : null

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Alpha firmware journey · {def.label}</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            {data.window_days}-day window · {data.alpha_device_id_count} alpha devices · production baseline = {data.production_baseline.versions.join(' + ')}
          </div>
        </div>
        <div>
          <select
            value={metric}
            onChange={e => setMetric(e.target.value as MetricKey)}
            className="deci-input"
            style={{ fontSize: 12 }}
          >
            {METRIC_DEFS.map(m => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </div>
      </div>

      {deltaVsBaseline != null ? (
        <div style={{
          fontSize: 12,
          marginBottom: 8,
          padding: '6px 10px',
          borderRadius: 6,
          background: deltaGood ? 'rgba(57, 208, 143, 0.08)' : 'rgba(255, 109, 122, 0.08)',
          borderLeft: `3px solid ${deltaGood ? 'var(--green)' : 'var(--red)'}`,
        }}>
          <strong>Last-3-version avg vs production baseline:</strong>{' '}
          <span style={{ color: deltaGood ? 'var(--green)' : 'var(--red)' }}>
            {deltaVsBaseline >= 0 ? '+' : ''}{deltaVsBaseline.toFixed(2)} {def.unit}
            {' '}({deltaGood ? 'better' : 'worse'} than prod)
          </span>
        </div>
      ) : null}

      <div style={{ height: 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 30 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
            <XAxis
              dataKey="firmware"
              tick={{ fontSize: 11 }}
              stroke="var(--muted)"
              angle={-25}
              textAnchor="end"
              height={50}
            />
            <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" />
            <Tooltip
              contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }}
              formatter={(v: number | null) => v == null ? '—' : def.formatter(v)}
              labelFormatter={(l: string) => {
                const pt = chartData.find(p => p.firmware === l)
                return `${l}${pt ? ` · n=${pt.sessions} sess, ${pt.devices} dev${pt.small_sample ? ' (small)' : ''}` : ''}`
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="value"
              name={`alpha ${def.label}`}
              stroke="var(--orange)"
              strokeWidth={2}
              dot={(props: { cx: number; cy: number; payload: { small_sample: boolean } }) => {
                const { cx, cy, payload } = props
                return (
                  <circle
                    cx={cx} cy={cy} r={payload.small_sample ? 3 : 5}
                    fill={payload.small_sample ? 'transparent' : 'var(--orange)'}
                    stroke="var(--orange)" strokeWidth={2}
                  />
                )
              }}
              connectNulls
            />
            {baseline != null ? (
              <ReferenceLine
                y={baseline}
                stroke="var(--blue)"
                strokeDasharray="6 3"
                label={{
                  value: `prod baseline ${def.formatter(baseline)}`,
                  fill: 'var(--blue)',
                  fontSize: 11,
                  position: 'right',
                }}
              />
            ) : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
        Open dot = small sample (&lt;10 devices or &lt;20 sessions) — directional only.
      </div>
    </section>
  )
}

/* ─── Per-version error-pattern card ──────────────────────────────── */

export function AlphaErrorPatternsCard() {
  const [data, setData] = useState<AlphaCohortErrorPatterns | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.betaAlphaErrorPatterns(ctl.signal)
      .then(r => { setData(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctl.abort()
  }, [])

  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Error patterns failed: {error}</div></section>
  if (!data) return <section className="card"><div className="state-message">Loading error patterns…</div></section>

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Top error codes per alpha version</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Last {data.window_days} days · alpha devices only · incidence % = sessions touched by the code / total sessions on that version
          </div>
        </div>
      </div>
      {data.versions.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>
          No alpha-cohort sessions yet in window. Run some cooks, then come back.
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: 12,
        }}>
          {data.versions.map(v => (
            <div key={v.firmware_version} style={{
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: 10,
              background: 'rgba(255,255,255,0.015)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <strong style={{ fontSize: 13 }}>{v.firmware_version}</strong>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {v.sessions} session{v.sessions === 1 ? '' : 's'}
                </span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, marginBottom: 8 }}>
                {v.error_free_sessions_pct != null
                  ? `${(v.error_free_sessions_pct * 100).toFixed(0)}% error-free cooks`
                  : 'no sessions'}
              </div>
              {v.top_error_codes.length === 0 ? (
                <div style={{ fontSize: 11, color: 'var(--green)' }}>No errors recorded — clean.</div>
              ) : (
                <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 11 }}>
                  {v.top_error_codes.map(c => (
                    <li key={c.code} style={{
                      display: 'flex', justifyContent: 'space-between',
                      padding: '3px 0', borderTop: '1px solid rgba(255,255,255,0.04)',
                    }}>
                      <code style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{c.code}</code>
                      <span style={{ color: 'var(--muted)' }}>
                        {c.occurrences}× · {c.incidence_pct != null ? `${(c.incidence_pct * 100).toFixed(1)}%` : '—'}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/* ─── Opus 4.7 narrative insight card ─────────────────────────────── */

const SEVERITY_COLOR: Record<string, string> = {
  improving: 'var(--green)',
  regressing: 'var(--red)',
  investigate: 'var(--orange)',
  info: 'var(--blue)',
}

const SEVERITY_ICON: Record<string, string> = {
  improving: '▲',
  regressing: '▼',
  investigate: '⚠',
  info: '•',
}

export function AlphaInsightCard() {
  const { user } = useAuth()
  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL
  const [data, setData] = useState<AlphaCohortInsight | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    api.betaAlphaInsight(ctl.signal)
      .then(r => setData(r))
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctl.abort()
  }, [])

  const regenerate = async () => {
    if (!confirm('Run Opus 4.7 on the alpha cohort data? This is a ~30-60 second call.')) return
    setBusy(true)
    setError(null)
    try {
      const fresh = await api.betaAlphaInsightRegenerate()
      setData(fresh)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const hasContent = data && (data.overall_theme || (data.observations?.length ?? 0) > 0)

  return (
    <section className="card" style={{ borderLeft: '3px solid #8b5cf6' }}>
      <div className="venom-panel-head">
        <div>
          <strong>Opus 4.7 · alpha program narrative</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            {data?.generated_at
              ? `Generated ${new Date(data.generated_at).toLocaleString()}${data.duration_ms ? ` · ${Math.round(data.duration_ms / 1000)}s` : ''}`
              : 'Not generated yet — click "Run Opus analysis" to write the narrative.'}
          </div>
        </div>
        {isOwner ? (
          <button
            className="range-button active"
            onClick={regenerate}
            disabled={busy}
          >
            {busy ? 'Opus is thinking…' : (hasContent ? 'Regenerate' : 'Run Opus analysis')}
          </button>
        ) : null}
      </div>
      {error ? <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 8 }}>{error}</div> : null}
      {hasContent ? (
        <>
          {data.overall_theme ? (
            <div style={{
              fontSize: 14,
              fontWeight: 500,
              padding: '10px 12px',
              background: 'rgba(139, 92, 246, 0.08)',
              borderRadius: 6,
              marginBottom: 12,
              lineHeight: 1.4,
            }}>
              {data.overall_theme}
            </div>
          ) : null}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {data.observations.map((o, i) => {
              const color = SEVERITY_COLOR[o.severity] || 'var(--muted)'
              const icon = SEVERITY_ICON[o.severity] || '•'
              return (
                <div
                  key={i}
                  style={{
                    borderLeft: `3px solid ${color}`,
                    padding: '8px 12px',
                    background: 'rgba(255,255,255,0.02)',
                    borderRadius: 4,
                  }}
                >
                  <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', marginBottom: 4 }}>
                    <span style={{ color, fontWeight: 700, fontSize: 14 }}>{icon}</span>
                    <strong style={{ fontSize: 13 }}>{o.title}</strong>
                    <span style={{
                      fontSize: 10, color, fontWeight: 600,
                      textTransform: 'uppercase', letterSpacing: 0.4,
                    }}>
                      {o.severity}
                    </span>
                    {o.firmware_versions_cited.length > 0 ? (
                      <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 'auto' }}>
                        cites: {o.firmware_versions_cited.join(', ')}
                      </span>
                    ) : null}
                  </div>
                  <p style={{ fontSize: 12, margin: '2px 0 6px', lineHeight: 1.5 }}>{o.detail}</p>
                  <div style={{
                    fontSize: 12, padding: '6px 10px',
                    background: 'rgba(110, 168, 255, 0.06)',
                    borderRadius: 4,
                    borderLeft: '2px solid var(--blue)',
                  }}>
                    <strong>→ Next action:</strong> {o.recommendation}
                  </div>
                </div>
              )
            })}
          </div>
        </>
      ) : (
        <div style={{ fontSize: 13, color: 'var(--muted)', padding: '8px 0' }}>
          {busy
            ? 'Opus is analyzing the alpha program — ~30-60 seconds…'
            : (isOwner
              ? 'Click "Run Opus analysis" above to generate 3-5 actionable observations from the trend + error-pattern data.'
              : 'No narrative generated yet.')}
        </div>
      )}
    </section>
  )
}

/* ─── Cohort-vs-fleet analytics card ──────────────────────────────── */

export function AlphaVsFleetAnalyticsCard() {
  const [data, setData] = useState<AlphaCohortAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    const ctl = new AbortController()
    api.betaAlphaAnalytics(ctl.signal)
      .then(r => { setData(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return ctl
  }

  useEffect(() => {
    const ctl = load()
    return () => ctl.abort()
  }, [])

  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Analytics error: {error}</div></section>
  if (!data) return <section className="card"><div className="state-message">Loading cohort analytics…</div></section>

  // Group segments by firmware version, then by cohort
  const byVersion: Record<string, { alpha?: typeof data.segments[number]; production?: typeof data.segments[number] }> = {}
  for (const s of data.segments) {
    byVersion[s.firmware_version] = byVersion[s.firmware_version] || {}
    byVersion[s.firmware_version][s.cohort] = s
  }
  const versionRows = Object.entries(byVersion)
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))

  return (
    <section className="card">
      <div className="card-title">Alpha cohort vs production fleet — {data.window_days}-day window</div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
        Per-firmware comparison across cook success, disconnects, overshoot, stability, and time-to-stabilize.
        Alpha row = sessions from devices registered in the alpha cohort.
        Production row = sessions from the rest of the fleet on the same firmware.
      </div>
      {versionRows.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>
          No sessions in the window. Once alpha testers are registered and their devices have cooked,
          this table populates automatically.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 900 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px' }}>Firmware</th>
                <th>Cohort</th>
                <th>Devices</th>
                <th>Sessions</th>
                <th>Cook success</th>
                <th>Disconnects/cook</th>
                <th>Max overshoot (°F)</th>
                <th>In-control %</th>
                <th>Stability</th>
                <th>Time-to-stabilize</th>
              </tr>
            </thead>
            <tbody>
              {versionRows.map(([version, pair]) => (
                <>
                  {pair.alpha ? (
                    <tr key={`${version}-alpha`} style={{ borderTop: '1px solid var(--border)', background: 'rgba(245, 158, 11, 0.06)' }}>
                      <td style={{ padding: '6px 8px', fontWeight: 600 }}>{version}</td>
                      <td><span className="badge badge-warn">alpha</span></td>
                      <td>{fmtInt(pair.alpha.devices)}</td>
                      <td>{fmtInt(pair.alpha.sessions)}</td>
                      <td>{fmtPct(pair.alpha.cook_success_rate, 0)}</td>
                      <td>{fmtNum(pair.alpha.avg_disconnects_per_session, 2)}</td>
                      <td>{fmtNum(pair.alpha.avg_max_overshoot_f)}</td>
                      <td>{fmtPct(pair.alpha.avg_in_control_pct, 0)}</td>
                      <td>{fmtPct(pair.alpha.avg_stability_score, 0)}</td>
                      <td>
                        {pair.alpha.avg_time_to_stabilize_seconds != null
                          ? `${Math.round(pair.alpha.avg_time_to_stabilize_seconds / 60)}m`
                          : '—'}
                      </td>
                    </tr>
                  ) : null}
                  {pair.production ? (
                    <tr key={`${version}-prod`} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px' }}>
                        {pair.alpha ? '' : version}
                      </td>
                      <td><span className="badge badge-neutral">prod</span></td>
                      <td>{fmtInt(pair.production.devices)}</td>
                      <td>{fmtInt(pair.production.sessions)}</td>
                      <td>{fmtPct(pair.production.cook_success_rate, 0)}</td>
                      <td>{fmtNum(pair.production.avg_disconnects_per_session, 2)}</td>
                      <td>{fmtNum(pair.production.avg_max_overshoot_f)}</td>
                      <td>{fmtPct(pair.production.avg_in_control_pct, 0)}</td>
                      <td>{fmtPct(pair.production.avg_stability_score, 0)}</td>
                      <td>
                        {pair.production.avg_time_to_stabilize_seconds != null
                          ? `${Math.round(pair.production.avg_time_to_stabilize_seconds / 60)}m`
                          : '—'}
                      </td>
                    </tr>
                  ) : null}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
