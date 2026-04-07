import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { CompareToolbar } from '../components/CompareToolbar'
import { RangeToolbar } from '../components/RangeToolbar'
import { TrendChart } from '../components/TrendChart'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { currency, impactFromConversion } from '../lib/operatingModel'
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
  const sessions = sum(currentRows, 'sessions')
  const orders = sum(currentRows, 'orders')
  const aov = orders ? revenue / orders : 0
  const conversion = sessions ? (orders / sessions) * 100 : 0
  const priorRevenue = sum(priorRows, 'revenue')
  const priorSessions = sum(priorRows, 'sessions')
  const priorOrders = sum(priorRows, 'orders')
  const priorAov = priorOrders ? priorRevenue / priorOrders : 0
  const priorConversion = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const revenueDelta = compareValue(revenue, priorRows.length === currentRows.length ? priorRevenue : null, 'Revenue')
  const sessionsDelta = compareValue(sessions, priorRows.length === currentRows.length ? priorSessions : null, 'Sessions')
  const ordersDelta = compareValue(orders, priorRows.length === currentRows.length ? priorOrders : null, 'Orders')
  const aovDelta = compareValue(aov, priorRows.length === currentRows.length ? priorAov : null, 'AOV')
  const conversionDelta = compareValue(conversion, priorRows.length === currentRows.length ? priorConversion : null, 'Conversion')
  const impact = impactFromConversion(sessions, Math.max(0, Math.abs((conversionDelta.deltaPct || 0) * 0.1)), aov) * 7
  const driverCards = [
    { label: 'Traffic', delta: sessionsDelta.deltaPct, impact: impactFromConversion(sessions, 0.1, aov) * 7 },
    { label: 'Conversion', delta: conversionDelta.deltaPct, impact: impactFromConversion(sessions, Math.max(0.1, Math.abs((conversionDelta.deltaPct || 0) * 0.1)), aov) * 7 },
    { label: 'AOV', delta: aovDelta.deltaPct, impact: impactFromConversion(sessions * 0.4, 0.08, aov) * 7 },
  ]

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Revenue Engine</h2>
        <p>Show the revenue movement, the driver, and the weekly dollars recoverable from the next intervention.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />
      <CompareToolbar mode={compareMode} onChange={setCompareMode} />
      {loading ? <Card title="Revenue Engine"><div className="state-message">Loading revenue system…</div></Card> : null}
      {error ? <Card title="Revenue Engine Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="three-col">
            <Card title="Revenue Delta"><div className="hero-metric">{formatDeltaPct(revenueDelta.deltaPct)}</div><div className="state-message">{currency(revenue)} in scope</div></Card>
            <Card title="Orders Delta"><div className="hero-metric">{formatDeltaPct(ordersDelta.deltaPct)}</div><div className="state-message">{orders.toFixed(0)} orders in scope</div></Card>
            <Card title="Recoverable Impact"><div className="hero-metric">{currency(impact)}</div><div className="state-message">impact = sessions × conversion_delta × AOV (weeklyized)</div></Card>
          </div>
          <Card title="Driver Story">
            <div className="three-col">
              {driverCards.map((card) => (
                <div className="list-item" key={card.label}>
                  <strong>{card.label}</strong>
                  <p>{formatDeltaPct(card.delta)}</p>
                  <small>Estimated weekly impact {currency(card.impact)}</small>
                </div>
              ))}
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
