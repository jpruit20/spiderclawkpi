import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BarIndicator } from '../components/BarIndicator'
import { Card } from '../components/Card'
import { TruthBadge, TruthState } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ProvenanceBanner } from '../components/ProvenanceBanner'
import { ClickUpComplianceCard } from '../components/ClickUpComplianceCard'
import { ClickUpOverlayChart } from '../components/ClickUpOverlayChart'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { ClickUpVelocityCard } from '../components/ClickUpVelocityCard'
import { SlackPulseCard } from '../components/SlackPulseCard'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { MetricTile, StatusLight, TileGrid, openSectionById } from '../components/tiles'
import { NearbyEventsBadge } from '../components/NearbyEventsBadge'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { WismoKpiCard } from '../components/WismoKpiCard'
import { ApiError, api } from '../lib/api'
import { fmtInt, formatFreshness } from '../lib/format'
import { ClusterTicketDetail, CXActionItem, CXMetricItem, CXSnapshotResponse, FreshdeskTicketItem, IssueRadarResponse, KPIDaily, SocialPulse, SupportOverviewResponse } from '../lib/types'
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
  const [tickets, setTickets] = useState<FreshdeskTicketItem[]>([])
  const [frictionData, setFrictionData] = useState<IssueRadarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [clusterDetail, setClusterDetail] = useState<ClusterTicketDetail | null>(null)
  const [clusterDetailLoading, setClusterDetailLoading] = useState(false)

  const loadClusterDetail = useCallback(async (theme: string) => {
    if (clusterDetail?.theme === theme) { setClusterDetail(null); return }
    setClusterDetailLoading(true)
    try {
      const detail = await api.clusterDetail(theme)
      setClusterDetail(detail)
    } catch { setClusterDetail(null) }
    finally { setClusterDetailLoading(false) }
  }, [clusterDetail])

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
      if (!created || isNaN(created.getTime())) return
      const ageDays = Math.floor((now.getTime() - created.getTime()) / (1000 * 60 * 60 * 24))
      if (ageDays < 0) return // Future dates are invalid
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
      if (!created || isNaN(created.getTime())) return
      const ageHours = (now.getTime() - created.getTime()) / (1000 * 60 * 60)
      if (ageHours < 0) return // Future dates are invalid
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
      const rawResponder = (ticket.raw_payload as Record<string, unknown>)?.responder_name
      const agent = (typeof rawResponder === 'string' ? rawResponder : null) || ticket.agent_id || 'Unassigned'
      if (!agentMap.has(agent)) {
        agentMap.set(agent, { name: agent, tickets: 0, resolved: 0, csat: [], responseTime: [], reopens: 0 })
      }
      const row = agentMap.get(agent)!
      row.tickets += 1
      if (ticket.resolved_at_source) row.resolved += 1
      if (ticket.csat_score && ticket.csat_score > 0) row.csat.push(ticket.csat_score)
      if (ticket.first_response_hours && ticket.first_response_hours > 0) row.responseTime.push(ticket.first_response_hours)
      const tags = (ticket.tags_json || []).map((t) => String(t)).join(' ').toLowerCase()
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

  /* ─── NEW IMPROVEMENTS ─── */

  /* 1. First Contact Resolution (FCR) Rate */
  const fcrMetrics = useMemo(() => {
    if (tickets.length === 0) return { rate: 0, resolved: 0, total: 0, noReopen: 0, noEscalation: 0 }
    const resolvedTickets = tickets.filter((t) => t.resolved_at_source)
    let noReopenCount = 0
    let noEscalationCount = 0
    resolvedTickets.forEach((ticket) => {
      const tags = (ticket.tags_json || []).map((t) => String(t)).join(' ').toLowerCase()
      const hasReopen = tags.includes('reopen') || tags.includes('re-open')
      const hasEscalation = tags.includes('escalat') || ticket.priority === 'urgent'
      if (!hasReopen) noReopenCount += 1
      if (!hasEscalation) noEscalationCount += 1
    })
    const fcrCount = resolvedTickets.filter((ticket) => {
      const tags = (ticket.tags_json || []).map((t) => String(t)).join(' ').toLowerCase()
      return !tags.includes('reopen') && !tags.includes('re-open') && !tags.includes('escalat')
    }).length
    return {
      rate: resolvedTickets.length > 0 ? (fcrCount / resolvedTickets.length) * 100 : 0,
      resolved: resolvedTickets.length,
      total: tickets.length,
      noReopen: noReopenCount,
      noEscalation: noEscalationCount,
      fcrCount,
    }
  }, [tickets])

  /* 2. Peak Hour Analysis */
  const peakHourAnalysis = useMemo(() => {
    const hourBuckets: { hour: number; created: number; resolved: number }[] = Array.from({ length: 24 }, (_, i) => ({
      hour: i,
      created: 0,
      resolved: 0,
    }))
    const dayBuckets: { day: string; created: number; resolved: number }[] = [
      { day: 'Sun', created: 0, resolved: 0 },
      { day: 'Mon', created: 0, resolved: 0 },
      { day: 'Tue', created: 0, resolved: 0 },
      { day: 'Wed', created: 0, resolved: 0 },
      { day: 'Thu', created: 0, resolved: 0 },
      { day: 'Fri', created: 0, resolved: 0 },
      { day: 'Sat', created: 0, resolved: 0 },
    ]
    tickets.forEach((ticket) => {
      const created = ticket.created_at_source ? new Date(ticket.created_at_source) : null
      if (created && !isNaN(created.getTime())) {
        const hour = created.getHours()
        const dayOfWeek = created.getDay()
        hourBuckets[hour].created += 1
        dayBuckets[dayOfWeek].created += 1
      }
      const resolved = ticket.resolved_at_source ? new Date(ticket.resolved_at_source) : null
      if (resolved && !isNaN(resolved.getTime())) {
        const hour = resolved.getHours()
        const dayOfWeek = resolved.getDay()
        hourBuckets[hour].resolved += 1
        dayBuckets[dayOfWeek].resolved += 1
      }
    })
    const peakCreationHour = hourBuckets.reduce((max, h) => h.created > max.created ? h : max, hourBuckets[0])
    const peakResolutionHour = hourBuckets.reduce((max, h) => h.resolved > max.resolved ? h : max, hourBuckets[0])
    const peakCreationDay = dayBuckets.reduce((max, d) => d.created > max.created ? d : max, dayBuckets[0])
    return { hourBuckets, dayBuckets, peakCreationHour, peakResolutionHour, peakCreationDay }
  }, [tickets])

  /* 3. Week-over-Week Comparison */
  const [showWoWComparison, setShowWoWComparison] = useState(false)
  const weekOverWeekComparison = useMemo(() => {
    const supportRows = (supportOverview?.rows || []) as KPIDaily[]
    if (supportRows.length < 14) return null
    const thisWeek = supportRows.slice(-7)
    const lastWeek = supportRows.slice(-14, -7)
    const sumMetric = (rows: KPIDaily[], key: keyof KPIDaily) => rows.reduce((sum, r) => sum + (Number(r[key]) || 0), 0)
    const avgMetric = (rows: KPIDaily[], key: keyof KPIDaily) => {
      const vals = rows.map(r => Number(r[key]) || 0).filter(v => v > 0)
      return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0
    }
    return {
      thisWeek: {
        ticketsCreated: sumMetric(thisWeek, 'tickets_created'),
        ticketsResolved: sumMetric(thisWeek, 'tickets_resolved'),
        avgBacklog: avgMetric(thisWeek, 'open_backlog'),
        avgCsat: avgMetric(thisWeek, 'csat'),
        avgResponseTime: avgMetric(thisWeek, 'first_response_time'),
      },
      lastWeek: {
        ticketsCreated: sumMetric(lastWeek, 'tickets_created'),
        ticketsResolved: sumMetric(lastWeek, 'tickets_resolved'),
        avgBacklog: avgMetric(lastWeek, 'open_backlog'),
        avgCsat: avgMetric(lastWeek, 'csat'),
        avgResponseTime: avgMetric(lastWeek, 'first_response_time'),
      },
    }
  }, [supportOverview])

  /* 4. Theme Trend Heatmap — filter out "unknown" */
  const themeTrendData = useMemo(() => {
    if (!frictionData?.trend_heatmap) return []
    return frictionData.trend_heatmap
      .filter((theme) => theme.theme !== 'unknown')
      .slice(0, 8).map((theme) => ({
        theme: theme.theme,
        points: theme.points.slice(-7),
        total: theme.points.reduce((sum, p) => sum + p.count, 0),
        trend: theme.points.length >= 2
          ? ((theme.points[theme.points.length - 1].count - theme.points[0].count) / Math.max(theme.points[0].count, 1)) * 100
          : 0,
      }))
  }, [frictionData])

  /* 5. At-Risk Ticket Predictor */
  const atRiskTickets = useMemo(() => {
    const now = new Date()
    const openTickets = tickets.filter((t) => !t.resolved_at_source)
    return openTickets
      .map((ticket) => {
        const created = ticket.created_at_source ? new Date(ticket.created_at_source) : null
        const ageHours = created && !isNaN(created.getTime()) ? (now.getTime() - created.getTime()) / (1000 * 60 * 60) : 0
        const responseHours = ticket.first_response_hours || 0
        const priority = ticket.priority || 'low'
        const tags = (ticket.tags_json || []).map((t) => String(t)).join(' ').toLowerCase()
        const hasEscalation = tags.includes('escalat') || priority === 'urgent'
        const hasComplaint = tags.includes('complaint') || tags.includes('angry') || tags.includes('frustrated')
        // Risk score calculation
        let riskScore = 0
        if (ageHours > 48) riskScore += 40
        else if (ageHours > 24) riskScore += 25
        else if (ageHours > 12) riskScore += 10
        if (responseHours > 8) riskScore += 30
        else if (responseHours > 4) riskScore += 15
        if (hasEscalation) riskScore += 20
        if (hasComplaint) riskScore += 15
        if (priority === 'urgent') riskScore += 20
        else if (priority === 'high') riskScore += 10
        return {
          id: ticket.ticket_id,
          subject: ticket.subject || 'Untitled',
          ageHours,
          responseHours,
          riskScore,
          riskLevel: riskScore >= 60 ? 'high' : riskScore >= 35 ? 'medium' : 'low',
          factors: [
            ageHours > 24 ? `Aging ${Math.round(ageHours)}h` : null,
            responseHours > 4 ? `Slow response ${responseHours.toFixed(1)}h` : null,
            hasEscalation ? 'Escalated' : null,
            hasComplaint ? 'Customer complaint' : null,
          ].filter(Boolean),
        }
      })
      .filter((t) => t.riskScore >= 35)
      .sort((a, b) => b.riskScore - a.riskScore)
      .slice(0, 5)
  }, [tickets])

  /* 6. Repeat Contact Analysis */
  const repeatContacts = useMemo(() => {
    const now = new Date()
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
    const recentTickets = tickets.filter((t) => {
      const created = t.created_at_source ? new Date(t.created_at_source) : null
      return created && !isNaN(created.getTime()) && created >= thirtyDaysAgo
    })
    const customerMap = new Map<string, { customerId: string; count: number; tickets: typeof recentTickets }>()
    recentTickets.forEach((ticket) => {
      // Use requester_id or extract email from raw_payload if available
      const rawPayload = ticket.raw_payload as Record<string, unknown> | undefined
      const email = (rawPayload?.requester_email as string) || (rawPayload?.email as string) || null
      const customerId = email || ticket.requester_id || 'unknown'
      if (customerId === 'unknown') return
      if (!customerMap.has(customerId)) customerMap.set(customerId, { customerId, count: 0, tickets: [] })
      const entry = customerMap.get(customerId)!
      entry.count += 1
      entry.tickets.push(ticket)
    })
    return Array.from(customerMap.values())
      .filter((c) => c.count >= 3)
      .sort((a, b) => b.count - a.count)
      .slice(0, 5)
      .map((c) => ({
        customerId: c.customerId,
        count: c.count,
        latestSubject: c.tickets[0]?.subject || 'Unknown',
        avgCsat: c.tickets.filter(t => t.csat_score && t.csat_score > 0).length > 0
          ? c.tickets.filter(t => t.csat_score && t.csat_score > 0).reduce((sum, t) => sum + (t.csat_score || 0), 0) /
            c.tickets.filter(t => t.csat_score && t.csat_score > 0).length
          : null,
      }))
  }, [tickets])

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
            Jeremiah's Team &mdash; Last updated {snapshotTimestamp}
          </p>
        </div>
        {!loading && !error && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* Queue Health Status */}
            {(() => {
              const backlogMetric = headerMetrics.find(m => m.key.includes('backlog'))
              const backlog = backlogMetric?.current ?? 0
              if (backlog > 150) return <span className="badge badge-bad">Queue Critical ({whole(backlog)})</span>
              if (backlog > 80) return <span className="badge badge-warn">Queue Elevated ({whole(backlog)})</span>
              return <span className="badge badge-good">Queue Healthy ({whole(backlog)})</span>
            })()}
            {/* SLA Breach Warning */}
            {slaBreachCountdown.breached > 0 && (
              <span className="badge badge-bad">{slaBreachCountdown.breached} SLA Breached</span>
            )}
            {slaBreachCountdown.in2h > 0 && (
              <span className="badge badge-warn">{slaBreachCountdown.in2h} SLA &lt;2h</span>
            )}
            {/* First Response Time Status */}
            {(() => {
              const frtMetric = headerMetrics.find(m => m.key.includes('first_response'))
              if (!frtMetric) return null
              const frt = frtMetric.current
              if (frt <= 4) return <span className="badge badge-good">FRT {hrs(frt)}</span>
              if (frt <= 8) return <span className="badge badge-warn">FRT {hrs(frt)}</span>
              return <span className="badge badge-bad">FRT {hrs(frt)}</span>
            })()}
          </div>
        )}
      </div>

      {loading ? <Card title="Customer Experience"><div className="state-message">Loading customer experience division...</div></Card> : null}
      {error ? <Card title="Customer Experience Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <ProvenanceBanner
            compact
            truthState="canonical"
            lastUpdated={snapshotTimestamp !== 'n/a' ? snapshotTimestamp : undefined}
            scope="Freshdesk + social signals · Jeremiah's team"
            caveat={tickets.length === 0 ? 'No tickets loaded — Freshdesk may be disconnected.' : undefined}
          />

          {/* Quick Stats & Navigation Bar */}
          <div className="scope-note" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600 }}>Quick Stats:</span>
              <span className={`badge ${fcrMetrics.rate >= 80 ? 'badge-good' : fcrMetrics.rate >= 60 ? 'badge-warn' : 'badge-bad'}`}>
                FCR {pct(fcrMetrics.rate)}
              </span>
              <span className="badge badge-neutral">{tickets.length} Total Tickets</span>
              <span className="badge badge-neutral">{tickets.filter(t => !t.resolved_at_source).length} Open</span>
              {socialPulse && (
                <span className={`badge ${(socialPulse.avg_sentiment_score ?? 0) >= 0.3 ? 'badge-good' : (socialPulse.avg_sentiment_score ?? 0) >= 0 ? 'badge-warn' : 'badge-bad'}`}>
                  Social {Math.round((socialPulse.avg_sentiment_score ?? 0) * 100)}%
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600 }}>Drill-down:</span>
              {DRILL_ROUTES.map(route => (
                <Link key={route.path} to={route.path} className="range-button" style={{ textDecoration: 'none', fontSize: 12 }}>
                  {route.icon} {route.label}
                </Link>
              ))}
            </div>
          </div>

          {/* Truth Legend */}
          <TruthLegend />

          {/* KPI Strip */}
          <VenomKpiStrip cards={kpiCards} cols={4} />

          {/* WISMO — target: 0. Customer follow-ups on undelivered orders.
              Every one is a proactive-comms gap. */}
          <WismoKpiCard days={30} />

          {/* Performance Metrics as a visual tile grid. Each tile is a
              car-gauge: big number, state color, 7-day trend arrow.
              Click a tile to jump into the Team Performance collapsible
              below where the full detail lives. */}
          <section className="card" style={{ padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <strong style={{ fontSize: 13 }}>Performance at a glance</strong>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>7-day trend vs. prior week</span>
            </div>
            {gridMetrics.length > 0 ? (
              <TileGrid cols={4}>
                {gridMetrics.map(metric => {
                  const tone = statusTone(metric.status)
                  const state: 'good' | 'warn' | 'bad' | 'neutral' =
                    tone === 'good' ? 'good' : tone === 'warn' ? 'warn' : tone === 'bad' ? 'bad' : 'neutral'
                  const dir = trendDirection(metric.trend7d)
                  // 'Up' is good for CSAT / FCR; bad for times / rates.
                  // Use metric.key to infer.
                  const upIsGood = !(metric.key.includes('time') || metric.key.includes('breach') || metric.key.includes('backlog') || metric.key.includes('reopen'))
                  return (
                    <MetricTile
                      key={metric.key}
                      label={metric.label}
                      value={metricValue(metric)}
                      sublabel={`target ${metricTarget(metric)}`}
                      state={state}
                      delta={`${Math.abs(metric.trend7d).toFixed(1)}%`}
                      deltaDir={dir}
                      upIsGood={upIsGood}
                      onClick={() => openSectionById('cx-team-performance')}
                    />
                  )
                })}
              </TileGrid>
            ) : (
              <div className="state-message">No performance metrics returned.</div>
            )}
          </section>

          {/* Today's Focus — kept list-style because these are action items
              needing titles + owner + description, not scannable gauges.
              But limited to top 3 + 'N more' expand. */}
          {todayFocus.length > 0 && (
            <section className="card" style={{ borderLeft: '3px solid var(--blue)' }}>
              <div className="venom-panel-head">
                <strong>Today's Focus</strong>
                <span className="venom-panel-hint">{todayFocus.length} action{todayFocus.length === 1 ? '' : 's'}</span>
              </div>
              <div className="stack-list compact">
                {todayFocus.slice(0, 3).map(item => (
                  <div className="list-item" key={item.id}>
                    <div className="item-head">
                      <strong>{item.title}</strong>
                      <span className={`badge ${priorityBadgeClass(item.priority)}`}>{item.priority}</span>
                    </div>
                    <p>{item.required_action}</p>
                    <small>Owner: {item.owner}</small>
                  </div>
                ))}
                {todayFocus.length > 3 && (
                  <div className="list-item status-muted" style={{ fontSize: 12 }}>
                    + {todayFocus.length - 3} more action{todayFocus.length - 3 === 1 ? '' : 's'} below in the full queue
                  </div>
                )}
              </div>
            </section>
          )}
          {todayFocus.length === 0 && (
            <section className="card" style={{ borderLeft: '3px solid var(--green)', padding: '10px 16px' }}>
              <span style={{ fontSize: 13 }}>✓ No open priority actions from today's snapshot — queue is healthy.</span>
            </section>
          )}

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
                  {item.opened_at && (
                    <div style={{ marginTop: 4 }}>
                      <NearbyEventsBadge businessDate={item.opened_at} division="customer-experience" windowDays={3} />
                    </div>
                  )}
                </div>
              ))}
              {!actions.length ? <div className="list-item status-good"><p>No actions in queue.</p></div> : null}
            </div>
          </section>

          {/* ==============================================================
              BELOW-THE-FOLD DETAIL — progressive disclosure.
              Hero above is kept tight: header, KPIs, WISMO card,
              performance metrics, today's focus, action queue. Everything
              downstream lives behind collapsible groups so the page
              doesn't overwhelm at open.
              ============================================================== */}
          <CollapsibleSection
            id="cx-team-performance"
            title="Team performance & ticket operations"
            subtitle="Agent comparison, team load, insights, queue trends, SLA breach countdowns, resolution-time distribution, ticket-aging heatmap, channel breakdown"
            accentColor="#6ea8ff"
          >
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
            const formatDate = (d?: string) => (d && d.length >= 10 ? d.slice(5) : d || '')
            const backlogData = last7Support.map((r) => ({ date: formatDate(r.business_date), backlog: Number(r.open_backlog) || 0 }))
            const csatData = last7Support.map((r) => ({ date: formatDate(r.business_date), csat: Number(r.csat) || 0 }))
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

          </CollapsibleSection>

          <CollapsibleSection
            id="cx-advanced-analytics"
            title="Advanced analytics & patterns"
            subtitle="First-contact resolution, week-over-week comparison, peak hour analysis, theme-trend heatmap (with cluster drill-down), at-risk ticket predictor, repeat-contact analysis"
            accentColor="#f59e0b"
          >
          {/* ─── NEW IMPROVEMENT WIDGETS ─── */}

          {/* First Contact Resolution (FCR) Rate */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>First Contact Resolution (FCR)</strong>
              <span className="venom-panel-hint">Tickets resolved without reopens or escalations</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', padding: '1rem' }}>
              <div style={{ textAlign: 'center', padding: '1rem', background: 'rgba(57, 208, 143, 0.1)', borderRadius: '8px' }}>
                <div style={{ fontSize: '2rem', fontWeight: 700, color: fcrMetrics.rate >= 80 ? 'var(--green)' : fcrMetrics.rate >= 60 ? 'var(--orange)' : 'var(--red)' }}>
                  {fcrMetrics.rate.toFixed(1)}%
                </div>
                <small>FCR Rate</small>
              </div>
              <div style={{ textAlign: 'center', padding: '1rem', background: 'rgba(110, 168, 255, 0.1)', borderRadius: '8px' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{fcrMetrics.fcrCount || 0}</div>
                <small>First-Contact Resolved</small>
              </div>
              <div style={{ textAlign: 'center', padding: '1rem', background: 'rgba(159, 176, 212, 0.1)', borderRadius: '8px' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{fcrMetrics.noReopen}</div>
                <small>No Reopens</small>
              </div>
              <div style={{ textAlign: 'center', padding: '1rem', background: 'rgba(159, 176, 212, 0.1)', borderRadius: '8px' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{fcrMetrics.noEscalation}</div>
                <small>No Escalations</small>
              </div>
            </div>
          </section>

          {/* Week-over-Week Comparison */}
          {weekOverWeekComparison ? (
            <section className="card">
              <div className="venom-panel-head">
                <strong>Week-over-Week Comparison</strong>
                <button
                  onClick={() => setShowWoWComparison(!showWoWComparison)}
                  className="badge badge-neutral"
                  style={{ cursor: 'pointer', border: 'none' }}
                >
                  {showWoWComparison ? 'Hide' : 'Show'} Details
                </button>
              </div>
              {showWoWComparison ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>This Week</th>
                        <th>Last Week</th>
                        <th>Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { label: 'Tickets Created', thisWeek: weekOverWeekComparison.thisWeek.ticketsCreated, lastWeek: weekOverWeekComparison.lastWeek.ticketsCreated, format: 'int', lowerBetter: true },
                        { label: 'Tickets Resolved', thisWeek: weekOverWeekComparison.thisWeek.ticketsResolved, lastWeek: weekOverWeekComparison.lastWeek.ticketsResolved, format: 'int', lowerBetter: false },
                        { label: 'Avg Backlog', thisWeek: weekOverWeekComparison.thisWeek.avgBacklog, lastWeek: weekOverWeekComparison.lastWeek.avgBacklog, format: 'dec', lowerBetter: true },
                        { label: 'Avg CSAT', thisWeek: weekOverWeekComparison.thisWeek.avgCsat, lastWeek: weekOverWeekComparison.lastWeek.avgCsat, format: 'dec', lowerBetter: false },
                        { label: 'Avg Response Time', thisWeek: weekOverWeekComparison.thisWeek.avgResponseTime, lastWeek: weekOverWeekComparison.lastWeek.avgResponseTime, format: 'hrs', lowerBetter: true },
                      ].map((row) => {
                        const change = row.lastWeek > 0 ? ((row.thisWeek - row.lastWeek) / row.lastWeek) * 100 : 0
                        const isImproved = row.lowerBetter ? change < 0 : change > 0
                        return (
                          <tr key={row.label}>
                            <td><strong>{row.label}</strong></td>
                            <td>{row.format === 'int' ? Math.round(row.thisWeek) : row.format === 'hrs' ? `${row.thisWeek.toFixed(1)}h` : row.thisWeek.toFixed(1)}</td>
                            <td>{row.format === 'int' ? Math.round(row.lastWeek) : row.format === 'hrs' ? `${row.lastWeek.toFixed(1)}h` : row.lastWeek.toFixed(1)}</td>
                            <td>
                              <span className={`badge ${isImproved ? 'badge-good' : Math.abs(change) < 5 ? 'badge-neutral' : 'badge-bad'}`}>
                                {change > 0 ? '+' : ''}{change.toFixed(1)}%
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem', padding: '1rem' }}>
                  {(() => {
                    const csatChange = weekOverWeekComparison.lastWeek.avgCsat > 0
                      ? ((weekOverWeekComparison.thisWeek.avgCsat - weekOverWeekComparison.lastWeek.avgCsat) / weekOverWeekComparison.lastWeek.avgCsat) * 100
                      : 0
                    const backlogChange = weekOverWeekComparison.lastWeek.avgBacklog > 0
                      ? ((weekOverWeekComparison.thisWeek.avgBacklog - weekOverWeekComparison.lastWeek.avgBacklog) / weekOverWeekComparison.lastWeek.avgBacklog) * 100
                      : 0
                    const responseChange = weekOverWeekComparison.lastWeek.avgResponseTime > 0
                      ? ((weekOverWeekComparison.thisWeek.avgResponseTime - weekOverWeekComparison.lastWeek.avgResponseTime) / weekOverWeekComparison.lastWeek.avgResponseTime) * 100
                      : 0
                    return (
                      <>
                        <div style={{ textAlign: 'center', padding: '0.75rem', background: csatChange >= 0 ? 'rgba(57, 208, 143, 0.1)' : 'rgba(255, 109, 122, 0.1)', borderRadius: '8px' }}>
                          <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{csatChange >= 0 ? '+' : ''}{csatChange.toFixed(1)}%</div>
                          <small>CSAT vs Last Week</small>
                        </div>
                        <div style={{ textAlign: 'center', padding: '0.75rem', background: backlogChange <= 0 ? 'rgba(57, 208, 143, 0.1)' : 'rgba(255, 109, 122, 0.1)', borderRadius: '8px' }}>
                          <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{backlogChange >= 0 ? '+' : ''}{backlogChange.toFixed(1)}%</div>
                          <small>Backlog vs Last Week</small>
                        </div>
                        <div style={{ textAlign: 'center', padding: '0.75rem', background: responseChange <= 0 ? 'rgba(57, 208, 143, 0.1)' : 'rgba(255, 109, 122, 0.1)', borderRadius: '8px' }}>
                          <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>{responseChange >= 0 ? '+' : ''}{responseChange.toFixed(1)}%</div>
                          <small>Response Time vs Last Week</small>
                        </div>
                      </>
                    )
                  })()}
                </div>
              )}
            </section>
          ) : null}

          {/* Peak Hour Analysis */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Peak Hour Analysis</strong>
                <span className="venom-panel-hint">Ticket volume by hour of day</span>
              </div>
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={peakHourAnalysis.hourBuckets.filter((_, i) => i >= 6 && i <= 22)}>
                  <XAxis dataKey="hour" tick={{ fill: '#9fb0d4', fontSize: 10 }} tickFormatter={(h) => `${h}:00`} />
                  <Tooltip formatter={(value: number, name: string) => [value, name === 'created' ? 'Created' : 'Resolved']} labelFormatter={(h) => `${h}:00`} />
                  <Bar dataKey="created" fill="var(--orange)" name="created" />
                  <Bar dataKey="resolved" fill="var(--green)" name="resolved" />
                </BarChart>
              </ResponsiveContainer>
              <div style={{ display: 'flex', justifyContent: 'space-around', padding: '0.5rem', fontSize: '0.85rem' }}>
                <span>Peak creation: <strong>{peakHourAnalysis.peakCreationHour.hour}:00</strong> ({peakHourAnalysis.peakCreationHour.created})</span>
                <span>Peak resolution: <strong>{peakHourAnalysis.peakResolutionHour.hour}:00</strong> ({peakHourAnalysis.peakResolutionHour.resolved})</span>
              </div>
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>Day of Week Distribution</strong>
                <span className="venom-panel-hint">Busiest day: {peakHourAnalysis.peakCreationDay.day}</span>
              </div>
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={peakHourAnalysis.dayBuckets}>
                  <XAxis dataKey="day" tick={{ fill: '#9fb0d4', fontSize: 11 }} />
                  <Tooltip formatter={(value: number, name: string) => [value, name === 'created' ? 'Created' : 'Resolved']} />
                  <Bar dataKey="created" fill="var(--orange)" name="created" />
                  <Bar dataKey="resolved" fill="var(--green)" name="resolved" />
                </BarChart>
              </ResponsiveContainer>
            </section>
          </div>

          {/* Theme Trend Heatmap — clickable for drill-down */}
          {themeTrendData.length > 0 ? (
            <section className="card">
              <div className="venom-panel-head">
                <strong>Theme Trend Heatmap</strong>
                <span className="venom-panel-hint">Click any theme to drill into individual tickets</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Theme</th>
                      <th style={{ textAlign: 'center' }}>7-Day Trend</th>
                      <th>Total</th>
                      <th>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {themeTrendData.map((theme) => (
                      <tr key={theme.theme}
                        style={{ cursor: 'pointer', background: clusterDetail?.theme === theme.theme ? 'rgba(110,168,255,0.12)' : undefined }}
                        onClick={() => loadClusterDetail(theme.theme)}>
                        <td><strong style={{ textTransform: 'capitalize' }}>{theme.theme.replace(/_/g, ' ')}</strong></td>
                        <td>
                          <div style={{ display: 'flex', gap: '2px', justifyContent: 'center' }}>
                            {theme.points.map((pt, idx) => {
                              const max = Math.max(...theme.points.map(p => p.count), 1)
                              const intensity = pt.count / max
                              return (
                                <div
                                  key={idx}
                                  title={`${pt.business_date}: ${pt.count}`}
                                  style={{
                                    width: '20px',
                                    height: '20px',
                                    borderRadius: '3px',
                                    background: `rgba(110, 168, 255, ${0.2 + intensity * 0.8})`,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '0.65rem',
                                    color: intensity > 0.5 ? '#fff' : '#9fb0d4',
                                  }}
                                >
                                  {pt.count}
                                </div>
                              )
                            })}
                          </div>
                        </td>
                        <td>{theme.total}</td>
                        <td>
                          <span className={`badge ${theme.trend > 10 ? 'badge-bad' : theme.trend < -10 ? 'badge-good' : 'badge-neutral'}`}>
                            {theme.trend > 0 ? '+' : ''}{theme.trend.toFixed(0)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {clusterDetailLoading && <div className="state-message" style={{ marginTop: 12 }}>Loading ticket detail...</div>}
              {clusterDetail && !clusterDetailLoading && (
                <div style={{ marginTop: 12, border: '1px solid var(--accent)', borderRadius: 8, padding: 16 }}>
                  <div className="venom-panel-head">
                    <strong>{clusterDetail.theme_title} — Ticket Deep-Dive</strong>
                    <button className="range-button" onClick={() => setClusterDetail(null)}>Close</button>
                  </div>

                  {/* Key metrics */}
                  <div className="venom-kpi-strip" style={{ marginBottom: 12 }}>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Total Tickets</div>
                      <div className="venom-kpi-value">{clusterDetail.total_tickets}</div>
                    </div>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Unique Customers</div>
                      <div className="venom-kpi-value">{clusterDetail.unique_customers}</div>
                      <div className="venom-kpi-sub">{(clusterDetail.customer_ratio * 100).toFixed(0)}% unique ratio</div>
                    </div>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Severity Assessment</div>
                      <div className="venom-kpi-value" style={{ fontSize: 16, color: clusterDetail.severity_adjustment === 'downgraded' ? 'var(--green)' : clusterDetail.severity_adjustment === 'upgraded' ? 'var(--red)' : 'var(--text)' }}>
                        {clusterDetail.severity_adjustment === 'downgraded' ? 'Lower Risk' : clusterDetail.severity_adjustment === 'upgraded' ? 'Higher Risk' : 'Normal'}
                      </div>
                      <div className="venom-kpi-sub">{clusterDetail.severity_reason}</div>
                    </div>
                    <div className="venom-kpi-card">
                      <div className="venom-kpi-label">Owner</div>
                      <div className="venom-kpi-value" style={{ fontSize: 16 }}>{clusterDetail.owner_team}</div>
                    </div>
                  </div>

                  {/* Sub-topics */}
                  {clusterDetail.sub_topics.length > 0 && (
                    <div style={{ marginBottom: 16 }}>
                      <div className="venom-breakdown-label">Common Sub-Topics</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                        {clusterDetail.sub_topics.map((t, i) => (
                          <span key={i} className="badge badge-neutral" style={{ fontSize: 11 }}>{t.keyword} ({t.count})</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Breakdowns */}
                  <div className="two-col two-col-equal" style={{ marginBottom: 12 }}>
                    <div>
                      <div className="venom-breakdown-label">Status Breakdown</div>
                      <div className="venom-breakdown-list">
                        {Object.entries(clusterDetail.status_breakdown).map(([k, v]) => (
                          <div key={k} className="venom-breakdown-row"><span>{k}</span><span className="venom-breakdown-val">{v}</span></div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="venom-breakdown-label">Top Reporters</div>
                      <div className="venom-breakdown-list">
                        {clusterDetail.top_requesters.slice(0, 5).map((r, i) => (
                          <div key={i} className="venom-breakdown-row">
                            <span>Customer #{r.requester_id.slice(-6)}</span>
                            <span className="venom-breakdown-val">{r.ticket_count} ticket{r.ticket_count !== 1 ? 's' : ''}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Ticket list */}
                  <div className="venom-breakdown-label">Individual Tickets ({clusterDetail.total_tickets})</div>
                  <div className="stack-list compact" style={{ maxHeight: 400, overflowY: 'auto' }}>
                    {clusterDetail.tickets.slice(0, 20).map((t, i) => (
                      <div key={i} className={`list-item status-${t.status === 'Resolved' || t.status === 'Closed' ? 'good' : 'muted'}`}>
                        <div className="item-head">
                          <strong>#{t.ticket_id} {t.subject}</strong>
                          <div className="inline-badges">
                            <span className="badge badge-neutral">{t.status || 'open'}</span>
                            {t.channel && <span className="badge badge-neutral" style={{ fontSize: 10 }}>{t.channel}</span>}
                          </div>
                        </div>
                        <p style={{ fontSize: 11, color: 'var(--muted)' }}>
                          Customer #{t.requester_id.slice(-6)}
                          {t.created_at && ` · Created ${formatFreshness(t.created_at)}`}
                          {t.resolution_hours != null && ` · Resolved in ${t.resolution_hours.toFixed(1)}h`}
                          {t.tags.length > 0 && ` · Tags: ${t.tags.join(', ')}`}
                        </p>
                      </div>
                    ))}
                  </div>
                  {clusterDetail.tickets.length > 20 && <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>Showing 20 of {clusterDetail.tickets.length} tickets</p>}
                </div>
              )}
            </section>
          ) : null}

          {/* At-Risk Ticket Predictor */}
          {atRiskTickets.length > 0 ? (
            <section className="card">
              <div className="venom-panel-head">
                <strong>At-Risk Tickets</strong>
                <span className="badge badge-bad">{atRiskTickets.length} tickets need attention</span>
              </div>
              <div className="stack-list compact">
                {atRiskTickets.map((ticket) => (
                  <div className={`list-item ${ticket.riskLevel === 'high' ? 'status-bad' : 'status-warn'}`} key={ticket.id}>
                    <div className="item-head">
                      <strong>#{ticket.id}: {ticket.subject}</strong>
                      <div className="inline-badges">
                        <span className={`badge ${ticket.riskLevel === 'high' ? 'badge-bad' : 'badge-warn'}`}>
                          Risk: {ticket.riskScore}
                        </span>
                      </div>
                    </div>
                    <div className="inline-badges" style={{ marginTop: '0.25rem' }}>
                      {ticket.factors.map((factor, idx) => (
                        <span className="badge badge-neutral" key={idx}>{factor}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {/* Repeat Contact Analysis */}
          {repeatContacts.length > 0 ? (
            <section className="card">
              <div className="venom-panel-head">
                <strong>Repeat Contacts (Churn Risk)</strong>
                <span className="venom-panel-hint">Customers with 3+ tickets in 30 days</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Customer</th>
                      <th>Tickets (30d)</th>
                      <th>Latest Issue</th>
                      <th>Avg CSAT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {repeatContacts.map((customer) => (
                      <tr key={customer.customerId}>
                        <td><strong>{customer.customerId.length > 25 ? customer.customerId.slice(0, 22) + '...' : customer.customerId}</strong></td>
                        <td>
                          <span className={`badge ${customer.count >= 5 ? 'badge-bad' : 'badge-warn'}`}>
                            {customer.count} tickets
                          </span>
                        </td>
                        <td>{customer.latestSubject.length > 30 ? customer.latestSubject.slice(0, 27) + '...' : customer.latestSubject}</td>
                        <td>
                          {customer.avgCsat !== null ? (
                            <span className={`badge ${customer.avgCsat >= 4 ? 'badge-good' : customer.avgCsat >= 3 ? 'badge-warn' : 'badge-bad'}`}>
                              {customer.avgCsat.toFixed(1)}
                            </span>
                          ) : <span className="badge badge-muted">N/A</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          </CollapsibleSection>

          <CollapsibleSection
            id="cx-external-coordination"
            title="External voice & coordination"
            subtitle="Social listening / brand pulse, auto-generated social actions, ClickUp CX tasks & team velocity, #marketing-customer-service Slack pulse, navigation shortcuts"
            accentColor="#a78bfa"
          >
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

          {/* ClickUp tasks + team velocity for CX */}
          <ClickUpTasksCard
            title="ClickUp tasks — Customer Experience"
            subtitle="Tasks tagged for CX work across ClickUp. Filter scope with the chips; link to open in ClickUp."
            defaultFilter={{ limit: 30 }}
          />
          <ClickUpVelocityCard
            title="Team velocity — all CX tasks"
            subtitle="Throughput, cycle time, and who's closing what this week."
          />
          <ClickUpComplianceCard
            title="Tagging compliance — CX view"
            subtitle="Grades every closed task against the required taxonomy (Division, Customer Impact, Category)."
          />

          {/* CX ticket volume overlaid with ClickUp task completions — did
              closing the direct-customer-impact task actually reduce ticket load? */}
          <ClickUpOverlayChart
            title="Support tickets ↔ Customer-facing task completions"
            subtitle="Daily Freshdesk tickets with Customer Impact=Direct ClickUp task completions as vertical markers. Precise field-match — after a customer-facing task closes, does ticket volume fall?"
            primarySeries={((supportOverview?.rows || []) as KPIDaily[]).map(r => ({
              date: r.business_date,
              value: Number(r.tickets_created) || 0,
            }))}
            primaryLabel="Tickets created"
            primaryColor="var(--orange)"
            clickupFilter={{
              customer_impact: 'Direct',
              event_types: 'completed',
              days: 90,
            }}
          />

          {/* Slack pulse — #marketing-customer-service */}
          <SlackPulseCard
            title="Slack pulse — Customer channels"
            subtitle="Live activity from customer-service-adjacent Slack channels. Message bodies + files are stored; keyword-matched issues bubble into Issue Radar."
            defaultChannelName="marketing-customer-service"
          />

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
          </CollapsibleSection>
        </>
      ) : null}
    </div>
  )
}
