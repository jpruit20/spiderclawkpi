import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { CompareToolbar } from '../components/CompareToolbar'
import { RangeToolbar } from '../components/RangeToolbar'
import { TrendChart } from '../components/TrendChart'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { currency } from '../lib/operatingModel'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { ActionObject, BlockedStateOutput, KPIDaily, KPIObject } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, enforceActionContract } from '../lib/divisionContract'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

export function RevenueEngine() {
  const todayDate = businessTodayDate()
  const [rows, setRows] = useState<KPIDaily[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '7d', startDate: '', endDate: '' })
  const [compareMode, setCompareMode] = useState<CompareMode>('prior_period')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await api.dailyKpis()
        if (cancelled) return
        const ordered = [...payload].sort((a, b) => a.business_date.localeCompare(b.business_date))
        setRows(ordered)
        setRange((current) => current.startDate && current.endDate ? current : buildPresetRange('7d', ordered, { anchorDate: todayDate }))
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load revenue engine')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const currentRows = useMemo(() => filterRowsByRange(rows, range), [rows, range])
  const priorRows = useMemo(() => compareMode === 'same_day_last_week' ? sameDayLastWeekRows(rows, currentRows) : priorPeriodRows(rows, currentRows[0]?.business_date || '', currentRows.length), [compareMode, rows, currentRows])
  const revenue = sum(currentRows, 'revenue')
  const refunds = sum(currentRows, 'refunds' as keyof KPIDaily)
  const sessions = sum(currentRows, 'sessions')
  const orders = sum(currentRows, 'orders')
  const aov = orders ? revenue / orders : 0
  const conversion = sessions ? (orders / sessions) * 100 : 0
  const adSpend = sum(currentRows, 'ad_spend')
  const discountsAvailable = false
  const discounts = null
  const grossProfitProxy = revenue - refunds
  const grossMarginProxy = revenue ? (grossProfitProxy / revenue) * 100 : 0
  const contributionProxy = grossProfitProxy - adSpend
  const priorRevenue = sum(priorRows, 'revenue')
  const priorRefunds = sum(priorRows, 'refunds' as keyof KPIDaily)
  const priorSessions = sum(priorRows, 'sessions')
  const priorOrders = sum(priorRows, 'orders')
  const priorAov = priorOrders ? priorRevenue / priorOrders : 0
  const priorConversion = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const priorAdSpend = sum(priorRows, 'ad_spend')
  const priorGrossProfitProxy = priorRevenue - priorRefunds
  const priorContributionProxy = priorGrossProfitProxy - priorAdSpend
  const revenueDelta = compareValue(revenue, priorRows.length === currentRows.length ? priorRevenue : null, 'Revenue')
  const sessionsDelta = compareValue(sessions, priorRows.length === currentRows.length ? priorSessions : null, 'Sessions')
  const ordersDelta = compareValue(orders, priorRows.length === currentRows.length ? priorOrders : null, 'Orders')
  const aovDelta = compareValue(aov, priorRows.length === currentRows.length ? priorAov : null, 'AOV')
  const conversionDelta = compareValue(conversion, priorRows.length === currentRows.length ? priorConversion : null, 'Conversion')
  const grossProfitDelta = compareValue(grossProfitProxy, priorRows.length === currentRows.length ? priorGrossProfitProxy : null, 'Gross profit proxy')
  const contributionDelta = compareValue(contributionProxy, priorRows.length === currentRows.length ? priorContributionProxy : null, 'Contribution proxy')
  const snapshotTimestamp = currentRows.at(-1)?.business_date ? `${currentRows.at(-1)?.business_date}T23:59:59Z` : new Date().toISOString()

  const kpis: KPIObject[] = [
    buildNumericKpi({ key: 'revenue_total', currentValue: revenue, targetValue: priorRevenue || null, priorValue: priorRevenue || null, owner: 'Joseph', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'gross_profit_proxy', currentValue: grossProfitProxy, targetValue: priorGrossProfitProxy || null, priorValue: priorGrossProfitProxy || null, owner: 'Joseph', truthState: 'proxy', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'gross_margin_proxy', currentValue: grossMarginProxy, targetValue: null, priorValue: null, owner: 'Joseph', truthState: 'proxy', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'contribution_proxy', currentValue: contributionProxy, targetValue: priorContributionProxy || null, priorValue: priorContributionProxy || null, owner: 'Joseph', truthState: 'proxy', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'mer', currentValue: adSpend ? (revenue / adSpend) : 0, targetValue: priorAdSpend ? (priorRevenue / priorAdSpend) : null, priorValue: priorAdSpend ? (priorRevenue / priorAdSpend) : null, owner: 'Bailey', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'channel_revenue_breakdown', currentValue: null, targetValue: null, priorValue: null, owner: 'Bailey', truthState: 'blocked', lastUpdated: snapshotTimestamp }),
  ]

  const blockedStates: Record<string, BlockedStateOutput> = {
    channel_revenue_breakdown: buildBlockedState({
      decision_blocked: 'Which channel should gain or lose spend based on revenue contribution',
      missing_source: 'channel-level revenue backend feed',
      still_trustworthy: ['total revenue', 'orders', 'sessions', 'MER'],
      owner: 'Bailey',
      required_action_to_unblock: 'Connect and expose channel-level revenue rows before reallocating channel budget',
    }),
  }

  const actions: ActionObject[] = enforceActionContract([
    actionFromKpi({
      id: 'revenue-unblock-channel-breakdown',
      triggerKpi: kpis.find((item) => item.key === 'channel_revenue_breakdown')!,
      triggerCondition: 'truth_state = blocked',
      owner: 'Bailey',
      requiredAction: 'Unblock channel revenue feed before making channel allocation decisions.',
      priority: 'critical',
      evidence: ['daily_kpis', 'revenue page'],
      dueDate: 'next sync',
      snapshotTimestamp,
      baseRankingScore: 100,
      blockedState: blockedStates.channel_revenue_breakdown,
    }),
  ])

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Financial / Revenue</h2>
        <p>Management view for the selected date range with explicit labeling when a metric is only a proxy, estimate, or incomplete input.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />
      <CompareToolbar mode={compareMode} onChange={setCompareMode} />
      {loading ? <Card title="Revenue Engine"><div className="state-message">Loading revenue system…</div></Card> : null}
      {error ? <Card title="Revenue Engine Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <Card title="Core financial block">
            <div className="four-col">
              <div className="list-item status-good"><strong>Revenue</strong><div className="hero-metric hero-metric-sm">{currency(revenue)}</div></div>
              <div className="list-item status-muted"><strong>Prior-period revenue</strong><div className="hero-metric hero-metric-sm">{currency(priorRevenue)}</div></div>
              <div className="list-item status-muted"><strong>Delta $</strong><div className="hero-metric hero-metric-sm">{currency(revenue - priorRevenue)}</div></div>
              <div className="list-item status-muted"><strong>Delta %</strong><div className="hero-metric hero-metric-sm">{formatDeltaPct(revenueDelta.deltaPct)}</div></div>
            </div>
          </Card>
          <div className="four-col">
            <Card title="Gross profit proxy"><div className="hero-metric hero-metric-sm">{currency(grossProfitProxy)}</div><small><strong>Proxy:</strong> revenue minus refunds only. Discounts / COGS not available here.</small></Card>
            <Card title="Gross margin proxy"><div className="hero-metric hero-metric-sm">{grossMarginProxy.toFixed(1)}%</div><small><strong>Proxy:</strong> derived from gross profit proxy, not accounting margin.</small></Card>
            <Card title="Contribution proxy"><div className="hero-metric hero-metric-sm">{currency(contributionProxy)}</div><small><strong>Proxy:</strong> gross profit proxy minus ad spend only.</small></Card>
            <Card title="MER / efficiency"><div className="hero-metric hero-metric-sm">{adSpend ? (revenue / adSpend).toFixed(2) : '0.00'}</div><small>Orders {orders.toFixed(0)} · {formatDeltaPct(compareValue(adSpend ? (revenue / adSpend) : 0, priorRows.length === currentRows.length ? (priorAdSpend ? (priorRevenue / priorAdSpend) : 0) : null, 'MER').deltaPct)}</small></Card>
          </div>
          <div className="four-col">
            <Card title="Sessions"><div className="hero-metric hero-metric-sm">{sessions.toFixed(0)}</div><small>{formatDeltaPct(sessionsDelta.deltaPct)} vs prior</small></Card>
            <Card title="Conversion"><div className="hero-metric hero-metric-sm">{conversion.toFixed(2)}%</div><small>{formatDeltaPct(conversionDelta.deltaPct)} vs prior</small></Card>
            <Card title="AOV"><div className="hero-metric hero-metric-sm">{currency(aov)}</div><small>{formatDeltaPct(aovDelta.deltaPct)} vs prior</small></Card>
            <Card title="Orders"><div className="hero-metric hero-metric-sm">{orders.toFixed(0)}</div><small>{formatDeltaPct(ordersDelta.deltaPct)} vs prior</small></Card>
          </div>
          <Card title="Financial composition">
            <div className="three-col">
              <div className="list-item"><strong>Revenue</strong><p>{currency(revenue)}</p><small>Selected period top line</small></div>
              <div className="list-item"><strong>Refunds</strong><p>{currency(refunds)}</p><small>Returned from current source payload</small></div>
              <div className="list-item status-warn"><strong>Discounts</strong><p>{discountsAvailable ? currency(discounts || 0) : 'Missing data'}</p><small>{discountsAvailable ? 'Discount component available' : 'Discount component not exposed by current backend payload.'}</small></div>
              <div className="list-item"><strong>Ad spend</strong><p>{currency(adSpend)}</p><small>Current selected range spend</small></div>
              <div className="list-item status-warn"><strong>Proxy profit calculation</strong><p>{currency(grossProfitProxy)}</p><small>Revenue - refunds only. Missing discounts/COGS.</small></div>
              <div className="list-item status-warn"><strong>Contribution proxy</strong><p>{currency(contributionProxy)}</p><small>Proxy profit calculation - ad spend.</small></div>
            </div>
          </Card>
          <Card title="Revenue by channel">
            <div className="list-item status-bad">
              <strong>{kpis.find((item) => item.key === 'channel_revenue_breakdown')?.key}</strong>
              <p>{blockedStates.channel_revenue_breakdown.decision_blocked}</p>
              <small><strong>truth_state:</strong> blocked · <strong>missing source:</strong> {blockedStates.channel_revenue_breakdown.missing_source}</small>
              <small><strong>still trustworthy:</strong> {blockedStates.channel_revenue_breakdown.still_trustworthy.join(', ')}</small>
              <small><strong>owner:</strong> {blockedStates.channel_revenue_breakdown.owner} · <strong>next action:</strong> {actions[0]?.required_action}</small>
            </div>
          </Card>
          <Card title="Diagnostic drill-downs">
            <div className="stack-list compact">
              <div className="list-item status-muted"><strong>View friction details</strong><p><a href="/friction">Open Friction Map</a></p></div>
              <div className="list-item status-muted"><strong>View root cause</strong><p><a href="/root-cause">Open Root Cause</a></p></div>
            </div>
          </Card>
          <Card title="Revenue Trend">
            {currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'revenue', label: 'Revenue', color: '#6ea8ff', axisId: 'left' }, { key: 'sessions', label: 'Sessions', color: '#ffb257', axisId: 'right' }, { key: 'orders', label: 'Orders', color: '#39d08f', axisId: 'right' }]} /> : <div className="state-message">No KPI rows returned.</div>}
          </Card>
        </>
      ) : null}
    </div>
  )
}
