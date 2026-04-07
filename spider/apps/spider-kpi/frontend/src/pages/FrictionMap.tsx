import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { confidenceScore, currency, frictionRankingScore, impactFromConversion } from '../lib/operatingModel'
import { FreshdeskTicketItem, IssueRadarResponse, KPIDaily, SourceHealthItem } from '../lib/types'

function normalizeDate(value?: string) {
  return value ? value.slice(0, 10) : undefined
}

function themeName(ticket: FreshdeskTicketItem) {
  return ticket.category || ticket.tags_json?.[0] || 'unclassified'
}

export function FrictionMap() {
  const [issues, setIssues] = useState<IssueRadarResponse | null>(null)
  const [tickets, setTickets] = useState<FreshdeskTicketItem[]>([])
  const [supportRows, setSupportRows] = useState<KPIDaily[]>([])
  const [sourceHealth, setSourceHealth] = useState<SourceHealthItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [issuesPayload, ticketsPayload, supportPayload, sourcePayload] = await Promise.all([
          api.issues(),
          api.supportTickets(),
          api.supportOverview(),
          api.sourceHealth(),
        ])
        if (cancelled) return
        setIssues(issuesPayload)
        setTickets(ticketsPayload)
        setSupportRows(supportPayload.rows || [])
        setSourceHealth(sourcePayload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load friction map')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const recentRows = supportRows.slice(-7)
  const recentOrders = recentRows.reduce((sum, row) => sum + Number(row.orders || 0), 0)
  const latestAov = recentRows.length ? recentRows.reduce((sum, row) => sum + Number(row.average_order_value || 0), 0) / recentRows.length : 0
  const frictionQueue = useMemo(() => {
    const themeMap = new Map<string, { theme: string; count: number; open: number }>()
    const windowStart = recentRows[0]?.business_date
    tickets.forEach((ticket) => {
      const created = normalizeDate(ticket.created_at_source)
      if (windowStart && created && created < windowStart) return
      const theme = themeName(ticket)
      if (!themeMap.has(theme)) themeMap.set(theme, { theme, count: 0, open: 0 })
      const row = themeMap.get(theme)!
      row.count += 1
      if (!ticket.resolved_at_source) row.open += 1
    })
    const issueMap = new Map((issues?.clusters || []).map((item) => [item.title.toLowerCase(), item]))
    return [...themeMap.values()].map((row) => {
      const linkedIssue = issueMap.get(row.theme.toLowerCase())
      const trafficFactor = Math.max(0.2, recentOrders / 1000)
      const frictionFactor = Math.max(0.08, row.count / Math.max(1, recentOrders))
      const impact = impactFromConversion(recentOrders * 2.2 * trafficFactor, frictionFactor * 100, latestAov) * 7
      const confidence = confidenceScore({
        sourceHealth,
        requiredSources: ['ga4', 'clarity', 'freshdesk'],
        sampleSize: row.count * 100,
        completeness: linkedIssue ? Number(linkedIssue.confidence || 0.65) : 0.6,
      })
      const corroborated = Boolean(linkedIssue)
      const rankingScore = frictionRankingScore({
        impact,
        confidence,
        sourceHealth,
        usesClarity: true,
        corroborated,
      })
      return {
        theme: row.theme,
        open: row.open,
        count: row.count,
        traffic: recentOrders,
        impact,
        confidence,
        corroborated,
        rankingScore,
        owner: linkedIssue?.owner_team || 'Product + CX',
        why: linkedIssue ? String(linkedIssue.details_json?.priority_reason_summary || 'Linked issue cluster is rising.') : 'Support burden indicates recurring friction worth fixing.',
      }
    }).sort((a, b) => b.rankingScore - a.rankingScore).slice(0, 5)
  }, [tickets, issues, recentRows, recentOrders, latestAov, sourceHealth])

  const telemetry = {
    ga4: sourceHealth.find((row) => row.source === 'ga4'),
    clarity: sourceHealth.find((row) => row.source === 'clarity'),
    freshdesk: sourceHealth.find((row) => row.source === 'freshdesk'),
  }
  const clarityDegraded = telemetry.clarity?.derived_status !== 'healthy'

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Friction Map</h2>
        <p>Merge UX and CX into one ranked friction surface: high friction + high traffic + revenue drag.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Friction Map"><div className="state-message">Loading friction signals…</div></Card> : null}
      {error ? <Card title="Friction Map Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          {clarityDegraded ? (
            <div className="trust-banner trust-banner-degraded">
              <div>
                <strong>Clarity degraded</strong>
                <p>Clarity is rate-limited or stale. Friction conclusions that would normally depend on rage/dead click evidence are being shown with lower confidence.</p>
              </div>
            </div>
          ) : null}
          <div className="three-col">
            <Card title="Telemetry Inputs"><div className="hero-metric">{Object.values(telemetry).filter((row) => row?.derived_status === 'healthy').length}/3</div><div className="state-message">GA4 + Clarity + Freshdesk feeding friction decisions</div></Card>
            <Card title="Priority Frictions"><div className="hero-metric">{frictionQueue.length}</div><div className="state-message">Ranked by impact × confidence</div></Card>
            <Card title="Traffic Context"><div className="hero-metric">{recentOrders}</div><div className="state-message">Orders across the recent friction window</div></Card>
          </div>
          <Card title="Ranked Friction Queue">
            <div className="stack-list">
              {frictionQueue.map((item, index) => (
                <div className={`list-item ${index === 0 ? 'status-bad' : 'status-warn'}`} key={item.theme}>
                  <div className="item-head">
                    <strong>{index + 1}. {item.theme}</strong>
                    <div className="inline-badges">
                      <span className="badge badge-good">{currency(item.impact)}/week</span>
                      <span className="badge badge-neutral">confidence {item.confidence.toFixed(2)}</span>
                      {clarityDegraded ? <span className="badge badge-warn">Clarity degraded</span> : null}
                      {clarityDegraded && !item.corroborated ? <span className="badge badge-warn">needs corroboration</span> : null}
                    </div>
                  </div>
                  <p>{item.why}</p>
                  <small>Owner {item.owner} · open tickets {item.open} · total signals {item.count} · traffic base {item.traffic} orders</small>
                </div>
              ))}
            </div>
          </Card>
          <div className="two-col two-col-equal">
            <Card title="Data Trust Layer">
              <div className="stack-list compact">
                {Object.entries(telemetry).map(([name, row]) => (
                  <div className={`list-item status-${row?.derived_status === 'healthy' ? 'good' : row?.derived_status === 'failed' ? 'bad' : 'warn'}`} key={name}>
                    <strong>{name}</strong>
                    <small>{row?.status_summary || 'Missing'}</small>
                  </div>
                ))}
              </div>
            </Card>
            <Card title="What to do next">
              <div className="stack-list compact">
                <div className="list-item"><strong>Fix first</strong><p>{frictionQueue[0]?.theme || 'No friction cluster ranked yet.'}</p></div>
                <div className="list-item"><strong>Why</strong><p>{frictionQueue[0]?.why || 'Need merged support + behavior evidence.'}</p></div>
                <div className="list-item"><strong>Financial impact</strong><p>{frictionQueue[0] ? `${currency(frictionQueue[0].impact)}/week` : '$0/week'}</p></div>
              </div>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}
