import { useCallback, useEffect, useState } from 'react'
import { api, type AISelfGradeRow } from '../lib/api'
import { useAuth } from './AuthGate'
import { formatFreshness } from '../lib/format'

const OWNER_EMAIL = 'joseph@spidergrills.com'

const GRADE_COLORS: Record<string, string> = {
  A: '#22c55e',
  B: '#84cc16',
  C: '#f59e0b',
  D: '#f97316',
  F: '#ef4444',
}

export function AISelfGradeCard() {
  const { user } = useAuth()
  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL

  const [grades, setGrades] = useState<AISelfGradeRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const r = await api.aiSelfGradeList(6)
      setGrades(r.grades)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  if (!isOwner) return null

  const runNow = async () => {
    setBusy(true)
    try {
      await api.aiSelfGradeRun()
      await load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const approve = async (id: number) => {
    setBusy(true)
    try { await api.aiSelfGradeApprove(id); await load() }
    catch (e: unknown) { setErr(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  const reject = async (id: number) => {
    setBusy(true)
    try { await api.aiSelfGradeReject(id); await load() }
    catch (e: unknown) { setErr(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  const latest = grades && grades.length > 0 ? grades[0] : null

  return (
    <section className="card" style={{ borderLeft: '3px solid #a855f7' }}>
      <div className="venom-panel-head">
        <strong>AI Self-Grade</strong>
        <span className="venom-panel-hint">
          Weekly Opus review of AI outputs vs. your feedback
        </span>
      </div>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
        Every Sunday at 10:00 ET, Opus 4.7 reviews the past week of AI-generated
        insights, DECI drafts, issue signals, and firmware verdicts against the
        reactions you and the team logged. It proposes a {'"'}prompt delta{'"'} —
        a tightening of the insight engine{"'"}s system prompt — that will only
        apply if you approve it.
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <button className="range-button active" disabled={busy} onClick={runNow} style={{ fontSize: 11 }}>
          {busy ? 'Running…' : 'Run self-grade now'}
        </button>
      </div>

      {loading && <div className="state-message">Loading…</div>}
      {err && <div className="state-message error">{err}</div>}

      {!loading && !err && (!grades || grades.length === 0) && (
        <div className="state-message">
          No self-grades yet. Click {'"'}Run self-grade now{'"'} or wait for Sunday.
        </div>
      )}

      {latest && (
        <div className="list-item status-neutral" style={{ marginBottom: 8 }}>
          <div className="item-head">
            <strong style={{ fontSize: 13 }}>
              Latest run · {formatFreshness(latest.run_at)}
            </strong>
            <div className="inline-badges">
              <span className="badge badge-muted" style={{ fontSize: 10 }}>
                {latest.artifacts_scored} artifacts · {latest.feedback_count} reactions
              </span>
              {latest.approved_at ? (
                <span className="badge badge-good" style={{ fontSize: 10 }}>
                  approved
                </span>
              ) : latest.prompt_delta ? (
                <span className="badge badge-warn" style={{ fontSize: 10 }}>
                  awaiting approval
                </span>
              ) : (
                <span className="badge badge-muted" style={{ fontSize: 10 }}>
                  no prompt change
                </span>
              )}
            </div>
          </div>
          {latest.overall_summary && (
            <p style={{ fontSize: 12, marginTop: 4 }}>{latest.overall_summary}</p>
          )}

          {latest.precision_by_source && (
            <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
              {Object.entries(latest.precision_by_source).map(([source, info]) => (
                <div key={source} style={{ fontSize: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      display: 'inline-block', width: 22, height: 22, lineHeight: '22px',
                      textAlign: 'center', borderRadius: 4, fontWeight: 700,
                      background: (GRADE_COLORS[info.grade] ?? '#6b7280') + '33',
                      color: GRADE_COLORS[info.grade] ?? '#6b7280',
                    }}>{info.grade}</span>
                    <strong style={{ fontSize: 12 }}>{source}</strong>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>{info.precision_note}</span>
                  </div>
                  {(info.specific_wins?.length || info.specific_misses?.length) ? (
                    <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, marginLeft: 30 }}>
                      {info.specific_wins?.length ? (
                        <div>✓ {info.specific_wins.join('; ')}</div>
                      ) : null}
                      {info.specific_misses?.length ? (
                        <div>✗ {info.specific_misses.join('; ')}</div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          {latest.rejection_themes && latest.rejection_themes.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                Rejection themes:
              </div>
              {latest.rejection_themes.map((t, i) => (
                <div key={i} style={{ fontSize: 11, marginBottom: 2 }}>
                  <strong>{t.theme}</strong>{' '}
                  <span style={{ color: 'var(--muted)' }}>({t.frequency}×) — {t.example}</span>
                </div>
              ))}
            </div>
          )}

          {latest.prompt_delta && (
            <div style={{ marginTop: 10, padding: 8, background: 'rgba(168, 85, 247, 0.08)', borderRadius: 4 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                Proposed prompt delta:
              </div>
              <pre style={{
                fontSize: 11, whiteSpace: 'pre-wrap', lineHeight: 1.4,
                margin: 0, fontFamily: 'inherit',
              }}>
                {latest.prompt_delta}
              </pre>
              {!latest.approved_at && (
                <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                  <button
                    className="range-button active"
                    disabled={busy}
                    onClick={() => approve(latest.id)}
                    style={{ fontSize: 11 }}
                  >
                    Approve
                  </button>
                  <button
                    className="range-button"
                    disabled={busy}
                    onClick={() => reject(latest.id)}
                    style={{ fontSize: 11 }}
                  >
                    Reject
                  </button>
                </div>
              )}
              {latest.approved_at && (
                <div style={{ marginTop: 6, fontSize: 11, color: 'var(--muted)' }}>
                  Approved {formatFreshness(latest.approved_at)} by {latest.approved_by ?? 'unknown'}
                  {latest.applied_at ? ` · applied ${formatFreshness(latest.applied_at)}` : ' · not yet applied'}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {grades && grades.length > 1 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ fontSize: 11, color: 'var(--muted)', cursor: 'pointer' }}>
            Past runs ({grades.length - 1})
          </summary>
          <div style={{ marginTop: 6, display: 'grid', gap: 4 }}>
            {grades.slice(1).map(g => (
              <div key={g.id} style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', gap: 8 }}>
                <span>{formatFreshness(g.run_at)}</span>
                <span>·</span>
                <span>{g.artifacts_scored} artifacts / {g.feedback_count} reactions</span>
                {g.prompt_delta ? (
                  <span className={g.approved_at ? 'badge badge-good' : 'badge badge-muted'} style={{ fontSize: 9 }}>
                    {g.approved_at ? 'approved' : 'no-action'}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  )
}
