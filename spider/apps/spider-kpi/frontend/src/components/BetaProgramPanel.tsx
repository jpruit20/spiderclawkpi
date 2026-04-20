import { useEffect, useMemo, useState } from 'react'
import { api, type BetaReleaseSummary } from '../lib/api'

/**
 * Firmware Beta + Gamma Waves program panel.
 *
 * Lives on the Product Engineering page below the firmware cohort
 * analytics. Phase 1 surfaces: issue-tag taxonomy editor, release
 * list + draft editor, candidate-device ranker, invite-cohort action,
 * per-release cohort state.
 *
 * Phase 2 (post Agustin review 2026-04-21) will add: OTA push, Gamma
 * Waves controls, post-deploy AI verdict panel. Everything below
 * assumes the release exists in DB; the dashboard is the source of
 * truth for release profiles.
 */

type Tag = { id: number; slug: string; label: string; description: string | null; archived: boolean }
type Candidate = { device_id: string; user_id: string | null; score: number; sessions_30d: number; tenure_days: number; matched_tags: string[] }
type CohortMember = { device_id: string; user_id: string | null; state: string; candidate_score: number | null; matched_tags: string[]; sessions_30d: number | null; tenure_days: number | null; invited_at: string | null; opted_in_at: string | null; opt_in_source: string | null }

const STATE_COLORS: Record<string, string> = {
  invited: '#6b7280',
  opted_in: '#6ea8ff',
  ota_pushed: '#f59e0b',
  ota_confirmed: '#8b5cf6',
  evaluated: '#22c55e',
  declined: '#ef4444',
  expired: '#4b5563',
}

export function BetaProgramPanel() {
  const [tags, setTags] = useState<Tag[]>([])
  const [releases, setReleases] = useState<BetaReleaseSummary[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [cohort, setCohort] = useState<CohortMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'candidates' | 'cohort' | 'taxonomy'>('candidates')

  // Draft create-release form
  const [showCreate, setShowCreate] = useState(false)
  const [draftVersion, setDraftVersion] = useState('')
  const [draftTitle, setDraftTitle] = useState('')
  const [draftIssues, setDraftIssues] = useState<string[]>([])
  const [draftTarget, setDraftTarget] = useState(100)

  // Draft new tag
  const [newTagSlug, setNewTagSlug] = useState('')
  const [newTagLabel, setNewTagLabel] = useState('')
  const [newTagDesc, setNewTagDesc] = useState('')

  const selected = useMemo(
    () => releases.find(r => r.id === selectedId) ?? null,
    [releases, selectedId],
  )

  const refreshReleases = async () => {
    const r = await api.betaReleases()
    setReleases(r.releases)
    if (r.releases.length > 0 && selectedId == null) setSelectedId(r.releases[0].id)
    return r.releases
  }

  const refreshTags = async () => {
    const r = await api.betaIssueTags()
    setTags(r.tags)
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        await Promise.all([refreshTags(), refreshReleases()])
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (selectedId == null) { setCandidates([]); setCohort([]); return }
    let cancelled = false
    ;(async () => {
      try {
        const [c, m] = await Promise.all([
          api.betaCandidates(selectedId, 150),
          api.betaCohort(selectedId),
        ])
        if (cancelled) return
        setCandidates(c.candidates)
        setCohort(m.members)
      } catch { /* silent */ }
    })()
    return () => { cancelled = true }
  }, [selectedId])

  const handleCreateRelease = async () => {
    if (!draftVersion.trim()) return
    try {
      const created = await api.betaReleaseCreate({
        version: draftVersion.trim(),
        title: draftTitle.trim() || undefined,
        addresses_issues: draftIssues,
        beta_cohort_target_size: draftTarget,
      })
      setReleases(prev => [created, ...prev])
      setSelectedId(created.id)
      setShowCreate(false)
      setDraftVersion(''); setDraftTitle(''); setDraftIssues([]); setDraftTarget(100)
    } catch (e: unknown) {
      alert('Create failed: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleInvite = async () => {
    if (selectedId == null) return
    try {
      const r = await api.betaInvite(selectedId)
      alert(`Invited ${r.invited_count} devices (${r.already_invited} already in cohort, ${r.candidates_found} candidates scored).`)
      const fresh = await api.betaCohort(selectedId)
      setCohort(fresh.members)
    } catch (e: unknown) {
      alert('Invite failed: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleAddTag = async () => {
    if (!newTagSlug.trim() || !newTagLabel.trim()) return
    try {
      await api.betaIssueTagCreate({
        slug: newTagSlug.trim(),
        label: newTagLabel.trim(),
        description: newTagDesc.trim() || undefined,
      })
      setNewTagSlug(''); setNewTagLabel(''); setNewTagDesc('')
      await refreshTags()
    } catch (e: unknown) {
      alert('Add tag failed: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleArchiveTag = async (t: Tag) => {
    await api.betaIssueTagUpdate(t.id, { archived: !t.archived })
    await refreshTags()
  }

  if (loading) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Firmware Beta + Gamma Waves</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Firmware Beta + Gamma Waves</strong>
          <p className="venom-chart-sub">
            Auto-select beta cohorts from users whose devices exhibit the issues a firmware release targets.
            Phase 1: taxonomy + candidates + opt-in tracking. OTA push + Gamma scheduling land after the 2026-04-21 Agustin review.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn-secondary" onClick={() => setShowCreate(v => !v)}>
            {showCreate ? 'Cancel' : '+ New release'}
          </button>
        </div>
      </div>
      {error && <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>}

      {showCreate && (
        <div style={{ padding: 12, background: 'rgba(110,168,255,0.06)', borderRadius: 8, marginBottom: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 8, marginBottom: 8 }}>
            <input placeholder="Version (e.g. 01.01.98)" value={draftVersion} onChange={e => setDraftVersion(e.target.value)} className="input" />
            <input placeholder="Title (optional)" value={draftTitle} onChange={e => setDraftTitle(e.target.value)} className="input" />
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Addresses issues:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
            {tags.filter(t => !t.archived).map(t => {
              const on = draftIssues.includes(t.slug)
              return (
                <button
                  key={t.id}
                  onClick={() => setDraftIssues(prev => on ? prev.filter(s => s !== t.slug) : [...prev, t.slug])}
                  style={{
                    fontSize: 11, padding: '3px 8px', borderRadius: 10,
                    border: `1px solid ${on ? '#6ea8ff' : 'rgba(255,255,255,0.15)'}`,
                    background: on ? 'rgba(110,168,255,0.2)' : 'transparent',
                    color: on ? '#fff' : 'var(--muted)', cursor: 'pointer',
                  }}
                >
                  {t.label}
                </button>
              )
            })}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 12, color: 'var(--muted)' }}>Cohort size:</label>
            <input type="number" value={draftTarget} onChange={e => setDraftTarget(parseInt(e.target.value) || 100)} style={{ width: 80 }} className="input" min={1} max={1000} />
            <button className="btn-primary" onClick={handleCreateRelease} disabled={!draftVersion.trim() || draftIssues.length === 0}>Create</button>
          </div>
        </div>
      )}

      {/* Release selector */}
      {releases.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {releases.map(r => (
            <button
              key={r.id}
              onClick={() => setSelectedId(r.id)}
              style={{
                fontSize: 12, padding: '4px 10px', borderRadius: 6,
                border: `1px solid ${r.id === selectedId ? '#6ea8ff' : 'rgba(255,255,255,0.12)'}`,
                background: r.id === selectedId ? 'rgba(110,168,255,0.15)' : 'transparent',
                color: '#fff', cursor: 'pointer',
              }}
            >
              <strong>{r.version}</strong>
              <span style={{ marginLeft: 6, color: 'var(--muted)' }}>{r.status}</span>
            </button>
          ))}
        </div>
      )}

      {releases.length === 0 && !showCreate && (
        <div className="state-message">
          No firmware releases yet. Click <strong>+ New release</strong> above to create one — pick the issue tags it addresses and we'll auto-rank eligible beta candidates.
        </div>
      )}

      {/* Tabs */}
      {selected && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 10, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
          {(['candidates', 'cohort', 'taxonomy'] as const).map(t => (
            <button
              key={t}
              onClick={() => setView(t)}
              style={{
                padding: '6px 0', fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5,
                background: 'none', border: 'none', cursor: 'pointer',
                color: view === t ? '#fff' : 'var(--muted)',
                borderBottom: view === t ? '2px solid #6ea8ff' : '2px solid transparent',
              }}
            >
              {t === 'candidates' ? 'Ranked candidates' : t === 'cohort' ? `Cohort (${(selected.cohort_counts && Object.values(selected.cohort_counts).reduce((a, b) => a + b, 0)) || 0})` : 'Issue taxonomy'}
            </button>
          ))}
        </div>
      )}

      {selected && view === 'candidates' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              Ranked by issue-match strength × recent usage × account tenure. Showing top {candidates.length}.
            </div>
            <button className="btn-primary" onClick={handleInvite} disabled={candidates.length === 0}>
              Invite top {selected.beta_cohort_target_size} to beta →
            </button>
          </div>
          {candidates.length === 0 ? (
            <div className="state-message">
              No devices match the issue tags on release {selected.version}. Either no devices currently exhibit these failure modes, or the tags need detectors wired up.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr>
                  <th>#</th><th>Device</th><th>Score</th><th>Matched tags</th><th>Sessions (30d)</th><th>Tenure (d)</th>
                </tr></thead>
                <tbody>
                  {candidates.slice(0, 50).map((c, i) => (
                    <tr key={c.device_id}>
                      <td>{i + 1}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{c.device_id}</td>
                      <td>{(c.score * 100).toFixed(0)}</td>
                      <td style={{ fontSize: 11 }}>{c.matched_tags.join(', ')}</td>
                      <td>{c.sessions_30d}</td>
                      <td>{c.tenure_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {selected && view === 'cohort' && (
        <div>
          {cohort.length === 0 ? (
            <div className="state-message">
              Cohort is empty. Run "Invite top {selected.beta_cohort_target_size} to beta" from the Candidates tab to populate it.
            </div>
          ) : (
            <>
              {/* State distribution bar */}
              <div style={{ display: 'flex', height: 22, borderRadius: 6, overflow: 'hidden', marginBottom: 10 }}>
                {Object.entries(
                  cohort.reduce<Record<string, number>>((acc, m) => { acc[m.state] = (acc[m.state] ?? 0) + 1; return acc }, {}),
                ).map(([state, n]) => (
                  <div
                    key={state}
                    title={`${state}: ${n}`}
                    style={{
                      flex: n, background: STATE_COLORS[state] ?? '#555',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: '#fff', fontSize: 10, fontWeight: 600,
                    }}
                  >{n}</div>
                ))}
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead><tr>
                    <th>Device</th><th>State</th><th>Score</th><th>Matched tags</th><th>Opted in</th><th>Source</th>
                  </tr></thead>
                  <tbody>
                    {cohort.slice(0, 200).map(m => (
                      <tr key={m.device_id}>
                        <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{m.device_id}</td>
                        <td>
                          <span style={{ padding: '2px 6px', borderRadius: 8, background: (STATE_COLORS[m.state] ?? '#555') + '33', color: STATE_COLORS[m.state] ?? '#fff', fontSize: 10 }}>
                            {m.state}
                          </span>
                        </td>
                        <td>{m.candidate_score != null ? (m.candidate_score * 100).toFixed(0) : '—'}</td>
                        <td style={{ fontSize: 11 }}>{m.matched_tags.join(', ')}</td>
                        <td>{m.opted_in_at ? new Date(m.opted_in_at).toLocaleDateString() : '—'}</td>
                        <td>{m.opt_in_source ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {view === 'taxonomy' && (
        <div>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
            Editable taxonomy of failure modes a firmware release can address. Archive instead of deleting so historical releases still resolve.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr 120px', gap: 6, marginBottom: 8 }}>
            <input placeholder="slug_here" value={newTagSlug} onChange={e => setNewTagSlug(e.target.value)} className="input" />
            <input placeholder="Label" value={newTagLabel} onChange={e => setNewTagLabel(e.target.value)} className="input" />
            <input placeholder="Description (optional)" value={newTagDesc} onChange={e => setNewTagDesc(e.target.value)} className="input" />
            <button className="btn-primary" onClick={handleAddTag} disabled={!newTagSlug.trim() || !newTagLabel.trim()}>Add tag</button>
          </div>
          <table className="data-table">
            <thead><tr><th>Slug</th><th>Label</th><th>Description</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {tags.map(t => (
                <tr key={t.id} style={{ opacity: t.archived ? 0.5 : 1 }}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{t.slug}</td>
                  <td>{t.label}</td>
                  <td style={{ fontSize: 12, color: 'var(--muted)' }}>{t.description ?? '—'}</td>
                  <td>{t.archived ? 'archived' : 'active'}</td>
                  <td><button className="btn-secondary" onClick={() => handleArchiveTag(t)}>{t.archived ? 'Restore' : 'Archive'}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
