import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type {
  KlaviyoCampaignsRecent,
  KlaviyoFlowsStatus,
  KlaviyoListsAndSegments,
} from '../lib/api'

/**
 * Three cards that surface Klaviyo's marketing-side state on the
 * Marketing division page:
 *
 * - KlaviyoCampaignsCard — the last N email campaigns (status,
 *   scheduled_at, send_time). Useful for "did our Saturday newsletter
 *   actually go out?" at a glance.
 * - KlaviyoFlowsStatusCard — every configured flow with status (live
 *   / draft / manual), trigger type, last updated. Surfaces stalled
 *   drafts that should be tied off and the live automation set.
 * - KlaviyoListsSegmentsCard — every list and segment with current
 *   member count. Lets the team monitor roster health and spot lists
 *   that have grown or shrunk unexpectedly.
 *
 * All three back onto the new /api/klaviyo/* proxy endpoints which
 * cache their underlying Klaviyo calls for 30 min — the Marketing
 * data doesn't change minute-to-minute, but the live API calls are
 * slow and rate-limited.
 */

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function statusColor(status: string | null | undefined): string {
  if (!status) return 'var(--muted)'
  const s = status.toLowerCase()
  if (s === 'live' || s === 'sent' || s === 'sending') return 'var(--green)'
  if (s === 'draft' || s === 'scheduled') return 'var(--blue)'
  if (s === 'paused' || s === 'manual') return 'var(--orange)'
  if (s === 'cancelled' || s === 'archived') return 'var(--muted)'
  return 'var(--muted)'
}

/* ── Campaigns ───────────────────────────────────────────────────── */

export function KlaviyoCampaignsCard() {
  const [data, setData] = useState<KlaviyoCampaignsRecent | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoCampaignsRecent(25, ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Recent campaigns</strong></div>
      <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
    </section>
  )
  if (!data) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Recent campaigns</strong></div>
      <div className="state-message">Loading…</div>
    </section>
  )

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Recent campaigns</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Last 25 email campaigns scheduled or sent in the past 90 days.
          </div>
        </div>
      </div>

      {data.missing_scope ? (
        <div className="state-message" style={{ marginTop: 10, color: 'var(--orange)' }}>
          {data.note ?? `Klaviyo API key is missing the ${data.missing_scope} scope.`}
        </div>
      ) : data.campaigns.length === 0 ? (
        <div className="state-message" style={{ marginTop: 10 }}>No campaigns in the last 90 days.</div>
      ) : (
        <div style={{ marginTop: 10, overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                <th style={{ padding: '6px 8px' }}>Campaign</th>
                <th style={{ padding: '6px 8px' }}>Status</th>
                <th style={{ padding: '6px 8px' }}>Scheduled</th>
                <th style={{ padding: '6px 8px' }}>Sent</th>
              </tr>
            </thead>
            <tbody>
              {data.campaigns.map(c => (
                <tr key={c.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '6px 8px', maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.name ?? c.id}>
                    {c.name ?? <code>{c.id}</code>}
                  </td>
                  <td style={{ padding: '6px 8px', color: statusColor(c.status), fontWeight: 600 }}>
                    {c.status ?? '—'}
                  </td>
                  <td style={{ padding: '6px 8px', color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                    {fmtDate(c.scheduled_at)}
                  </td>
                  <td style={{ padding: '6px 8px', color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                    {fmtDate(c.send_time)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/* ── Flows ───────────────────────────────────────────────────────── */

export function KlaviyoFlowsStatusCard() {
  const [data, setData] = useState<KlaviyoFlowsStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoFlowsStatus(ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Flows</strong></div>
      <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
    </section>
  )
  if (!data) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Flows</strong></div>
      <div className="state-message">Loading…</div>
    </section>
  )

  const summary = Object.entries(data.by_status).sort(([, a], [, b]) => b - a)

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Flows</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Every configured automation. Live flows fire on triggers; drafts sit idle.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, fontSize: 11 }}>
          {summary.map(([s, n]) => (
            <span key={s} style={{
              padding: '2px 8px',
              borderRadius: 10,
              background: 'var(--panel-2)',
              color: statusColor(s),
              fontWeight: 600,
              textTransform: 'capitalize',
            }}>
              {s} {n}
            </span>
          ))}
        </div>
      </div>

      {data.missing_scope ? (
        <div className="state-message" style={{ marginTop: 10, color: 'var(--orange)' }}>
          {data.note ?? `Klaviyo API key is missing the ${data.missing_scope} scope.`}
        </div>
      ) : data.flows.length === 0 ? (
        <div className="state-message" style={{ marginTop: 10 }}>No flows configured.</div>
      ) : (
        <div style={{ marginTop: 10, maxHeight: 320, overflowY: 'auto' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--muted)', borderBottom: '1px solid rgba(255,255,255,0.08)', position: 'sticky', top: 0, background: 'var(--panel)' }}>
                <th style={{ padding: '6px 8px' }}>Flow</th>
                <th style={{ padding: '6px 8px' }}>Status</th>
                <th style={{ padding: '6px 8px' }}>Trigger</th>
                <th style={{ padding: '6px 8px' }}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {data.flows.map(f => (
                <tr key={f.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '6px 8px' }}>{f.name ?? <code>{f.id}</code>}</td>
                  <td style={{ padding: '6px 8px', color: statusColor(f.status), fontWeight: 600, textTransform: 'capitalize' }}>
                    {f.status ?? '—'}
                  </td>
                  <td style={{ padding: '6px 8px', color: 'var(--muted)' }}>{f.trigger_type ?? '—'}</td>
                  <td style={{ padding: '6px 8px', color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                    {fmtDate(f.updated)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/* ── Lists + Segments ────────────────────────────────────────────── */

export function KlaviyoListsSegmentsCard() {
  const [data, setData] = useState<KlaviyoListsAndSegments | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.klaviyoListsAndSegments(ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [])

  if (error) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Lists & segments</strong></div>
      <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
    </section>
  )
  if (!data) return (
    <section className="card">
      <div className="venom-panel-head"><strong>Lists & segments</strong></div>
      <div className="state-message">Loading…</div>
    </section>
  )

  const sortedLists = [...data.lists].sort((a, b) => (b.member_count ?? 0) - (a.member_count ?? 0))
  const sortedSegments = [...data.segments].sort((a, b) => (b.member_count ?? 0) - (a.member_count ?? 0))

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Lists & segments</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Lists are explicit subscriber rosters; segments are dynamic queries.
            Counts refresh every 30 min.
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16, marginTop: 10 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
            Lists ({data.lists.length})
          </div>
          <div style={{ fontSize: 12 }}>
            {sortedLists.map(l => (
              <div key={l.id} style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '4px 0',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
              }}>
                <span title={l.name ?? l.id}>{l.name ?? l.id}</span>
                <span style={{ color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                  {fmtInt(l.member_count)}
                </span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
            Segments ({data.segments.length})
          </div>
          <div style={{ fontSize: 12 }}>
            {sortedSegments.map(s => (
              <div key={s.id} style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '4px 0',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                opacity: s.is_active === false ? 0.5 : 1,
              }}>
                <span title={s.name ?? s.id}>
                  {s.name ?? s.id}
                  {s.is_processing ? <em style={{ color: 'var(--muted)', marginLeft: 6 }}>(processing)</em> : null}
                </span>
                <span style={{ color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
                  {fmtInt(s.member_count)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
