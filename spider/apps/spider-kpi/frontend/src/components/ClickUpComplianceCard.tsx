import { useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { ClickUpComplianceResponse } from '../lib/types'
import { fmtInt, fmtPct, formatFreshness } from '../lib/format'

/**
 * Tagging-compliance card. Grades tasks against the required-field taxonomy
 * (Division, Customer Impact, Category) and shows:
 *   - Compliance rate for tasks closed in the window
 *   - Week-over-week trend
 *   - Per-assignee rate
 *   - Which fields are most often missing
 *   - Direct links to non-compliant tasks
 *
 * Shows a helpful "taxonomy not yet configured" state if the custom fields
 * haven't been created in ClickUp yet.
 */
type Props = {
  title?: string
  subtitle?: string
  spaceId?: string
  days?: number
}

function rateColor(rate: number | null | undefined): string {
  if (rate == null) return 'var(--muted)'
  if (rate >= 0.9) return 'var(--green)'
  if (rate >= 0.7) return 'var(--orange)'
  return 'var(--red)'
}

export function ClickUpComplianceCard({
  title = 'Tagging compliance',
  subtitle,
  spaceId,
  days = 14,
}: Props) {
  const [data, setData] = useState<ClickUpComplianceResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.clickupCompliance(spaceId, days)
      .then(r => { if (!cancelled) setData(r) })
      .catch(err => { if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load compliance') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [spaceId, days])

  const runbookLink = 'https://github.com/jpruit20/spiderclawkpi/blob/master/spider/apps/spider-kpi/deploy/CLICKUP_TAGGING_SETUP.md'

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>{title}</strong>
        <span className="venom-panel-hint">
          {data ? `${data.window.days}-day window` : ''}
        </span>
      </div>

      {subtitle && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>{subtitle}</p>
      )}

      {loading && <div className="state-message">Loading compliance…</div>}
      {error && <div className="state-message error">{error}</div>}

      {!loading && !error && data && !data.taxonomy_configured && (
        <div className="state-message warn">
          <div>
            <strong>Taxonomy not yet detected in any task.</strong>
            <p style={{ fontSize: 12, marginTop: 4 }}>
              The dashboard looks for three Custom Fields on tasks: <code>Division</code>,
              {' '}<code>Customer Impact</code>, <code>Category</code>. None of them are
              showing up in the synced tasks yet. Create them in ClickUp (workspace scope),
              mark them "required when closing", and this card will come to life.
            </p>
            <p style={{ fontSize: 12, marginTop: 6 }}>
              <a href={runbookLink} target="_blank" rel="noopener noreferrer" className="analysis-link">
                Setup runbook ↗
              </a>
            </p>
            <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>
              Field presence so far:
              {data.required_fields.map((f, i) => (
                <span key={f.name} style={{ marginLeft: 8 }}>
                  <span style={{ color: data.taxonomy_field_presence[f.name] > 0 ? 'var(--green)' : 'var(--red)' }}>
                    {data.taxonomy_field_presence[f.name] > 0 ? '✓' : '×'}
                  </span>{' '}
                  {f.name} ({data.taxonomy_field_presence[f.name] || 0} tasks)
                  {i < data.required_fields.length - 1 ? ',' : ''}
                </span>
              ))}
            </p>
          </div>
        </div>
      )}

      {!loading && !error && data && data.taxonomy_configured && (
        <>
          <div className="venom-bar-list" style={{ marginBottom: 10 }}>
            <div className="venom-breakdown-row">
              <span className="venom-bar-label">Closed + tagged (window)</span>
              <span className="venom-breakdown-val" style={{ color: rateColor(data.closed_in_window.rate) }}>
                {data.closed_in_window.rate == null ? '—' : fmtPct(data.closed_in_window.rate)}
              </span>
              <span style={{ color: 'var(--muted)', fontSize: 11 }}>
                {fmtInt(data.closed_in_window.compliant)}/{fmtInt(data.closed_in_window.total)}
                {data.wow_delta_rate != null && (
                  <span style={{ marginLeft: 6, color: data.wow_delta_rate >= 0 ? 'var(--green)' : 'var(--red)' }}>
                    {data.wow_delta_rate >= 0 ? '+' : ''}{(data.wow_delta_rate * 100).toFixed(0)}pp vs prior
                  </span>
                )}
              </span>
            </div>
            <div className="venom-breakdown-row">
              <span className="venom-bar-label">Open tasks drift</span>
              <span className="venom-breakdown-val" style={{ color: rateColor(data.open_now.rate) }}>
                {data.open_now.rate == null ? '—' : fmtPct(data.open_now.rate)}
              </span>
              <span style={{ color: 'var(--muted)', fontSize: 11 }}>
                {fmtInt(data.open_now.compliant)}/{fmtInt(data.open_now.total)} open tasks tagged
              </span>
            </div>
          </div>

          {/* Missing-field breakdown */}
          {Object.values(data.closed_in_window.by_missing_field).some(v => v > 0) && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                Most-missed fields on closed tasks:
              </div>
              <div className="venom-breakdown-list">
                {Object.entries(data.closed_in_window.by_missing_field)
                  .filter(([, v]) => v > 0)
                  .sort(([, a], [, b]) => b - a)
                  .map(([name, count]) => (
                    <div key={name} className="venom-breakdown-row">
                      <span>{name}</span>
                      <span className="venom-breakdown-val">{fmtInt(count)}</span>
                      <span style={{ color: 'var(--muted)', fontSize: 11 }}>
                        missed on {fmtPct(count / Math.max(1, data.closed_in_window.total))} of closes
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Per-assignee */}
          {data.closed_in_window.by_assignee.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                Compliance by closer (window):
              </div>
              <div className="venom-breakdown-list">
                {data.closed_in_window.by_assignee.slice(0, 8).map((row) => (
                  <div key={row.user} className="venom-breakdown-row">
                    <span>{row.user}</span>
                    <span className="venom-breakdown-val" style={{ color: rateColor(row.rate) }}>
                      {row.rate == null ? '—' : fmtPct(row.rate)}
                    </span>
                    <span style={{ color: 'var(--muted)', fontSize: 11 }}>
                      {fmtInt(row.compliant)}/{fmtInt(row.total)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Non-compliant offenders — direct-fix links */}
          {data.closed_in_window.non_compliant.length > 0 && (
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                Closed without required tags (top {Math.min(8, data.closed_in_window.non_compliant.length)}):
              </div>
              <div className="stack-list compact">
                {data.closed_in_window.non_compliant.slice(0, 8).map((t) => {
                  const content = (
                    <>
                      <div className="item-head">
                        <strong style={{ fontSize: 12 }}>
                          {(t.name || '(untitled)').slice(0, 100)}
                        </strong>
                        <div className="inline-badges">
                          {t.missing.map(m => (
                            <span key={m} className="badge badge-bad" style={{ fontSize: 10 }}>
                              no {m}
                            </span>
                          ))}
                        </div>
                      </div>
                      <p style={{ fontSize: 11 }}>
                        {[t.space_name, t.list_name].filter(Boolean).join(' · ')}
                        {t.assignees.length > 0 && ` · ${t.assignees.filter(Boolean).join(', ')}`}
                        {t.date_done && ` · closed ${formatFreshness(t.date_done)}`}
                      </p>
                    </>
                  )
                  if (t.url) {
                    return (
                      <a
                        key={t.task_id}
                        href={t.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="list-item status-bad"
                        style={{ textDecoration: 'none', color: 'inherit' }}
                      >
                        {content}
                      </a>
                    )
                  }
                  return (
                    <div key={t.task_id} className="list-item status-bad">
                      {content}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {data.closed_in_window.total === 0 && (
            <div className="state-message">No tasks closed in this window yet.</div>
          )}
        </>
      )}
    </section>
  )
}
