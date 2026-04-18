import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { TruthBadge } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ClickUpComplianceCard } from '../components/ClickUpComplianceCard'
import { ClickUpOverlayChart } from '../components/ClickUpOverlayChart'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { ClickUpVelocityCard } from '../components/ClickUpVelocityCard'
import { SlackPulseCard } from '../components/SlackPulseCard'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { RangeToolbar } from '../components/RangeToolbar'
import { CompareToolbar } from '../components/CompareToolbar'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { currency, fmtInt, fmtPct, deltaPct, deltaDirection } from '../lib/format'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { CompareMode as Mode } from '../lib/compare'
import { ActionObject, BlockedStateOutput, ClarityPageMetric, IssueRadarResponse, KPIDaily, KPIObject, OverviewResponse, SocialTrendsResponse, SourceHealthItem } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, buildTextKpi, enforceActionContract, truthStateFromSource } from '../lib/divisionContract'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

function clarityIsDegraded(sourceHealth: SourceHealthItem[]) {
  const clarity = sourceHealth.find((row) => row.source === 'clarity')
  return clarity && clarity.derived_status !== 'healthy'
}

const DRILL_ROUTES = [
  { path: '/friction', label: 'Friction Map', icon: '\u26A0' },
  { path: '/root-cause', label: 'Root Cause', icon: '\uD83D\uDD0D' },
  { path: '/revenue', label: 'Revenue', icon: '\uD83D\uDCC8' },
]

const FUNNEL_COLORS: Record<string, string> = {
  Sessions: 'var(--blue)',
  PDP: '#5b8ad8',
  'Add to Cart': 'var(--orange)',
  Checkout: '#c98a3a',
  Purchase: 'var(--green)',
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function MarketingDivision() {
  const todayDate = businessTodayDate()
  const [rows, setRows] = useState<KPIDaily[]>([])
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [issues, setIssues] = useState<IssueRadarResponse | null>(null)
  const [socialTrends, setSocialTrends] = useState<SocialTrendsResponse | null>(null)
  const [clarityFriction, setClarityFriction] = useState<ClarityPageMetric[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '30d', startDate: '', endDate: '' })
  const [compareMode, setCompareMode] = useState<Mode>('prior_period')

  /* ---- data fetch ---- */
  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [dailyPayload, overviewPayload, issuesPayload, trendsPayload, frictionPayload] = await Promise.all([
          api.dailyKpis(),
          api.overview(),
          api.issues(),
          api.socialTrends(30).catch(() => null as SocialTrendsResponse | null),
          api.clarityFriction().catch(() => [] as ClarityPageMetric[]),
        ])
        if (cancelled) return
        const ordered = [...dailyPayload].sort((a, b) => a.business_date.localeCompare(b.business_date))
        setRows(ordered)
        setOverview(overviewPayload)
        setIssues(issuesPayload)
        setSocialTrends(trendsPayload)
        setClarityFriction(frictionPayload)
        setRange((current) =>
          current.startDate && current.endDate ? current : buildPresetRange('30d', ordered, { anchorDate: todayDate }),
        )
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load marketing division')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  /* ---- derived data ---- */
  const currentRows = useMemo(() => filterRowsByRange(rows, range), [rows, range])
  const priorRows = useMemo(
    () =>
      compareMode === 'same_day_last_week'
        ? sameDayLastWeekRows(rows, currentRows)
        : priorPeriodRows(rows, currentRows[0]?.business_date || '', currentRows.length),
    [compareMode, rows, currentRows],
  )
  const sourceHealth = overview?.source_health || []
  const clarityDegraded = clarityIsDegraded(sourceHealth)

  /* ---- aggregates ---- */
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

  /* ---- funnel estimates ---- */
  const addToCartRate = currentRows.length
    ? currentRows.reduce((s, row) => s + Number(row.add_to_cart_rate || 0), 0) / currentRows.length
    : 0
  const priorAddToCartRate = priorRows.length
    ? priorRows.reduce((s, row) => s + Number(row.add_to_cart_rate || 0), 0) / priorRows.length
    : 0
  const pdpViewsEstimate = sessions * 0.62
  const priorPdpViewsEstimate = priorSessions * 0.62
  const addToCartEstimate = pdpViewsEstimate * (addToCartRate / 100)
  const priorAddToCartEstimate = priorPdpViewsEstimate * (priorAddToCartRate / 100)
  const checkoutEstimate = addToCartEstimate * 0.58
  const priorCheckoutEstimate = priorAddToCartEstimate * 0.58
  const purchaseEstimate = orders
  const priorPurchaseEstimate = priorOrders

  const funnel = useMemo(() => [
    { label: 'Sessions', volume: sessions, prior: priorSessions, widthPct: 100, dropoff: 0 },
    { label: 'PDP', volume: pdpViewsEstimate, prior: priorPdpViewsEstimate, widthPct: sessions ? (pdpViewsEstimate / sessions) * 100 : 0, dropoff: sessions ? (1 - pdpViewsEstimate / sessions) * 100 : 0 },
    { label: 'Add to Cart', volume: addToCartEstimate, prior: priorAddToCartEstimate, widthPct: sessions ? (addToCartEstimate / sessions) * 100 : 0, dropoff: pdpViewsEstimate ? (1 - addToCartEstimate / pdpViewsEstimate) * 100 : 0 },
    { label: 'Checkout', volume: checkoutEstimate, prior: priorCheckoutEstimate, widthPct: sessions ? (checkoutEstimate / sessions) * 100 : 0, dropoff: addToCartEstimate ? (1 - checkoutEstimate / addToCartEstimate) * 100 : 0 },
    { label: 'Purchase', volume: purchaseEstimate, prior: priorPurchaseEstimate, widthPct: sessions ? (purchaseEstimate / sessions) * 100 : 0, dropoff: checkoutEstimate ? (1 - purchaseEstimate / checkoutEstimate) * 100 : 0 },
  ], [sessions, priorSessions, pdpViewsEstimate, priorPdpViewsEstimate, addToCartEstimate, priorAddToCartEstimate, checkoutEstimate, priorCheckoutEstimate, purchaseEstimate, priorPurchaseEstimate])

  /* ---- funnel leak detection ---- */
  const biggestLeak = useMemo(() => {
    const leaks = funnel.filter((step) => step.dropoff > 0)
    if (leaks.length === 0) return null
    return leaks.reduce((max, step) => (step.dropoff > max.dropoff ? step : max), leaks[0])
  }, [funnel])

  const getLeakSeverity = (dropoff: number): { label: string; class: string } => {
    if (dropoff >= 50) return { label: 'Critical', class: 'badge-bad' }
    if (dropoff >= 25) return { label: 'High', class: 'badge-warn' }
    return { label: 'Medium', class: 'badge-neutral' }
  }

  /* ---- issues / friction ---- */
  const topFriction = issues?.highest_business_risk?.[0] || issues?.clusters?.[0]
  const topFrictionTruthState = clarityDegraded ? 'degraded' : 'proxy'
  const snapshotTimestamp = currentRows.at(-1)?.business_date
    ? `${currentRows.at(-1)?.business_date}T23:59:59Z`
    : new Date().toISOString()

  /* ---- KPI contract objects ---- */
  const kpis: KPIObject[] = [
    buildNumericKpi({ key: 'marketing_revenue', currentValue: revenue, targetValue: priorRevenue || null, priorValue: priorRevenue || null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_conversion_rate', currentValue: conversion, targetValue: priorConversion || null, priorValue: priorConversion || null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_mer', currentValue: mer, targetValue: priorMer || null, priorValue: priorMer || null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_add_to_cart_rate', currentValue: addToCartRate, targetValue: priorAddToCartRate || null, priorValue: priorAddToCartRate || null, owner: 'Bailey', truthState: 'proxy', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_checkout_completion', currentValue: checkoutEstimate ? (purchaseEstimate / checkoutEstimate) * 100 : 0, targetValue: priorCheckoutEstimate ? (priorPurchaseEstimate / priorCheckoutEstimate) * 100 : null, priorValue: priorCheckoutEstimate ? (priorPurchaseEstimate / priorCheckoutEstimate) * 100 : null, owner: 'Bailey', truthState: 'estimated', lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'marketing_top_friction', currentValue: topFriction?.title || 'Awaiting ranked friction source', targetValue: 'No dominant leak', owner: 'Bailey', status: topFriction ? 'red' : 'yellow', truthState: topFrictionTruthState, lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_channel_revenue_breakdown', currentValue: null, targetValue: 1, priorValue: null, owner: 'Bailey', truthState: 'blocked', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'marketing_campaign_breakdown', currentValue: null, targetValue: 1, priorValue: null, owner: 'Bailey', truthState: 'blocked', lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'marketing_clarity_behavior_evidence', currentValue: clarityDegraded ? 'Clarity degraded' : 'Clarity healthy', targetValue: 'Clarity healthy', owner: 'Bailey', status: clarityDegraded ? 'red' : 'green', truthState: truthStateFromSource(sourceHealth, ['clarity'], 'proxy'), lastUpdated: snapshotTimestamp }),
  ]

  /* ---- blocked states ---- */
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

  /* ---- actions ---- */
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
      requiredAction: mer < priorMer
        ? 'Reallocate spend away from lower-efficiency traffic until channel mix recovers.'
        : 'Keep scale pressure on the best-performing channels.',
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
      requiredAction: clarityDegraded
        ? 'Recover Clarity and do not top-rank page-friction actions without corroboration.'
        : `Use Clarity and GA4 together to validate whether ${topFriction?.title || 'the leading friction signal'} is truly suppressing conversion.`,
      priority: clarityDegraded ? 'high' : 'medium',
      evidence: ['clarity', 'ga4', 'issue radar'],
      dueDate: 'next sync',
      snapshotTimestamp,
      baseRankingScore: 90,
      blockedState: blockedStates.marketing_clarity_behavior_evidence,
    }),
  ])

  /* ---- 7-day sparkline data ---- */
  const last7Days = useMemo(() => currentRows.slice(-7), [currentRows])
  const revenueSparkline = useMemo(() => last7Days.map((r) => Number(r.revenue) || 0), [last7Days])
  const conversionSparkline = useMemo(() => {
    return last7Days.map((r) => {
      const s = Number(r.sessions) || 0
      const o = Number(r.orders) || 0
      return s > 0 ? (o / s) * 100 : 0
    })
  }, [last7Days])
  const merSparkline = useMemo(() => {
    return last7Days.map((r) => {
      const rev = Number(r.revenue) || 0
      const spend = Number(r.ad_spend) || 0
      return spend > 0 ? rev / spend : 0
    })
  }, [last7Days])
  const adSpendSparkline = useMemo(() => last7Days.map((r) => Number(r.ad_spend) || 0), [last7Days])

  /* ---- KPI strip cards ---- */
  const kpiCards: KpiCardDef[] = useMemo(() => [
    {
      label: 'Revenue',
      value: currency(revenue),
      sub: `Prior ${currency(priorRevenue)}`,
      truthState: 'canonical',
      delta: { text: deltaPct(revenue, priorRevenue), direction: deltaDirection(revenue, priorRevenue) },
      sparkline: revenueSparkline,
    },
    {
      label: 'Conversion',
      value: `${conversion.toFixed(2)}%`,
      sub: `Prior ${priorConversion.toFixed(2)}%`,
      truthState: 'canonical',
      delta: { text: deltaPct(conversion, priorConversion), direction: deltaDirection(conversion, priorConversion) },
      sparkline: conversionSparkline,
    },
    {
      label: 'MER',
      value: mer.toFixed(2),
      sub: `Prior ${priorMer.toFixed(2)}`,
      truthState: 'canonical',
      delta: { text: deltaPct(mer, priorMer), direction: deltaDirection(mer, priorMer) },
      sparkline: merSparkline,
    },
    {
      label: 'Ad Spend',
      value: currency(adSpend),
      sub: `Prior ${currency(priorAdSpend)}`,
      truthState: 'canonical',
      delta: { text: deltaPct(adSpend, priorAdSpend), direction: deltaDirection(adSpend, priorAdSpend) },
      sparkline: adSpendSparkline,
    },
  ], [revenue, priorRevenue, conversion, priorConversion, mer, priorMer, adSpend, priorAdSpend, revenueSparkline, conversionSparkline, merSparkline, adSpendSparkline])

  /* ---- dynamic action items ---- */
  const weekActions = useMemo(() => {
    const items: { text: string; status: 'status-warn' | 'status-bad' }[] = []
    if (conversion < priorConversion) {
      items.push({ text: 'Fix top high-traffic friction path — conversion is declining vs prior period.', status: 'status-bad' })
    }
    if (mer < priorMer) {
      items.push({ text: 'Reallocate spend away from lower-efficiency traffic — MER is softening.', status: 'status-warn' })
    }
    if (adSpend > priorAdSpend * 1.1) {
      items.push({ text: 'Ad spend increased >10% vs prior — verify incremental return.', status: 'status-warn' })
    }
    if (items.length === 0) {
      items.push({ text: 'No critical regression detected this period — maintain current trajectory.', status: 'status-warn' })
    }
    return items
  }, [conversion, priorConversion, mer, priorMer, adSpend, priorAdSpend])

  /* ---- positive signals ---- */
  const positiveItems = useMemo(() => {
    const items: string[] = []
    if (mer >= priorMer) items.push('Channel efficiency is holding or improving versus comparison period.')
    if (aov >= priorAov) items.push('AOV is holding or improving.')
    if (conversion >= priorConversion) items.push('Conversion rate is stable or improving.')
    if (items.length === 0) items.push('Review metric trends for emerging positive signals.')
    return items
  }, [mer, priorMer, aov, priorAov, conversion, priorConversion])

  /* ================================================================ */
  /*  RENDER                                                           */
  /* ================================================================ */

  return (
    <div className="page-grid venom-page">

      {/* ---- Header ---- */}
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Marketing Division</h2>
          <p className="venom-subtitle">Bailey's operating page</p>
        </div>
      </div>

      <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />
      <CompareToolbar mode={compareMode} onChange={setCompareMode as (mode: CompareMode) => void} />

      {/* ---- Loading / error ---- */}
      {loading ? <Card title="Marketing"><div className="state-message">Loading marketing division...</div></Card> : null}
      {error ? <Card title="Marketing Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <TruthLegend />

          {/* ---- KPI Strip (4 cards) ---- */}
          <VenomKpiStrip cards={kpiCards} cols={4} />

          {/* ---- Clarity Degraded Banner (conditional) ---- */}
          {clarityDegraded ? (
            <div className="trust-banner trust-banner-degraded">
              <div>
                <strong>Clarity degraded</strong>
                <p>
                  Clarity is currently rate-limited or stale. Friction insights that depend on Clarity
                  are annotated as lower confidence until source health recovers.
                </p>
              </div>
            </div>
          ) : null}

          {/* ---- Visual Funnel ---- */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Visual Funnel</strong>
              <span className="venom-panel-hint">Sessions to purchase</span>
            </div>
            {biggestLeak ? (
              <div className="trust-banner trust-banner-warn" style={{ marginBottom: 12 }}>
                <strong>Biggest Leak: {biggestLeak.label}</strong>
                <p>
                  {biggestLeak.dropoff.toFixed(1)}% drop-off — focus optimization efforts here for maximum conversion impact.
                </p>
              </div>
            ) : null}
            <div className="venom-bar-list">
              {funnel.map((step) => {
                const isBiggestLeak = biggestLeak && step.label === biggestLeak.label
                const severity = step.dropoff > 0 ? getLeakSeverity(step.dropoff) : null
                return (
                  <div key={step.label} style={isBiggestLeak ? { background: 'var(--warning-bg)', borderRadius: 4, padding: '4px 8px', marginLeft: -8, marginRight: -8 } : undefined}>
                    <div className="venom-bar-row">
                      <span className="venom-bar-label">{step.label}</span>
                      <BarIndicator value={step.volume} max={sessions || 1} color={FUNNEL_COLORS[step.label] || 'var(--blue)'} />
                      <span className="venom-bar-value">{fmtInt(Math.round(step.volume))}</span>
                    </div>
                    {step.dropoff > 0 ? (
                      <div style={{ paddingLeft: 140, marginTop: -4, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <small className="venom-panel-footer" style={{ margin: 0 }}>
                          {step.dropoff.toFixed(1)}% drop-off from prior stage
                        </small>
                        {severity ? <span className={`badge ${severity.class}`}>{severity.label}</span> : null}
                        {isBiggestLeak ? <span className="badge badge-bad">Biggest Leak</span> : null}
                      </div>
                    ) : null}
                    {step.label === 'PDP' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Estimated: sessions x 0.62 PDP view rate</small> : null}
                    {step.label === 'Add to Cart' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Estimated: uses GA4 add_to_cart_rate x PDP estimate</small> : null}
                    {step.label === 'Checkout' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Estimated: ATC x 0.58</small> : null}
                    {step.label === 'Purchase' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Canonical: Shopify order count</small> : null}
                  </div>
                )
              })}
            </div>
            <small className="venom-panel-footer">
              Estimated funnel — stages 2-4 are modeled from behavioral proxies
            </small>
          </section>

          {/* ---- Two-col: Actions + What's Working / Friction ---- */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>This Week's Actions</strong>
              </div>
              <div className="stack-list compact">
                {weekActions.map((item, idx) => (
                  <div className={`list-item ${item.status}`} key={idx}>
                    <p>{item.text}</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>What's Working</strong>
              </div>
              <div className="stack-list compact">
                {positiveItems.map((text, idx) => (
                  <div className="list-item status-good" key={idx}>
                    <p>{text}</p>
                  </div>
                ))}
              </div>
              <div className="venom-panel-head" style={{ marginTop: 12 }}>
                <strong>Top Friction</strong>
              </div>
              <div className="stack-list compact">
                <div className="list-item status-warn">
                  <p>{topFriction?.title || 'Awaiting ranked friction source'}</p>
                  <small>
                    {clarityDegraded
                      ? 'Reduced confidence — Clarity degraded'
                      : 'Normal confidence'}
                  </small>
                </div>
              </div>
            </section>
          </div>

          {/* Progressive disclosure — everything below the hero lives in
              collapsibles so the page opens clean. */}
          <CollapsibleSection
            id="mkt-efficiency-friction"
            title="Marketing efficiency & website friction"
            subtitle="Campaign/channel efficiency, UX friction from Clarity, blocked-state diagnostics, industry pulse"
            accentColor="#6ea8ff"
          >
          {/* ---- Marketing Efficiency ---- */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Marketing Efficiency</strong>
            </div>
            <div className="venom-breakdown-list">
              <div className="venom-breakdown-row">
                <span>MER (Marketing Efficiency Ratio)</span>
                <span className="venom-breakdown-val">{mer > 0 ? `${mer.toFixed(2)}x` : '\u2014'}</span>
                <span className={`badge ${deltaDirection(mer, priorMer) === 'up' ? 'badge-good' : deltaDirection(mer, priorMer) === 'down' ? 'badge-bad' : 'badge-neutral'}`}>{deltaPct(mer, priorMer)}</span>
              </div>
              <div className="venom-breakdown-row">
                <span>Ad Spend / Revenue</span>
                <span className="venom-breakdown-val">{revenue > 0 ? fmtPct(adSpend / revenue) : '\u2014'}</span>
                <span className="badge badge-neutral">ratio</span>
              </div>
              <div className="venom-breakdown-row">
                <span>Cost per Acquisition</span>
                <span className="venom-breakdown-val">{orders > 0 ? currency(adSpend / orders) : '\u2014'}</span>
                <span className={`badge ${priorOrders > 0 && orders > 0 ? (deltaDirection(priorAdSpend / priorOrders, adSpend / orders) === 'up' ? 'badge-good' : deltaDirection(priorAdSpend / priorOrders, adSpend / orders) === 'down' ? 'badge-bad' : 'badge-neutral') : 'badge-neutral'}`}>{priorOrders > 0 && orders > 0 ? deltaPct(priorAdSpend / priorOrders, adSpend / orders) : 'n/a'}</span>
              </div>
            </div>
          </section>

          {/* ---- Website UX Friction ---- */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Website UX Friction</strong>
              <span className="venom-panel-hint">Clarity behavioral analytics — top friction pages</span>
            </div>
            {clarityFriction.length > 0 ? (
              <div className="stack-list compact">
                {clarityFriction.slice(0, 5).map((page, idx) => (
                  <div className="list-item status-muted" key={idx}>
                    <div className="item-head">
                      <strong>{page.page_path}</strong>
                      <div className="inline-badges">
                        <span className="badge badge-neutral">{page.page_type}</span>
                        <span className="badge badge-neutral">{fmtInt(page.sessions)} sessions</span>
                      </div>
                    </div>
                    <div className="venom-bar-row" style={{ marginTop: 4 }}>
                      <span className="venom-bar-label">Friction</span>
                      <BarIndicator
                        value={page.friction_score}
                        max={100}
                        color={page.friction_score > 50 ? 'var(--red)' : page.friction_score > 25 ? 'var(--orange)' : 'var(--green)'}
                      />
                      <span className="venom-bar-value">{page.friction_score.toFixed(1)}</span>
                    </div>
                    <div className="inline-badges" style={{ marginTop: 4 }}>
                      {page.dead_clicks > 0 ? <span className="badge badge-warn">{fmtInt(page.dead_clicks)} dead clicks ({page.dead_click_pct.toFixed(1)}%)</span> : null}
                      {page.quick_backs > 0 ? <span className="badge badge-warn">{fmtInt(page.quick_backs)} quick backs ({page.quick_back_pct.toFixed(1)}%)</span> : null}
                      {page.script_errors > 0 ? <span className="badge badge-bad">{fmtInt(page.script_errors)} script errors ({page.script_error_pct.toFixed(1)}%)</span> : null}
                      {page.rage_clicks > 0 ? <span className="badge badge-bad">{fmtInt(page.rage_clicks)} rage clicks ({page.rage_click_pct.toFixed(1)}%)</span> : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="state-message">Clarity UX data will populate after next sync</div>
            )}
          </section>

          {/* ---- Two-col: Blocked States ---- */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head">
                <strong>Campaign Breakdown</strong>
                <TruthBadge state="unavailable" />
              </div>
              <div className="stack-list compact">
                <div className="list-item status-bad">
                  <strong>Blocked</strong>
                  <p>{blockedStates.marketing_campaign_breakdown.decision_blocked}</p>
                  <small>
                    Missing source: {blockedStates.marketing_campaign_breakdown.missing_source}
                  </small>
                  <small>
                    Owner: {blockedStates.marketing_campaign_breakdown.owner} — {blockedStates.marketing_campaign_breakdown.required_action_to_unblock}
                  </small>
                </div>
              </div>
            </section>

            <section className="card">
              <div className="venom-panel-head">
                <strong>Channel Revenue</strong>
                <TruthBadge state="unavailable" />
              </div>
              <div className="stack-list compact">
                <div className="list-item status-bad">
                  <strong>Blocked</strong>
                  <p>{blockedStates.marketing_channel_revenue_breakdown.decision_blocked}</p>
                  <small>
                    Missing source: {blockedStates.marketing_channel_revenue_breakdown.missing_source}
                  </small>
                  <small>
                    Owner: {blockedStates.marketing_channel_revenue_breakdown.owner} — {blockedStates.marketing_channel_revenue_breakdown.required_action_to_unblock}
                  </small>
                </div>
              </div>
            </section>
          </div>

          {/* ---- Industry Pulse — Social Listening ---- */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Industry Pulse — Charcoal Grilling</strong>
              <span className="venom-panel-hint">Reddit + YouTube</span>
            </div>
            {socialTrends?.trending_topics && socialTrends.trending_topics.length > 0 ? (
              <div className="stack-list compact">
                {socialTrends.trending_topics.slice(0, 5).map((trend, idx) => (
                  <div className="list-item status-muted" key={idx}>
                    <div className="item-head">
                      <strong>{trend.topic}</strong>
                      <div className="inline-badges">
                        <span className="badge badge-neutral">{fmtInt(trend.mention_count)} mentions</span>
                        <span className="badge badge-neutral">{fmtInt(trend.total_engagement)} engagement</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="state-message">Social listening will populate after first Reddit sync</div>
            )}
          </section>

          </CollapsibleSection>

          <CollapsibleSection
            id="mkt-coordination"
            title="Team coordination & navigation"
            subtitle="ClickUp marketing tasks + velocity + compliance, Slack marketing-customer-service + general-news, cross-page navigation"
            accentColor="#a78bfa"
          >
          {/* ClickUp tasks + velocity — Marketing space */}
          <ClickUpTasksCard
            title="ClickUp tasks — Marketing"
            subtitle="Marketing space: campaigns, content, website, ambassadors, graphic design."
            defaultFilter={{ space_id: '901310388813', limit: 30 }}
          />
          <ClickUpVelocityCard
            title="Team velocity — Marketing space"
            subtitle="Throughput, cycle time, and who's closing what this week."
            spaceId="901310388813"
          />
          <ClickUpComplianceCard
            title="Tagging compliance — Marketing space"
            subtitle="Are closed marketing tasks carrying Division + Category so campaign attribution stays precise?"
            spaceId="901310388813"
          />

          {/* Campaign launches overlaid on the daily revenue line.
              Vertical markers = ClickUp Marketing-space task due dates
              (campaign launch schedule). Hover the line to read revenue. */}
          <ClickUpOverlayChart
            title="Campaign launches ↔ Revenue"
            subtitle="Daily revenue line with Division=Marketing + Category=Campaign due dates as vertical markers. Precise field-match (not keyword) — does a campaign launch correlate with a revenue bump the day-of or day-after?"
            primarySeries={rows.map(r => ({ date: r.business_date, value: Number(r.revenue) || 0 }))}
            primaryLabel="Revenue"
            primaryColor="var(--green)"
            clickupFilter={{
              division: 'Marketing',
              category: 'Campaign',
              event_types: 'due',
              days: 90,
            }}
          />

          {/* Slack pulse — marketing-customer-service + general-news */}
          <SlackPulseCard
            title="Slack pulse — Marketing"
            subtitle="Campaign conversation + customer-facing channel activity."
            defaultChannelName="marketing-customer-service"
          />

          {/* ---- Navigation Tiles ---- */}
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
