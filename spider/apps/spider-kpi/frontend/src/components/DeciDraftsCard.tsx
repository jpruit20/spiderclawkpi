import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { DeciDraft } from '../lib/types'
import { formatFreshness } from '../lib/format'

/**
 * Auto-generated DECI drafts awaiting review. Drops at the top of the DECI
 * page. Each draft comes from the auto-draft engine (Slack / ClickUp issue
 * signals) — Joseph reviews and either promotes to a real decision or
 * dismisses as noise.
 */
type Props = {
  /** Called after a draft is promoted or dismissed so the parent page can refresh. */
  onChange?: () => void
}

function badgeForSignal(sigType: string | null | undefined): string {
  if (!sigType) return 'badge-muted'
  if (sigType.includes('crash') || sigType.includes('urgent') || sigType.includes('fault')) return 'badge-bad'
  if (sigType.includes('refund') || sigType.includes('complaint')) return 'badge-warn'
  return 'badge-neutral'
}

function sourceLabel(sigType: string | null | undefined): string {
  if (!sigType) return 'auto'
  const [src] = sigType.split('.', 1)
  return src
}

export function DeciDraftsCard({ onChange }: Props) {
  const [drafts, setDrafts] = useState<DeciDraft[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await api.deciDrafts()
      setDrafts(resp.drafts)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load auto-drafts')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function handlePromote(id: string) {
    setPendingId(id)
    try {
      await api.deciPromoteDraft(id)
      await load()
      onChange?.()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Promote failed')
    } finally {
      setPendingId(null)
    }
  }

  async function handleDismiss(id: string) {
    setPendingId(id)
    try {
      await api.deciDismissDraft(id)
      await load()
      onChange?.()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Dismiss failed')
    } finally {
      setPendingId(null)
    }
  }

  if (!loading && !error && drafts && drafts.length === 0) {
    // Empty state is quiet — only show the card when there's something to do.
    return null
  }

  return (
    <section className="card" style={{ borderLeft: '3px solid var(--blue)' }}>
      <div className="venom-panel-head">
        <strong>Drafts awaiting review</strong>
        <span className="venom-panel-hint">
          {drafts ? `${drafts.length} auto-drafted from Slack + ClickUp activity` : ''}
        </span>
      </div>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
        Auto-drafted DECI items from upstream team activity (Slack messages + ClickUp tasks).
        Review and either promote to an active decision or dismiss if not actionable.
      </p>

      {loading && <div className="state-message">Loading drafts…</div>}
      {error && <div className="state-message error">{error}</div>}

      {!loading && !error && drafts && drafts.length > 0 && (
        <div className="stack-list compact">
          {drafts.map((d) => {
            const isPending = pendingId === d.id
            return (
              <div key={d.id} className="list-item status-neutral" style={{ opacity: isPending ? 0.5 : 1 }}>
                <div className="item-head">
                  <strong style={{ fontSize: 13 }}>{d.title}</strong>
                  <div className="inline-badges">
                    {d.origin_signal_type && (
                      <span className={`badge ${badgeForSignal(d.origin_signal_type)}`} style={{ fontSize: 10 }}>
                        {sourceLabel(d.origin_signal_type)}
                      </span>
                    )}
                    <span className="badge badge-neutral" style={{ fontSize: 10 }}>{d.priority}</span>
                    {d.department && (
                      <span className="badge badge-muted" style={{ fontSize: 10 }}>{d.department}</span>
                    )}
                  </div>
                </div>
                <p style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'pre-wrap' }}>
                  {(d.description || '').slice(0, 400)}
                  {d.description && d.description.length > 400 ? '…' : ''}
                </p>
                {d.recent_logs && d.recent_logs.length > 0 && (
                  <div style={{ marginTop: 6, padding: 6, background: 'rgba(255,255,255,0.02)', borderRadius: 3 }}>
                    <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 4 }}>
                      {d.recent_logs.length} related update{d.recent_logs.length === 1 ? '' : 's'}:
                    </div>
                    {d.recent_logs.slice(0, 3).map((l, i) => (
                      <div key={i} style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 2 }}>
                        {l.created_at && <span>{formatFreshness(l.created_at)} · </span>}
                        {l.decision_text.slice(0, 160)}
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                  <button
                    className="range-button active"
                    disabled={isPending}
                    onClick={() => handlePromote(d.id)}
                    style={{ fontSize: 11 }}
                  >
                    Promote
                  </button>
                  <button
                    className="range-button"
                    disabled={isPending}
                    onClick={() => handleDismiss(d.id)}
                    style={{ fontSize: 11 }}
                  >
                    Dismiss
                  </button>
                  {d.auto_drafted_at && (
                    <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 'auto', alignSelf: 'center' }}>
                      auto-drafted {formatFreshness(d.auto_drafted_at)}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
