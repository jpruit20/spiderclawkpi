import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type {
  AlphaBulkImportResult,
  AlphaCohortAnalytics,
  AlphaFirmwareTimeline,
} from '../lib/api'
import { fmtInt } from '../lib/format'

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
          Unknown firmware (no recent telemetry): {r.unknown_firmware.slice(0, 10).join(', ')}
          {r.unknown_firmware.length > 10 ? ` +${r.unknown_firmware.length - 10} more` : ''}
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
