import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { CompareToolbar } from '../components/CompareToolbar'
import { RangeToolbar } from '../components/RangeToolbar'
import { TrendChart } from '../components/TrendChart'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { currency } from '../lib/operatingModel'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { KPIDaily } from '../lib/types'

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

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Financial / Revenue</h2>
        <p>Management view for the selected date range: top-line revenue, prior-period comparison, margin proxies, efficiency, and channel-ready commercial context.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />
      <CompareToolbar mode={compareMode} onChange={setCompareMode} />
      {loading ? <Card title="Revenue Engine"><div className="state-message">Loading revenue system…</div></Card> : null}
      {error ? <Card title="Revenue Engine Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="four-col">
            <Card title="Revenue"><div className="hero-metric hero-metric-sm">{currency(revenue)}</div><small>Prior {currency(priorRevenue)} · Δ {currency(revenue - priorRevenue)} · {formatDeltaPct(revenueDelta.deltaPct)}</small></Card>
            <Card title="Gross profit proxy"><div className="hero-metric hero-metric-sm">{currency(grossProfitProxy)}</div><small>Revenue minus refunds · margin proxy {grossMarginProxy.toFixed(1)}%</small></Card>
            <Card title="Contribution proxy"><div className="hero-metric hero-metric-sm">{currency(contributionProxy)}</div><small>Gross profit proxy minus ad spend · prior {currency(priorContributionProxy)}</small></Card>
            <Card title="Refund / discount drag"><div className="hero-metric hero-metric-sm">{currency(refunds)}</div><small>Prior {currency(priorRefunds)} · ad spend {currency(adSpend)}</small></Card>
          </div>
          <div className="four-col">
            <Card title="Sessions"><div className="hero-metric hero-metric-sm">{sessions.toFixed(0)}</div><small>{formatDeltaPct(sessionsDelta.deltaPct)} vs prior</small></Card>
            <Card title="Conversion"><div className="hero-metric hero-metric-sm">{conversion.toFixed(2)}%</div><small>{formatDeltaPct(conversionDelta.deltaPct)} vs prior</small></Card>
            <Card title="AOV"><div className="hero-metric hero-metric-sm">{currency(aov)}</div><small>{formatDeltaPct(aovDelta.deltaPct)} vs prior</small></Card>
            <Card title="MER / efficiency"><div className="hero-metric hero-metric-sm">{adSpend ? (revenue / adSpend).toFixed(2) : '0.00'}</div><small>Orders {orders.toFixed(0)} · {formatDeltaPct(compareValue(adSpend ? (revenue / adSpend) : 0, priorRows.length === currentRows.length ? (priorAdSpend ? (priorRevenue / priorAdSpend) : 0) : null, 'MER').deltaPct)}</small></Card>
          </div>
          <Card title="Financial management view">
            <div className="three-col">
              <div className="list-item"><strong>Prior-period revenue</strong><p>{currency(priorRevenue)}</p><small>Selected comparison window</small></div>
              <div className="list-item"><strong>Revenue delta</strong><p>{currency(revenue - priorRevenue)}</p><small>{formatDeltaPct(revenueDelta.deltaPct)} versus prior period</small></div>
              <div className="list-item"><strong>Revenue by channel</strong><p>Pending explicit channel feed</p><small>Current backend does not yet expose channel split; page now reserves this management slot instead of hiding it.</small></div>
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
