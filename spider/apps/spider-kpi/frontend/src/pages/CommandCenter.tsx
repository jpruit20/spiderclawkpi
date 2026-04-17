import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import { ApiError, api } from '../lib/api'
import { currency, fmtInt, fmtPct, formatFreshness } from '../lib/format'
import type { MorningBriefResponse } from '../lib/types'

/**
 * Executive morning brief — "coffee in hand, 8am, what needs my attention."
 * Aggregates the top items from every integrated source into a single
 * scrollable view. Pure synthesis of already-materialized data.
 */
export function CommandCenter() {
  const [data, setData] = useState<MorningBriefResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.morningBrief()
      .then(r => { if (!cancelled) setData(r) })
      .catch(err => { if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load morning brief') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  if (loading) return <div className="page-grid"><section className="card"><div className="state-message">Loading morning brief…</div></section></div>
  if (error || !data) return <div className="page-grid"><section className="card"><div className="state-message error">{error || 'No data'}</div></section></div>

  const h = data.headline
  const revWoWColor = h.revenue_wow_pct == null ? 'var(--muted)' : h.revenue_wow_pct >= 0 ? 'var(--green)' : 'var(--red)'
  const veloWoWColor = h.clickup_wow_delta === 0 ? 'var(--muted)' : h.clickup_wow_delta > 0 ? 'var(--green)' : 'var(--red)'

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Good morning — here's what needs you</h2>
        <p>As of {new Date(data.generated_at).toLocaleString()}. One screen, everything material.</p>
      </div>

      <section className="card">
        <div className="venom-panel-head">
          <strong>Overnight at a glance</strong>
          <span className="venom-panel-hint">{data.business_date}</span>
        </div>
        <div className="venom-kpi-strip">
          <div className="venom-kpi">
            <div className="venom-kpi-label">Drafts to review</div>
            <div className="venom-kpi-value" style={{ color: h.drafts_awaiting_review > 0 ? 'var(--blue)' : 'var(--muted)' }}>
              {fmtInt(h.drafts_awaiting_review)}
            </div>
          </div>
          <div className="venom-kpi">
            <div className="venom-kpi-label">Critical signals (24h)</div>
            <div className="venom-kpi-value" style={{ color: h.critical_signals_24h > 0 ? 'var(--red)' : 'var(--muted)' }}>
              {fmtInt(h.critical_signals_24h)}
            </div>
          </div>
          <div className="venom-kpi">
            <div className="venom-kpi-label">Overdue urgent/high</div>
            <div className="venom-kpi-value" style={{ color: h.overdue_urgent_or_high > 0 ? 'var(--red)' : 'var(--muted)' }}>
              {fmtInt(h.overdue_urgent_or_high)}
            </div>
          </div>
          <div className="venom-kpi">
            <div className="venom-kpi-label">Revenue WoW</div>
            <div className="venom-kpi-value" style={{ color: revWoWColor }}>
              {h.revenue_wow_pct == null ? '—' : `${h.revenue_wow_pct >= 0 ? '+' : ''}${h.revenue_wow_pct.toFixed(0)}%`}
            </div>
          </div>
          <div className="venom-kpi">
            <div className="venom-kpi-label">Tasks closed WoW</div>
            <div className="venom-kpi-value" style={{ color: veloWoWColor }}>
              {h.clickup_wow_delta >= 0 ? '+' : ''}{h.clickup_wow_delta}
            </div>
          </div>
        </div>
      </section>

      {data.drafts.length > 0 && (
        <section className="card" style={{ borderLeft: '3px solid var(--blue)' }}>
          <div className="venom-panel-head">
            <strong>Drafts awaiting your review ({h.drafts_awaiting_review})</strong>
            <Link to="/deci" className="analysis-link">Open DECI ↗</Link>
          </div>
          <div className="stack-list compact">
            {data.drafts.map(d => (
              <Link key={d.id} to="/deci" className="list-item status-neutral" style={{ textDecoration: 'none', color: 'inherit' }}>
                <div className="item-head">
                  <strong style={{ fontSize: 13 }}>{d.title}</strong>
                  <div className="inline-badges">
                    {d.origin_signal_type && (
                      <span className="badge badge-muted" style={{ fontSize: 10 }}>
                        {d.origin_signal_type.split('.')[0]}
                      </span>
                    )}
                    <span className="badge badge-neutral" style={{ fontSize: 10 }}>{d.priority}</span>
                    {d.department && (
                      <span className="badge badge-muted" style={{ fontSize: 10 }}>{d.department}</span>
                    )}
                  </div>
                </div>
                {d.auto_drafted_at && (
                  <p style={{ fontSize: 11, color: 'var(--muted)' }}>auto-drafted {formatFreshness(d.auto_drafted_at)}</p>
                )}
              </Link>
            ))}
          </div>
        </section>
      )}

      {(data.critical_signals.length > 0 || data.stale_tasks.length > 0) && (
        <div className="two-col two-col-equal">
          {data.critical_signals.length > 0 && (
            <section className="card" style={{ borderLeft: '3px solid var(--red)' }}>
              <div className="venom-panel-head">
                <strong>Critical signals — last 24h</strong>
                <Link to="/issues" className="analysis-link">Issue Radar ↗</Link>
              </div>
              <div className="stack-list compact">
                {data.critical_signals.map(s => {
                  const content = (
                    <>
                      <div className="item-head">
                        <strong style={{ fontSize: 12 }}>{(s.title || '').slice(0, 100)}</strong>
                        <span className="badge badge-bad" style={{ fontSize: 10 }}>{s.source}</span>
                      </div>
                      <p style={{ fontSize: 11 }}>
                        {(s.summary || '').slice(0, 140)}
                        {s.created_at && <span style={{ color: 'var(--muted)', marginLeft: 6 }}>· {formatFreshness(s.created_at)}</span>}
                      </p>
                    </>
                  )
                  if (s.metadata.url) {
                    return (
                      <a key={s.id} href={s.metadata.url} target="_blank" rel="noopener noreferrer" className="list-item status-bad" style={{ textDecoration: 'none', color: 'inherit' }}>
                        {content}
                      </a>
                    )
                  }
                  return <div key={s.id} className="list-item status-bad">{content}</div>
                })}
              </div>
            </section>
          )}

          {data.stale_tasks.length > 0 && (
            <section className="card" style={{ borderLeft: '3px solid var(--orange)' }}>
              <div className="venom-panel-head">
                <strong>Overdue urgent/high tasks</strong>
                <span className="venom-panel-hint">ClickUp</span>
              </div>
              <div className="stack-list compact">
                {data.stale_tasks.map(t => (
                  <a key={t.task_id} href={t.url || '#'} target="_blank" rel="noopener noreferrer" className={`list-item status-${t.priority === 'urgent' ? 'bad' : 'warn'}`} style={{ textDecoration: 'none', color: 'inherit' }}>
                    <div className="item-head">
                      <strong style={{ fontSize: 12 }}>{(t.name || '(untitled)').slice(0, 100)}</strong>
                      <div className="inline-badges">
                        <span className={`badge ${t.priority === 'urgent' ? 'badge-bad' : 'badge-warn'}`} style={{ fontSize: 10 }}>{t.priority}</span>
                        <span className="badge badge-bad" style={{ fontSize: 10 }}>{t.days_overdue}d overdue</span>
                      </div>
                    </div>
                    <p style={{ fontSize: 11 }}>
                      {[t.space_name, t.list_name].filter(Boolean).join(' · ')}
                      {t.assignees.length > 0 && ` · ${t.assignees.filter(Boolean).join(', ')}`}
                    </p>
                  </a>
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      <div className="two-col two-col-equal">
        <section className="card">
          <div className="venom-panel-head">
            <strong>Revenue trailing 7 days</strong>
            <Link to="/revenue" className="analysis-link">Details ↗</Link>
          </div>
          <div className="venom-kpi-strip" style={{ marginBottom: 10 }}>
            <div className="venom-kpi">
              <div className="venom-kpi-label">Last 7d</div>
              <div className="venom-kpi-value">{currency(data.revenue.trailing_7)}</div>
            </div>
            <div className="venom-kpi">
              <div className="venom-kpi-label">Prior 7d</div>
              <div className="venom-kpi-value" style={{ color: 'var(--muted)' }}>{currency(data.revenue.prior_7)}</div>
            </div>
            <div className="venom-kpi">
              <div className="venom-kpi-label">Delta</div>
              <div className="venom-kpi-value" style={{ color: revWoWColor }}>
                {data.revenue.wow_delta >= 0 ? '+' : ''}{currency(data.revenue.wow_delta)}
                {data.revenue.wow_pct != null && (
                  <span style={{ fontSize: 12, marginLeft: 6 }}>({data.revenue.wow_pct >= 0 ? '+' : ''}{data.revenue.wow_pct.toFixed(0)}%)</span>
                )}
              </div>
            </div>
          </div>
          {data.revenue.sparkline.length > 0 && (
            <ResponsiveContainer width="100%" height={60}>
              <LineChart data={data.revenue.sparkline}>
                <Line type="monotone" dataKey="revenue" stroke="var(--green)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </section>

        {data.telemetry && (
          <section className="card">
            <div className="venom-panel-head">
              <strong>Fleet telemetry — {data.telemetry.business_date}</strong>
              <Link to="/division/product-engineering" className="analysis-link">Product/Eng ↗</Link>
            </div>
            <div className="venom-bar-list">
              <div className="venom-breakdown-row">
                <span className="venom-bar-label">Active devices</span>
                <span className="venom-breakdown-val">{fmtInt(data.telemetry.active_devices)}</span>
                <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtInt(data.telemetry.engaged_devices)} cooking</span>
              </div>
              <div className="venom-breakdown-row">
                <span className="venom-bar-label">Cook success rate</span>
                <span className="venom-breakdown-val" style={{
                  color: data.telemetry.cook_success_rate != null
                    ? (data.telemetry.cook_success_rate >= 0.85 ? 'var(--green)' : data.telemetry.cook_success_rate >= 0.7 ? 'var(--orange)' : 'var(--red)')
                    : 'var(--muted)'
                }}>
                  {data.telemetry.cook_success_rate != null ? fmtPct(data.telemetry.cook_success_rate) : '—'}
                </span>
                <span style={{ color: 'var(--muted)', fontSize: 11 }}>of {fmtInt(data.telemetry.session_count || 0)} sessions</span>
              </div>
              <div className="venom-breakdown-row">
                <span className="venom-bar-label">Error rate</span>
                <span className="venom-breakdown-val" style={{
                  color: data.telemetry.error_rate != null
                    ? (data.telemetry.error_rate >= 0.05 ? 'var(--red)' : data.telemetry.error_rate >= 0.02 ? 'var(--orange)' : 'var(--green)')
                    : 'var(--muted)'
                }}>
                  {data.telemetry.error_rate != null ? fmtPct(data.telemetry.error_rate) : '—'}
                </span>
                <span style={{ color: 'var(--muted)', fontSize: 11 }}>{fmtInt(data.telemetry.error_events)} of {fmtInt(data.telemetry.total_events)} events</span>
              </div>
            </div>
          </section>
        )}
      </div>

      <div className="two-col two-col-equal">
        <section className="card">
          <div className="venom-panel-head">
            <strong>ClickUp velocity — last 7d</strong>
            <Link to="/division/product-engineering" className="analysis-link">Details ↗</Link>
          </div>
          <div className="venom-kpi-strip">
            <div className="venom-kpi">
              <div className="venom-kpi-label">Closed</div>
              <div className="venom-kpi-value">{fmtInt(data.clickup_velocity.closed_last_7)}</div>
              <div className="venom-kpi-trend" style={{ color: veloWoWColor }}>
                {data.clickup_velocity.wow_delta >= 0 ? '+' : ''}{data.clickup_velocity.wow_delta} vs prior 7
              </div>
            </div>
            <div className="venom-kpi">
              <div className="venom-kpi-label">Prior 7d</div>
              <div className="venom-kpi-value" style={{ color: 'var(--muted)' }}>{fmtInt(data.clickup_velocity.closed_prior_7)}</div>
            </div>
          </div>
          {data.compliance && data.compliance.taxonomy_configured && (
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Tagging compliance</div>
              <div className="venom-breakdown-row">
                <span className="venom-bar-label">Closed + tagged (14d)</span>
                <span className="venom-breakdown-val" style={{
                  color: data.compliance.rate_closed_in_window == null ? 'var(--muted)' :
                    data.compliance.rate_closed_in_window >= 0.9 ? 'var(--green)' :
                    data.compliance.rate_closed_in_window >= 0.7 ? 'var(--orange)' : 'var(--red)'
                }}>
                  {data.compliance.rate_closed_in_window != null ? fmtPct(data.compliance.rate_closed_in_window) : '—'}
                </span>
                {data.compliance.wow_delta_rate != null && (
                  <span style={{ color: data.compliance.wow_delta_rate >= 0 ? 'var(--green)' : 'var(--red)', fontSize: 11 }}>
                    {data.compliance.wow_delta_rate >= 0 ? '+' : ''}{(data.compliance.wow_delta_rate * 100).toFixed(0)}pp
                  </span>
                )}
              </div>
            </div>
          )}
          {data.compliance && !data.compliance.taxonomy_configured && (
            <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
              Taxonomy not yet configured — <Link to="/division/product-engineering" className="analysis-link">setup runbook</Link>
            </div>
          )}
        </section>

        {data.slack_hot && (
          <section className="card">
            <div className="venom-panel-head">
              <strong>Hottest Slack thread — last 24h</strong>
              <span className="venom-panel-hint">{data.slack_hot.reactions} reactions</span>
            </div>
            <div className="list-item status-muted">
              <div className="item-head">
                <strong style={{ fontSize: 12 }}>{data.slack_hot.user_name || '?'}</strong>
                {data.slack_hot.ts_dt && (
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>{formatFreshness(data.slack_hot.ts_dt)}</span>
                )}
              </div>
              <p style={{ fontSize: 11 }}>{data.slack_hot.text}</p>
            </div>
          </section>
        )}
      </div>

      <section className="card">
        <div className="venom-panel-head">
          <strong>Jump into a division</strong>
        </div>
        <div className="venom-drill-grid">
          <Link to="/division/product-engineering" className="venom-drill-tile">
            <span className="venom-drill-icon">⚙</span>
            <div><strong>Product / Engineering</strong><small>Telemetry, firmware, NPD</small></div>
          </Link>
          <Link to="/division/customer-experience" className="venom-drill-tile">
            <span className="venom-drill-icon">☎</span>
            <div><strong>Customer Experience</strong><small>Support, complaints, CSAT</small></div>
          </Link>
          <Link to="/division/marketing" className="venom-drill-tile">
            <span className="venom-drill-icon">📣</span>
            <div><strong>Marketing</strong><small>Campaigns, content, ads</small></div>
          </Link>
          <Link to="/division/operations" className="venom-drill-tile">
            <span className="venom-drill-icon">📦</span>
            <div><strong>Operations</strong><small>Inventory, fulfillment</small></div>
          </Link>
          <Link to="/deci" className="venom-drill-tile">
            <span className="venom-drill-icon">✓</span>
            <div><strong>DECI</strong><small>Decision tracking</small></div>
          </Link>
          <Link to="/issues" className="venom-drill-tile">
            <span className="venom-drill-icon">⚠</span>
            <div><strong>Issue Radar</strong><small>Cross-source signals</small></div>
          </Link>
        </div>
      </section>
    </div>
  )
}
