import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { CXActionItem, FreshdeskAgentDailyItem, FreshdeskTicketItem, IssueClusterItem, KPIDaily, SupportOverviewResponse } from '../lib/types'

type KpiStatus = 'green' | 'yellow' | 'red'
type ActionStatus = 'open' | 'in_progress' | 'resolved'

type KpiKey =
  | 'open_backlog'
  | 'aged_tickets_24h'
  | 'avg_close_time'
  | 'reopen_rate'
  | 'escalation_rate'
  | 'queue_concentration_pct'

type SnapshotMetric = {
  key: KpiKey
  label: string
  owner: string
  current: number
  target: number
  delta: number
  trend7d: number
  trend30d: number
  status: KpiStatus
  lastUpdated: string
  confidence?: 'normal' | 'low'
  triggerCondition?: string
  criticalImmediate: boolean
  consecutiveBadDays: number
}

type ActionItem = {
  dedupKey: string
  triggerKpi: KpiKey
  triggerCondition: string
  title: string
  owner: string
  coOwner?: string
  escalationOwner?: string
  requiredAction: string
  dueDate: string
  priority: 'critical' | 'high' | 'medium'
  status: ActionStatus
  autoCloseRule: string
  evidence: string[]
  consecutiveBadDays: number
  triggerSnapshot: string
  priorityScore: number
}

type RepLoad = {
  name: string
  assigned: number
  closedPerDay: number
  activeQueueSize: number
  throughputRatio: number
  avgCloseTime: number
  reopenRate: number
  sharePct: number
}

function pct(value: number, digits = 1) {
  return `${value.toFixed(digits)}%`
}

function hrs(value: number) {
  return `${value.toFixed(1)}h`
}

function whole(value: number) {
  return `${Math.round(value)}`
}

function statusTone(status: KpiStatus | ActionItem['priority']) {
  if (status === 'red' || status === 'critical') return 'bad'
  if (status === 'yellow' || status === 'high') return 'warn'
  return 'good'
}

function normalizeDate(value?: string) {
  return value ? value.slice(0, 10) : undefined
}

function isClosedStatus(status?: string) {
  const normalized = String(status || '').toLowerCase()
  return normalized.includes('closed') || normalized.includes('resolved') || normalized.includes('solved')
}

function deltaDirection(current: number, target: number, inverseGood = false) {
  const diff = current - target
  if (Math.abs(diff) < 0.001) return 'on target'
  const better = inverseGood ? diff < 0 : diff > 0
  return better ? 'better' : 'worse'
}

function computeTrend(rows: KPIDaily[], selector: (row: KPIDaily) => number, days: number) {
  if (!rows.length) return 0
  const recent = rows.slice(-days)
  const prior = rows.slice(-days * 2, -days)
  const recentAvg = recent.reduce((sum, row) => sum + selector(row), 0) / Math.max(recent.length, 1)
  const priorAvg = prior.reduce((sum, row) => sum + selector(row), 0) / Math.max(prior.length, 1)
  if (!prior.length || priorAvg === 0) return 0
  return ((recentAvg - priorAvg) / priorAvg) * 100
}

function consecutiveBadDays(rows: KPIDaily[], selector: (row: KPIDaily) => number, isBad: (value: number) => boolean) {
  let count = 0
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (isBad(selector(rows[i]))) count += 1
    else break
  }
  return count
}

function businessDays(rows: KPIDaily[]) {
  return [...rows].sort((a, b) => a.business_date.localeCompare(b.business_date))
}

function issueIsProductLinked(item?: IssueClusterItem) {
  const text = JSON.stringify(item?.details_json || {}).toLowerCase()
  return text.includes('firmware') || text.includes('venom') || text.includes('temperature') || text.includes('disconnect') || text.includes('product')
}

export function CustomerExperienceDivision() {
  const [support, setSupport] = useState<SupportOverviewResponse | null>(null)
  const [agents, setAgents] = useState<FreshdeskAgentDailyItem[]>([])
  const [tickets, setTickets] = useState<FreshdeskTicketItem[]>([])
  const [issues, setIssues] = useState<IssueClusterItem[]>([])
  const [persistedActions, setPersistedActions] = useState<CXActionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [supportPayload, agentsPayload, ticketsPayload, issuesPayload, actionsPayload] = await Promise.all([
          api.supportOverview(),
          api.supportAgents(),
          api.supportTickets(),
          api.issues(),
          api.cxActions(),
        ])
        if (cancelled) return
        setSupport(supportPayload)
        setAgents(agentsPayload || [])
        setTickets(ticketsPayload || [])
        setIssues(issuesPayload.clusters || [])
        setPersistedActions(actionsPayload || [])
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load customer experience division')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const rows = useMemo(() => businessDays(support?.rows || []), [support])
  const snapshotDate = rows.at(-1)?.business_date || 'n/a'
  const snapshotTimestamp = `${snapshotDate}T00:00:00Z`
  const snapshotRow = rows.at(-1)
  const snapshotTickets = useMemo(() => tickets.filter((ticket) => {
    const created = normalizeDate(ticket.created_at_source)
    const resolved = normalizeDate(ticket.resolved_at_source)
    if (!created || created > snapshotDate) return false
    if (resolved && resolved <= snapshotDate) return false
    return !isClosedStatus(ticket.status) || !resolved
  }), [tickets, snapshotDate])

  const assignedIn7d = useMemo(() => {
    const startDate = rows[Math.max(0, rows.length - 7)]?.business_date
    const map = new Map<string, number>()
    if (!startDate) return map
    tickets.forEach((ticket) => {
      const created = normalizeDate(ticket.created_at_source)
      if (!created || created < startDate || created > snapshotDate) return
      const agent = String(ticket.raw_payload?.responder_name || ticket.agent_id || 'Unassigned')
      map.set(agent, (map.get(agent) || 0) + 1)
    })
    return map
  }, [tickets, rows, snapshotDate])

  const escalationRateCurrent = useMemo(() => {
    const startDate = rows[Math.max(0, rows.length - 7)]?.business_date
    if (!startDate) return 0
    const relevant = tickets.filter((ticket) => {
      const created = normalizeDate(ticket.created_at_source)
      return created && created >= startDate && created <= snapshotDate
    })
    if (!relevant.length) return 0
    const escalated = relevant.filter((ticket) => {
      const text = `${ticket.category || ''} ${(ticket.tags_json || []).join(' ')} ${ticket.subject || ''}`.toLowerCase()
      return text.includes('escalat') || text.includes('urgent') || text.includes('engineering') || text.includes('firmware')
    }).length
    return (escalated / relevant.length) * 100
  }, [tickets, rows, snapshotDate])

  const queueConcentrationCurrent = useMemo(() => {
    const values = Array.from(assignedIn7d.values())
    const total = values.reduce((a, b) => a + b, 0)
    if (!total) return 0
    return (Math.max(...values) / total) * 100
  }, [assignedIn7d])

  const reps = useMemo<RepLoad[]>(() => {
    const startDate = rows[Math.max(0, rows.length - 7)]?.business_date
    const repNames = ['Jeremiah', 'Miles', 'Bodhi']
    const openByRep = new Map<string, number>()
    snapshotTickets.forEach((ticket) => {
      const name = String(ticket.raw_payload?.responder_name || ticket.agent_id || 'Unassigned')
      openByRep.set(name, (openByRep.get(name) || 0) + 1)
    })

    const agentRows = agents.filter((agent) => !startDate || (agent.business_date >= startDate && agent.business_date <= snapshotDate))
    const resolvedMap = new Map<string, { resolved: number; resolutionHours: number[] }>()
    agentRows.forEach((agent) => {
      const name = String(agent.agent_name || agent.agent_id || 'Unassigned')
      if (!resolvedMap.has(name)) resolvedMap.set(name, { resolved: 0, resolutionHours: [] })
      const row = resolvedMap.get(name)!
      row.resolved += Number(agent.tickets_resolved || 0)
      if ((agent.resolution_hours || 0) > 0) row.resolutionHours.push(Number(agent.resolution_hours || 0))
    })

    const reopenedMap = new Map<string, { total: number; reopened: number }>()
    const assignedMap = new Map<string, number>()
    tickets.forEach((ticket) => {
      const created = normalizeDate(ticket.created_at_source)
      if (!created || (startDate && created < startDate) || created > snapshotDate) return
      const name = String(ticket.raw_payload?.responder_name || ticket.agent_id || 'Unassigned')
      assignedMap.set(name, (assignedMap.get(name) || 0) + 1)
      if (!reopenedMap.has(name)) reopenedMap.set(name, { total: 0, reopened: 0 })
      const row = reopenedMap.get(name)!
      row.total += 1
      const text = `${ticket.category || ''} ${(ticket.tags_json || []).join(' ')}`.toLowerCase()
      if (text.includes('reopen') || text.includes('re-open')) row.reopened += 1
    })

    const totalAssigned = Array.from(assignedMap.values()).reduce((a, b) => a + b, 0)

    return repNames.map((preferred) => {
      const assignedEntry = Array.from(assignedMap.entries()).find(([name]) => name.toLowerCase().includes(preferred.toLowerCase()))
      const resolvedEntry = Array.from(resolvedMap.entries()).find(([name]) => name.toLowerCase().includes(preferred.toLowerCase()))
      const reopenEntry = Array.from(reopenedMap.entries()).find(([name]) => name.toLowerCase().includes(preferred.toLowerCase()))
      const openEntry = Array.from(openByRep.entries()).find(([name]) => name.toLowerCase().includes(preferred.toLowerCase()))
      const assigned = assignedEntry?.[1] || 0
      const resolved = resolvedEntry?.[1].resolved || 0
      const resolutionHours = resolvedEntry?.[1].resolutionHours || []
      const activeQueueSize = openEntry?.[1] || 0
      const reopened = reopenEntry?.[1].reopened || 0
      const reopenBase = reopenEntry?.[1].total || 0
      return {
        name: preferred,
        assigned,
        closedPerDay: resolved / 7,
        activeQueueSize,
        throughputRatio: assigned ? resolved / assigned : 0,
        avgCloseTime: resolutionHours.length ? resolutionHours.reduce((a, b) => a + b, 0) / resolutionHours.length : 0,
        reopenRate: reopenBase ? (reopened / reopenBase) * 100 : 0,
        sharePct: totalAssigned ? (assigned / totalAssigned) * 100 : 0,
      }
    })
  }, [agents, tickets, snapshotTickets, rows, snapshotDate])

  const topIssue = issues[0]
  const productLinked = issueIsProductLinked(topIssue)

  const metrics = useMemo<SnapshotMetric[]>(() => {
    if (!snapshotRow) return []
    const burdenCurrent = snapshotRow.tickets_per_100_orders
    const burdenTrend7 = computeTrend(rows, (row) => row.tickets_per_100_orders, 7)
    const burdenTrend30 = computeTrend(rows, (row) => row.tickets_per_100_orders, 30)

    const defs: SnapshotMetric[] = [
      {
        key: 'open_backlog', label: 'Open backlog', owner: 'Jeremiah', current: snapshotRow.open_backlog, target: 90,
        delta: snapshotRow.open_backlog - 90, trend7d: computeTrend(rows, (row) => row.open_backlog, 7), trend30d: computeTrend(rows, (row) => row.open_backlog, 30),
        status: snapshotRow.open_backlog > 140 ? 'red' : snapshotRow.open_backlog > 90 ? 'yellow' : 'green', lastUpdated: snapshotTimestamp,
        triggerCondition: snapshotRow.open_backlog > 140 ? 'open_backlog_gt_140' : snapshotRow.open_backlog > 90 ? 'open_backlog_gt_90' : undefined,
        criticalImmediate: snapshotRow.open_backlog > 180, consecutiveBadDays: consecutiveBadDays(rows, (row) => row.open_backlog, (v) => v > 90),
      },
      {
        key: 'aged_tickets_24h', label: 'Aged tickets >24h', owner: 'Jeremiah', current: snapshotTickets.length, target: 50,
        delta: snapshotTickets.length - 50, trend7d: 0, trend30d: 0,
        status: snapshotTickets.length > 90 ? 'red' : snapshotTickets.length > 50 ? 'yellow' : 'green', lastUpdated: snapshotTimestamp,
        triggerCondition: snapshotTickets.length > 90 ? 'aged_tickets_gt_90' : snapshotTickets.length > 50 ? 'aged_tickets_gt_50' : undefined,
        criticalImmediate: snapshotTickets.length > 120, consecutiveBadDays: consecutiveBadDays(rows, (row) => row.open_backlog, (v) => v > 50),
      },
      {
        key: 'avg_close_time', label: 'Avg close time', owner: 'Jeremiah', current: snapshotRow.resolution_time, target: 24,
        delta: snapshotRow.resolution_time - 24, trend7d: computeTrend(rows, (row) => row.resolution_time, 7), trend30d: computeTrend(rows, (row) => row.resolution_time, 30),
        status: snapshotRow.resolution_time > 48 ? 'red' : snapshotRow.resolution_time > 24 ? 'yellow' : 'green', lastUpdated: snapshotTimestamp,
        triggerCondition: snapshotRow.resolution_time > 48 ? 'avg_close_time_gt_48h' : snapshotRow.resolution_time > 24 ? 'avg_close_time_gt_24h' : undefined,
        criticalImmediate: snapshotRow.resolution_time > 60, consecutiveBadDays: consecutiveBadDays(rows, (row) => row.resolution_time, (v) => v > 24),
      },
      {
        key: 'reopen_rate', label: 'Reopen rate', owner: 'Jeremiah', current: snapshotRow.reopen_rate, target: 5,
        delta: snapshotRow.reopen_rate - 5, trend7d: computeTrend(rows, (row) => row.reopen_rate, 7), trend30d: computeTrend(rows, (row) => row.reopen_rate, 30),
        status: snapshotRow.reopen_rate > 8 ? 'red' : snapshotRow.reopen_rate > 5 ? 'yellow' : 'green', lastUpdated: snapshotTimestamp,
        triggerCondition: snapshotRow.reopen_rate > 8 ? 'reopen_rate_gt_8' : snapshotRow.reopen_rate > 5 ? 'reopen_rate_gt_5' : undefined,
        criticalImmediate: snapshotRow.reopen_rate > 12, consecutiveBadDays: consecutiveBadDays(rows, (row) => row.reopen_rate, (v) => v > 5),
      },
      {
        key: 'escalation_rate', label: 'Escalation rate', owner: 'Jeremiah', current: escalationRateCurrent, target: 8,
        delta: escalationRateCurrent - 8, trend7d: 0, trend30d: 0,
        status: escalationRateCurrent > 12 ? 'red' : escalationRateCurrent > 8 ? 'yellow' : 'green', lastUpdated: snapshotTimestamp,
        triggerCondition: escalationRateCurrent > 12 ? 'escalation_rate_gt_12' : escalationRateCurrent > 8 ? 'escalation_rate_gt_8' : undefined,
        criticalImmediate: escalationRateCurrent > 18, consecutiveBadDays: consecutiveBadDays(rows, (row) => row.reopen_rate, (v) => v > 5),
      },
      {
        key: 'queue_concentration_pct', label: 'Queue concentration %', owner: 'Jeremiah', current: queueConcentrationCurrent, target: 40,
        delta: queueConcentrationCurrent - 40, trend7d: 0, trend30d: 0,
        status: queueConcentrationCurrent > 50 ? 'red' : queueConcentrationCurrent > 40 ? 'yellow' : 'green', lastUpdated: snapshotTimestamp,
        triggerCondition: queueConcentrationCurrent > 50 ? 'queue_concentration_gt_50' : queueConcentrationCurrent > 40 ? 'queue_concentration_gt_40' : undefined,
        criticalImmediate: queueConcentrationCurrent > 60, consecutiveBadDays: consecutiveBadDays(rows, (row) => row.open_backlog, (v) => v > 90),
      },
    ]

    const burdenCard: SnapshotMetric = {
      key: 'open_backlog', label: 'Support burden', owner: 'Jeremiah', current: burdenCurrent, target: 4.5,
      delta: burdenCurrent - 4.5, trend7d: burdenTrend7, trend30d: burdenTrend30,
      status: burdenCurrent > 7 ? 'red' : burdenCurrent > 4.5 ? 'yellow' : 'green', lastUpdated: snapshotTimestamp,
      confidence: 'low', triggerCondition: undefined, criticalImmediate: false, consecutiveBadDays: 0,
    }

    return [burdenCard, ...defs]
  }, [snapshotRow, snapshotTickets.length, snapshotTimestamp, rows, escalationRateCurrent, queueConcentrationCurrent])

  const headerMetrics = metrics.slice(0, 4)
  const gridMetrics = metrics.slice(1)

  const actions = useMemo<ActionItem[]>(() => persistedActions.map((item) => ({
    dedupKey: item.dedup_key,
    triggerKpi: item.trigger_kpi as KpiKey,
    triggerCondition: item.trigger_condition,
    title: item.title,
    owner: item.owner,
    coOwner: item.co_owner || undefined,
    escalationOwner: item.escalation_owner || undefined,
    requiredAction: item.required_action,
    dueDate: item.priority === 'critical' ? `${snapshotDate} EOD` : item.priority === 'high' ? '24h' : item.priority === 'medium' ? '48h' : '72h',
    priority: item.priority === 'low' ? 'medium' : item.priority,
    status: item.status as ActionStatus,
    autoCloseRule: typeof item.auto_close_rule === 'object' ? JSON.stringify(item.auto_close_rule) : String(item.auto_close_rule),
    evidence: (item.evidence || []).map((entry) => typeof entry === 'string' ? entry : JSON.stringify(entry)),
    consecutiveBadDays: 0,
    triggerSnapshot: item.snapshot_timestamp,
    priorityScore: (item.priority === 'critical' ? 100 : item.priority === 'high' ? 70 : item.priority === 'medium' ? 40 : 20) + (item.escalation_owner ? 20 : 0),
  })).sort((a, b) => b.priorityScore - a.priorityScore), [persistedActions, snapshotDate])

  const todayFocus = actions.filter((item) => item.status !== 'resolved').slice(0, 3)

  const insights = useMemo(() => {
    const out: { text: string; evidence: string[] }[] = []
    const concentration = gridMetrics.find((item) => item.key === 'queue_concentration_pct')
    const backlog = gridMetrics.find((item) => item.key === 'open_backlog')
    const closeTime = gridMetrics.find((item) => item.key === 'avg_close_time')
    const reopen = gridMetrics.find((item) => item.key === 'reopen_rate')
    const escalation = gridMetrics.find((item) => item.key === 'escalation_rate')
    if (concentration && backlog && concentration.status !== 'green' && backlog.status !== 'green') {
      out.push({
        text: 'Queue pressure is being driven by workload concentration, not just raw ticket volume.',
        evidence: [`Queue concentration ${concentration.current.toFixed(1)}%`, `Open backlog ${backlog.current}`, `Top rep share exceeds target`],
      })
    }
    if (closeTime && reopen && closeTime.status !== 'green' && reopen.status !== 'green') {
      out.push({
        text: 'Repeat-contact risk is tied to slow resolution, not just intake volume.',
        evidence: [`Avg close time ${closeTime.current.toFixed(1)}h`, `Reopen rate ${reopen.current.toFixed(1)}%`, `Both above target in same snapshot`],
      })
    }
    if (escalation && topIssue) {
      out.push({
        text: 'Escalations are clustering around a specific issue family rather than being evenly distributed.',
        evidence: [`Escalation rate ${escalation.current.toFixed(1)}%`, `Top issue cluster ${topIssue.title}`, `Issue owner ${topIssue.owner_team || 'TBD'}`],
      })
    }
    return out.slice(0, 3)
  }, [gridMetrics, topIssue])

  const sampleSnapshot = useMemo(() => ({
    snapshot_timestamp: snapshotTimestamp,
    kpis: gridMetrics.map((item) => ({ key: item.key, current: item.current, target: item.target, status: item.status, owner: item.owner })),
    today_focus: todayFocus.map((item) => ({ title: item.title, owner: item.owner, priority: item.priority, due_date: item.dueDate })),
    actions: actions.map((item) => ({ dedup_key: item.dedupKey, status: item.status, escalation_owner: item.escalationOwner || null, co_owner: item.coOwner || null })),
  }), [snapshotTimestamp, gridMetrics, todayFocus, actions])

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Customer Experience</h2>
        <p>Division-first operating page for Jeremiah’s team using a single daily snapshot across KPIs, focus, actions, load, and insights.</p>
        <small className="page-meta">API base: {getApiBase()} · snapshot: {snapshotTimestamp}</small>
      </div>
      {loading ? <Card title="Customer Experience"><div className="state-message">Loading customer experience division…</div></Card> : null}
      {error ? <Card title="Customer Experience Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="four-col">
            {headerMetrics.map((metric) => (
              <Card key={metric.label} title={metric.label}>
                <div className="hero-metric hero-metric-sm">{metric.label === 'First Response Time' ? hrs(metric.current) : metric.label === 'Aged Backlog' ? whole(metric.current) : metric.label === 'Support burden' ? pct(metric.current, 2) : pct(Math.max(0, 100 - metric.current), 1)}</div>
                <div className="inline-badges">
                  <span className={`badge badge-${statusTone(metric.status)}`}>{metric.status}</span>
                  <span className="badge badge-neutral">owner {metric.owner}</span>
                  {metric.confidence === 'low' ? <span className="badge badge-warn">LOW CONFIDENCE</span> : null}
                </div>
                <small>Target {metric.label === 'First Response Time' ? hrs(metric.target) : whole(metric.target)} · {deltaDirection(metric.current, metric.target, true)}</small>
                <small>7d {metric.trend7d.toFixed(1)}% · 30d {metric.trend30d.toFixed(1)}%</small>
              </Card>
            ))}
          </div>

          <Card title="KPI Grid">
            <div className="three-col">
              {gridMetrics.map((metric) => (
                <div className={`list-item status-${statusTone(metric.status)}`} key={metric.key}>
                  <div className="item-head">
                    <strong>{metric.label}</strong>
                    <span className={`badge badge-${statusTone(metric.status)}`}>{metric.status}</span>
                  </div>
                  <p>
                    {metric.key.includes('time') ? hrs(metric.current) : metric.key.includes('rate') || metric.key.includes('pct') ? pct(metric.current) : whole(metric.current)}
                    {' '}vs target {' '}
                    {metric.key.includes('time') ? hrs(metric.target) : metric.key.includes('rate') || metric.key.includes('pct') ? pct(metric.target) : whole(metric.target)}
                  </p>
                  <small>Owner: {metric.owner} · Last updated: {metric.lastUpdated}</small>
                  <small>7d trend {metric.trend7d.toFixed(1)}% · Consecutive bad days {metric.consecutiveBadDays}</small>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Today Focus">
            <div className="stack-list">
              {todayFocus.map((item) => (
                <div className={`list-item status-${statusTone(item.priority)}`} key={item.dedupKey}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge badge-${statusTone(item.priority)}`}>{item.priority}</span>
                      <span className="badge badge-neutral">{item.status}</span>
                    </div>
                  </div>
                  <p>{item.requiredAction}</p>
                  <small>Owner: {item.owner}{item.coOwner ? ` · Co-owner: ${item.coOwner}` : ''}{item.escalationOwner ? ` · Escalated: ${item.escalationOwner}` : ''}</small>
                  <small>Due: {item.dueDate} · Trigger: {item.triggerCondition}</small>
                </div>
              ))}
              {!todayFocus.length ? <div className="list-item status-good"><p>No open priority actions from the current daily snapshot.</p></div> : null}
            </div>
          </Card>

          <Card title="Action Queue">
            <div className="stack-list">
              {actions.map((item) => (
                <div className={`list-item status-${statusTone(item.priority)}`} key={item.dedupKey}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge badge-${statusTone(item.priority)}`}>{item.priority}</span>
                      <span className="badge badge-neutral">{item.status}</span>
                    </div>
                  </div>
                  <p>{item.requiredAction}</p>
                  <small>Dedup key: {item.dedupKey}</small>
                  <small>Owner: {item.owner}{item.coOwner ? ` · Co-owner: ${item.coOwner}` : ''}{item.escalationOwner ? ` · Escalation owner: ${item.escalationOwner}` : ''}</small>
                  <small>Auto-close: {item.autoCloseRule}</small>
                  <small>Evidence: {item.evidence.join(' · ')}</small>
                </div>
              ))}
              {!actions.length ? <div className="list-item status-good"><p>No non-green KPI has met persistence or critical-trigger requirements.</p></div> : null}
            </div>
          </Card>

          <Card title="Team Load + Distribution">
            <div className="three-col">
              {reps.map((rep) => (
                <div className={`list-item status-${rep.sharePct > 50 ? 'bad' : rep.sharePct > 40 ? 'warn' : 'good'}`} key={rep.name}>
                  <div className="item-head"><strong>{rep.name}</strong><span className="badge badge-neutral">share {rep.sharePct.toFixed(1)}%</span></div>
                  <small>Tickets closed/day: {rep.closedPerDay.toFixed(1)}</small>
                  <small>Active queue size: {rep.activeQueueSize}</small>
                  <small>Throughput ratio: {rep.throughputRatio.toFixed(2)}</small>
                  <small>Avg close time: {rep.avgCloseTime.toFixed(1)}h</small>
                  <small>Reopen rate: {rep.reopenRate.toFixed(1)}%</small>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Root Cause / Insights">
            <div className="stack-list">
              {insights.map((item, idx) => (
                <div className="list-item" key={idx}>
                  <strong>{item.text}</strong>
                  <small>Evidence: {item.evidence.join(' · ')}</small>
                </div>
              ))}
              {!insights.length ? <div className="list-item status-muted"><p>No multi-signal insights triggered from the current snapshot.</p></div> : null}
            </div>
          </Card>

          <Card title="Sample Snapshot Output">
            <pre className="code-block">{JSON.stringify(sampleSnapshot, null, 2)}</pre>
          </Card>
        </>
      ) : null}
    </div>
  )
}
