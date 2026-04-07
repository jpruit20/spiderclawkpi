import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { CompareToolbar } from '../components/CompareToolbar'
import { RangeToolbar } from '../components/RangeToolbar'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { currency } from '../lib/operatingModel'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { CompareMode as Mode } from '../lib/compare'
import { IssueRadarResponse, KPIDaily, OverviewResponse, SourceHealthItem } from '../lib/types'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

function clarityIsDegraded(sourceHealth: SourceHealthItem[]) {
  const clarity = sourceHealth.find((row) => row.source === 'clarity')
  return clarity && clarity.derived_status !== 'healthy'
}

export function MarketingDivision() {
  const todayDate = businessTodayDate()
  const [rows, setRows] = useState<KPIDaily[]>([])
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [issues, setIssues] = useState<IssueRadarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '30d', startDate: '', endDate: '' })
  const [compareMode, setCompareMode] = useState<Mode>('prior_period')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [dailyPayload, overviewPayload, issuesPayload] = await Promise.all([
          api.dailyKpis(),
          api.overview(),
          api.issues(),
        ])
        if (cancelled) return
        const ordered = [...dailyPayload].sort((a, b) => a.business_date.localeCompare(b.business_date))
        setRows(ordered)
        setOverview(overviewPayload)
        setIssues(issuesPayload)
        setRange((current) => current.startDate && current.endDate ? current : buildPresetRange('30d', ordered, { anchorDate: todayDate }))
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load marketing division')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const currentRows = useMemo(() => filterRowsByRange(rows, range), [rows, range])
  const priorRows = useMemo(() => compareMode === 'same_day_last_week' ? sameDayLastWeekRows(rows, currentRows) : priorPeriodRows(rows, currentRows[0]?.business_date || '', currentRows.length), [compareMode, rows, currentRows])
  const sourceHealth = overview?.source_health || []
  const clarityDegraded = clarityIsDegraded(sourceHealth)

  const revenue = sum(currentRows, 'revenue')
  const priorRevenue = sum(priorRows, 'revenue')
  const refunds = sum(currentRows, 'refunds' as keyof KPIDaily)
  const priorRefunds = sum(priorRows, 'refunds' as keyof KPIDaily)
  const sessions = sum(currentRows, 'sessions')
  const priorSessions = sum(priorRows, 'sessions')
  const orders = sum(currentRows, 'orders')
  const priorOrders = sum(priorRows, 'orders')
  const adSpend = sum(currentRows, 'ad_spend')
  const priorAdSpend = sum(priorRows, 'ad_spend')
  const aov = orders ? revenue / orders : 0
  const priorAov = priorOrders ? priorRevenue / priorOrders : 0
  const conversion = sessions ? (orders / sessions) * 100 : 0
  const priorConversion = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const mer = adSpend ? revenue / adSpend : 0
  const priorMer = priorAdSpend ? priorRevenue / priorAdSpend : 0
  const grossProfitProxy = revenue - refunds
  const priorGrossProfitProxy = priorRevenue - priorRefunds
  const contributionProxy = grossProfitProxy - adSpend
  const priorContributionProxy = priorGrossProfitProxy - priorAdSpend

  const topFriction = issues?.highest_business_risk?.[0] || issues?.clusters?.[0]
  const actions = [
    conversion < priorConversion ? `Conversion is down ${formatDeltaPct(compareValue(conversion, priorConversion, 'Conversion').deltaPct)}. Fix the top high-traffic friction path before adding more spend.` : 'Conversion is not the main drag right now; preserve funnel changes and focus on scaling efficient traffic.',
    mer < priorMer ? `MER softened to ${mer.toFixed(2)}. Reallocate spend away from lower-efficiency traffic until channel mix recovers.` : `MER is holding at ${mer.toFixed(2)}. Keep scale pressure on the best-performing channels.`,
    clarityDegraded ? 'Clarity is degraded/rate-limited. Treat rage/dead-click evidence as low confidence until the connector recovers.' : `Use Clarity and GA4 together to validate whether ${topFriction?.title || 'the leading friction signal'} is truly suppressing conversion.`,
  ]

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Marketing</h2>
        <p>Bailey’s page: traffic efficiency, conversion, funnel drag, and what to fix this week.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />
      <CompareToolbar mode={compareMode} onChange={setCompareMode as (mode: CompareMode) => void} />
      {loading ? <Card title="Marketing"><div className="state-message">Loading marketing division…</div></Card> : null}
      {error ? <Card title="Marketing Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          {clarityDegraded ? (
            <div className="trust-banner trust-banner-degraded">
              <div>
                <strong>Clarity degraded</strong>
                <p>Clarity is currently rate-limited or stale. Friction insights that depend on Clarity are annotated as lower confidence until source health recovers.</p>
              </div>
            </div>
          ) : null}
          <div className="four-col">
            <Card title="Revenue"><div className="hero-metric hero-metric-sm">{currency(revenue)}</div><small>Prior {currency(priorRevenue)} · {currency(revenue - priorRevenue)} · {formatDeltaPct(compareValue(revenue, priorRevenue, 'Revenue').deltaPct)}</small></Card>
            <Card title="Sessions"><div className="hero-metric hero-metric-sm">{sessions.toFixed(0)}</div><small>Prior {priorSessions.toFixed(0)} · {formatDeltaPct(compareValue(sessions, priorSessions, 'Sessions').deltaPct)}</small></Card>
            <Card title="Conversion"><div className="hero-metric hero-metric-sm">{conversion.toFixed(2)}%</div><small>Prior {priorConversion.toFixed(2)}% · {formatDeltaPct(compareValue(conversion, priorConversion, 'Conversion').deltaPct)}</small></Card>
            <Card title="MER"><div className="hero-metric hero-metric-sm">{mer.toFixed(2)}</div><small>Prior {priorMer.toFixed(2)} · {formatDeltaPct(compareValue(mer, priorMer, 'MER').deltaPct)}</small></Card>
          </div>
          <div className="three-col">
            <Card title="What’s working"><div className="stack-list compact"><div className="list-item status-good"><p>{mer >= priorMer ? 'Channel efficiency is not deteriorating versus the comparison period.' : 'Efficient-channel mix needs attention.'}</p></div><div className="list-item status-good"><p>{aov >= priorAov ? 'AOV is holding or improving.' : 'AOV is softer than the comparison period.'}</p></div></div></Card>
            <Card title="What’s not working"><div className="stack-list compact"><div className="list-item status-bad"><p>{conversion < priorConversion ? 'Conversion is down versus the selected comparison window.' : 'Conversion is not currently the primary regression.'}</p></div><div className="list-item status-bad"><p>{clarityDegraded ? 'Clarity-based friction evidence is degraded by rate limiting.' : (topFriction?.title ? `Top friction risk: ${topFriction.title}` : 'No ranked friction risk returned.')}</p></div></div></Card>
            <Card title="What to do"><div className="stack-list compact">{actions.map((item, idx) => <div className="list-item status-warn" key={idx}><p>{item}</p></div>)}</div></Card>
          </div>
        </>
      ) : null}
    </div>
  )
}
