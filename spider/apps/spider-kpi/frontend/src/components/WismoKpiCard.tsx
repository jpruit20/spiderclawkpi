import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Line, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, ComposedChart, Bar } from 'recharts'
import { api } from '../lib/api'
import { formatFreshness } from '../lib/format'
import { DailyHeatmap } from './tiles'
import type { WismoKpiResponse } from '../lib/types'

/**
 * WISMO KPI — "Where is my order?" follow-up ticket count.
 *
 * Thesis (from Joseph, 2026-04-18): customers should not be reaching
 * out to ask where their order is. Every WISMO ticket represents a
 * communication gap — we should have proactively told them about
 * shipment status, tracking, delays, ETAs. Target is zero.
 *
 * Trend arrow vs. prior 7-day period; lower is better, so a negative
 * delta is the green "good" colour here.
 */
export function WismoKpiCard({ days = 30 }: { days?: number }) {
  const [data, setData] = useState<WismoKpiResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.wismoKpi(days)
      .then(r => { if (!cancelled) setData(r) })
      .catch(() => { /* silent */ })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [days])

  if (loading) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>WISMO follow-ups (target: 0)</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }
  if (!data || !data.ok) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>WISMO follow-ups (target: 0)</strong></div>
        <div className="state-message">No data yet.</div>
      </section>
    )
  }

  const wow = data.week_over_week
  // For WISMO, LOWER is better. Flip the colour logic.
  const deltaPct = wow.delta_pct
  const deltaColor = deltaPct == null
    ? 'var(--muted)'
    : deltaPct <= 0 ? 'var(--green)' : 'var(--red)'
  const deltaPrefix = deltaPct == null ? '' : deltaPct > 0 ? '+' : ''

  // Colour rate-per-100 by severity. Anything over ~5/100 orders means
  // one in twenty customers is chasing their order — unacceptable.
  const rate = data.rate_per_100_orders ?? 0
  const rateColor = rate >= 5 ? 'var(--red)' : rate >= 2 ? 'var(--orange)' : rate > 0 ? 'var(--blue)' : 'var(--green)'

  return (
    <section className="card" style={{ borderLeft: '3px solid var(--orange)' }}>
      <div className="venom-panel-head" style={{ alignItems: 'center' }}>
        <div>
          <strong>WISMO follow-ups — target: 0</strong>
          {expanded ? (
            <p className="venom-chart-sub">
              Customers reaching out asking "where is my order?" in the last {data.window_days} days.
              Every ticket = a proactive-comms opportunity we missed.
            </p>
          ) : null}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="venom-panel-hint">{data.tickets_in_window} total tickets in window</span>
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
            title={expanded ? 'Collapse detail' : 'Show trend chart, daily pattern, and recent tickets'}
          >
            {expanded ? 'Hide detail ▲' : 'Show detail ▼'}
          </button>
        </div>
      </div>

      <div className="venom-kpi-strip" style={{ marginBottom: 12 }}>
        <div className="venom-kpi-card">
          <div className="venom-kpi-label">WISMO tickets ({data.window_days}d)</div>
          <div className="venom-kpi-value" style={{ color: rateColor }}>
            {data.wismo_count}
          </div>
          <div className="venom-kpi-sub">
            {data.wismo_pct_of_tickets}% of all tickets
          </div>
        </div>
        <div className="venom-kpi-card">
          <div className="venom-kpi-label">Rate per 100 orders</div>
          <div className="venom-kpi-value" style={{ color: rateColor }}>
            {data.rate_per_100_orders != null ? data.rate_per_100_orders.toFixed(1) : '—'}
          </div>
          <div className="venom-kpi-sub">
            {data.orders_in_window.toLocaleString()} orders in window
          </div>
        </div>
        <div className="venom-kpi-card">
          <div className="venom-kpi-label">Week-over-week</div>
          <div className="venom-kpi-value" style={{ color: deltaColor, fontSize: 18 }}>
            {wow.last_7} <span style={{ color: 'var(--muted)', fontSize: 12 }}>vs {wow.prior_7}</span>
          </div>
          <div className="venom-kpi-sub" style={{ color: deltaColor }}>
            {deltaPct == null ? 'n/a' : `${deltaPrefix}${deltaPct.toFixed(0)}% ${deltaPct < 0 ? '(down — good)' : deltaPct > 0 ? '(up — bad)' : ''}`}
          </div>
        </div>
      </div>

      {expanded && data.trend.length > 0 && (
        <div style={{ marginBottom: 12, display: 'grid', gridTemplateColumns: '1fr auto', gap: 16, alignItems: 'center' }}>
          {/* Left: daily bar chart (quantitative trend). */}
          <div className="chart-wrap" style={{ margin: 0 }}>
            <ResponsiveContainer width="100%" height={120}>
              <ComposedChart data={data.trend}>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="var(--muted)" tickFormatter={(d: string) => (d || '').slice(5)} />
                <YAxis tick={{ fontSize: 10 }} stroke="var(--muted)" allowDecimals={false} />
                <Tooltip contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }} />
                <Bar name="WISMO tickets" dataKey="wismo" fill="var(--orange)" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {/* Right: calendar-style heatmap (pattern — which days? weekends?). */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.4 }}>
              Daily pattern
            </div>
            <DailyHeatmap
              days={data.trend.map(d => ({ date: d.date, value: d.wismo }))}
              color="#f59e0b"
              cellSize={11}
              labelFormatter={(c) => `${c.date}: ${c.value} WISMO ticket${c.value === 1 ? '' : 's'}`}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'var(--muted)' }}>
              <span>less</span>
              <div style={{ display: 'flex', gap: 2 }}>
                <span style={{ width: 10, height: 10, background: 'rgba(255,255,255,0.05)', borderRadius: 2 }} />
                <span style={{ width: 10, height: 10, background: '#f59e0b', opacity: 0.3, borderRadius: 2 }} />
                <span style={{ width: 10, height: 10, background: '#f59e0b', opacity: 0.5, borderRadius: 2 }} />
                <span style={{ width: 10, height: 10, background: '#f59e0b', opacity: 0.75, borderRadius: 2 }} />
                <span style={{ width: 10, height: 10, background: '#f59e0b', opacity: 1, borderRadius: 2 }} />
              </div>
              <span>more</span>
            </div>
          </div>
        </div>
      )}

      {expanded && data.recent_tickets.length > 0 && (
        <div>
          <div className="venom-breakdown-label">Recent WISMO tickets — click through to Freshdesk</div>
          <div className="stack-list compact">
            {data.recent_tickets.map(t => {
              const content = (
                <>
                  <div className="item-head">
                    <strong style={{ fontSize: 12 }}>{t.subject || '(no subject)'}</strong>
                    <div className="inline-badges">
                      <span className="badge badge-muted" style={{ fontSize: 10 }}>
                        {Math.round((t.confidence || 0) * 100)}%
                      </span>
                      {t.status && <span className="badge badge-neutral" style={{ fontSize: 10 }}>{t.status}</span>}
                    </div>
                  </div>
                  <p style={{ fontSize: 11, color: 'var(--muted)' }}>
                    #{t.ticket_id} · {t.created_at ? formatFreshness(t.created_at) : 'no date'}
                    {t.matched_rule && <> · rule: <code style={{ background: 'rgba(255,255,255,0.05)', padding: '1px 4px', borderRadius: 3, fontSize: 10 }}>{t.matched_rule.slice(0, 60)}</code></>}
                  </p>
                </>
              )
              if (t.url) {
                return (
                  <a key={t.ticket_id} href={t.url} target="_blank" rel="noopener noreferrer" className="list-item status-warn" style={{ textDecoration: 'none', color: 'inherit' }}>
                    {content}
                  </a>
                )
              }
              return <div key={t.ticket_id} className="list-item status-warn">{content}</div>
            })}
          </div>
        </div>
      )}

      {expanded ? (
        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)' }}>
          <strong>Working toward zero:</strong> proactive shipping notifications (tracking updates before customers ask), ETA visibility in the app, automated comms on transit delays. Every ticket here is a chance to ship a communication earlier next time.
        </div>
      ) : null}
    </section>
  )
}
