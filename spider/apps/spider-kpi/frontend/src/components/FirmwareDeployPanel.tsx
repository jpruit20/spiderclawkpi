/**
 * Owner-only firmware OTA deploy panel. Two-phase confirm: preview
 * returns a token + preflight verdict; execute consumes it with a typed
 * version-match string. Gamma deploys reject overrides entirely; alpha/
 * beta allow per-device soft-block overrides with a reason.
 *
 * The component is render-safe for non-owners (it renders a 403-style
 * notice) — the routing guard on FirmwareHub still short-circuits, but
 * this is belt-and-suspenders so the UI can never show deploy controls
 * to a session that backend wouldn't authorize anyway.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from './AuthGate'
import {
  api,
  type BetaReleaseSummary,
  type FirmwareDeployLogRow,
  type FirmwareDeployPreviewResponse,
  type FirmwareDeployStatusResponse,
  type FirmwareDeviceCheck,
} from '../lib/api'

const OWNER_EMAIL = 'joseph@spidergrills.com'
type Cohort = 'alpha' | 'beta' | 'gamma'

function isOwner(email: string | null | undefined): boolean {
  return (email ?? '').toLowerCase() === OWNER_EMAIL
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#6b7280',
  in_flight: '#f59e0b',
  succeeded: '#22c55e',
  failed: '#ef4444',
  rolled_back: '#ef4444',
  aborted: '#4b5563',
}

export function FirmwareDeployPanel() {
  const { user } = useAuth()
  if (!isOwner(user?.email)) {
    return (
      <section className="card">
        <div className="card-title">Deploy</div>
        <div className="state-message" style={{ color: 'var(--red)' }}>
          Owner-only surface. Ask Joseph if you need access.
        </div>
      </section>
    )
  }
  return <DeployPanelInner />
}

function DeployPanelInner() {
  const [releases, setReleases] = useState<BetaReleaseSummary[]>([])
  const [selectedReleaseId, setSelectedReleaseId] = useState<number | null>(null)
  const [cohort, setCohort] = useState<Cohort>('alpha')
  const [macsRaw, setMacsRaw] = useState('')
  const [deviceIdsRaw, setDeviceIdsRaw] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [approvalBusy, setApprovalBusy] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<FirmwareDeployPreviewResponse | null>(null)
  const [executeBusy, setExecuteBusy] = useState(false)
  const [executeResult, setExecuteResult] = useState<{ aws_job_id: string; deployed: string[] } | null>(null)
  const [confirmText, setConfirmText] = useState('')
  const [overrideIds, setOverrideIds] = useState<Set<string>>(new Set())
  const [overrideReason, setOverrideReason] = useState('')

  const selected = useMemo(
    () => releases.find(r => r.id === selectedReleaseId) ?? null,
    [releases, selectedReleaseId],
  )

  const refreshReleases = useCallback(async () => {
    const r = await api.betaReleases()
    setReleases(r.releases)
    setSelectedReleaseId(prev => prev ?? (r.releases[0]?.id ?? null))
  }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    refreshReleases()
      .then(() => { if (alive) setError(null) })
      .catch(e => { if (alive) setError(String(e.message || e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [refreshReleases])

  const onToggleApproval = async (c: Cohort, approve: boolean) => {
    if (!selected) return
    setApprovalBusy(true)
    try {
      await api.firmwareReleaseApprove(selected.id, { cohort: c, approve })
      await refreshReleases()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setApprovalBusy(false)
    }
  }

  const onPreview = async () => {
    if (!selected) return
    setPreviewing(true)
    setError(null)
    setPreview(null)
    setConfirmText('')
    setOverrideIds(new Set())
    setOverrideReason('')
    setExecuteResult(null)
    const macs = macsRaw.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean)
    const device_ids = deviceIdsRaw.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean)
    try {
      const res = await api.firmwareDeployPreview({
        release_id: selected.id,
        cohort,
        macs,
        device_ids,
      })
      setPreview(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setPreviewing(false)
    }
  }

  const onExecute = async () => {
    if (!preview) return
    setExecuteBusy(true)
    setError(null)
    try {
      const res = await api.firmwareDeployExecute({
        preview_token: preview.token,
        confirm_version_typed: confirmText,
        override_device_ids: cohort === 'gamma' ? [] : Array.from(overrideIds),
        override_reason: overrideReason || undefined,
      })
      setExecuteResult({ aws_job_id: res.aws_job_id, deployed: res.deployed_device_ids })
      setPreview(null)
      setConfirmText('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setExecuteBusy(false)
    }
  }

  if (loading) {
    return <section className="card"><div className="state-message">Loading releases…</div></section>
  }

  return (
    <>
      <section className="card">
        <div className="card-title">Deploy firmware OTA</div>
        <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
          Two-phase confirm. Preview runs preflight checks and issues a 10-minute token.
          Deploy requires typing the target version exactly. Gamma is hard-blocked during active cooks; alpha/beta allow per-device override.
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 12 }}>
          <div>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Release</label>
            <select
              className="deci-input"
              value={selectedReleaseId ?? ''}
              onChange={e => setSelectedReleaseId(Number(e.target.value) || null)}
              style={{ width: '100%' }}
            >
              <option value="">—</option>
              {releases.map(r => (
                <option key={r.id} value={r.id}>
                  v{r.version}{r.title ? ` · ${r.title}` : ''} [{r.status}]
                </option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Cohort</label>
            <div style={{ display: 'flex', gap: 4 }}>
              {(['alpha', 'beta', 'gamma'] as Cohort[]).map(c => (
                <button
                  key={c}
                  className={`range-button${cohort === c ? ' active' : ''}`}
                  onClick={() => setCohort(c)}
                  style={{ flex: 1 }}
                >{c}</button>
              ))}
            </div>
          </div>
        </div>

        {selected ? (
          <ReleaseDetails
            release={selected}
            approvalBusy={approvalBusy}
            onToggleApproval={onToggleApproval}
          />
        ) : null}

        <div style={{ marginTop: 16 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
            MACs (one per line or comma-separated). Case/separators don't matter.
          </label>
          <textarea
            className="deci-input"
            value={macsRaw}
            onChange={e => setMacsRaw(e.target.value)}
            rows={4}
            placeholder="fcb467f9b456&#10;fc:b4:67:f9:b4:57"
            style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }}
          />
        </div>

        <div style={{ marginTop: 8 }}>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
            Device IDs (optional — 32-char hex thing names). Merged with MAC resolutions.
          </label>
          <textarea
            className="deci-input"
            value={deviceIdsRaw}
            onChange={e => setDeviceIdsRaw(e.target.value)}
            rows={2}
            style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }}
          />
        </div>

        <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="range-button active"
            onClick={onPreview}
            disabled={previewing || !selected || (!macsRaw.trim() && !deviceIdsRaw.trim())}
          >
            {previewing ? 'Running preflight…' : 'Preview deploy'}
          </button>
        </div>

        {error ? <div style={{ marginTop: 10, color: 'var(--red)', fontSize: 13 }}>{error}</div> : null}

        {executeResult ? (
          <div style={{ marginTop: 16, padding: 12, background: 'rgba(34,197,94,0.12)', borderRadius: 8 }}>
            <div style={{ fontWeight: 600 }}>✓ Deploy queued</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              AWS job id: <code>{executeResult.aws_job_id}</code> — {executeResult.deployed.length} device(s)
            </div>
            <StatusPoller aws_job_id={executeResult.aws_job_id} />
          </div>
        ) : null}
      </section>

      {preview ? (
        <PreviewModal
          preview={preview}
          cohort={cohort}
          confirmText={confirmText}
          setConfirmText={setConfirmText}
          overrideIds={overrideIds}
          setOverrideIds={setOverrideIds}
          overrideReason={overrideReason}
          setOverrideReason={setOverrideReason}
          executeBusy={executeBusy}
          onExecute={onExecute}
          onCancel={() => setPreview(null)}
        />
      ) : null}
    </>
  )
}

function ReleaseDetails({
  release,
  approvalBusy,
  onToggleApproval,
}: {
  release: BetaReleaseSummary
  approvalBusy: boolean
  onToggleApproval: (c: Cohort, approve: boolean) => void
}) {
  const approvals: Array<[Cohort, boolean]> = [
    ['alpha', !!release.approved_for_alpha],
    ['beta', !!release.approved_for_beta],
    ['gamma', !!release.approved_for_gamma],
  ]
  const missingBinary = !release.binary_url || !release.binary_sha256 || !release.binary_size_bytes
  return (
    <div style={{ marginTop: 12, padding: 12, background: 'var(--panel-2)', borderRadius: 8 }}>
      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
        Target model: <strong>{release.target_controller_model ?? '—'}</strong> ·
        size: {release.binary_size_bytes != null ? `${release.binary_size_bytes.toLocaleString()} B` : '—'} ·
        sha256: <code style={{ fontSize: 11 }}>{(release.binary_sha256 ?? '—').slice(0, 16)}{release.binary_sha256 ? '…' : ''}</code>
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, wordBreak: 'break-all' }}>
        url: <code style={{ fontSize: 11 }}>{release.binary_url ?? '—'}</code>
      </div>
      {missingBinary ? (
        <div style={{ marginTop: 6, fontSize: 12, color: 'var(--red)' }}>
          Release is missing binary metadata. Deploy will fail preflight until url + sha256 + size are set on the release row.
        </div>
      ) : null}
      <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {approvals.map(([c, approved]) => (
          <button
            key={c}
            className="range-button"
            disabled={approvalBusy}
            onClick={() => onToggleApproval(c, !approved)}
            style={{
              background: approved ? 'rgba(34,197,94,0.2)' : 'transparent',
              color: approved ? 'var(--green)' : 'var(--fg)',
            }}
          >
            {approved ? '✓' : '○'} {c}
          </button>
        ))}
      </div>
    </div>
  )
}

function PreviewModal({
  preview,
  cohort,
  confirmText,
  setConfirmText,
  overrideIds,
  setOverrideIds,
  overrideReason,
  setOverrideReason,
  executeBusy,
  onExecute,
  onCancel,
}: {
  preview: FirmwareDeployPreviewResponse
  cohort: Cohort
  confirmText: string
  setConfirmText: (s: string) => void
  overrideIds: Set<string>
  setOverrideIds: (s: Set<string>) => void
  overrideReason: string
  setOverrideReason: (s: string) => void
  executeBusy: boolean
  onExecute: () => void
  onCancel: () => void
}) {
  const pf = preview.preflight
  const hardBlocked = pf.devices.filter(d => d.hard_block_reasons.length > 0)
  const softBlocked = pf.devices.filter(d => d.hard_block_reasons.length === 0 && d.soft_block_reasons.length > 0)
  const clean = pf.devices.filter(d => d.hard_block_reasons.length === 0 && d.soft_block_reasons.length === 0)

  const canOverride = cohort !== 'gamma' && softBlocked.length > 0
  const expectedSoft = new Set(softBlocked.map(d => d.device_id))
  const enabledOverrides = Array.from(overrideIds).filter(id => expectedSoft.has(id))

  const deployableCount =
    clean.length + (cohort === 'gamma' ? 0 : enabledOverrides.length)

  const versionMatch = confirmText.trim() === (preview.confirmation_required_text || '').trim()
  const killSwitch = preview.kill_switch_enabled

  const toggle = (id: string) => {
    const next = new Set(overrideIds)
    if (next.has(id)) next.delete(id); else next.add(id)
    setOverrideIds(next)
  }

  return (
    <div
      role="dialog"
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, padding: 16,
      }}
      onClick={onCancel}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12, width: 'min(900px, 100%)', maxHeight: '90vh', overflow: 'auto' }}
      >
        <div style={{ padding: 16, borderBottom: '1px solid var(--border)' }}>
          <div className="card-title">Preflight verdict — v{preview.confirmation_required_text}</div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Token expires {new Date(preview.expires_at).toLocaleString()}. Release-level: {pf.release_ok ? '✓ approved' : '✗ blocked'}
            {pf.release_reasons.length ? ` (${pf.release_reasons.join('; ')})` : ''}.
          </div>
          {!killSwitch ? (
            <div style={{ marginTop: 6, fontSize: 12, color: 'var(--red)' }}>
              ⚠ FIRMWARE_OTA_ENABLED is off. /execute will fail until the kill switch is flipped on the droplet.
            </div>
          ) : null}
        </div>

        <div style={{ padding: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginBottom: 12 }}>
            <Stat label="Clean" value={String(clean.length)} tint="var(--green)" />
            <Stat label="Soft-blocked" value={String(softBlocked.length)} tint="var(--yellow, #f59e0b)" />
            <Stat label="Hard-blocked" value={String(hardBlocked.length)} tint="var(--red)" />
            <Stat label="Will deploy" value={String(deployableCount)} tint="var(--fg)" />
          </div>

          <DeviceTable title="Clean" devices={clean} kind="clean" />
          <DeviceTable
            title="Soft-blocked (override available for alpha/beta)"
            devices={softBlocked}
            kind="soft"
            canOverride={canOverride}
            overrideIds={overrideIds}
            onToggle={toggle}
          />
          <DeviceTable title="Hard-blocked" devices={hardBlocked} kind="hard" />

          {canOverride && enabledOverrides.length > 0 ? (
            <div style={{ marginTop: 12 }}>
              <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
                Override reason (required when overriding soft blocks)
              </label>
              <input
                className="deci-input"
                value={overrideReason}
                onChange={e => setOverrideReason(e.target.value)}
                placeholder="e.g. empty office grill, safe to interrupt"
                style={{ width: '100%' }}
              />
            </div>
          ) : null}

          <div style={{ marginTop: 16, padding: 12, background: 'var(--panel-2)', borderRadius: 8 }}>
            <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>
              Type version <code>{preview.confirmation_required_text}</code> exactly to confirm
            </label>
            <input
              className="deci-input"
              value={confirmText}
              onChange={e => setConfirmText(e.target.value)}
              placeholder={preview.confirmation_required_text}
              style={{ width: '100%', fontFamily: 'monospace' }}
            />
          </div>
        </div>

        <div style={{ padding: 16, borderTop: '1px solid var(--border)', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="range-button" onClick={onCancel} disabled={executeBusy}>Cancel</button>
          <button
            className="range-button active"
            onClick={onExecute}
            disabled={
              executeBusy
              || !versionMatch
              || deployableCount === 0
              || (canOverride && enabledOverrides.length > 0 && !overrideReason.trim())
            }
            style={{ background: 'rgba(239,68,68,0.15)' }}
          >
            {executeBusy ? 'Creating AWS job…' : `Deploy to ${deployableCount} device(s)`}
          </button>
        </div>
      </div>
    </div>
  )
}

function DeviceTable({
  title,
  devices,
  kind,
  canOverride,
  overrideIds,
  onToggle,
}: {
  title: string
  devices: FirmwareDeviceCheck[]
  kind: 'clean' | 'soft' | 'hard'
  canOverride?: boolean
  overrideIds?: Set<string>
  onToggle?: (id: string) => void
}) {
  if (devices.length === 0) return null
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>{title} ({devices.length})</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 640 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
              {kind === 'soft' ? <th style={{ padding: '4px 6px', width: 28 }}></th> : null}
              <th style={{ padding: '4px 6px' }}>Device</th>
              <th>MAC</th>
              <th>Current</th>
              <th>Model</th>
              <th>Cook</th>
              <th>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {devices.map(d => (
              <tr key={d.device_id} style={{ borderTop: '1px solid var(--border)' }}>
                {kind === 'soft' ? (
                  <td>
                    <input
                      type="checkbox"
                      disabled={!canOverride}
                      checked={!!overrideIds?.has(d.device_id)}
                      onChange={() => onToggle?.(d.device_id)}
                    />
                  </td>
                ) : null}
                <td style={{ padding: '4px 6px', fontFamily: 'monospace' }}>{d.device_id.slice(0, 12)}…</td>
                <td style={{ fontFamily: 'monospace' }}>{d.mac ?? '—'}</td>
                <td>{d.current_version ?? '—'}</td>
                <td>{d.controller_model ?? '—'}</td>
                <td style={{ color: d.active_cook ? 'var(--red)' : 'var(--muted)' }}>
                  {d.active_cook ? '● LIVE' : 'idle'}
                </td>
                <td style={{ color: kind === 'hard' ? 'var(--red)' : kind === 'soft' ? '#f59e0b' : 'var(--muted)' }}>
                  {[...d.hard_block_reasons, ...d.soft_block_reasons].join('; ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Stat({ label, value, tint }: { label: string; value: string; tint?: string }) {
  return (
    <div style={{ padding: 8, background: 'var(--panel-2)', borderRadius: 6 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: tint ?? 'var(--fg)' }}>{value}</div>
    </div>
  )
}

function StatusPoller({ aws_job_id }: { aws_job_id: string }) {
  const [state, setState] = useState<FirmwareDeployStatusResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const res = await api.firmwareDeployStatus(aws_job_id)
        if (alive) setState(res)
      } catch (e) {
        if (alive) setErr(e instanceof Error ? e.message : String(e))
      }
    }
    pull()
    const t = window.setInterval(pull, 15_000)
    return () => { alive = false; window.clearInterval(t) }
  }, [aws_job_id])
  if (err) return <div style={{ marginTop: 8, color: 'var(--red)', fontSize: 12 }}>Status poll error: {err}</div>
  if (!state) return <div style={{ marginTop: 8, fontSize: 12, color: 'var(--muted)' }}>Polling AWS…</div>
  return (
    <div style={{ marginTop: 8, fontSize: 12 }}>
      {state.devices.map(d => (
        <div key={d.device_id} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontFamily: 'monospace' }}>{d.device_id.slice(0, 12)}…</span>
          <span style={{ color: STATUS_COLORS[d.dashboard_status] ?? 'var(--muted)' }}>
            ● {d.dashboard_status}
          </span>
          <span style={{ color: 'var(--muted)' }}>
            ({String((d.aws as { status?: string }).status ?? 'UNKNOWN')})
          </span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Deploy log viewer
// ---------------------------------------------------------------------------

export function FirmwareDeployLogView() {
  const { user } = useAuth()
  const [rows, setRows] = useState<FirmwareDeployLogRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [cohortFilter, setCohortFilter] = useState<'' | Cohort>('')

  useEffect(() => {
    if (!isOwner(user?.email)) return
    let alive = true
    const ctl = new AbortController()
    setLoading(true)
    api.firmwareDeployLog({ cohort: cohortFilter || undefined, limit: 100 }, ctl.signal)
      .then(r => { if (alive) { setRows(r.rows); setTotal(r.total); setError(null) } })
      .catch(e => { if (alive && e.name !== 'AbortError') setError(String(e.message || e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false; ctl.abort() }
  }, [user, cohortFilter])

  if (!isOwner(user?.email)) {
    return (
      <section className="card">
        <div className="state-message" style={{ color: 'var(--red)' }}>Owner-only surface.</div>
      </section>
    )
  }

  return (
    <section className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="card-title">Deploy log</div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>{total.toLocaleString()} total rows · showing most recent 100</div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['', 'alpha', 'beta', 'gamma'] as Array<'' | Cohort>).map(c => (
            <button
              key={c || 'all'}
              className={`range-button${cohortFilter === c ? ' active' : ''}`}
              onClick={() => setCohortFilter(c)}
            >{c || 'all'}</button>
          ))}
        </div>
      </div>
      {loading ? <div className="state-message">Loading…</div> : null}
      {error ? <div className="state-message" style={{ color: 'var(--red)' }}>{error}</div> : null}
      {!loading && rows.length === 0 ? <div className="state-message">No deploys yet.</div> : null}
      {rows.length ? (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 900 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                <th style={{ padding: '6px 8px' }}>Created</th>
                <th>Release</th>
                <th>Cohort</th>
                <th>Device</th>
                <th>MAC</th>
                <th>v prior → target</th>
                <th>Status</th>
                <th>Finished</th>
                <th>By</th>
                <th>Job</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px' }}>{fmtDateTime(r.created_at)}</td>
                  <td>#{r.release_id}</td>
                  <td>{r.cohort}</td>
                  <td style={{ fontFamily: 'monospace' }}>{r.device_id.slice(0, 10)}…</td>
                  <td style={{ fontFamily: 'monospace' }}>{r.mac ?? '—'}</td>
                  <td>{r.prior_version ?? '—'} → {r.target_version ?? '—'}</td>
                  <td style={{ color: STATUS_COLORS[r.status] ?? 'var(--muted)' }}>● {r.status}</td>
                  <td>{fmtDateTime(r.finished_at)}</td>
                  <td>{r.initiated_by}</td>
                  <td style={{ fontFamily: 'monospace' }}>{r.aws_job_id ? r.aws_job_id.slice(-16) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  )
}
