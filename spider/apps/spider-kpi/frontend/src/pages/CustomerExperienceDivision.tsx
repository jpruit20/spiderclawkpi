import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BarIndicator } from '../components/BarIndicator'
import { Card } from '../components/Card'
import { TruthBadge, TruthState } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { ApiError, api } from '../lib/api'
import { fmtInt } from '../lib/format'
import { CXActionItem, CXMetricItem, CXSnapshotResponse, KPIDaily, SocialPulse, SupportOverviewResponse } from '../lib/types'
import { LineChart, Line, ResponsiveContainer } from 'recharts'

/* ── helpers ── */

function pct(value: number, digits = 1) {
  return `${value.toFixed(digits)}%`
}

function hrs(value: number) {
  return `${value.toFixed(1)}h`
}

function whole(value: number) {
  return `${Math.round(value)}`
}

function statusTone(status: string) {
  if (status === 'red' || status === 'critical') return 'bad'
  if (status === 'yellow' || status === 'high') return 'warn'
  return 'good'
}

function metricValue(metric: CXMetricItem) {
  if (metric.key.includes('time')) return hrs(metric.current)
  if (metric.key.includes('rate') || metric.key.includes('pct') || metric.key.includes('burden') || metric.key.includes('sla')) return pct(metric.current)
  return whole(metric.current)
}

function metricTarget(metric: CXMetricItem) {
  if (metric.key.includes('time')) return hrs(metric.target)
  if (metric.key.includes('rate') || metric.key.includes('pct') || metric.key.includes('burden') || metric.key.includes('sla')) return pct(metric.target)
  return whole(metric.target)
}

function priorityScore(item: CXActionItem) {
  const base = item.priority === 'critical' ? 100 : item.priority === 'high' ? 70 : item.priority === 'medium' ? 40 : 20
  return base + (item.escalation_owner ? 20 : 0)
}

function priorityBadgeClass(priority: string) {
  if (priority === 'critical') return 'badge-bad'
  if (priority === 'high') return 'badge-warn'
  if (priority === 'medium') return 'badge-neutral'
  return 'badge-muted'
}

function statusBadgeClass(status: string) {
  if (status === 'resolved') return 'badge-good'
  if (status === 'in_progress') return 'badge-warn'
  return 'badge-neutral'
}

function trendDirection(trend7d: number): 'up' | 'down' | 'flat' {
  if (trend7d > 1) return 'up'
  if (trend7d < -1) return 'down'
  return 'flat'
}

const DRILL_ROUTES = [
  { path: '/issues', label: 'Issue Radar', icon: '\u26a0\ufe0f' },
  { path: '/friction', label: 'Friction Map', icon: '\ud83d\udcc9' },
  { path: '/root-cause', label: 'Root Cause', icon: '\ud83d\udd0d' },
]

/* ── page ── */

export function CustomerExperienceDivision() {
  const [snapshot, setSnapshot] = useState<CXSnapshotResponse | null>(null)
  const [socialPulse, setSocialPulse] = useState<SocialPulse | null>(null)
  const [supportOverview, setSupportOverview] = useState<SupportOverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [cxPayload, pulsePayload, supportPayload] = await Promise.all([
          api.cxSnapshot(),
          api.socialPulse(7).catch(() => null as SocialPulse | null),
          api.supportOverview().catch(() => null as SupportOverviewResponse | null),
        ])
        if (cancelled) return
        setSnapshot(cxPayload)
        setSocialPulse(pulsePayload)
        setSupportOverview(supportPayload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load customer experience division')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const headerMetrics = snapshot?.header_metrics || []
  const gridMetrics = snapshot?.grid_metrics || []
  const actions = useMemo(() => [...(snapshot?.actions || [])].sort((a, b) => priorityScore(b) - priorityScore(a)), [snapshot])
  const todayFocus = snapshot?.today_focus || []
  const teamLoad = snapshot?.team_load || []
  const rawInsights = snapshot?.insights || []
  const insights = useMemo(() => {
    if (rawInsights.length >= 2) return rawInsights
    const baseline = [
      ...rawInsights,
      ...(rawInsights.length < 1 ? [{
        text: `Support queue is ${(snapshot?.header_metrics?.find(m => m.key.includes('backlog'))?.current ?? 0) > 100 ? 'elevated' : 'within healthy range'} — monitor for trend changes.`,
        evidence: ['freshdesk'],
      }] : []),
      ...(rawInsights.length < 2 ? [{
        text: 'Review team load distribution for optimization opportunities.',
        evidence: ['freshdesk', 'internal'],
      }] : []),
    ]
    return baseline.slice(0, Math.max(rawInsights.length, 2))
  }, [rawInsights, snapshot])
  const snapshotTimestamp = snapshot?.snapshot_timestamp || 'n/a'

  /* Map header_metrics -> KpiCardDef[] */
  const kpiCards: KpiCardDef[] = headerMetrics.map((m) => ({
    label: m.label,
    value: metricValue(m),
    sub: `target ${metricTarget(m)}`,
    truthState: (m.confidence === 'low' ? 'estimated' : 'canonical') as TruthState,
    delta: {
      text: `7d ${m.trend7d > 0 ? '+' : ''}${m.trend7d.toFixed(1)}%`,
      direction: trendDirection(m.trend7d),
    },
  }))

  return (
    <div className="page-grid venom-page">
      {/* Header */}
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Customer Experience</h2>
          <p className="venom-subtitle">
            Jeremiah's team &mdash; snapshot {snapshotTimestamp}
          </p>
        </div>
      </div>

      {loading ? <Card title="Customer Experience"><div className="state-message">Loading customer experience division...</div></Card> : null}
      {error ? <Card title="Customer Experience Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          {/* Truth Legend */}
          <TruthLegend />

          {/* KPI Strip */}
          <VenomKpiStrip cards={kpiCards} cols={4} />

          {/* Two-col: Performance Metrics + Today's Focus */}
          <div className="two-col two-col-equal">
            {/* Left: Performance Metrics */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Performance Metrics</strong>
              </div>
              <div className="venom-breakdown-list">
                {gridMetrics.map((metric) => (
                  <div className="venom-breakdown-row" key={metric.key}>
                    <span className="venom-breakdown-label">{metric.label}</span>
                    <span className="venom-breakdown-val">{metricValue(metric)}</span>
                    <span className={`badge badge-${statusTone(metric.status)}`}>{metric.status}</span>
                    <span className={`venom-delta venom-delta-${trendDirection(metric.trend7d)}`}>
                      7d {metric.trend7d > 0 ? '+' : ''}{metric.trend7d.toFixed(1)}%
                    </span>
                  </div>
                ))}
                {!gridMetrics.length ? <div className="state-message">No performance metrics returned.</div> : null}
              </div>
            </section>

            {/* Right: Today's Focus */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Today's Focus</strong>
              </div>
              <div className="stack-list compact">
                {todayFocus.map((item) => (
                  <div className="list-item" key={item.id}>
                    <div className="item-head">
                      <strong>{item.title}</strong>
                      <span className={`badge ${priorityBadgeClass(item.priority)}`}>{item.priority}</span>
                    </div>
                    <p>{item.required_action}</p>
                    <small>Owner: {item.owner}</small>
                  </div>
                ))}
                {!todayFocus.length ? <div className="list-item status-good"><p>No open priority actions from the current daily snapshot.</p></div> : null}
              </div>
            </section>
          </div>

          {/* Action Queue (full width) */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Action Queue ({actions.length})</strong>
            </div>
            <div className="stack-list compact">
              {actions.map((item) => (
                <div className="list-item" key={item.id}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge ${priorityBadgeClass(item.priority)}`}>{item.priority}</span>
                      <span className={`badge ${statusBadgeClass(item.status)}`}>{item.status}</span>
                    </div>
                  </div>
                  <p>{item.required_action}</p>
                  <small>
                    Owner: {item.owner}
                    {item.co_owner ? ` · Co-owner: ${item.co_owner}` : ''}
                    {item.escalation_owner ? ` · Escalation: ${item.escalation_owner}` : ''}
                  </small>
                </div>
              ))}
              {!actions.length ? <div className="list-item status-good"><p>No actions in queue.</p></div> : null}
            </div>
          </section>

          {/* Two-col: Team Load + Insights */}
          <div className="two-col two-col-equal">
            {/* Left: Team Load */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Team Load</strong>
              </div>
              <div className="venom-bar-list">
                {teamLoad.map((rep) => (
                  <div key={rep.name}>
                    <div className="venom-bar-row">
                      <span className="venom-breakdown-label">{rep.name}</span>
                      <BarIndicator
                        value={rep.share_pct}
                        max={50}
                        color={rep.share_pct >= 50 ? 'var(--red)' : rep.share_pct >= 35 ? 'var(--orange)' : 'var(--green)'}
                      />
                      <span className="venom-breakdown-val">{rep.share_pct.toFixed(1)}%</span>
                    </div>
                    <small style={{ paddingLeft: 4, opacity: 0.7 }}>
                      closed/day: {rep.tickets_closed_per_day.toFixed(1)} | queue: {rep.active_queue_size} | reopen: {rep.reopen_rate.toFixed(1)}%
                    </small>
                  </div>
                ))}
                {!teamLoad.length ? <div className="state-message">No team load data returned.</div> : null}
              </div>
            </section>

            {/* Right: Insights */}
            <section className="card">
              <div className="venom-panel-head">
                <strong>Insights</strong>
              </div>
              <div className="stack-list compact">
                {insights.map((item, idx) => (
                  <div className="list-item status-muted" key={idx}>
                    <p>{item.text}</p>
                    <div className="inline-badges">
                      {item.evidence.map((ev, evIdx) => (
                        <span className="badge badge-neutral" key={evIdx}>{ev}</span>
                      ))}
                    </div>
                  </div>
                ))}
                {!insights.length ? <div className="list-item status-muted"><p>No multi-signal insights triggered from the current snapshot.</p></div> : null}
              </div>
            </section>
          </div>

          {/* Queue Health Trend */}
          {(() => {
            const supportRows = (supportOverview?.rows || []) as KPIDaily[]
            const last7Support = supportRows.slice(-7)
            if (last7Support.length === 0) return null
            const sparkData = last7Support.map((r) => ({ date: r.business_date?.slice(5) || '', backlog: Number(r.open_backlog) || 0 }))
            return (
              <section className="card">
                <div className="venom-panel-head">
                  <strong>Queue Health Trend</strong>
                  <span className="venom-panel-hint">Last 7 days — open backlog</span>
                </div>
                <ResponsiveContainer width="100%" height={60}>
                  <LineChart data={sparkData}>
                    <Line type="monotone" dataKey="backlog" stroke="var(--blue)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </section>
            )
          })()}

          {/* Social Listening — Brand Pulse */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Social Listening — Brand Pulse</strong>
              <span className="venom-panel-hint">Last 7 days</span>
            </div>
            {socialPulse ? (
              <>
                <div className="venom-social-stat">
                  <div className="venom-social-stat-item">
                    <small>Total Mentions</small>
                    <strong>{fmtInt(socialPulse.total_mentions)}</strong>
                  </div>
                  <div className="venom-social-stat-item">
                    <small>Brand Mentions</small>
                    <strong>{fmtInt(socialPulse.brand_mentions)}</strong>
                  </div>
                  <div className="venom-social-stat-item">
                    <small>Avg Sentiment</small>
                    <strong>{(socialPulse.avg_sentiment_score ?? 0) >= 0 ? '+' : ''}{(socialPulse.avg_sentiment_score ?? 0).toFixed(2)}</strong>
                  </div>
                </div>
                {socialPulse.top_mentions.length > 0 ? (
                  <div className="stack-list compact">
                    {socialPulse.top_mentions.slice(0, 5).map((mention) => (
                      <div className={`list-item ${mention.sentiment === 'positive' ? 'status-good' : mention.sentiment === 'negative' ? 'status-bad' : 'status-warn'}`} key={mention.external_id || mention.id}>
                        <div className="item-head">
                          <strong>{mention.title || 'Untitled mention'}</strong>
                          <div className="inline-badges">
                            <span className="badge badge-neutral">{mention.platform}</span>
                            {mention.subreddit ? <span className="badge badge-muted">r/{mention.subreddit}</span> : null}
                            <span className="badge badge-neutral">engagement {mention.engagement_score}</span>
                          </div>
                        </div>
                        {mention.body ? (
                          <div className="venom-mention-body">
                            {mention.body.length > 150 ? `${mention.body.slice(0, 150)}...` : mention.body}
                          </div>
                        ) : null}
                        {mention.source_url ? (
                          <div className="venom-mention-meta">
                            <a href={mention.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">View source</a>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="state-message">No top mentions in the current window</div>
                )}
              </>
            ) : (
              <div className="state-message">Social listening will populate after first Reddit sync</div>
            )}
          </section>

          {/* Navigation tiles */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Drill-down routes</strong>
              <span className="venom-panel-hint">Click to explore</span>
            </div>
            <div className="venom-drill-grid">
              {DRILL_ROUTES.map((route) => (
                <Link key={route.path} to={route.path} className="venom-drill-tile">
                  <span className="venom-drill-icon">{route.icon}</span>
                  <div>
                    <strong>{route.label}</strong>
                    <small>{route.path}</small>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
