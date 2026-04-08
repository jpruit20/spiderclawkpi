import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { CompareToolbar } from '../components/CompareToolbar'
import { RangeToolbar } from '../components/RangeToolbar'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { currency } from '../lib/operatingModel'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { CompareMode as Mode } from '../lib/compare'
import { ActionObject, BlockedStateOutput, IssueRadarResponse, KPIDaily, KPIObject, OverviewResponse, SourceHealthItem } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, buildTextKpi, enforceActionContract, truthStateFromSource } from '../lib/divisionContract'

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
  const snapshotTimestamp = currentRows.at(-1)?.business_date ? `${currentRows.at(-1)?.business_date}T23:59:59Z` : new Date().toISOString()
  const topFrictionTruthState = clarityDegraded ? 'degraded' : 'proxy'
  const kpis: KPIObject[] = [
    buildNumericKpi({ key: 'marketing_revenue', currentValue: revenue, targetValue: priorRevenue || null, priorValue: priorRevenue || null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_conversion_rate', currentValue: conversion, targetValue: priorConversion || null, priorValue: priorConversion || null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_mer', currentValue: mer, targetValue: priorMer || null, priorValue: priorMer || null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_add_to_cart_rate', currentValue: addToCartRate, targetValue: priorAddToCartRate || null, priorValue: priorAddToCartRate || null, owner: 'Bailey', truthState: 'proxy', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_checkout_completion', currentValue: checkoutEstimate ? (purchaseEstimate / checkoutEstimate) * 100 : 0, targetValue: priorCheckoutEstimate ? (priorPurchaseEstimate / priorCheckoutEstimate) * 100 : null, priorValue: priorCheckoutEstimate ? (priorPurchaseEstimate / priorCheckoutEstimate) * 100 : null, owner: 'Bailey', truthState: 'estimated', lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'marketing_top_friction', currentValue: topFriction?.title || 'Awaiting ranked friction source', targetValue: 'No dominant leak', owner: 'Bailey', status: topFriction ? 'red' : 'yellow', truthState: topFrictionTruthState, lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_channel_revenue_breakdown', currentValue: campaignBreakdownAvailable ? 1 : null, targetValue: 1, priorValue: null, owner: 'Bailey', truthState: 'blocked', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_campaign_breakdown', currentValue: landingPageBreakdownAvailable ? 1 : null, targetValue: 1, priorValue: null, owner: 'Bailey', truthState: 'blocked', lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'marketing_clarity_behavior_evidence', currentValue: clarityDegraded ? 'Clarity degraded' : 'Clarity healthy', targetValue: 'Clarity healthy', owner: 'Bailey', status: clarityDegraded ? 'red' : 'green', truthState: truthStateFromSource(sourceHealth, ['clarity'], 'proxy'), lastUpdated: snapshotTimestamp }),
  ]

  const blockedStates: Record<string, BlockedStateOutput> = {
    marketing_channel_revenue_breakdown: buildBlockedState({
      decision_blocked: 'Which channel should gain or lose spend this week',
      missing_source: 'channel-level revenue mapping feed',
      still_trustworthy: ['total revenue', 'orders', 'sessions', 'MER'],
      owner: 'Bailey',
      required_action_to_unblock: 'Restore channel revenue feed before reallocating spend by channel',
    }),
    marketing_campaign_breakdown: buildBlockedState({
      decision_blocked: 'Which campaign should be scaled, paused, or rewritten',
      missing_source: 'campaign-level performance feed',
      still_trustworthy: ['blended MER', 'overall conversion', 'total spend'],
      owner: 'Bailey',
      required_action_to_unblock: 'Add campaign-level performance rows before making campaign-specific optimization calls',
    }),
    marketing_clarity_behavior_evidence: buildBlockedState({
      decision_blocked: 'Which page-level friction should be treated as the top-confidence marketing fix',
      missing_source: 'reliable Clarity behavioral evidence',
      still_trustworthy: ['GA4 funnel movement', 'Shopify purchases', 'top issue cluster'],
      owner: 'Joseph',
      required_action_to_unblock: 'Recover Clarity health and require corroboration until it is healthy',
    }),
  }

  const actions: ActionObject[] = enforceActionContract([
    actionFromKpi({
      id: 'marketing-conversion-fix',
      triggerKpi: kpis.find((item) => item.key === 'marketing_conversion_rate')!,
      triggerCondition: 'conversion declines vs prior period',
      owner: 'Bailey',
      coOwner: 'Kyle',
      escalationOwner: 'Joseph',
      requiredAction: 'Fix the top high-traffic friction path before adding more spend.',
      priority: conversion < priorConversion ? 'critical' : 'high',
      evidence: ['ga4', 'clarity', 'shopify'],
      dueDate: 'this week',
      snapshotTimestamp,
      baseRankingScore: 95,
    }),
    actionFromKpi({
      id: 'marketing-mer-reallocation',
      triggerKpi: kpis.find((item) => item.key === 'marketing_mer')!,
      triggerCondition: 'MER softens vs prior period',
      owner: 'Bailey',
      escalationOwner: 'Joseph',
      requiredAction: mer < priorMer ? 'Reallocate spend away from lower-efficiency traffic until channel mix recovers.' : 'Keep scale pressure on the best-performing channels.',
      priority: mer < priorMer ? 'high' : 'medium',
      evidence: ['triplewhale', 'shopify'],
      dueDate: 'this week',
      snapshotTimestamp,
      baseRankingScore: 80,
    }),
    actionFromKpi({
      id: 'marketing-unblock-channel-revenue',
      triggerKpi: kpis.find((item) => item.key === 'marketing_channel_revenue_breakdown')!,
      triggerCondition: 'truth_state = blocked',
      owner: 'Bailey',
      coOwner: 'Joseph',
      requiredAction: 'Unblock channel revenue feed before reallocating spend by channel.',
      priority: 'critical',
      evidence: ['marketing page', 'backend model gap'],
      dueDate: 'next sync',
      snapshotTimestamp,
      baseRankingScore: 70,
      blockedState: blockedStates.marketing_channel_revenue_breakdown,
    }),
    actionFromKpi({
      id: 'marketing-unblock-campaign-breakdown',
      triggerKpi: kpis.find((item) => item.key === 'marketing_campaign_breakdown')!,
      triggerCondition: 'truth_state = blocked',
      owner: 'Bailey',
      coOwner: 'Joseph',
      requiredAction: 'Unblock campaign performance feed before campaign-specific optimization.',
      priority: 'critical',
      evidence: ['marketing page', 'backend model gap'],
      dueDate: 'next sync',
      snapshotTimestamp,
      baseRankingScore: 65,
      blockedState: blockedStates.marketing_campaign_breakdown,
    }),
    actionFromKpi({
      id: 'marketing-clarity-degraded',
      triggerKpi: kpis.find((item) => item.key === 'marketing_clarity_behavior_evidence')!,
      triggerCondition: 'truth_state = degraded',
      owner: 'Joseph',
      coOwner: 'Bailey',
      requiredAction: clarityDegraded ? 'Recover Clarity and do not top-rank page-friction actions without corroboration.' : `Use Clarity and GA4 together to validate whether ${topFriction?.title || 'the leading friction signal'} is truly suppressing conversion.`,
      priority: clarityDegraded ? 'high' : 'medium',
      evidence: ['clarity', 'ga4', 'issue radar'],
      dueDate: 'next sync',
      snapshotTimestamp,
      baseRankingScore: 90,
      blockedState: blockedStates.marketing_clarity_behavior_evidence,
    }),
  ])

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
                <div className="list-item status-warn"><strong>WHAT TO DO</strong><p>{actions[0]?.required_action}</p><small><strong>OWNER:</strong> {actions[0]?.owner} · <strong>DUE:</strong> {actions[0]?.due_date} · <strong>truth_state:</strong> {(actions[0] as any)?.truth_state}</small></div>
                <div className="list-item status-warn"><strong>WHAT TO DO</strong><p>{actions[1]?.required_action}</p><small><strong>OWNER:</strong> {actions[1]?.owner} · <strong>DUE:</strong> {actions[1]?.due_date} · <strong>truth_state:</strong> {(actions[1] as any)?.truth_state}</small></div>
              </div>
            </Card>
          </div>
          <div className="two-col two-col-equal">
            <Card title="Campaign-level breakdown">
              <div className="stack-list compact">
                <div className="list-item status-bad"><strong>{kpis.find((item) => item.key === 'marketing_campaign_breakdown')?.key}</strong><p>{blockedStates.marketing_campaign_breakdown.decision_blocked}</p><small><strong>truth_state:</strong> blocked · <strong>missing source:</strong> {blockedStates.marketing_campaign_breakdown.missing_source}</small><small><strong>owner:</strong> {blockedStates.marketing_campaign_breakdown.owner} · <strong>next action:</strong> {blockedStates.marketing_campaign_breakdown.required_action_to_unblock}</small></div>
              </div>
            </Card>
            <Card title="Landing page by source">
              <div className="stack-list compact">
                <div className={`list-item status-${clarityDegraded ? 'warn' : 'good'}`}><strong>{kpis.find((item) => item.key === 'marketing_clarity_behavior_evidence')?.key}</strong><p>{clarityDegraded ? blockedStates.marketing_clarity_behavior_evidence.decision_blocked : 'Clarity evidence is healthy enough to support page-level friction review.'}</p><small><strong>truth_state:</strong> {kpis.find((item) => item.key === 'marketing_clarity_behavior_evidence')?.truth_state} · <strong>owner:</strong> {kpis.find((item) => item.key === 'marketing_clarity_behavior_evidence')?.owner}</small><small><strong>next action:</strong> {actions.find((item) => item.id === 'marketing-clarity-degraded')?.required_action}</small></div>
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
