import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { RangeToolbar } from '../components/RangeToolbar'
import { TrendChart } from '../components/TrendChart'
import { ApiError, api, getApiBase } from '../lib/api'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { FreshdeskAgentDailyItem, FreshdeskTicketItem, IssueRadarResponse, KPIDaily } from '../lib/types'

function percentShare(value: number, total: number) {
  return total ? `${((value / total) * 100).toFixed(1)}%` : '0.0%'
}

function median(values: number[]) {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function themeName(ticket: FreshdeskTicketItem) {
  return ticket.category || ticket.tags_json?.[0] || 'unclassified'
}

function normalizeDate(value?: string) {
  return value ? value.slice(0, 10) : undefined
}

function isClosedStatus(status?: string) {
  const normalized = String(status || '').toLowerCase()
  return normalized.includes('closed') || normalized.includes('resolved') || normalized.includes('solved')
}

export function SupportCX() {
  const todayDate = businessTodayDate()
  const [rows, setRows] = useState<KPIDaily[]>([])
  const [issues, setIssues] = useState<IssueRadarResponse | null>(null)
  const [agents, setAgents] = useState<FreshdeskAgentDailyItem[]>([])
  const [tickets, setTickets] = useState<FreshdeskTicketItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '7d', startDate: '', endDate: '' })
  const requestIdRef = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      const requestId = ++requestIdRef.current
      setLoading(true)
      setError(null)
      try {
        const [supportPayload, issuesPayload, agentsPayload, ticketsPayload] = await Promise.all([
          api.supportOverview(controller.signal),
          api.issues(controller.signal),
          api.supportAgents(controller.signal),
          api.supportTickets(controller.signal),
        ])
        if (controller.signal.aborted || requestId !== requestIdRef.current) return
        const supportRows = [...(supportPayload.rows || [])].sort((a, b) => a.business_date.localeCompare(b.business_date))
        setRows(supportRows)
        setIssues(issuesPayload)
        setAgents(agentsPayload || [])
        setTickets(ticketsPayload || [])
        setRange((current) => current.startDate && current.endDate ? current : buildPresetRange('7d', supportRows, { anchorDate: todayDate }))
      } catch (err) {
        if (controller.signal.aborted || requestId !== requestIdRef.current) return
        setError(err instanceof ApiError ? err.message : 'Failed to load support overview')
      } finally {
        if (controller.signal.aborted || requestId !== requestIdRef.current) return
        setLoading(false)
      }
    }
    void load()
    return () => {
      controller.abort()
      requestIdRef.current += 1
    }
  }, [])

  const currentRows = useMemo(() => filterRowsByRange(rows, range), [rows, range])
  const rangeTicketDates = useMemo(() => new Set(currentRows.map((row) => row.business_date)), [currentRows])
  const rangeAgents = useMemo(() => agents.filter((row) => rangeTicketDates.has(row.business_date)), [agents, rangeTicketDates])
  const rangeTickets = useMemo(() => tickets.filter((ticket) => {
    const created = normalizeDate(ticket.created_at_source)
    return created ? created >= range.startDate && created <= range.endDate : false
  }), [tickets, range])
  const backlogSnapshotTickets = useMemo(() => tickets.filter((ticket) => {
    const created = normalizeDate(ticket.created_at_source)
    const resolved = normalizeDate(ticket.resolved_at_source)
    if (!created || created > range.endDate) return false
    if (isClosedStatus(ticket.status) && resolved && resolved <= range.endDate) return false
    if (resolved && resolved <= range.endDate) return false
    return true
  }), [tickets, range.endDate])

  const burdenAvg = useMemo(() => {
    if (!currentRows.length) return 0
    return currentRows.reduce((sum, row) => sum + row.tickets_per_100_orders, 0) / currentRows.length
  }, [currentRows])

  const agentWorkload = useMemo(() => {
    const map = new Map<string, {
      agent: string
      assigned: number
      resolved: number
      openBacklog: number
    }>()

    function ensureAgent(key: string, label?: string) {
      const agent = label || key
      if (!map.has(key)) {
        map.set(key, {
          agent: String(agent || key),
          assigned: 0,
          resolved: 0,
          openBacklog: 0,
        })
      }
      return map.get(key)!
    }

    rangeTickets.forEach((ticket) => {
      const key = ticket.agent_id || 'unassigned'
      const row = ensureAgent(key, ticket.raw_payload?.responder_name || ticket.agent_id || key)
      row.assigned += 1
    })

    rangeAgents.forEach((agent) => {
      const key = agent.agent_id || agent.agent_name || 'unassigned'
      const row = ensureAgent(key, agent.agent_name || key)
      row.resolved += Number(agent.tickets_resolved || 0)
    })

    backlogSnapshotTickets.forEach((ticket) => {
      const key = ticket.agent_id || 'unassigned'
      const row = ensureAgent(key, ticket.raw_payload?.responder_name || ticket.agent_id || key)
      row.openBacklog += 1
    })

    const totalAssigned = Array.from(map.values()).reduce((sum, row) => sum + row.assigned, 0)
    const totalResolved = Array.from(map.values()).reduce((sum, row) => sum + row.resolved, 0)

    return Array.from(map.values())
      .map((row) => ({
        ...row,
        assignedShare: percentShare(row.assigned, totalAssigned),
        resolvedShare: percentShare(row.resolved, totalResolved),
      }))
      .sort((a, b) => b.assigned - a.assigned || b.resolved - a.resolved || b.openBacklog - a.openBacklog)
  }, [rangeTickets, rangeAgents, backlogSnapshotTickets])

  const responsePerformance = useMemo(() => {
    const map = new Map<string, {
      agent: string
      resolved: number
      firstResponseValues: number[]
      resolutionValues: number[]
    }>()

    function ensureAgent(key: string, label?: string) {
      const agent = label || key
      if (!map.has(key)) {
        map.set(key, {
          agent: String(agent || key),
          resolved: 0,
          firstResponseValues: [],
          resolutionValues: [],
        })
      }
      return map.get(key)!
    }

    rangeAgents.forEach((agent) => {
      const key = agent.agent_id || agent.agent_name || 'unassigned'
      const row = ensureAgent(key, agent.agent_name || key)
      row.resolved += Number(agent.tickets_resolved || 0)
      if ((agent.first_response_hours || 0) > 0) row.firstResponseValues.push(Number(agent.first_response_hours || 0))
      if ((agent.resolution_hours || 0) > 0) row.resolutionValues.push(Number(agent.resolution_hours || 0))
    })

    return Array.from(map.values())
      .map((row) => ({
        agent: row.agent,
        resolved: row.resolved,
        avgFirstResponse: row.firstResponseValues.length ? row.firstResponseValues.reduce((a, b) => a + b, 0) / row.firstResponseValues.length : 0,
        medianFirstResponse: median(row.firstResponseValues),
        avgResolution: row.resolutionValues.length ? row.resolutionValues.reduce((a, b) => a + b, 0) / row.resolutionValues.length : 0,
        medianResolution: median(row.resolutionValues),
      }))
      .sort((a, b) => b.resolved - a.resolved || a.avgFirstResponse - b.avgFirstResponse)
  }, [rangeAgents])

  const themeRows = useMemo(() => {
    const map = new Map<string, { theme: string; count: number; open: number; priorities: Record<string, number> }>()
    rangeTickets.forEach((ticket) => {
      const theme = themeName(ticket)
      if (!map.has(theme)) map.set(theme, { theme, count: 0, open: 0, priorities: {} })
      const row = map.get(theme)!
      row.count += 1
      if (!ticket.resolved_at_source && !isClosedStatus(ticket.status)) row.open += 1
      const priority = String(ticket.priority || 'unknown')
      row.priorities[priority] = (row.priorities[priority] || 0) + 1
    })
    const orders = currentRows.reduce((sum, row) => sum + row.orders, 0)
    return Array.from(map.values())
      .map((row) => ({
        ...row,
        ticketsPer100Orders: orders ? (row.count / orders) * 100 : 0,
        severityMix: Object.entries(row.priorities).map(([key, value]) => `${key}:${value}`).join(' · '),
      }))
      .sort((a, b) => b.count - a.count)
  }, [rangeTickets, currentRows])

  const managementFlags = useMemo(() => {
    const flags: string[] = []
    if (agentWorkload[0] && parseFloat(agentWorkload[0].assignedShare) >= 70) flags.push(`${agentWorkload[0].agent} is carrying ${agentWorkload[0].assignedShare} of assigned tickets.`)
    const unowned = agentWorkload.find((row) => row.agent === 'unassigned' && row.openBacklog > 0)
    if (unowned) flags.push(`Unowned backlog detected: ${unowned.openBacklog} open tickets.`)
    if (currentRows.length >= 2 && currentRows[currentRows.length - 1].first_response_time > currentRows[0].first_response_time) flags.push('First response time is worsening across the selected range.')
    if (themeRows[0] && themeRows[0].ticketsPer100Orders > 25) flags.push(`Theme spike alert: ${themeRows[0].theme} at ${themeRows[0].ticketsPer100Orders.toFixed(2)} tickets / 100 orders.`)
    return flags
  }, [agentWorkload, currentRows, themeRows])

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Support / CX</h2>
        <p>Management-grade view of support workload, speed, issue burden, and operational flags.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>

      <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />

      {loading ? <Card title="Support Status"><div className="state-message">Loading live support data…</div></Card> : null}
      {error ? <Card title="Support Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <div className="three-col">
            <Card title="Selected Range Avg Tickets / 100 Orders"><div className="hero-metric">{burdenAvg.toFixed(2)}</div></Card>
            <Card title="Latest Open Backlog"><div className="hero-metric">{currentRows[currentRows.length - 1]?.open_backlog ?? 0}</div></Card>
            <Card title="Management Flags">
              <div className="stack-list">
                {managementFlags.map((flag, index) => <div className="list-item status-warn" key={index}><p>{flag}</p></div>)}
                {!managementFlags.length ? <div className="list-item status-good"><p>No management flags triggered for the selected range.</p></div> : null}
              </div>
            </Card>
          </div>

          <div className="two-col">
            <Card title="Team Workload">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th>Assigned</th>
                      <th>Assigned Share</th>
                      <th>Resolved</th>
                      <th>Resolved Share</th>
                      <th>Open Backlog</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agentWorkload.map((row) => (
                      <tr key={row.agent}>
                        <td>{row.agent}</td>
                        <td>{row.assigned}</td>
                        <td>{row.assignedShare}</td>
                        <td>{row.resolved}</td>
                        <td>{row.resolvedShare}</td>
                        <td>{row.openBacklog}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card title="Response Performance">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Agent</th>
                      <th>Avg FRT</th>
                      <th>Median FRT</th>
                      <th>Avg Resolution</th>
                      <th>Median Resolution</th>
                      <th>Resolved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {responsePerformance.map((row) => (
                      <tr key={`${row.agent}-perf`}>
                        <td>{row.agent}</td>
                        <td>{row.avgFirstResponse.toFixed(2)}h</td>
                        <td>{row.medianFirstResponse.toFixed(2)}h</td>
                        <td>{row.avgResolution.toFixed(2)}h</td>
                        <td>{row.medianResolution.toFixed(2)}h</td>
                        <td>{row.resolved}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <div className="two-col">
            <Card title="Issue Intelligence">
              <div className="stack-list">
                {themeRows.slice(0, 8).map((row) => (
                  <div className="list-item" key={row.theme}>
                    <div className="item-head">
                      <strong>{row.theme}</strong>
                      <span className="badge badge-neutral">{row.count} tickets</span>
                    </div>
                    <small>Tickets / 100 orders: {row.ticketsPer100Orders.toFixed(2)}</small>
                    <small>Severity mix: {row.severityMix}</small>
                    <small>Open backlog in theme: {row.open}</small>
                  </div>
                ))}
                {!themeRows.length ? <div className="state-message">No issue-theme rows returned.</div> : null}
              </div>
            </Card>

            <Card title="Rising Issue Alerts">
              <div className="stack-list">
                {(issues?.fastest_rising || []).slice(0, 6).map((item) => (
                  <div className="list-item" key={item.id}>
                    <strong>{item.title}</strong>
                    <p>{String(item.details_json?.recommended_action || 'No action')}</p>
                    <small>Trend: {String(item.details_json?.trend_pct ?? 'n/a')}% · Urgency: {String(item.details_json?.urgency ?? 'n/a')} · Owner: {item.owner_team || 'TBD'}</small>
                    <small>Priority reason: {String(item.details_json?.priority_reason_summary || 'n/a')}</small>
                  </div>
                ))}
                {!(issues?.fastest_rising || []).length ? <div className="state-message">No rising issue alerts returned.</div> : null}
              </div>
            </Card>
          </div>

          <div className="two-col two-col-equal">
            <Card title="Created vs Resolved Trend">
              {currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'tickets_created', label: 'Created', color: '#ffb257', axisId: 'left' }, { key: 'tickets_resolved', label: 'Resolved', color: '#39d08f', axisId: 'right' }]} /> : <div className="state-message">No support trend rows returned.</div>}
            </Card>
            <Card title="Open Backlog Trend">
              {currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'open_backlog', label: 'Open Backlog', color: '#ff6d7a', axisId: 'left' }]} height={220} /> : <div className="state-message">No backlog trend rows returned.</div>}
            </Card>
          </div>

          <div className="two-col two-col-equal">
            <Card title="First Response Time Trend">
              {currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'first_response_time', label: 'First Response Time', color: '#6ea8ff', axisId: 'left' }]} height={220} /> : <div className="state-message">No response-time rows returned.</div>}
            </Card>
            <Card title="Resolution Time Trend">
              {currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'resolution_time', label: 'Resolution Time', color: '#39d08f', axisId: 'left' }]} height={220} /> : <div className="state-message">No resolution-time rows returned.</div>}
            </Card>
          </div>

          <Card title="Support Trend Table">
            {currentRows.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Tickets Created</th>
                      <th>Tickets Resolved</th>
                      <th>Open Backlog</th>
                      <th>FRT</th>
                      <th>Resolution</th>
                      <th>SLA Breach</th>
                      <th>Tickets / 100 Orders</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentRows.map((row) => (
                      <tr key={row.business_date}>
                        <td>{row.business_date}</td>
                        <td>{row.tickets_created}</td>
                        <td>{row.tickets_resolved}</td>
                        <td>{row.open_backlog}</td>
                        <td>{row.first_response_time.toFixed(2)}h</td>
                        <td>{row.resolution_time.toFixed(2)}h</td>
                        <td>{row.sla_breach_rate.toFixed(2)}%</td>
                        <td>{row.tickets_per_100_orders.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="state-message">No support KPI rows returned.</div>
            )}
          </Card>
        </>
      ) : null}
    </div>
  )
}
