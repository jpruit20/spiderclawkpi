import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { RangeToolbar } from '../components/RangeToolbar'
import { TrendChart } from '../components/TrendChart'
import { ApiError, api, getApiBase } from '../lib/api'
import { buildPresetRange, filterRowsByRange, RangeState } from '../lib/range'
import { KPIDaily } from '../lib/types'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0)
}

function compare(current: number, prior: number) {
  if (!prior) return 'n/a'
  const delta = ((current - prior) / prior) * 100
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}%`
}

function SummaryBlock({ label, current, prior, format = (v: number) => v.toFixed(2) }: { label: string; current: number; prior: number; format?: (v: number) => string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value compact">{format(current)}</div>
      <div className="stat-subvalue">vs prior period {compare(current, prior)}</div>
    </div>
  )
}

function isIncompleteLatestDay(row?: KPIDaily) {
  if (!row) return false
  return (row.sessions === 0 || row.sessions == null) && ((row.orders || 0) > 0 || (row.revenue || 0) > 0)
}

export function CommercialPerformance() {
  const [rows, setRows] = useState<KPIDaily[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '7d', startDate: '', endDate: '' })

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await api.dailyKpis()
        if (!cancelled) {
          const ordered = [...payload].sort((a, b) => a.business_date.localeCompare(b.business_date))
          const safeRows = isIncompleteLatestDay(ordered[ordered.length - 1]) ? ordered.slice(0, -1) : ordered
          setRows(safeRows)
          setRange(buildPresetRange('7d', safeRows))
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load daily KPIs')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const currentRows = useMemo(() => filterRowsByRange(rows, range), [rows, range])
  const currentRevenue = sum(currentRows, 'revenue')
  const currentSessions = sum(currentRows, 'sessions')
  const currentOrders = sum(currentRows, 'orders')
  const currentAdSpend = sum(currentRows, 'ad_spend')
  const currentConversion = currentSessions ? (currentOrders / currentSessions) * 100 : 0
  const currentAov = currentOrders ? currentRevenue / currentOrders : 0
  const currentMer = currentAdSpend ? currentRevenue / currentAdSpend : 0

  const priorRows = useMemo(() => {
    const endIndex = rows.findIndex((row) => row.business_date === range.startDate)
    const span = currentRows.length
    if (endIndex <= 0 || !span) return []
    return rows.slice(Math.max(0, endIndex - span), endIndex)
  }, [rows, range, currentRows])

  const priorRevenue = sum(priorRows, 'revenue')
  const priorSessions = sum(priorRows, 'sessions')
  const priorOrders = sum(priorRows, 'orders')
  const priorAdSpend = sum(priorRows, 'ad_spend')
  const priorConversion = priorSessions ? (priorOrders / priorSessions) * 100 : 0
  const priorAov = priorOrders ? priorRevenue / priorOrders : 0
  const priorMer = priorAdSpend ? priorRevenue / priorAdSpend : 0
  const trafficContribution = priorRevenue ? ((currentSessions - priorSessions) / Math.max(priorSessions, 1)) * 100 : 0
  const conversionContribution = priorConversion ? ((currentConversion - priorConversion) / priorConversion) * 100 : 0
  const aovContribution = priorAov ? ((currentAov - priorAov) / priorAov) * 100 : 0

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Commercial Performance</h2>
        <p>Revenue and sessions on the main chart, orders on a separate chart, all tied to one truthful range control.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>

      <RangeToolbar rows={rows} range={range} onChange={setRange} />

      <div className="kpi-grid summary-grid">
        <SummaryBlock label="Revenue" current={currentRevenue} prior={priorRevenue} format={(v) => `$${v.toFixed(2)}`} />
        <SummaryBlock label="Sessions" current={currentSessions} prior={priorSessions} format={(v) => v.toFixed(0)} />
        <SummaryBlock label="Orders" current={currentOrders} prior={priorOrders} format={(v) => v.toFixed(0)} />
        <SummaryBlock label="Conversion" current={currentConversion} prior={priorConversion} format={(v) => `${v.toFixed(2)}%`} />
        <SummaryBlock label="AOV" current={currentAov} prior={priorAov} format={(v) => `$${v.toFixed(2)}`} />
        <SummaryBlock label="Ad Spend" current={currentAdSpend} prior={priorAdSpend} format={(v) => `$${v.toFixed(2)}`} />
        <SummaryBlock label="MER" current={currentMer} prior={priorMer} format={(v) => v.toFixed(2)} />
      </div>
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
      <div className="two-col two-col-equal">
        <Card title="Orders Trend">
          {!loading && !error && currentRows.length ? <TrendChart rows={currentRows} lines={[{ key: 'orders', label: 'Orders', color: '#39d08f', axisId: 'left' }]} height={220} /> : <div className="state-message">No order rows returned.</div>}
        </Card>
        <Card title="Revenue Delta Decomposition">
          <div className="stack-list">
            <div className="list-item"><strong>Traffic contribution</strong><p>{trafficContribution.toFixed(1)}%</p></div>
            <div className="list-item"><strong>Conversion contribution</strong><p>{conversionContribution.toFixed(1)}%</p></div>
            <div className="list-item"><strong>AOV contribution</strong><p>{aovContribution.toFixed(1)}%</p></div>
            <div className="list-item"><strong>Formula</strong><p>Revenue delta = traffic + conversion + AOV. This is directional decomposition for operating review, not causal attribution.</p></div>
          </div>
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
                    <td>${row.revenue.toFixed(2)}</td>
                    <td>{row.orders}</td>
                    <td>${row.average_order_value.toFixed(2)}</td>
                    <td>{row.sessions.toFixed(0)}</td>
                    <td>{row.conversion_rate.toFixed(2)}%</td>
                    <td>${row.ad_spend.toFixed(2)}</td>
                    <td>{row.mer.toFixed(2)}</td>
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
