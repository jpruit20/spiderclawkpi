import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { KpiTargetRow, KpiTargetUpsertPayload } from '../lib/api'
import { METRIC_DIRECTION_DEFAULT, METRIC_LABELS } from './TrendSnapshotCard'

/**
 * Modal for setting/editing seasonal KPI targets.
 *
 * Each metric can have multiple targets with non-overlapping date
 * windows (Spring 2026 grilling season vs Fall 2026 off-season).
 * The narrowest window containing today wins; the snapshot tile
 * reads that target.
 *
 * Open dates (no start / no end) = always-active catch-all that
 * specific seasonal rows override.
 */

interface Props {
  metrics: string[]
  onClose: () => void
  /** Division scope for this panel. null = global (Command Center; only Joseph can edit). */
  division?: string | null
}

const SEASON_PRESETS = [
  { label: 'Spring grilling (Apr 1 – Jun 30)', start: '-04-01', end: '-07-01' },
  { label: 'Summer peak (Jul 1 – Sep 30)', start: '-07-01', end: '-10-01' },
  { label: 'Fall transition (Oct 1 – Nov 30)', start: '-10-01', end: '-12-01' },
  { label: 'Winter off-season (Dec 1 – Mar 31)', start: '-12-01', end: '-04-01' },
]

export function KpiTargetsPanel({ metrics, onClose, division = null }: Props) {
  const [rows, setRows] = useState<KpiTargetRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Partial<KpiTargetRow & { metric_key: string }> | null>(null)
  const [saving, setSaving] = useState(false)
  const [permissions, setPermissions] = useState<{
    user_email: string | null
    is_platform_owner: boolean
    editable_divisions: Array<{ code: string | null; label: string }>
  } | null>(null)

  // What can the calling user edit?
  const canEditThisDivision = useMemo(() => {
    if (!permissions) return false
    if (permissions.is_platform_owner) return true
    return permissions.editable_divisions.some(d => d.code === division)
  }, [permissions, division])

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const [tgts, perms] = await Promise.all([
        api.kpiTargetsList({ division: division ?? undefined, include_global: true }),
        api.kpiTargetsPermissions().catch(() => null),
      ])
      setRows(tgts.targets)
      if (perms) setPermissions(perms)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [division])

  const groupedByMetric = useMemo(() => {
    const map: Record<string, KpiTargetRow[]> = {}
    for (const m of metrics) map[m] = []
    for (const r of rows) (map[r.metric_key] = map[r.metric_key] || []).push(r)
    return map
  }, [rows, metrics])

  async function save() {
    if (!editing || !editing.metric_key || editing.target_value == null) return
    setSaving(true)
    setError(null)
    try {
      const payload: KpiTargetUpsertPayload = {
        id: editing.id ?? null,
        metric_key: editing.metric_key,
        target_value: Number(editing.target_value),
        direction: (editing.direction as 'min' | 'max') ?? (METRIC_DIRECTION_DEFAULT[editing.metric_key] || 'min'),
        effective_start: editing.effective_start || null,
        effective_end: editing.effective_end || null,
        season_label: editing.season_label || null,
        notes: editing.notes || null,
        division: editing.division ?? division,
      }
      await api.kpiTargetUpsert(payload)
      setEditing(null)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save (check auth)')
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: number) {
    if (!confirm('Delete this target?')) return
    try {
      await api.kpiTargetDelete(id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete')
    }
  }

  function startCreate(metric: string) {
    setEditing({
      metric_key: metric,
      target_value: 0 as any,
      direction: METRIC_DIRECTION_DEFAULT[metric] || 'min',
      effective_start: null,
      effective_end: null,
      season_label: null,
      notes: null,
    })
  }

  function startEdit(row: KpiTargetRow) {
    setEditing({ ...row })
  }

  function applySeasonPreset(label: string, start: string, end: string) {
    if (!editing) return
    const today = new Date()
    const year = today.getFullYear()
    const startDate = `${year}${start}`
    // If end month wraps the year (e.g. winter Dec→Mar), end goes to next year
    const endYear = (start === '-12-01') ? year + 1 : year
    const endDate = `${endYear}${end}`
    setEditing({ ...editing, effective_start: startDate, effective_end: endDate, season_label: label })
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        zIndex: 100, display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        padding: 30, overflowY: 'auto',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={{
          background: 'var(--panel)',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: 8,
          padding: 20,
          width: '100%',
          maxWidth: 760,
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16 }}>
              KPI targets
              <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--muted)', marginLeft: 8 }}>
                {division === null ? '· Global (Command Center)' : `· ${division.toUpperCase()}`}
              </span>
            </h3>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4, lineHeight: 1.5 }}>
              Set per-metric targets. Use date windows for seasonal swings (e.g. raise Revenue target Apr–Sep,
              lower it Oct–Mar). Narrowest matching window wins.
              {permissions && (
                <span style={{ display: 'block', marginTop: 4, color: canEditThisDivision ? 'var(--green)' : 'var(--orange)' }}>
                  {canEditThisDivision
                    ? `✓ You (${permissions.user_email}) can edit ${division === null ? 'global' : division} targets.`
                    : `🔒 Read-only — ${permissions.user_email || 'unknown'} cannot edit ${division === null ? 'global' : division} targets. ${
                        division === null
                          ? 'Global targets are platform-owner-only.'
                          : 'Each division lead controls their own division.'
                      }`}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--muted)', fontSize: 18, cursor: 'pointer' }}
          >
            ✕
          </button>
        </div>

        {error && <div style={{ background: 'rgba(231,76,60,0.1)', color: 'var(--red)', padding: 8, borderRadius: 4, fontSize: 12, marginBottom: 10 }}>{error}</div>}
        {loading && <div style={{ fontSize: 12, color: 'var(--muted)' }}>Loading targets…</div>}

        {!loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {metrics.map(m => (
              <div key={m} style={{ background: 'var(--panel-2)', borderRadius: 6, padding: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <strong style={{ fontSize: 13 }}>{METRIC_LABELS[m] || m}</strong>
                  {canEditThisDivision && (
                    <button
                      onClick={() => startCreate(m)}
                      style={{ background: 'var(--blue)', border: 'none', color: '#fff', padding: '3px 8px', borderRadius: 3, fontSize: 11, fontWeight: 600, cursor: 'pointer' }}
                    >
                      + Add target
                    </button>
                  )}
                </div>
                {groupedByMetric[m]?.length ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11 }}>
                    {groupedByMetric[m].map(r => (
                      <div key={r.id} style={{ display: 'grid', gridTemplateColumns: '110px 1fr auto auto', gap: 8, alignItems: 'center', padding: '4px 6px', background: 'var(--panel)', borderRadius: 3 }}>
                        <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                          {r.direction === 'max' ? '≤' : '≥'} {r.target_value.toLocaleString('en-US')}
                        </span>
                        <span style={{ color: 'var(--muted)' }}>
                          {r.effective_start || r.effective_end
                            ? `${r.effective_start || '∞'} → ${r.effective_end || '∞'}`
                            : 'Always active'}
                          {r.season_label && <> · {r.season_label}</>}
                          <span style={{ marginLeft: 6, fontSize: 9, padding: '0 5px', borderRadius: 3, background: r.division ? 'var(--panel-2)' : 'rgba(110,168,255,0.12)', color: r.division ? 'var(--muted)' : 'var(--blue)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>
                            {r.division ?? 'global'}
                          </span>
                          {r.owner_email && (
                            <span style={{ marginLeft: 4, fontSize: 9, color: 'var(--muted)' }}>
                              · {r.owner_email.split('@')[0]}
                            </span>
                          )}
                        </span>
                        {(permissions?.is_platform_owner || (canEditThisDivision && r.division === division)) ? (
                          <>
                            <button onClick={() => startEdit(r)} style={{ background: 'none', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', padding: '1px 6px', borderRadius: 3, fontSize: 10, cursor: 'pointer' }}>edit</button>
                            <button onClick={() => remove(r.id)} style={{ background: 'none', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--red)', padding: '1px 6px', borderRadius: 3, fontSize: 10, cursor: 'pointer' }}>×</button>
                          </>
                        ) : (
                          <>
                            <span style={{ fontSize: 10, color: 'var(--muted)', gridColumn: '3 / 5', textAlign: 'right' }}>read-only</span>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: 11, color: 'var(--muted)', fontStyle: 'italic' }}>No targets set yet.</div>
                )}
              </div>
            ))}
          </div>
        )}

        {editing && (
          <div style={{ marginTop: 14, padding: 14, background: 'var(--panel-2)', borderRadius: 6, border: '1px solid var(--blue)' }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              {editing.id ? 'Edit target' : 'New target'} — {METRIC_LABELS[editing.metric_key!] || editing.metric_key}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 11 }}>
              <label>
                <span style={{ color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Target value</span>
                <input
                  type="number"
                  step="any"
                  value={editing.target_value as any ?? ''}
                  onChange={e => setEditing({ ...editing, target_value: Number(e.target.value) as any })}
                  style={{ width: '100%', padding: 5, background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: 3 }}
                />
              </label>
              <label>
                <span style={{ color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Direction</span>
                <select
                  value={editing.direction as string}
                  onChange={e => setEditing({ ...editing, direction: e.target.value as 'min' | 'max' })}
                  style={{ width: '100%', padding: 5, background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: 3 }}
                >
                  <option value="min">≥ floor (at-or-above is good — revenue, orders, etc.)</option>
                  <option value="max">≤ cap (at-or-below is good — tickets, errors, FRT)</option>
                </select>
              </label>
              <label>
                <span style={{ color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Effective start (optional)</span>
                <input
                  type="date"
                  value={editing.effective_start || ''}
                  onChange={e => setEditing({ ...editing, effective_start: e.target.value || null })}
                  style={{ width: '100%', padding: 5, background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: 3 }}
                />
              </label>
              <label>
                <span style={{ color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Effective end (optional)</span>
                <input
                  type="date"
                  value={editing.effective_end || ''}
                  onChange={e => setEditing({ ...editing, effective_end: e.target.value || null })}
                  style={{ width: '100%', padding: 5, background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: 3 }}
                />
              </label>
              <label style={{ gridColumn: '1 / -1' }}>
                <span style={{ color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Season label (optional)</span>
                <input
                  type="text"
                  placeholder="e.g. Spring 2026, Off-season Q4"
                  value={editing.season_label || ''}
                  onChange={e => setEditing({ ...editing, season_label: e.target.value || null })}
                  style={{ width: '100%', padding: 5, background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: 3 }}
                />
              </label>
              <label style={{ gridColumn: '1 / -1' }}>
                <span style={{ color: 'var(--muted)', display: 'block', marginBottom: 2 }}>Notes (optional)</span>
                <textarea
                  rows={2}
                  value={editing.notes || ''}
                  onChange={e => setEditing({ ...editing, notes: e.target.value || null })}
                  style={{ width: '100%', padding: 5, background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: 3, resize: 'vertical' }}
                />
              </label>
            </div>
            <div style={{ marginTop: 8 }}>
              <span style={{ fontSize: 10, color: 'var(--muted)', marginRight: 6 }}>quick season presets:</span>
              {SEASON_PRESETS.map(s => (
                <button
                  key={s.label}
                  onClick={() => applySeasonPreset(s.label, s.start, s.end)}
                  style={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', padding: '2px 6px', borderRadius: 3, fontSize: 10, cursor: 'pointer', marginRight: 4 }}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <div style={{ marginTop: 12, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setEditing(null)}
                disabled={saving}
                style={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--muted)', padding: '5px 12px', borderRadius: 3, fontSize: 11, cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving || !editing.target_value || !canEditThisDivision}
                style={{ background: canEditThisDivision ? 'var(--blue)' : 'var(--muted)', border: 'none', color: '#fff', padding: '5px 14px', borderRadius: 3, fontSize: 11, fontWeight: 600, cursor: canEditThisDivision ? 'pointer' : 'not-allowed' }}
              >
                {saving ? 'Saving…' : (editing.id ? 'Update' : 'Create')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
