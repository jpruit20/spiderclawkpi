import { useEffect, useMemo, useRef, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { Card } from '../components/Card'
import { CompareToolbar } from '../components/CompareToolbar'
import { CompareSummary } from '../components/CompareSummary'
import { EventAnnotationList } from '../components/EventAnnotationList'
import { MetricProvenancePanel, MetricProvenanceItem } from '../components/MetricProvenancePanel'
import { RangeToolbar } from '../components/RangeToolbar'
import { StatePanel } from '../components/StatePanel'
import { ThresholdPanel } from '../components/ThresholdPanel'
import { TrendChart } from '../components/TrendChart'
import { BaselineBand } from '../components/BaselineBand'
import { SeasonalContextBadge } from '../components/SeasonalContextBadge'
import { ApiError, api, getApiBase } from '../lib/api'
import { CompareMode, compareValue, formatDeltaPct, priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { buildPresetRange, businessTodayDate, filterRowsByRange, RangeState } from '../lib/range'
import { KPIDaily, OverviewResponse } from '../lib/types'
import { useUrlRange } from '../lib/urlRange'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

function compare(current: number, prior: number) {
  if (!prior) return 'n/a'
  const delta = ((current - prior) / prior) * 100
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}%`
}

function formatNumber(value?: number | null, digits = 2, prefix = '', suffix = '') {
  if (value == null) return '—'
  return `${prefix}${value.toFixed(digits)}${suffix}`
}

function SummaryBlock({ label, current, prior, comparable, format = (v: number) => v.toFixed(2) }: { label: string; current: number; prior: number; comparable: boolean; format?: (v: number) => string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value compact">{format(current)}</div>
      <div className="stat-subvalue">{comparable ? `vs prior period ${compare(current, prior)}` : 'Prior period not comparable'}</div>
    </div>
  )
}

function isIncompleteLatestDay(row?: KPIDaily) {
  if (!row) return false
  return (row.sessions === 0 || row.sessions == null) && ((row.orders || 0) > 0 || (row.revenue || 0) > 0)
}

export function CommercialPerformance() {
  const todayDate = businessTodayDate()
  const [rows, setRows] = useState<KPIDaily[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '7d', startDate: '', endDate: '' })
  const [compareMode, setCompareMode] = useState<CompareMode>('prior_period')
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const requestIdRef = useRef(0)
  const hydratedRangeRef = useRef(false)

  useUrlRange(range, (nextRange) => {
    if (hydratedRangeRef.current) return
    hydratedRangeRef.current = true
    setRange(nextRange)
  })

  async function load(signal?: AbortSignal) {
      const requestId = ++requestIdRef.current
      setLoading(true)
      setError(null)
      try {
        const [payload, overviewPayload] = await Promise.all([api.dailyKpis(signal), api.overview(signal)])
        if (signal?.aborted || requestId !== requestIdRef.current) return
        const ordered = [...payload].sort((a, b) => a.business_date.localeCompare(b.business_date))
        const safeRows = isIncompleteLatestDay(ordered[ordered.length - 1]) ? ordered.slice(0, -1) : ordered
        setRows(safeRows)
        setOverview(overviewPayload)
        setRange((current) => current.startDate && current.endDate ? current : buildPresetRange('7d', safeRows, { anchorDate: todayDate }))
      } catch (err) {
        if (signal?.aborted || requestId !== requestIdRef.current) return
        setError(err instanceof ApiError ? err.message : 'Failed to load daily KPIs')
      } finally {
        if (signal?.aborted || requestId !== requestIdRef.current) return
        setLoading(false)
      }
  }

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => {
      controller.abort()
      requestIdRef.current += 1
    }
  }, [])

  const currentRows = useMemo(() => filterRowsByRange(rows, range), [rows, range])
  const latestCompleteDay = currentRows[currentRows.length - 1]
  const seasonalityApplicable = range.preset !== 'today' && !!range.startDate && !!range.endDate && currentRows.length > 0
  const currentRevenue = sum(currentRows, 'revenue')
  const currentSessions = sum(currentRows, 'sessions')
  const currentOrders = sum(currentRows, 'orders')
  const currentAdSpend = sum(currentRows, 'ad_spend')
  const currentConversion = currentSessions ? (currentOrders / currentSessions) * 100 : 0
  const currentAov = currentOrders ? currentRevenue / currentOrders : 0
  const currentMer = currentAdSpend ? currentRevenue / currentAdSpend : 0

  const priorRows = useMemo(() => {
    if (compareMode === 'same_day_last_week') return sameDayLastWeekRows(rows, currentRows)
    if (compareMode === 'none') return []
    return priorPeriodRows(rows, range.startDate, currentRows.length)
  }, [compareMode, rows, range.startDate, currentRows])

  const priorRevenue = sum(priorRows, 'revenue')
  const priorSessions = sum(priorRows, 'sessions')
  const priorOrders = sum(priorRows, 'orders')
  const priorAdSpend = sum(priorRows, 'ad_spend')
  const priorConversion = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const priorAov = priorOrders ? priorRevenue / priorOrders : 0
  const priorMer = priorAdSpend ? priorRevenue / priorAdSpend : 0
  const priorComparable = priorRows.length === currentRows.length && currentRows.length > 0
  const revenueCompare = compareValue(currentRevenue, priorComparable ? priorRevenue : null, 'Revenue')
  const ordersCompare = compareValue(currentOrders, priorComparable ? priorOrders : null, 'Orders')
  const trafficContribution = priorRevenue ? ((currentSessions - priorSessions) / Math.max(priorSessions, 1)) * 100 : 0
  const conversionContribution = priorConversion ? ((currentConversion - priorConversion) / priorConversion) * 100 : 0
  const aovContribution = priorAov ? ((currentAov - priorAov) / priorAov) * 100 : 0
  const comparePoints = [
    compareValue(currentRevenue, priorComparable ? priorRevenue : null, 'Revenue'),
    compareValue(currentOrders, priorComparable ? priorOrders : null, 'Orders'),
    compareValue(currentSessions, priorComparable ? priorSessions : null, 'Sessions'),
    compareValue(currentConversion, priorComparable ? priorConversion : null, 'Conversion'),
  ]
  const provenanceItems: MetricProvenanceItem[] = [
    {
      metric: 'Revenue / Orders / AOV',
      sourceSystem: 'Shopify via backend /api/kpis/daily',
      queryLogic: 'daily KPI rows filtered to selected range',
      timeWindow: `${range.startDate} → ${range.endDate}`,
      refreshCadence: 'Shopify poll + webhook backed sync',
      transformationLogic: 'range sum with derived AOV',
      caveats: 'Business-date attribution follows backend KPI mart logic.',
    },
    {
      metric: 'Sessions / Conversion / MER',
      sourceSystem: 'Triple Whale + KPI mart via /api/kpis/daily',
      queryLogic: 'daily KPI rows filtered to selected range',
      timeWindow: `${range.startDate} → ${range.endDate}`,
      refreshCadence: 'Triple Whale poll sync',
      transformationLogic: 'range sum with derived conversion and MER',
      caveats: 'Comparison quality depends on a full prior window being available.',
    },
  ]
  const actionItems = [
    currentMer < 3 ? 'MER is soft; inspect paid efficiency and landing page conversion before increasing spend.' : 'MER is holding; focus on where volume quality or AOV can move the next decision.',
    currentConversion < 1 ? 'Conversion is below a healthy operating band; inspect session-to-cart and checkout leakage before traffic expansion.' : 'Conversion is not the primary bottleneck; inspect AOV and merchandising mix.',
    currentAov < 400 ? 'AOV is below target shape; prioritize bundles, accessories, and SKU-mix interventions.' : 'AOV is supportive; next action should focus on volume quality and order rate.',
  ]

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Commercial Performance</h2>
        <p>Revenue and sessions on the main chart, orders on a separate chart, all tied to one truthful range control.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>

      <RangeToolbar rows={rows} range={range} onChange={setRange} anchorDate={todayDate} />
      <CompareToolbar mode={compareMode} onChange={setCompareMode} />

      {!loading && !error && currentRows.length ? (
        <div className="three-col">
          <Card title="Revenue in Scope">
            <div className="hero-metric">${currentRevenue.toFixed(0)}</div>
            {seasonalityApplicable && latestCompleteDay ? (
              <div style={{ marginTop: 4 }}>
                <SeasonalContextBadge metric="revenue" onDate={latestCompleteDay.business_date} value={latestCompleteDay.revenue} />
              </div>
            ) : null}
            <div className="state-message">Selected-range revenue with current compare mode applied below</div>
          </Card>
          <Card title="MER in Scope"><div className="hero-metric">{currentMer.toFixed(2)}</div><div className="state-message">Media efficiency at the current range scope</div></Card>
          <Card title="Conversion in Scope"><div className="hero-metric">{currentConversion.toFixed(2)}%</div><div className="state-message">Order-rate signal before traffic expansion decisions</div></Card>
        </div>
      ) : null}

      <ActionBlock items={actionItems} />
      <ThresholdPanel metrics={[
        { metric: 'conversion_rate', value: currentConversion },
        { metric: 'mer', value: currentMer },
        { metric: 'average_order_value', value: currentAov },
        { metric: 'bounce_rate', value: currentRows.length ? currentRows.reduce((sum, row) => sum + Number(row.bounce_rate || 0), 0) / currentRows.length : null },
      ]} />
      <MetricProvenancePanel items={provenanceItems} />

      {loading ? (
        <Card title="Performance Summary"><div className="state-message">Loading live KPI summary…</div></Card>
      ) : error ? (
        <Card title="Performance Summary"><div className="state-message error">{error}</div><button className="button" onClick={() => void load()}>Retry</button></Card>
      ) : currentRows.length ? (
        <>
          <div className="kpi-grid summary-grid">
            <SummaryBlock label="Revenue" current={currentRevenue} prior={priorRevenue} comparable={priorComparable} format={(v) => `$${v.toFixed(2)}`} />
            <SummaryBlock label="Sessions" current={currentSessions} prior={priorSessions} comparable={priorComparable} format={(v) => v.toFixed(0)} />
            <SummaryBlock label="Orders" current={currentOrders} prior={priorOrders} comparable={priorComparable} format={(v) => v.toFixed(0)} />
            <SummaryBlock label="Conversion" current={currentConversion} prior={priorConversion} comparable={priorComparable} format={(v) => `${v.toFixed(2)}%`} />
            <SummaryBlock label="AOV" current={currentAov} prior={priorAov} comparable={priorComparable} format={(v) => `$${v.toFixed(2)}`} />
            <SummaryBlock label="Ad Spend" current={currentAdSpend} prior={priorAdSpend} comparable={priorComparable} format={(v) => `$${v.toFixed(2)}`} />
            <SummaryBlock label="MER" current={currentMer} prior={priorMer} comparable={priorComparable} format={(v) => v.toFixed(2)} />
          </div>
          {!priorComparable ? <StatePanel kind="partial" tone="warn" title="Comparison window incomplete" message="Deltas are not trustworthy yet because the selected range cannot be fully matched to the comparison window." /> : null}
          {priorComparable ? <div className="scope-note">Compare mode: {compareMode === 'same_day_last_week' ? 'Same day last week' : 'Prior period'} · Revenue {formatDeltaPct(revenueCompare.deltaPct)} · Orders {formatDeltaPct(ordersCompare.deltaPct)}</div> : null}
          <CompareSummary mode={compareMode} points={comparePoints} />
        </>
      ) : (
        <Card title="Performance Summary"><div className="state-message">No KPI rows returned.</div></Card>
      )}
      <Card title="Revenue + Sessions Trend">
        {loading ? <div className="state-message">Loading live KPI trend…</div> : null}
        {error ? <div className="state-message error">{error}</div> : null}
        {!loading && !error && currentRows.length ? (
          <TrendChart
            rows={currentRows}
            lines={[
              { key: 'revenue', label: 'Revenue', color: '#6ea8ff', axisId: 'left' },
              { key: 'sessions', label: 'Sessions', color: '#ffb257', axisId: 'right' },
            ]}
          />
        ) : null}
        {!loading && !error && !currentRows.length ? <div className="state-message">No KPI rows returned.</div> : null}
      </Card>
      {seasonalityApplicable ? (
        <Card title="Revenue vs Seasonal Baseline">
          <BaselineBand
            metric="revenue"
            start={range.startDate}
            end={range.endDate}
            currentSeries={currentRows.map((row) => ({ date: row.business_date, value: Number(row.revenue) || 0 }))}
            currentLabel="Revenue"
            color="#6ea8ff"
            valueFormatter={(v) => `$${v.toLocaleString()}`}
          />
        </Card>
      ) : null}
      <div className="two-col two-col-equal">
        <Card title="Orders Trend">
          {seasonalityApplicable && latestCompleteDay ? (
            <div style={{ marginBottom: 6 }}>
              <SeasonalContextBadge metric="orders" onDate={latestCompleteDay.business_date} value={latestCompleteDay.orders} />
            </div>
          ) : null}
          {loading ? <div className="state-message">Loading live orders trend…</div> : error ? <div className="state-message error">{error}</div> : currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'orders', label: 'Orders', color: '#39d08f', axisId: 'left' }]} height={220} /> : <div className="state-message">No order rows returned.</div>}
        </Card>
        <Card title="Driver Change Summary">
          <div className="stack-list">
            <div className="list-item"><strong>Traffic change</strong><p>{priorComparable ? `${trafficContribution.toFixed(1)}%` : '—'}</p></div>
            <div className="list-item"><strong>Conversion change</strong><p>{priorComparable ? `${conversionContribution.toFixed(1)}%` : '—'}</p></div>
            <div className="list-item"><strong>AOV change</strong><p>{priorComparable ? `${aovContribution.toFixed(1)}%` : '—'}</p></div>
            <div className="list-item"><strong>Interpretation</strong><p>These are directional driver changes vs the prior comparison window, not an additive revenue decomposition.</p></div>
          </div>
        </Card>
      </div>
      <div className="two-col two-col-equal">
        <Card title="Decision Event Annotations">
          <EventAnnotationList diagnostics={overview?.diagnostics || []} recommendations={overview?.recommendations || []} rangeStart={range.startDate} rangeEnd={range.endDate} />
        </Card>
        <Card title="Inventory / Fulfillment Risk Layer">
          <StatePanel kind="partial" tone="warn" title="Inventory layer still blocked by ERP coverage" message="Commercial decisions can be made on demand efficiency today, but stockout and ship-delay risk are not yet wired into this page. Avoid scaling campaigns blindly if a SKU family is supply-constrained." detail="Needed next metrics: SKU stock cover, backorder exposure, fulfillment aging, and delayed-ship rate by product line." />
        </Card>
      </div>
      <Card title="Daily Performance Table">
        {loading ? <div className="state-message">Loading live KPI table…</div> : null}
        {error ? <div className="state-message error">{error}</div> : null}
        {!loading && !error && currentRows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Revenue</th>
                  <th>Orders</th>
                  <th>AOV</th>
                  <th>Sessions</th>
                  <th>Conversion</th>
                  <th>Ad Spend</th>
                  <th>MER</th>
                </tr>
              </thead>
              <tbody>
                {currentRows.map((row) => (
                  <tr key={row.business_date}>
                    <td>{row.business_date}</td>
                    <td>{formatNumber(row.revenue, 2, '$')}</td>
                    <td>{row.orders}</td>
                    <td>{formatNumber(row.average_order_value, 2, '$')}</td>
                    <td>{formatNumber(row.sessions, 0)}</td>
                    <td>{formatNumber(row.conversion_rate, 2, '', '%')}</td>
                    <td>{formatNumber(row.ad_spend, 2, '$')}</td>
                    <td>{formatNumber(row.mer, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {!loading && !error && !currentRows.length ? <div className="state-message">No KPI rows returned.</div> : null}
      </Card>
    </div>
  )
}
