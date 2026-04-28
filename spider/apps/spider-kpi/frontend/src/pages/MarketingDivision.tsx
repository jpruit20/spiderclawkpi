import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { DivisionPageHeader } from '../components/DivisionPageHeader'
import { GridEditor, type GridEditorItem } from '../components/GridEditor'
import { usePageConfig } from '../lib/usePageConfig'
import { MetricTile, TileGrid, openSectionById } from '../components/tiles'
import { TruthBadge } from '../components/TruthBadge'
import { TruthLegend } from '../components/TruthLegend'
import { ClickUpComplianceCard } from '../components/ClickUpComplianceCard'
import { ClickUpOverlayChart } from '../components/ClickUpOverlayChart'
import { ChannelMixCard } from '../components/ChannelMixCard'
import { ChannelTrendsCard, MarketingPacingCard, MerHealthCard } from '../components/MarketingIntelligenceCards'
import { GrossProfitCard } from '../components/GrossProfitCard'
import { DivisionTargetsButton } from '../components/DivisionTargetsButton'
import { MarketingContributionStrip } from '../components/MarketingContributionStrip'
import { ClickUpTasksCard } from '../components/ClickUpTasksCard'
import { ClickUpVelocityCard } from '../components/ClickUpVelocityCard'
import { SlackPulseCard } from '../components/SlackPulseCard'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { BaselineBand } from '../components/BaselineBand'
import { EventTimelinePanel } from '../components/EventTimelinePanel'
import { EventTimelineStrip } from '../components/EventTimelineStrip'
import { SeasonalContextBadge } from '../components/SeasonalContextBadge'
import { RangeToolbar } from '../components/RangeToolbar'
import { CompareToolbar } from '../components/CompareToolbar'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { currency, fmtInt, fmtPct, deltaPct, deltaDirection } from '../lib/format'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { CompareMode as Mode } from '../lib/compare'
import { ActionObject, BlockedStateOutput, ClarityPageMetric, IssueRadarResponse, KPIDaily, KPIObject, OverviewResponse, SocialTrendsResponse, SourceHealthItem } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, buildTextKpi, enforceActionContract, truthStateFromSource } from '../lib/divisionContract'
import { DivisionHero } from '../components/DivisionHero'
import { AudienceSegmentationCard } from '../components/AudienceSegmentationCard'
import { KlaviyoFriendbuyCard } from '../components/KlaviyoFriendbuyCard'
import { RecommendationsCard } from '../components/RecommendationsCard'
import { KlaviyoMarketingCard } from '../components/KlaviyoMarketingCard'
import {
  KlaviyoCampaignsCard,
  KlaviyoFlowsStatusCard,
  KlaviyoListsSegmentsCard,
} from '../components/KlaviyoMarketingActivityCards'

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
  const cfg = usePageConfig('marketing')
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
  // Hour-trimmed comparison totals (2026-04-18 fix for issue Joseph
  // flagged: today-so-far vs yesterday-full is apples-to-oranges).
  // When the backend applies hour-trimming, this payload's current
  // and prior totals override the daily-sum versions below.
  const [periodCompare, setPeriodCompare] = useState<import('../lib/types').MarketingPeriodCompareResponse | null>(null)
  const [yoyCompare, setYoyCompare] = useState<import('../lib/types').MarketingPeriodCompareResponse | null>(null)

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

  // Fetch hour-trimmed period-compare whenever range or mode changes.
  useEffect(() => {
    if (!range.startDate || !range.endDate) return
    let cancelled = false
    api.marketingPeriodCompare({
      start: range.startDate,
      end: range.endDate,
      mode: compareMode === 'same_day_last_week' ? 'same_day_last_week' : 'prior_period',
    })
      .then(r => { if (!cancelled) setPeriodCompare(r) })
      .catch(() => { if (!cancelled) setPeriodCompare(null) })
    return () => { cancelled = true }
  }, [range.startDate, range.endDate, compareMode])

  // YoY fetch — independent of compareMode so the strip always shows a
  // "vs last year" delta when data is available. Useful on seasonally
  // sensitive channels like grilling where prior-week compares mask
  // demand shifts that year-ago comparison catches.
  useEffect(() => {
    if (!range.startDate || !range.endDate) return
    let cancelled = false
    api.marketingPeriodCompare({
      start: range.startDate,
      end: range.endDate,
      mode: 'yoy',
    })
      .then(r => { if (!cancelled) setYoyCompare(r) })
      .catch(() => { if (!cancelled) setYoyCompare(null) })
    return () => { cancelled = true }
  }, [range.startDate, range.endDate])

  /* ---- derived data ---- */
  const currentRows = useMemo(() => filterRowsByRange(rows, range), [rows, range])
  const latestCompleteDay = currentRows[currentRows.length - 1]
  const seasonalityApplicable = range.preset !== 'today' && !!range.startDate && !!range.endDate && currentRows.length > 0
  const priorRows = useMemo(
    () =>
      compareMode === 'same_day_last_week'
        ? sameDayLastWeekRows(rows, currentRows)
        : priorPeriodRows(rows, currentRows[0]?.business_date || '', currentRows.length),
    [compareMode, rows, currentRows],
  )
  const sourceHealth = overview?.source_health || []
  const clarityDegraded = clarityIsDegraded(sourceHealth)

  /* ---- aggregates ----
     When the backend applies hour-trimming (current window includes
     partial today), use its precisely-trimmed current/prior totals
     from KPIIntraday — apples-to-apples same-hours-of-day comparison.
     Otherwise fall back to whole-row daily sums. Refunds stay on
     daily rows because KPIIntraday doesn't track them yet. */
  const trimApplied = periodCompare?.hour_trim_applied === true
  const revenue = trimApplied && periodCompare ? periodCompare.current.revenue : sum(currentRows, 'revenue')
  const priorRevenue = trimApplied && periodCompare ? periodCompare.prior.revenue : sum(priorRows, 'revenue')
  const refunds = sum(currentRows, 'refunds' as keyof KPIDaily)
  const priorRefunds = sum(priorRows, 'refunds' as keyof KPIDaily)
  const sessions = trimApplied && periodCompare ? periodCompare.current.sessions : sum(currentRows, 'sessions')
  const priorSessions = trimApplied && periodCompare ? periodCompare.prior.sessions : sum(priorRows, 'sessions')
  const orders = trimApplied && periodCompare ? periodCompare.current.orders : sum(currentRows, 'orders')
  const priorOrders = trimApplied && periodCompare ? periodCompare.prior.orders : sum(priorRows, 'orders')
  const adSpend = trimApplied && periodCompare ? periodCompare.current.ad_spend : sum(currentRows, 'ad_spend')
  const priorAdSpend = trimApplied && periodCompare ? periodCompare.prior.ad_spend : sum(priorRows, 'ad_spend')
  const aov = orders ? revenue / orders : 0
  const priorAov = priorOrders ? priorRevenue / priorOrders : 0
  const conversion = sessions ? (orders / sessions) * 100 : 0
  const priorConversion = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const mer = adSpend ? revenue / adSpend : 0
  const priorMer = priorAdSpend ? priorRevenue / priorAdSpend : 0
  // Removed orphan grossProfitProxy / contributionProxy — they computed
  // GP = revenue − refunds (no COGS, no shipping) and were unused in the
  // page. The real numbers now come from <MarketingContributionStrip />
  // which reads /api/financials/gross-profit (canonical: SharePoint COGS
  // + ShipStation shipping + ad spend folded in).

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

  // Funnel stages. Each stage carries TWO distinct comparisons — Joseph
  // flagged the ambiguity 2026-04-18:
  //   - ``dropoff_to_next``: intra-funnel — what % of THIS stage's
  //     volume did not advance to the NEXT stage in the funnel.
  //     Only meaningful on non-terminal stages; Purchase has no next.
  //   - ``prior_period_delta_pct``: time-based — how this stage's
  //     volume compares to the same stage in the prior period (or
  //     same-day-last-week if that mode is active).
  // ``prev_label`` is the previous funnel step's display name, used
  // in the rendered copy to disambiguate ("Sessions → PDP drop").
  const funnel = useMemo(() => {
    const stages = [
      { label: 'Sessions', volume: sessions, prior: priorSessions },
      { label: 'PDP', volume: pdpViewsEstimate, prior: priorPdpViewsEstimate },
      { label: 'Add to Cart', volume: addToCartEstimate, prior: priorAddToCartEstimate },
      { label: 'Checkout', volume: checkoutEstimate, prior: priorCheckoutEstimate },
      { label: 'Purchase', volume: purchaseEstimate, prior: priorPurchaseEstimate },
    ]
    return stages.map((s, i) => {
      const prevVol = i > 0 ? stages[i - 1].volume : 0
      const nextVol = i < stages.length - 1 ? stages[i + 1].volume : null
      const widthPct = sessions ? (s.volume / sessions) * 100 : 0
      // Intra-funnel: what % of THIS stage drops before the next step.
      const dropoffToNext = (nextVol != null && s.volume > 0)
        ? (1 - nextVol / s.volume) * 100
        : 0
      // Time-based: this stage vs same stage in prior period.
      const priorPeriodDeltaPct = s.prior > 0 ? ((s.volume - s.prior) / s.prior) * 100 : null
      return {
        label: s.label,
        volume: s.volume,
        prior: s.prior,
        prev_label: i > 0 ? stages[i - 1].label : null,
        next_label: i < stages.length - 1 ? stages[i + 1].label : null,
        widthPct,
        dropoff: dropoffToNext,   // retained for back-compat with biggestLeak
        dropoff_to_next: dropoffToNext,
        prior_period_delta_pct: priorPeriodDeltaPct,
      }
    })
  }, [sessions, priorSessions, pdpViewsEstimate, priorPdpViewsEstimate, addToCartEstimate, priorAddToCartEstimate, checkoutEstimate, priorCheckoutEstimate, purchaseEstimate, priorPurchaseEstimate])

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

  /* ---- YoY helper ---- */
  // YoY strip text. Silent when the backend didn't have a year-ago window
  // to compare (e.g., data history too short). For MER we compute from
  // YoY revenue÷spend since the payload doesn't ship it directly.
  const yoyCur = yoyCompare?.current
  const yoyPrior = yoyCompare?.prior
  const yoyRevStr = yoyCur && yoyPrior && yoyPrior.revenue > 0
    ? `YoY ${deltaPct(yoyCur.revenue, yoyPrior.revenue)}`
    : null
  const yoyConvStr = (() => {
    if (!yoyCur || !yoyPrior) return null
    const curConv = yoyCur.sessions > 0 ? (yoyCur.orders / yoyCur.sessions) * 100 : 0
    const priorConv = yoyPrior.sessions > 0 ? (yoyPrior.orders / yoyPrior.sessions) * 100 : 0
    return priorConv > 0 ? `YoY ${deltaPct(curConv, priorConv)}` : null
  })()
  const yoyMerStr = (() => {
    if (!yoyCur || !yoyPrior) return null
    const curMer = yoyCur.ad_spend > 0 ? yoyCur.revenue / yoyCur.ad_spend : 0
    const priorMer_ = yoyPrior.ad_spend > 0 ? yoyPrior.revenue / yoyPrior.ad_spend : 0
    return priorMer_ > 0 ? `YoY ${deltaPct(curMer, priorMer_)}` : null
  })()
  const yoyAdSpendStr = yoyCur && yoyPrior && yoyPrior.ad_spend > 0
    ? `YoY ${deltaPct(yoyCur.ad_spend, yoyPrior.ad_spend)}`
    : null

  /* ---- KPI strip cards ---- */
  const kpiCards: KpiCardDef[] = useMemo(() => [
    {
      label: 'Revenue',
      value: currency(revenue),
      sub: yoyRevStr ? `Prior ${currency(priorRevenue)} · ${yoyRevStr}` : `Prior ${currency(priorRevenue)}`,
      truthState: 'canonical',
      delta: { text: deltaPct(revenue, priorRevenue), direction: deltaDirection(revenue, priorRevenue) },
      sparkline: revenueSparkline,
    },
    {
      label: 'Conversion',
      value: `${conversion.toFixed(2)}%`,
      sub: yoyConvStr ? `Prior ${priorConversion.toFixed(2)}% · ${yoyConvStr}` : `Prior ${priorConversion.toFixed(2)}%`,
      truthState: 'canonical',
      delta: { text: deltaPct(conversion, priorConversion), direction: deltaDirection(conversion, priorConversion) },
      sparkline: conversionSparkline,
    },
    {
      label: 'MER',
      value: mer.toFixed(2),
      sub: yoyMerStr ? `Prior ${priorMer.toFixed(2)} · ${yoyMerStr}` : `Prior ${priorMer.toFixed(2)}`,
      truthState: 'canonical',
      delta: { text: deltaPct(mer, priorMer), direction: deltaDirection(mer, priorMer) },
      sparkline: merSparkline,
    },
    {
      label: 'Ad Spend',
      value: currency(adSpend),
      sub: yoyAdSpendStr ? `Prior ${currency(priorAdSpend)} · ${yoyAdSpendStr}` : `Prior ${currency(priorAdSpend)}`,
      truthState: 'canonical',
      delta: { text: deltaPct(adSpend, priorAdSpend), direction: deltaDirection(adSpend, priorAdSpend) },
      sparkline: adSpendSparkline,
    },
  ], [revenue, priorRevenue, conversion, priorConversion, mer, priorMer, adSpend, priorAdSpend, revenueSparkline, conversionSparkline, merSparkline, adSpendSparkline, yoyRevStr, yoyConvStr, yoyMerStr, yoyAdSpendStr])

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

      {/* ── DIVISION HERO — signature: funnel ─────────────────────────
          Trapezoidal conversion funnel is the Marketing fingerprint.
          Stage widths taper from sessions → add-to-cart → orders. */}
      {(() => {
        const topOfFunnel = Math.max(1, sessions)
        const atcProgress = Math.min(1, addToCartEstimate / topOfFunnel)
        const orderProgress = Math.min(1, purchaseEstimate / topOfFunnel)
        const merState: 'good' | 'warn' | 'bad' | 'neutral' =
          mer >= 2.0 ? 'good' : mer >= 1.5 ? 'warn' : mer > 0 ? 'bad' : 'neutral'
        const convState: 'good' | 'warn' | 'bad' | 'neutral' =
          conversion >= 3 ? 'good' : conversion >= 1.5 ? 'warn' : conversion > 0 ? 'bad' : 'neutral'
        const aovState: 'good' | 'warn' | 'bad' | 'neutral' =
          priorAov === 0 ? 'neutral'
          : aov >= priorAov ? 'good'
          : aov >= priorAov * 0.9 ? 'warn'
          : 'bad'
        return (
          <DivisionHero
            accentColor="#ec4899"
            accentColorSoft="#8b5cf6"
            signature="funnel"
            title="Marketing Division"
            subtitle="Bailey's operating page — paid media, site funnel, channel mix, and campaign execution."
            rightMeta={
              <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'right' }}>
                <div>{range.preset ? `Range · ${range.preset}` : 'Custom range'}</div>
                <div>Updated {new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
              </div>
            }
            primary={{
              label: 'Sessions → Add-to-cart → Orders',
              value: fmtInt(orders),
              sublabel: `${fmtInt(sessions)} sessions`,
              state: convState,
              progress: 1,
              progressSecondary: atcProgress,
              progressInner: orderProgress,
              layers: [
                { label: 'Sessions', value: fmtInt(sessions) },
                { label: 'Add to cart', value: fmtInt(Math.round(addToCartEstimate)) },
                { label: 'Orders', value: fmtInt(orders) },
              ],
            }}
            flanking={[
              {
                label: 'MER',
                value: mer > 0 ? mer.toFixed(2) : '—',
                sublabel: priorMer > 0 ? `vs ${priorMer.toFixed(2)} prior` : 'target 2.0',
                state: merState,
                progress: Math.min(1, mer / 3),
                delta: priorMer > 0 ? {
                  dir: mer > priorMer ? 'up' : mer < priorMer ? 'down' : 'flat',
                  label: `${Math.abs(((mer - priorMer) / priorMer) * 100).toFixed(0)}%`,
                  good: mer >= priorMer,
                } : undefined,
              },
              {
                label: 'Ad spend',
                value: currency(adSpend),
                sublabel: priorAdSpend > 0 ? `vs ${currency(priorAdSpend)} prior` : undefined,
                state: 'neutral',
              },
            ]}
            tiles={[
              {
                label: 'Revenue',
                value: currency(revenue),
                sublabel: priorRevenue > 0 ? `${((revenue - priorRevenue) / priorRevenue * 100).toFixed(0)}% vs prior` : undefined,
                state: priorRevenue > 0 ? (revenue >= priorRevenue ? 'good' : 'bad') : 'neutral',
              },
              {
                label: 'AOV',
                value: aov > 0 ? currency(aov) : '—',
                state: aovState,
              },
              {
                label: 'Conversion',
                value: conversion > 0 ? `${conversion.toFixed(2)}%` : '—',
                state: convState,
              },
              {
                label: 'Orders',
                value: fmtInt(orders),
                sublabel: priorOrders > 0 ? `vs ${fmtInt(priorOrders)} prior` : undefined,
                state: priorOrders > 0 ? (orders >= priorOrders ? 'good' : 'warn') : 'neutral',
              },
            ]}
          />
        )
      })()}

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />
        <DivisionTargetsButton division="marketing" metrics={["revenue", "orders", "csat"]} label="Marketing targets" />
      </div>
      {/* Marketing-side contribution margin: pulls SharePoint COGS +
          ShipStation shipping + ad spend from /api/financials/gross-profit
          so the same canonical figures show up here as on Executive +
          Commercial pages. */}
      <MarketingContributionStrip days={30} />
      <CompareToolbar mode={compareMode} onChange={setCompareMode as (mode: CompareMode) => void} />
      {/* Apples-to-apples comparison hint. When today is partial,
          the backend clips the prior window's matching day to the
          same elapsed hours, so "today through 2:42pm" is compared
          against "yesterday through 2:42pm" instead of full-day. */}
      {periodCompare?.hour_trim_applied && (
        <div style={{ fontSize: 12, color: 'var(--muted)', padding: '4px 12px', marginTop: -4, marginBottom: 4 }}>
          <span style={{ color: 'var(--blue)' }}>⏱ Hour-trimmed:</span> comparing current period{periodCompare.window.label_suffix} against the prior period clipped to the same elapsed hours.
        </div>
      )}

      {/* ---- Loading / error ---- */}
      {loading ? <Card title="Marketing"><div className="state-message">Loading marketing division...</div></Card> : null}
      {error ? <Card title="Marketing Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <TruthLegend />

          <DivisionPageHeader cfg={cfg} divisionLabel="Marketing · Bailey" />

          {/* Editing layer — Bailey (and Joseph) drag/resize cards via
              the Customize button in the header above. */}
          <GridEditor
            cfg={cfg}
            items={[
              {
                id: 'recommendations',
                defaultH: 8,
                node: <RecommendationsCard division="marketing" />,
              },
            ] satisfies GridEditorItem[]}
          />

          {/* Audience context folded — useful background but not first-glance. */}
          <CollapsibleSection
            id="mkt-audience"
            title="Audience segmentation"
            subtitle="Who actually buys / engages — denominator context for every metric below"
            density="compact"
          >
            <AudienceSegmentationCard />
          </CollapsibleSection>

          {/* Klaviyo bundle folded — 4 heavy cards consolidated under one
              "Klaviyo activity" disclosure so the Marketing page leads with
              gauges, funnel, and recommendations. */}
          <CollapsibleSection
            id="mkt-klaviyo"
            title="Klaviyo activity"
            subtitle="Funnel · campaigns · flows · lists & segments · Friendbuy"
            density="compact"
          >
            <KlaviyoMarketingCard />
            <KlaviyoCampaignsCard />
            <KlaviyoFlowsStatusCard />
            <KlaviyoListsSegmentsCard />
            <KlaviyoFriendbuyCard />
          </CollapsibleSection>

          {/* ---- KPI tiles (car-dashboard style: big number, color state,
                 trend arrow, optional sparkline) ---- */}
          <section className="card" style={{ padding: '14px 16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <strong style={{ fontSize: 13 }}>Marketing gauges</strong>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>selected range</span>
            </div>
            <TileGrid cols={4}>
              {kpiCards.map(card => {
                const dirMap: Record<string, 'up' | 'down' | 'flat'> =
                  { up: 'up', down: 'down', flat: 'flat', stable: 'flat' }
                const dir: 'up' | 'down' | 'flat' =
                  card.delta ? (dirMap[card.delta.direction] || 'flat') : 'flat'
                // For marketing KPIs up is generally good (revenue, conv rate,
                // AOV). Sessions/traffic also up-is-good.
                return (
                  <MetricTile
                    key={card.label}
                    label={card.label}
                    value={card.value}
                    sublabel={card.sub}
                    state={dir === 'up' ? 'good' : dir === 'down' ? 'warn' : 'neutral'}
                    delta={card.delta?.text}
                    deltaDir={dir}
                    upIsGood
                    sparkline={card.sparkline}
                    onClick={() => openSectionById('mkt-efficiency-friction')}
                  />
                )
              })}
            </TileGrid>
            {seasonalityApplicable && latestCompleteDay ? (
              <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>Seasonal context ({latestCompleteDay.business_date}):</span>
                <SeasonalContextBadge metric="ad_spend" onDate={latestCompleteDay.business_date} value={latestCompleteDay.ad_spend} />
                <SeasonalContextBadge metric="sessions" onDate={latestCompleteDay.business_date} value={latestCompleteDay.sessions} />
              </div>
            ) : null}
          </section>

          {seasonalityApplicable ? (
            <section className="card">
              <div className="venom-panel-head">
                <strong>Ad Spend vs Seasonal Baseline</strong>
                <span className="venom-panel-hint">Observed spend vs p10–p90 / p25–p75 / median by day-of-year</span>
              </div>
              <BaselineBand
                metric="ad_spend"
                start={range.startDate}
                end={range.endDate}
                currentSeries={currentRows.map((row) => ({ date: row.business_date, value: Number(row.ad_spend) || 0 }))}
                currentLabel="Ad spend"
                color="#ff6d7a"
                valueFormatter={(v) => `$${v.toLocaleString()}`}
              />
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                  Events during this window:
                </div>
                <EventTimelineStrip
                  start={range.startDate}
                  end={range.endDate}
                  division="marketing"
                  showStates={false}
                />
              </div>
            </section>
          ) : null}

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
              <span className="venom-panel-hint">Sessions → PDP → Add to Cart → Checkout → Purchase</span>
            </div>
            <details style={{ marginBottom: 10 }}>
              <summary style={{ fontSize: 11, color: 'var(--muted)', cursor: 'pointer' }}>What the colors mean</summary>
              <div style={{ fontSize: 11, color: 'var(--muted)', display: 'flex', gap: 14, marginTop: 6, flexWrap: 'wrap' }}>
                <span>
                  <span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--orange)', borderRadius: 2, marginRight: 4, verticalAlign: 'middle' }} />
                  <strong>Drop to next step</strong> = % of this stage that did not advance in the funnel
                </span>
                <span>
                  <span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--blue)', borderRadius: 2, marginRight: 4, verticalAlign: 'middle' }} />
                  <strong>vs prior period</strong> = this stage's volume vs same stage in the prior window
                </span>
              </div>
            </details>
            {biggestLeak ? (
              <div className="trust-banner trust-banner-warn" style={{ marginBottom: 12 }}>
                <strong>Biggest in-funnel leak: {biggestLeak.prev_label ? `${biggestLeak.prev_label} → ${biggestLeak.label}` : biggestLeak.label}</strong>
                <p>
                  {biggestLeak.dropoff.toFixed(1)}% of {biggestLeak.prev_label || 'prior step'} traffic didn't reach {biggestLeak.label}.
                  Focus optimization here for maximum conversion impact.
                </p>
              </div>
            ) : null}
            <div className="venom-bar-list">
              {funnel.map((step) => {
                const isBiggestLeak = biggestLeak && step.label === biggestLeak.label
                const severity = step.dropoff_to_next > 0 ? getLeakSeverity(step.dropoff_to_next) : null
                const ppDelta = step.prior_period_delta_pct
                const ppBadgeClass = ppDelta == null
                  ? 'badge-neutral'
                  : ppDelta > 2 ? 'badge-good' : ppDelta < -2 ? 'badge-bad' : 'badge-neutral'
                return (
                  <div key={step.label} style={isBiggestLeak ? { background: 'var(--warning-bg)', borderRadius: 4, padding: '4px 8px', marginLeft: -8, marginRight: -8 } : undefined}>
                    <div className="venom-bar-row">
                      <span className="venom-bar-label">{step.label}</span>
                      <BarIndicator value={step.volume} max={sessions || 1} color={FUNNEL_COLORS[step.label] || 'var(--blue)'} />
                      <span className="venom-bar-value">{fmtInt(Math.round(step.volume))}</span>
                    </div>
                    <div style={{ paddingLeft: 140, marginTop: -4, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      {step.next_label && step.dropoff_to_next > 0 ? (
                        <small className="venom-panel-footer" style={{ margin: 0 }}>
                          <span style={{ color: 'var(--orange)' }}>↘</span> <strong>{step.dropoff_to_next.toFixed(1)}%</strong> drop to {step.next_label}
                          {severity ? <span className={`badge ${severity.class}`} style={{ marginLeft: 6 }}>{severity.label}</span> : null}
                          {isBiggestLeak ? <span className="badge badge-bad" style={{ marginLeft: 4 }}>Biggest leak</span> : null}
                        </small>
                      ) : null}
                      {ppDelta != null ? (
                        <small className="venom-panel-footer" style={{ margin: 0 }}>
                          <span style={{ color: 'var(--blue)' }}>Δ</span> <span className={`badge ${ppBadgeClass}`}>{ppDelta >= 0 ? '+' : ''}{ppDelta.toFixed(1)}%</span> vs prior period
                        </small>
                      ) : null}
                    </div>
                    {step.label === 'PDP' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Estimated: sessions × 0.62 PDP view rate</small> : null}
                    {step.label === 'Add to Cart' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Estimated: PDP × GA4 add-to-cart rate</small> : null}
                    {step.label === 'Checkout' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Estimated: ATC × 0.58</small> : null}
                    {step.label === 'Purchase' ? <small style={{color:'var(--muted)', fontSize:11, fontStyle:'italic'}}>Canonical: Shopify order count</small> : null}
                  </div>
                )
              })}
            </div>
            <small className="venom-panel-footer">
              Estimated funnel — stages 2-4 are modeled from behavioral proxies.
              Drop percentages are intra-funnel (this stage → next step); the
              Δ badges compare volume to the same stage in the prior period
              (or same-day-last-week when that compare mode is active).
            </small>
          </section>

          {/* Weekly status — folded by default. Lists are useful but heavy
              when the page is also showing gauges + funnel + Klaviyo bundle. */}
          <CollapsibleSection
            id="mkt-weekly-status"
            title="Weekly status"
            subtitle="This week's actions · what's working · top friction"
            density="compact"
            meta={`${weekActions.length} actions`}
          >
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
          </CollapsibleSection>

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

            <ChannelMixCard range={range} />
            {/* Smarter TW-driven cards — built on the same TWSummaryDaily
                data but surface patterns the mix card misses: week-over-week
                shifts, pacing vs recent baseline, and MER anomaly detection. */}
            <ChannelTrendsCard days={30} />
            <MarketingPacingCard />
            <MerHealthCard days={90} />
          </div>

          {/* Gross profit context — same component / same number as
              Executive / Commercial / Revenue / Command Center. Marketing
              decisions read against gross profit, not just revenue. */}
          <GrossProfitCard days={30} title="Gross profit (marketing context)" />

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
          {range.startDate && range.endDate ? (
            <EventTimelinePanel
              title="Marketing event timeline"
              division="marketing"
              defaultStart={range.startDate}
              defaultEnd={range.endDate}
            />
          ) : null}
        </>
      ) : null}
    </div>
  )
}
