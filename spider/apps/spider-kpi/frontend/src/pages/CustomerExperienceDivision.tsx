import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BarIndicator } from '../components/BarIndicator'
import { Card } from '../components/Card'
import { TruthBadge, TruthState } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { ApiError, api } from '../lib/api'
import { fmtInt } from '../lib/format'
import { CXActionItem, CXMetricItem, CXSnapshotResponse, FreshdeskTicketItem, IssueRadarResponse, KPIDaily, SocialPulse, SupportOverviewResponse } from '../lib/types'
import { LineChart, Line, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell } from 'recharts'

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
  // Time-based metrics (display as hours)
  if (metric.key.includes('time') || metric.key.includes('response')) return hrs(metric.current)
  // Percentage and rate metrics
  if (metric.key.includes('rate') || metric.key.includes('pct') || metric.key.includes('burden') || metric.key.includes('sla')) return pct(metric.current)
  // Engagement depth (display with decimal)
  if (metric.key.includes('engagement') || metric.key.includes('depth')) return metric.current.toFixed(1)
  // Whole number metrics (ticket counts, etc)
  return whole(metric.current)
}

function metricTarget(metric: CXMetricItem) {
  // Time-based metrics (display as hours)
  if (metric.key.includes('time') || metric.key.includes('response')) return hrs(metric.target)
  // Percentage and rate metrics
  if (metric.key.includes('rate') || metric.key.includes('pct') || metric.key.includes('burden') || metric.key.includes('sla')) return pct(metric.target)
  // Engagement depth (display with decimal)
  if (metric.key.includes('engagement') || metric.key.includes('depth')) return metric.target.toFixed(1)
  // Whole number metrics (ticket counts, etc)
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
  const [tickets, setTickets] = useState<FreshdeskTicketItem[]>([])
  const [frictionData, setFrictionData] = useState<IssueRadarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [cxPayload, pulsePayload, supportPayload, ticketsPayload, frictionPayload] = await Promise.all([
          api.cxSnapshot(),
          api.socialPulse(7).catch(() => null as SocialPulse | null),
          api.supportOverview().catch(() => null as SupportOverviewResponse | null),
          api.supportTickets().catch(() => [] as FreshdeskTicketItem[]),
          api.issues().catch(() => null as IssueRadarResponse | null),
        ])
        if (cancelled) return
        setSnapshot(cxPayload)
        setSocialPulse(pulsePayload)
        setSupportOverview(supportPayload)
        setTickets(ticketsPayload)
        setFrictionData(frictionPayload)
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

  /* Compute Resolution Time Distribution */
  const resolutionDistribution = useMemo(() => {
    const buckets = [
      { label: '<4h', min: 0, max: 4, count: 0, color: '#39d08f' },
      { label: '4-24h', min: 4, max: 24, count: 0, color: '#6ea8ff' },
      { label: '24-48h', min: 24, max: 48, count: 0, color: '#ffb257' },
      { label: '>48h', min: 48, max: Infinity, count: 0, color: '#ff6d7a' },
    ]
    tickets.forEach((ticket) => {
      const hours = ticket.resolution_hours || 0
      if (hours <= 0) return
      for (const bucket of buckets) {
        if (hours > bucket.min && hours <= bucket.max) {
          bucket.count += 1
          break
        }
      }
    })
    const total = buckets.reduce((sum, b) => sum + b.count, 0)
    return buckets.map((b) => ({ ...b, pct: total > 0 ? (b.count / total) * 100 : 0 }))
  }, [tickets])

  /* Compute Channel Breakdown */
  const channelBreakdown = useMemo(() => {
    const channelMap = new Map<string, { count: number; resolved: number }>()
    tickets.forEach((ticket) => {
      const channel = ticket.channel || 'unknown'
      if (!channelMap.has(channel)) channelMap.set(channel, { count: 0, resolved: 0 })
      const row = channelMap.get(channel)!
      row.count += 1
      if (ticket.resolved_at_source) row.resolved += 1
    })
    const total = Array.from(channelMap.values()).reduce((sum, v) => sum + v.count, 0)
    return Array.from(channelMap.entries())
      .map(([channel, data]) => ({
        channel,
        count: data.count,
        resolved: data.resolved,
        resolutionRate: data.count > 0 ? (data.resolved / data.count) * 100 : 0,
        pct: total > 0 ? (data.count / total) * 100 : 0,
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5)
  }, [tickets])

  /* Compute Ticket Aging Heatmap */
  const ticketAging = useMemo(() => {
    const now = new Date()
    const buckets = [
      { label: '1 day', maxDays: 1, count: 0, severity: 'low' },
      { label: '2-3 days', maxDays: 3, count: 0, severity: 'medium' },
      { label: '4-7 days', maxDays: 7, count: 0, severity: 'high' },
      { label: '>7 days', maxDays: Infinity, count: 0, severity: 'critical' },
    ]
    const openTickets = tickets.filter((t) => !t.resolved_at_source)
    openTickets.forEach((ticket) => {
      const created = ticket.created_at_source ? new Date(ticket.created_at_source) : null
      if (!created) return
      const ageDays = Math.floor((now.getTime() - created.getTime()) / (1000 * 60 * 60 * 24))
      for (let i = 0; i < buckets.length; i++) {
        if (ageDays <= buckets[i].maxDays || i === buckets.length - 1) {
          buckets[i].count += 1
          break
        }
      }
    })
    return buckets
  }, [tickets])

  /* Compute SLA Breach Countdown */
  const slaBreachCountdown = useMemo(() => {
    const now = new Date()
    const SLA_HOURS = 24 // Assume 24h SLA
    const countdowns = { in2h: 0, in4h: 0, in8h: 0, breached: 0 }
    const openTickets = tickets.filter((t) => !t.resolved_at_source)
    openTickets.forEach((ticket) => {
      const created = ticket.created_at_source ? new Date(ticket.created_at_source) : null
      if (!created) return
      const ageHours = (now.getTime() - created.getTime()) / (1000 * 60 * 60)
      const hoursUntilBreach = SLA_HOURS - ageHours
      if (hoursUntilBreach <= 0) countdowns.breached += 1
      else if (hoursUntilBreach <= 2) countdowns.in2h += 1
      else if (hoursUntilBreach <= 4) countdowns.in4h += 1
      else if (hoursUntilBreach <= 8) countdowns.in8h += 1
    })
    return countdowns
  }, [tickets])

  /* Generate Social Pulse Actions */
  const socialActions = useMemo(() => {
    if (!socialPulse) return []
    const negativeHighEngagement = socialPulse.top_mentions
      .filter((m) => m.sentiment === 'negative' && m.engagement_score >= 50)
      .slice(0, 3)
    return negativeHighEngagement.map((mention) => ({
      id: `social-${mention.id}`,
      title: `High-engagement negative mention: ${mention.title || 'Untitled'}`,
      platform: mention.platform,
      engagement: mention.engagement_score,
      action: 'Review and respond to negative social feedback to prevent escalation',
      source_url: mention.source_url,
    }))
  }, [socialPulse])

  /* Agent Performance with CSAT and Response Time */
  const agentPerformance = useMemo(() => {
    const agentMap = new Map<string, {
      name: string
      tickets: number
      resolved: number
      csat: number[]
      responseTime: number[]
      reopens: number
    }>()
    tickets.forEach((ticket) => {
      const agent = (ticket.raw_payload as Record<string, unknown>)?.responder_name as string || ticket.agent_id || 'Unassigned'
      if (!agentMap.has(agent)) {
        agentMap.set(agent, { name: agent, tickets: 0, resolved: 0, csat: [], responseTime: [], reopens: 0 })
      }
      const row = agentMap.get(agent)!
      row.tickets += 1
      if (ticket.resolved_at_source) row.resolved += 1
      if (ticket.csat_score && ticket.csat_score > 0) row.csat.push(ticket.csat_score)
      if (ticket.first_response_hours && ticket.first_response_hours > 0) row.responseTime.push(ticket.first_response_hours)
      const tags = (ticket.tags_json || []).join(' ').toLowerCase()
      if (tags.includes('reopen') || tags.includes('re-open')) row.reopens += 1
    })
    return Array.from(agentMap.values())
      .map((row) => ({
        ...row,
        avgCsat: row.csat.length > 0 ? row.csat.reduce((a, b) => a + b, 0) / row.csat.length : null,
        avgResponseTime: row.responseTime.length > 0 ? row.responseTime.reduce((a, b) => a + b, 0) / row.responseTime.length : null,
        reopenRate: row.tickets > 0 ? (row.reopens / row.tickets) * 100 : 0,
      }))
      .filter((a) => a.tickets > 0)
      .sort((a, b) => b.resolved - a.resolved)
      .slice(0, 5)
  }, [tickets])

  /* Friction Cross-Link for Insights */
  const frictionInsights = useMemo(() => {
    if (!frictionData?.clusters) return []
    // Find issues that might relate to current support themes
    const supportThemes = new Set(
      tickets
        .map((t) => t.category?.toLowerCase() || '')
        .filter(Boolean)
    )
    return frictionData.clusters
      .filter((cluster) => {
        const title = cluster.title.toLowerCase()
        return Array.from(supportThemes).some((theme) => title.includes(theme) || theme.includes(title.split(' ')[0]))
      })
      .slice(0, 3)
      .map((cluster) => ({
        id: cluster.id,
        title: cluster.title,
        severity: cluster.severity,
        owner: cluster.owner_team,
        link: '/friction',
      }))
  }, [frictionData, tickets])

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

          {/* Agent Performance Comparison */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Agent Performance Comparison</strong>
              <span className="venom-panel-hint">CSAT, response times, and efficiency</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Tickets</th>
                    <th>Resolved</th>
                    <th>Avg CSAT</th>
                    <th>Avg Response</th>
                    <th>Reopen Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {agentPerformance.map((agent) => (
                    <tr key={agent.name}>
                      <td><strong>{agent.name}</strong></td>
                      <td>{agent.tickets}</td>
                      <td>{agent.resolved}</td>
                      <td>
                        {agent.avgCsat !== null ? (
                          <span className={`badge ${agent.avgCsat >= 4 ? 'badge-good' : agent.avgCsat >= 3 ? 'badge-warn' : 'badge-bad'}`}>
                            {agent.avgCsat.toFixed(1)}
                          </span>
                        ) : <span className="badge badge-muted">N/A</span>}
                      </td>
                      <td>
                        {agent.avgResponseTime !== null ? (
                          <span className={`badge ${agent.avgResponseTime <= 4 ? 'badge-good' : agent.avgResponseTime <= 8 ? 'badge-warn' : 'badge-bad'}`}>
                            {agent.avgResponseTime.toFixed(1)}h
                          </span>
                        ) : <span className="badge badge-muted">N/A</span>}
                      </td>
                      <td>
                        <span className={`badge ${agent.reopenRate <= 5 ? 'badge-good' : agent.reopenRate <= 10 ? 'badge-warn' : 'badge-bad'}`}>
                          {agent.reopenRate.toFixed(1)}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!agentPerformance.length ? <div className="state-message">No agent performance data available</div> : null}
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

            {/* Right: Insights + Friction Cross-Links */}
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
                {frictionInsights.length > 0 ? (
                  <div className="list-item status-warn">
                    <div className="item-head">
                      <strong>Related Friction Issues</strong>
                      <Link to="/friction" className="badge badge-neutral">View Friction Map</Link>
                    </div>
                    {frictionInsights.map((friction) => (
                      <div key={friction.id} style={{ marginTop: '0.5rem' }}>
                        <span className={`badge ${friction.severity === 'critical' ? 'badge-bad' : friction.severity === 'high' ? 'badge-warn' : 'badge-neutral'}`}>
                          {friction.severity}
                        </span>
                        <span style={{ marginLeft: '0.5rem' }}>{friction.title}</span>
                        {friction.owner ? <small style={{ marginLeft: '0.5rem', opacity: 0.7 }}>Owner: {friction.owner}</small> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {!insights.length && !frictionInsights.length ? <div className="list-item status-muted"><p>No multi-signal insights triggered from the current snapshot.</p></div> : null}
              </div>
            </section>
          </div>

          {/* Queue Health Trend + CSAT Trend (side by side) */}
          {(() => {
            const supportRows = (supportOverview?.rows || []) as KPIDaily[]
            const last7Support = supportRows.slice(-7)
            if (last7Support.length === 0) return null
            const backlogData = last7Support.map((r) => ({ date: r.business_date?.slice(5) || '', backlog: Number(r.open_backlog) || 0 }))
            const csatData = last7Support.map((r) => ({ date: r.business_date?.slice(5) || '', csat: Number(r.csat) || 0 }))
            return (
              <div className="two-col two-col-equal">
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>Queue Health Trend</strong>
                    <span className="venom-panel-hint">Last 7 days — open backlog</span>
                  </div>
                  <ResponsiveContainer width="100%" height={60}>
                    <LineChart data={backlogData}>
                      <Line type="monotone" dataKey="backlog" stroke="var(--blue)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </section>
                <section className="card">
                  <div className="venom-panel-head">
                    <strong>CSAT Trend</strong>
                    <span className="venom-panel-hint">Last 7 days — customer satisfaction</span>
                  </div>
                  <ResponsiveContainer width="100%" height={60}>
                    <LineChart data={csatData}>
                      <Line type="monotone" dataKey="csat" stroke="var(--green)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </section>
              </div>
            )
          })()}

          {/* SLA Breach Countdown */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>SLA Breach Countdown</strong>
              <span className="venom-panel-hint">Tickets at risk of SLA breach</span>
            </div>
            <div className="venom-sla-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', padding: '1rem' }}>
              <div className={`venom-sla-item ${slaBreachCountdown.in2h > 0 ? 'status-bad' : 'status-good'}`} style={{ textAlign: 'center', padding: '0.75rem', borderRadius: '8px', background: slaBreachCountdown.in2h > 0 ? 'rgba(255, 109, 122, 0.15)' : 'rgba(57, 208, 143, 0.1)' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{slaBreachCountdown.in2h}</div>
                <small>Breach in 2h</small>
              </div>
              <div className={`venom-sla-item ${slaBreachCountdown.in4h > 0 ? 'status-warn' : 'status-good'}`} style={{ textAlign: 'center', padding: '0.75rem', borderRadius: '8px', background: slaBreachCountdown.in4h > 0 ? 'rgba(255, 178, 87, 0.15)' : 'rgba(57, 208, 143, 0.1)' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{slaBreachCountdown.in4h}</div>
                <small>Breach in 4h</small>
              </div>
              <div className={`venom-sla-item ${slaBreachCountdown.in8h > 0 ? 'status-muted' : 'status-good'}`} style={{ textAlign: 'center', padding: '0.75rem', borderRadius: '8px', background: slaBreachCountdown.in8h > 0 ? 'rgba(159, 176, 212, 0.15)' : 'rgba(57, 208, 143, 0.1)' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{slaBreachCountdown.in8h}</div>
                <small>Breach in 8h</small>
              </div>
              <div className={`venom-sla-item ${slaBreachCountdown.breached > 0 ? 'status-bad' : 'status-good'}`} style={{ textAlign: 'center', padding: '0.75rem', borderRadius: '8px', background: slaBreachCountdown.breached > 0 ? 'rgba(255, 109, 122, 0.25)' : 'rgba(57, 208, 143, 0.1)' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 700, color: slaBreachCountdown.breached > 0 ? 'var(--red)' : undefined }}>{slaBreachCountdown.breached}</div>
                <small>Already Breached</small>
              </div>
            </div>
          </section>

          {/* Resolution Time Distribution + Ticket Aging Heatmap */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Resolution Time Distribution</strong>
                <span className="venom-panel-hint">How quickly tickets get resolved</span>
              </div>
              <ResponsiveContainer width="100%" height={120}>
                <BarChart data={resolutionDistribution} layout="vertical">
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="label" width={60} tick={{ fill: '#9fb0d4', fontSize: 12 }} />
                  <Tooltip formatter={(value: number) => [`${value.toFixed(1)}%`, 'Share']} />
                  <Bar dataKey="pct" radius={[0, 4, 4, 0]}>
                    {resolutionDistribution.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="venom-breakdown-list" style={{ marginTop: '0.5rem' }}>
                {resolutionDistribution.map((bucket) => (
                  <div className="venom-breakdown-row" key={bucket.label}>
                    <span className="venom-breakdown-label">{bucket.label}</span>
                    <span className="venom-breakdown-val">{bucket.count} tickets</span>
                    <span className="badge badge-neutral">{bucket.pct.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>Ticket Aging Heatmap</strong>
                <span className="venom-panel-hint">Open tickets by age</span>
              </div>
              <div className="venom-aging-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.75rem', padding: '1rem' }}>
                {ticketAging.map((bucket) => (
                  <div
                    key={bucket.label}
                    className={`venom-aging-cell status-${bucket.severity === 'critical' ? 'bad' : bucket.severity === 'high' ? 'warn' : bucket.severity === 'medium' ? 'muted' : 'good'}`}
                    style={{
                      padding: '1rem',
                      borderRadius: '8px',
                      textAlign: 'center',
                      background: bucket.severity === 'critical' ? 'rgba(255, 109, 122, 0.2)' :
                                  bucket.severity === 'high' ? 'rgba(255, 178, 87, 0.2)' :
                                  bucket.severity === 'medium' ? 'rgba(159, 176, 212, 0.15)' :
                                  'rgba(57, 208, 143, 0.1)',
                    }}
                  >
                    <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{bucket.count}</div>
                    <small>{bucket.label}</small>
                  </div>
                ))}
              </div>
            </section>
          </div>

          {/* Channel Breakdown */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Channel Breakdown</strong>
              <span className="venom-panel-hint">Ticket volume and resolution by channel</span>
            </div>
            <div className="venom-breakdown-list">
              {channelBreakdown.map((channel) => (
                <div className="venom-breakdown-row" key={channel.channel}>
                  <span className="venom-breakdown-label" style={{ textTransform: 'capitalize' }}>{channel.channel}</span>
                  <BarIndicator
                    value={channel.pct}
                    max={100}
                    color={channel.resolutionRate >= 80 ? 'var(--green)' : channel.resolutionRate >= 60 ? 'var(--orange)' : 'var(--red)'}
                  />
                  <span className="venom-breakdown-val">{channel.count} tickets</span>
                  <span className={`badge ${channel.resolutionRate >= 80 ? 'badge-good' : channel.resolutionRate >= 60 ? 'badge-warn' : 'badge-bad'}`}>
                    {channel.resolutionRate.toFixed(0)}% resolved
                  </span>
                </div>
              ))}
              {!channelBreakdown.length ? <div className="state-message">No channel data available</div> : null}
            </div>
          </section>

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

                {/* Social Actions - Auto-generated from negative high-engagement mentions */}
                {socialActions.length > 0 ? (
                  <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'rgba(255, 109, 122, 0.1)', borderRadius: '8px', border: '1px solid rgba(255, 109, 122, 0.3)' }}>
                    <div className="venom-panel-head" style={{ marginBottom: '0.5rem' }}>
                      <strong style={{ color: 'var(--red)' }}>Suggested Actions</strong>
                      <span className="badge badge-bad">{socialActions.length} high-priority</span>
                    </div>
                    <div className="stack-list compact">
                      {socialActions.map((action) => (
                        <div className="list-item status-bad" key={action.id}>
                          <div className="item-head">
                            <strong>{action.title}</strong>
                            <div className="inline-badges">
                              <span className="badge badge-neutral">{action.platform}</span>
                              <span className="badge badge-warn">engagement {action.engagement}</span>
                            </div>
                          </div>
                          <p>{action.action}</p>
                          {action.source_url ? (
                            <a href={action.source_url} target="_blank" rel="noopener noreferrer" className="badge badge-neutral">Respond now</a>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

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
