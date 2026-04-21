import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ApiError, api } from '../lib/api'
import { fmtInt } from '../lib/format'
import type { ProductComplaintsResponse } from '../lib/types'

type Props = {
  title?: string
  subtitle?: string
  defaultQuery?: string
  defaultAliases?: string
  defaultDays?: number
  /** If true, start collapsed and show an expand toggle in the header. */
  collapsible?: boolean
  defaultExpanded?: boolean
}

const DAY_OPTIONS: { label: string; value: number }[] = [
  { label: '30d', value: 30 },
  { label: '90d', value: 90 },
  { label: '180d', value: 180 },
  { label: '1y', value: 365 },
  { label: '5y', value: 1825 },
]

export function ProductComplaintsCard({
  title = 'Product complaint search',
  subtitle = 'Counts Freshdesk tickets (subject + description + conversations) plus social, reviews, and community mentions for any product term.',
  defaultQuery = 'Kettle Cart',
  defaultAliases = 'kettle-cart, cart upgrade',
  defaultDays = 180,
  collapsible = false,
  defaultExpanded = true,
}: Props) {
  const [query, setQuery] = useState(defaultQuery)
  const [aliases, setAliases] = useState(defaultAliases)
  const [days, setDays] = useState(defaultDays)
  const [submittedQuery, setSubmittedQuery] = useState(defaultQuery)
  const [submittedAliases, setSubmittedAliases] = useState(defaultAliases)
  const [submittedDays, setSubmittedDays] = useState(defaultDays)
  const [data, setData] = useState<ProductComplaintsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(collapsible ? defaultExpanded : true)

  useEffect(() => {
    if (!collapsible || expanded) return
    // When collapsed, abort any in-flight request and don't refetch until
    // the user expands. Keeps the card cheap when it's just a header.
  }, [collapsible, expanded])

  useEffect(() => {
    if (collapsible && !expanded) return
    if (!submittedQuery.trim()) {
      setData(null)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    api.complaintsByProduct({
      q: submittedQuery.trim(),
      aliases: submittedAliases.trim(),
      days: submittedDays,
    }, controller.signal)
      .then(r => setData(r))
      .catch(err => {
        if (controller.signal.aborted) return
        setError(err instanceof ApiError ? err.message : 'Failed to load complaints')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [submittedQuery, submittedAliases, submittedDays, collapsible, expanded])

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setSubmittedQuery(query)
    setSubmittedAliases(aliases)
    setSubmittedDays(days)
  }

  const counts = data?.counts
  const total = counts?.total ?? 0

  const tileRow = useMemo(() => {
    if (!counts) return null
    return (
      <div className="venom-kpi-strip" style={{ marginTop: 10 }}>
        <div className="venom-kpi-tile">
          <div className="venom-kpi-label">Total matches</div>
          <div className="venom-kpi-value">{fmtInt(counts.total)}</div>
          <div className="venom-kpi-sub">across all sources</div>
        </div>
        <div className="venom-kpi-tile">
          <div className="venom-kpi-label">Freshdesk tickets</div>
          <div className="venom-kpi-value">{fmtInt(counts.freshdesk_tickets)}</div>
          <div className="venom-kpi-sub">{fmtInt(counts.freshdesk_conversations_with_match)} via conversation body</div>
        </div>
        <div className="venom-kpi-tile">
          <div className="venom-kpi-label">Social mentions</div>
          <div className="venom-kpi-value">{fmtInt(counts.social_mentions)}</div>
          <div className="venom-kpi-sub">Reddit, YouTube, etc.</div>
        </div>
        <div className="venom-kpi-tile">
          <div className="venom-kpi-label">Reviews</div>
          <div className="venom-kpi-value">{fmtInt(counts.review_mentions)}</div>
          <div className="venom-kpi-sub">Amazon, Google reviews</div>
        </div>
        <div className="venom-kpi-tile">
          <div className="venom-kpi-label">Community</div>
          <div className="venom-kpi-value">{fmtInt(counts.community_messages)}</div>
          <div className="venom-kpi-sub">forums, Slack, Discord</div>
        </div>
      </div>
    )
  }, [counts])

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'center' }}>
        <div>
          <strong>{title}</strong>
          {(!collapsible || expanded) ? (
            <span className="venom-panel-hint" style={{ display: 'block', marginTop: 2 }}>{subtitle}</span>
          ) : null}
        </div>
        {collapsible ? (
          <button
            type="button"
            onClick={() => setExpanded(x => !x)}
            style={{
              fontSize: 11,
              padding: '4px 10px',
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: 6,
              color: 'var(--muted)',
              cursor: 'pointer',
            }}
            title={expanded ? 'Collapse search' : 'Expand product complaint search'}
          >
            {expanded ? 'Hide search ▲' : 'Open search ▼'}
          </button>
        ) : null}
      </div>

      {collapsible && !expanded ? null : (
      <>
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 4 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: '1 1 220px' }}>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>Product / keyword</span>
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder='e.g. Kettle Cart'
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--fg)' }}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: '2 1 320px' }}>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>Aliases (comma-separated)</span>
          <input
            type="text"
            value={aliases}
            onChange={e => setAliases(e.target.value)}
            placeholder='kettle-cart, cart upgrade'
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--fg)' }}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>Window</span>
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--fg)' }}
          >
            {DAY_OPTIONS.map(opt => (<option key={opt.value} value={opt.value}>{opt.label}</option>))}
          </select>
        </label>
        <button type="submit" className="btn btn-primary" style={{ padding: '6px 14px' }}>Search</button>
      </form>

      {error ? <div className="state-message error" style={{ marginTop: 10 }}>{error}</div> : null}
      {loading ? <div className="state-message" style={{ marginTop: 10 }}>Searching…</div> : null}

      {data && !loading ? (
        <>
          {tileRow}

          {total === 0 ? (
            <div className="state-message" style={{ marginTop: 10 }}>No matches in the last {data.days} days.</div>
          ) : (
            <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
              {data.samples.tickets.length > 0 ? (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Freshdesk sample ({data.samples.tickets.length} of {counts?.freshdesk_tickets ?? 0})
                  </div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {data.samples.tickets.map(t => (
                      <li key={t.ticket_id} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px' }}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span className={`badge ${t.priority === 'high' || t.priority === 'urgent' ? 'badge-warn' : 'badge-neutral'}`}>{t.status}</span>
                          {t.matched_in_conversation ? <span className="badge badge-muted" title="Matched inside a reply, not the initial ticket">via reply</span> : null}
                          <small style={{ color: 'var(--muted)' }}>#{t.ticket_id}</small>
                          {t.created_at ? <small style={{ color: 'var(--muted)' }}>{t.created_at.slice(0, 10)}</small> : null}
                        </div>
                        <div style={{ fontSize: 13, marginTop: 2 }}>{t.subject || '(no subject)'}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {data.samples.social.length > 0 ? (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Social sample ({data.samples.social.length} of {counts?.social_mentions ?? 0})
                  </div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {data.samples.social.map((s, i) => (
                      <li key={i} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px' }}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span className="badge badge-neutral">{s.platform}</span>
                          <span className={`badge ${s.sentiment === 'negative' ? 'badge-bad' : s.sentiment === 'positive' ? 'badge-good' : 'badge-muted'}`}>{s.sentiment}</span>
                          {s.published_at ? <small style={{ color: 'var(--muted)' }}>{s.published_at.slice(0, 10)}</small> : null}
                          {s.source_url ? <a href={s.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-muted">open</a> : null}
                        </div>
                        {s.title ? <div style={{ fontSize: 13, marginTop: 2, fontWeight: 500 }}>{s.title}</div> : null}
                        {s.body ? <div style={{ fontSize: 12, marginTop: 2, color: 'var(--muted)' }}>{s.body}</div> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {data.samples.reviews.length > 0 ? (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Reviews sample ({data.samples.reviews.length} of {counts?.review_mentions ?? 0})
                  </div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {data.samples.reviews.map((r, i) => (
                      <li key={i} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px' }}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span className="badge badge-neutral">{r.source}</span>
                          {r.rating != null ? <span className="badge badge-muted">★ {r.rating.toFixed(1)}</span> : null}
                          {r.sentiment ? <span className={`badge ${r.sentiment === 'negative' ? 'badge-bad' : r.sentiment === 'positive' ? 'badge-good' : 'badge-muted'}`}>{r.sentiment}</span> : null}
                          {r.published_at ? <small style={{ color: 'var(--muted)' }}>{r.published_at.slice(0, 10)}</small> : null}
                        </div>
                        <div style={{ fontSize: 12, marginTop: 2, color: 'var(--muted)' }}>{r.body}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {data.samples.community.length > 0 ? (
                <div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    Community sample ({data.samples.community.length} of {counts?.community_messages ?? 0})
                  </div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {data.samples.community.map((c, i) => (
                      <li key={i} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px' }}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span className="badge badge-neutral">{c.source}</span>
                          {c.channel ? <small style={{ color: 'var(--muted)' }}>#{c.channel}</small> : null}
                          {c.sentiment ? <span className={`badge ${c.sentiment === 'negative' ? 'badge-bad' : c.sentiment === 'positive' ? 'badge-good' : 'badge-muted'}`}>{c.sentiment}</span> : null}
                          {c.published_at ? <small style={{ color: 'var(--muted)' }}>{c.published_at.slice(0, 10)}</small> : null}
                        </div>
                        <div style={{ fontSize: 12, marginTop: 2, color: 'var(--muted)' }}>{c.body}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          )}
        </>
      ) : null}
      </>
      )}
    </section>
  )
}
