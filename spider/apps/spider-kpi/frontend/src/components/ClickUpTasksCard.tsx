import { useEffect, useMemo, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { ClickUpTaskFilter, ClickUpTaskListResponse, ClickUpTask } from '../lib/types'
import { formatFreshness } from '../lib/format'

/**
 * Reusable ClickUp tasks card. Drop on any division page with an initial
 * filter — the card owns its own data loading, filter refinement, and
 * "open | overdue | all" view toggle so page-level callers only pick defaults.
 */
type Props = {
  /** Title shown on the card header. */
  title?: string
  /** Optional hint / subheader explaining why these tasks live on this page. */
  subtitle?: string
  /** Baseline filter. User can narrow further via the inline chips. */
  defaultFilter?: ClickUpTaskFilter
  /** How many rows to show (defaults to 25). */
  limit?: number
  /** Show the "view in ClickUp" quick-link; defaults to true. */
  showExternalLinks?: boolean
}

const PRIORITY_BADGE_CLASS: Record<string, string> = {
  urgent: 'badge-bad',
  high: 'badge-warn',
  normal: 'badge-neutral',
  low: 'badge-muted',
}

function priorityClass(priority: string | null | undefined): string {
  if (!priority) return 'badge-muted'
  return PRIORITY_BADGE_CLASS[priority.toLowerCase()] || 'badge-muted'
}

function statusSeverity(t: ClickUpTask, now: number): 'bad' | 'warn' | 'muted' | 'neutral' {
  if (t.due_date && t.is_open && new Date(t.due_date).getTime() < now) return 'bad'
  if (t.priority && ['urgent', 'high'].includes((t.priority || '').toLowerCase()) && t.is_open) return 'warn'
  if (!t.is_open) return 'muted'
  return 'neutral'
}

export function ClickUpTasksCard({
  title = 'ClickUp tasks',
  subtitle,
  defaultFilter,
  limit = 25,
  showExternalLinks = true,
}: Props) {
  const [data, setData] = useState<ClickUpTaskListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scope, setScope] = useState<'open' | 'overdue' | 'all'>('open')

  const effectiveFilter: ClickUpTaskFilter = useMemo(() => {
    const f: ClickUpTaskFilter = { limit, ...defaultFilter }
    if (scope === 'open') f.status_type = f.status_type || 'open'
    else if (scope === 'overdue') { f.overdue_only = true; f.status_type = 'open' }
    else if (scope === 'all') { /* no extra filter */ }
    return f
  }, [defaultFilter, limit, scope])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.clickupTasks(effectiveFilter)
      .then((resp) => { if (!cancelled) setData(resp) })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load ClickUp tasks')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [JSON.stringify(effectiveFilter)])  // eslint-disable-line react-hooks/exhaustive-deps

  const now = Date.now()
  const notConfigured = data !== null && data.configured === false

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>{title}</strong>
        <span className="venom-panel-hint">
          {data ? (
            <>
              {data.summary.open} open
              {data.summary.overdue > 0 && (
                <span style={{ color: 'var(--red)', marginLeft: 6 }}>
                  · {data.summary.overdue} overdue
                </span>
              )}
            </>
          ) : ''}
        </span>
      </div>
      {subtitle && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>{subtitle}</p>
      )}

      {notConfigured && (
        <div className="state-message warn">
          ClickUp is not configured on the server. Add
          <code style={{ margin: '0 4px' }}>CLICKUP_API_TOKEN</code>
          and <code style={{ margin: '0 4px' }}>CLICKUP_TEAM_ID</code> to the backend env to enable.
        </div>
      )}

      {!notConfigured && (
        <>
          <div className="inline-badges" style={{ marginBottom: 10 }}>
            <button
              className={`badge ${scope === 'open' ? 'badge-neutral' : 'badge-muted'}`}
              onClick={() => setScope('open')}
              style={{ cursor: 'pointer', border: 'none' }}
            >
              open
            </button>
            <button
              className={`badge ${scope === 'overdue' ? 'badge-bad' : 'badge-muted'}`}
              onClick={() => setScope('overdue')}
              style={{ cursor: 'pointer', border: 'none' }}
            >
              overdue
            </button>
            <button
              className={`badge ${scope === 'all' ? 'badge-neutral' : 'badge-muted'}`}
              onClick={() => setScope('all')}
              style={{ cursor: 'pointer', border: 'none' }}
            >
              all
            </button>
          </div>

          {loading && <div className="state-message">Loading ClickUp tasks…</div>}
          {error && <div className="state-message error">{error}</div>}

          {!loading && !error && data && data.tasks.length === 0 && (
            <div className="state-message">No tasks match this filter yet.</div>
          )}

          {!loading && !error && data && data.tasks.length > 0 && (
            <div className="stack-list compact">
              {data.tasks.map((t) => {
                const sev = statusSeverity(t, now)
                const dueAbs = t.due_date ? new Date(t.due_date) : null
                const overdue = Boolean(dueAbs && t.is_open && dueAbs.getTime() < now)
                const assignees = (t.assignees || []).slice(0, 3).map(a => a.username || a.email || a.id).filter(Boolean).join(', ')
                const content = (
                  <>
                    <div className="item-head">
                      <strong style={{ fontSize: 12 }}>
                        {t.custom_id && <span style={{ fontFamily: 'monospace', marginRight: 4, color: 'var(--muted)' }}>{t.custom_id}</span>}
                        {t.name || '(untitled)'}
                      </strong>
                      <div className="inline-badges">
                        {t.status && <span className="badge badge-neutral" style={{ fontSize: 10 }}>{t.status}</span>}
                        {t.priority && <span className={`badge ${priorityClass(t.priority)}`} style={{ fontSize: 10 }}>{t.priority}</span>}
                        {overdue && <span className="badge badge-bad" style={{ fontSize: 10 }}>overdue</span>}
                      </div>
                    </div>
                    <p style={{ fontSize: 11 }}>
                      {[t.space_name, t.list_name].filter(Boolean).join(' · ')}
                      {assignees && ` · ${assignees}`}
                      {dueAbs && ` · due ${dueAbs.toISOString().slice(0, 10)}`}
                      {t.date_updated && ` · updated ${formatFreshness(t.date_updated)}`}
                    </p>
                  </>
                )
                if (showExternalLinks && t.url) {
                  return (
                    <a
                      key={t.task_id}
                      href={t.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`list-item status-${sev}`}
                      style={{ textDecoration: 'none', color: 'inherit' }}
                    >
                      {content}
                    </a>
                  )
                }
                return (
                  <div key={t.task_id} className={`list-item status-${sev}`}>
                    {content}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </section>
  )
}
