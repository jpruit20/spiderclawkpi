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

  const addToCartRate = currentRows.length ? currentRows.reduce((sum, row) => sum + Number(row.add_to_cart_rate || 0), 0) / currentRows.length : 0
  const priorAddToCartRate = priorRows.length ? priorRows.reduce((sum, row) => sum + Number(row.add_to_cart_rate || 0), 0) / priorRows.length : 0
  const pdpViewsEstimate = sessions * 0.62
  const priorPdpViewsEstimate = priorSessions * 0.62
  const addToCartEstimate = pdpViewsEstimate * (addToCartRate / 100)
  const priorAddToCartEstimate = priorPdpViewsEstimate * (priorAddToCartRate / 100)
  const checkoutEstimate = addToCartEstimate * 0.58
  const priorCheckoutEstimate = priorAddToCartEstimate * 0.58
  const purchaseEstimate = orders
  const priorPurchaseEstimate = priorOrders
  const funnel = [
    { label: 'Sessions', volume: sessions, prior: priorSessions, conversion: 100, dropoff: 0, trend: compareValue(sessions, priorSessions, 'Sessions').deltaPct },
    { label: 'PDP', volume: pdpViewsEstimate, prior: priorPdpViewsEstimate, conversion: sessions ? (pdpViewsEstimate / sessions) * 100 : 0, dropoff: sessions ? (1 - (pdpViewsEstimate / sessions)) * 100 : 0, trend: compareValue(pdpViewsEstimate, priorPdpViewsEstimate, 'PDP').deltaPct },
    { label: 'Add to Cart', volume: addToCartEstimate, prior: priorAddToCartEstimate, conversion: pdpViewsEstimate ? (addToCartEstimate / pdpViewsEstimate) * 100 : 0, dropoff: pdpViewsEstimate ? (1 - (addToCartEstimate / pdpViewsEstimate)) * 100 : 0, trend: compareValue(addToCartEstimate, priorAddToCartEstimate, 'ATC').deltaPct },
    { label: 'Checkout', volume: checkoutEstimate, prior: priorCheckoutEstimate, conversion: addToCartEstimate ? (checkoutEstimate / addToCartEstimate) * 100 : 0, dropoff: addToCartEstimate ? (1 - (checkoutEstimate / addToCartEstimate)) * 100 : 0, trend: compareValue(checkoutEstimate, priorCheckoutEstimate, 'Checkout').deltaPct },
    { label: 'Purchase', volume: purchaseEstimate, prior: priorPurchaseEstimate, conversion: checkoutEstimate ? (purchaseEstimate / checkoutEstimate) * 100 : 0, dropoff: checkoutEstimate ? (1 - (purchaseEstimate / checkoutEstimate)) * 100 : 0, trend: compareValue(purchaseEstimate, priorPurchaseEstimate, 'Purchase').deltaPct },
  ]
  const topFriction = issues?.highest_business_risk?.[0] || issues?.clusters?.[0]
  const frictionItems = [
    { label: 'Highest drop-off path', text: topFriction?.title || 'Awaiting ranked friction source', confidence: clarityDegraded ? 'Reduced confidence' : 'Normal confidence', corroborated: Boolean(topFriction) },
    { label: 'Rage-click pages', text: clarityDegraded ? 'Clarity data degraded — insights have reduced confidence' : 'Use Friction Map for rage-click page detail', confidence: clarityDegraded ? 'Reduced confidence' : 'Normal confidence', corroborated: false },
    { label: 'Dead-click clusters', text: clarityDegraded ? 'Clarity data degraded — dead-click clusters are currently low-confidence' : 'Use Friction Map for dead-click cluster detail', confidence: clarityDegraded ? 'Reduced confidence' : 'Normal confidence', corroborated: false },
  ]
  const campaignBreakdownAvailable = false
  const landingPageBreakdownAvailable = false
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
          <div className="five-col">
            <Card title="Revenue"><div className="hero-metric hero-metric-sm">{currency(revenue)}</div><small>Prior {currency(priorRevenue)} · {formatDeltaPct(compareValue(revenue, priorRevenue, 'Revenue').deltaPct)}</small></Card>
            <Card title="Conversion rate"><div className="hero-metric hero-metric-sm">{conversion.toFixed(2)}%</div><small>Prior {priorConversion.toFixed(2)}%</small></Card>
            <Card title="AOV"><div className="hero-metric hero-metric-sm">{currency(aov)}</div><small>Prior {currency(priorAov)}</small></Card>
            <Card title="Sessions"><div className="hero-metric hero-metric-sm">{sessions.toFixed(0)}</div><small>Prior {priorSessions.toFixed(0)}</small></Card>
            <Card title="MER"><div className="hero-metric hero-metric-sm">{mer.toFixed(2)}</div><small>Prior {priorMer.toFixed(2)}</small></Card>
          </div>
          <Card title="Funnel">
            <div className="five-col">
              {funnel.map((step) => (
                <div className="list-item" key={step.label}>
                  <strong>{step.label}</strong>
                  <p>{Math.round(step.volume).toLocaleString()}</p>
                  <small>Conversion {step.conversion.toFixed(1)}%</small>
                  <small>Drop-off {step.dropoff.toFixed(1)}%</small>
                  <small>Trend {formatDeltaPct(step.trend)}</small>
                </div>
              ))}
            </div>
            <small><strong>Estimated funnel — intermediate stages are modeled.</strong> PDP and checkout stages are not event-perfect counts from a canonical funnel event feed yet.</small>
          </Card>
          <div className="three-col">
            <Card title="Page-level friction">
              <div className="stack-list compact">
                {frictionItems.map((item, idx) => <div className="list-item status-warn" key={idx}><strong>{item.label}</strong><p>{item.text}</p><small>{item.confidence}{clarityDegraded && !item.corroborated ? ' · Will not drive top-ranked actions without non-Clarity corroboration' : ''}</small></div>)}
              </div>
            </Card>
            <Card title="What’s working">
              <div className="stack-list compact">
                <div className="list-item status-good"><p>{mer >= priorMer ? 'Channel efficiency is not deteriorating versus the comparison period.' : 'Efficient-channel mix needs attention.'}</p></div>
                <div className="list-item status-good"><p>{aov >= priorAov ? 'AOV is holding or improving.' : 'AOV is softer than the comparison period.'}</p></div>
              </div>
            </Card>
            <Card title="What’s not / What to do">
              <div className="stack-list compact">
                <div className="list-item status-bad"><strong>WHAT’S NOT</strong><p>{conversion < priorConversion ? 'Conversion is down versus the selected comparison window.' : 'Conversion is not currently the primary regression.'}</p></div>
                <div className="list-item status-warn"><strong>WHAT TO DO</strong><p>{actions[0]}</p><small><strong>OWNER:</strong> Bailey · <strong>SLA:</strong> This week</small></div>
                <div className="list-item status-warn"><strong>WHAT TO DO</strong><p>{actions[1]}</p><small><strong>OWNER:</strong> Bailey · <strong>SLA:</strong> This week</small></div>
              </div>
            </Card>
          </div>
          <div className="two-col two-col-equal">
            <Card title="Campaign-level breakdown">
              <div className="stack-list compact">
                <div className="list-item status-warn"><strong>{campaignBreakdownAvailable ? 'Campaign breakdown available' : 'Campaign-level breakdown unavailable'}</strong><p>{campaignBreakdownAvailable ? 'Campaign conversion and efficiency rows would render here.' : 'Current backend does not expose campaign-level marketing performance yet.'}</p><small>{campaignBreakdownAvailable ? 'Live campaign table' : 'Awaiting source feed / backend model.'}</small></div>
              </div>
            </Card>
            <Card title="Landing page by source">
              <div className="stack-list compact">
                <div className="list-item status-warn"><strong>{landingPageBreakdownAvailable ? 'Landing page breakdown available' : 'Landing page performance by source unavailable'}</strong><p>{landingPageBreakdownAvailable ? 'Landing pages by source/medium would render here.' : 'Current backend does not expose landing-page-by-source performance yet.'}</p><small>{landingPageBreakdownAvailable ? 'Live landing page table' : 'Awaiting GA4/source feed and backend model.'}</small></div>
              </div>
            </Card>
          </div>
          <Card title="Marketing drill-downs">
            <div className="stack-list compact">
              <div className="list-item status-muted"><strong>View friction details</strong><p><a href="/friction">Open Friction Map</a></p></div>
              <div className="list-item status-muted"><strong>View root cause</strong><p><a href="/root-cause">Open Root Cause</a></p></div>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
