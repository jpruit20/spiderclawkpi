import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge } from '../components/TruthBadge'
import { VenomKpiStrip, KpiCardDef } from '../components/VenomKpiStrip'
import { RangeToolbar } from '../components/RangeToolbar'
import { CompareToolbar } from '../components/CompareToolbar'
import { ApiError, api } from '../lib/api'
import { currency, deltaPct, deltaDirection, fmtPct, fmtInt } from '../lib/format'
import { KPIDaily } from '../lib/types'
import { filterRowsByRange, type RangeState } from '../lib/range'
import { priorPeriodRows, sameDayLastWeekRows } from '../lib/compare'
import { ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts'

function sum(rows: KPIDaily[], key: keyof KPIDaily) {
  return rows.reduce((s, r) => s + (Number(r[key]) || 0), 0)
}
function avg(rows: KPIDaily[], key: keyof KPIDaily) {
  if (!rows.length) return 0
  return sum(rows, key) / rows.length
}

function generateRevenueInsight(rev: number, revPrior: number, sessions: number, sessionsPrior: number, conv: number, convPrior: number, aov: number, aovPrior: number): string {
  const revDelta = revPrior ? ((rev - revPrior) / revPrior * 100) : 0
  const direction = revDelta > 1 ? 'up' : revDelta < -1 ? 'down' : 'flat'
  const drivers = [
    { name: 'traffic', delta: sessionsPrior ? ((sessions - sessionsPrior) / sessionsPrior * 100) : 0 },
    { name: 'conversion', delta: convPrior ? ((conv - convPrior) / convPrior * 100) : 0 },
    { name: 'AOV', delta: aovPrior ? ((aov - aovPrior) / aovPrior * 100) : 0 },
  ].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
  const primary = drivers[0]
  let insight = `Revenue is ${direction} ${revDelta >= 0 ? '+' : ''}${revDelta.toFixed(1)}% vs prior period, driven primarily by ${primary.name}.`
  if (primary.name === 'traffic' && primary.delta < -5) insight += ' Consider increasing acquisition spend or reviewing SEO performance.'
  else if (primary.name === 'conversion' && primary.delta < -5) insight += ' Review the friction map for conversion blockers.'
  else if (primary.name === 'AOV' && primary.delta > 5) insight += ' Strong AOV suggests upsell strategies are working.'
  else if (direction === 'up') insight += ' Maintain current trajectory.'
  return insight
}

export function RevenueEngine() {
  const [allRows, setAllRows] = useState<KPIDaily[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeState>({ preset: '7d', startDate: '', endDate: '' })
  const [compareMode, setCompareMode] = useState<'prior_period' | 'same_day_last_week'>('prior_period')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const rows = await api.dailyKpis()
        if (!cancelled) setAllRows(rows)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load revenue data')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const currentRows = useMemo(() => filterRowsByRange(allRows, range), [allRows, range])
  const priorRows = useMemo(() => {
    return compareMode === 'same_day_last_week' ? sameDayLastWeekRows(allRows, currentRows) : priorPeriodRows(allRows, currentRows)
  }, [allRows, currentRows, compareMode])

  const rev = sum(currentRows, 'revenue')
  const revPrior = sum(priorRows, 'revenue')
  const refunds = sum(currentRows, 'refunds')
  const adSpend = sum(currentRows, 'ad_spend')
  const orders = sum(currentRows, 'orders')
  const ordersPrior = sum(priorRows, 'orders')
  const sessions = sum(currentRows, 'sessions')
  const sessionsPrior = sum(priorRows, 'sessions')
  const convAvg = avg(currentRows, 'conversion_rate')
  const convPrior = avg(priorRows, 'conversion_rate')
  const aovAvg = avg(currentRows, 'average_order_value')
  const aovPrior = avg(priorRows, 'average_order_value')
  const mer = adSpend > 0 ? rev / adSpend : 0
  const merPrior = sum(priorRows, 'ad_spend') > 0 ? revPrior / sum(priorRows, 'ad_spend') : 0
  const grossProfit = rev - refunds - adSpend
  const grossProfitPrior = revPrior - sum(priorRows, 'refunds') - sum(priorRows, 'ad_spend')

  const kpiCards = useMemo<KpiCardDef[]>(() => [
    { label: 'Revenue', value: currency(rev), sub: `${currentRows.length} days`, truthState: 'canonical', delta: { text: deltaPct(rev, revPrior), direction: deltaDirection(rev, revPrior) } },
    { label: 'Gross Profit Proxy', value: currency(grossProfit), sub: 'Revenue - refunds - ad spend', truthState: 'proxy', delta: { text: deltaPct(grossProfit, grossProfitPrior), direction: deltaDirection(grossProfit, grossProfitPrior) } },
    { label: 'MER', value: mer > 0 ? `${mer.toFixed(1)}x` : '\u2014', sub: 'Revenue / ad spend', truthState: 'canonical', delta: merPrior > 0 ? { text: deltaPct(mer, merPrior), direction: deltaDirection(mer, merPrior) } : undefined },
    { label: 'Conversion', value: fmtPct(convAvg / 100, 2), sub: 'Period average', truthState: 'canonical', delta: { text: deltaPct(convAvg, convPrior), direction: deltaDirection(convAvg, convPrior) } },
  ], [rev, revPrior, grossProfit, grossProfitPrior, mer, merPrior, convAvg, convPrior, currentRows.length])

  const chartData = useMemo(() => {
    return currentRows.map((r, i) => ({
      date: r.business_date.slice(5),
      revenue: Math.round(r.revenue),
      sessions: Math.round(r.sessions),
      orders: r.orders,
      prior_revenue: priorRows[i] ? Math.round(priorRows[i].revenue) : null,
    }))
  }, [currentRows, priorRows])

  return (
    <div className="page-grid venom-page">
      <div className="venom-header">
        <div>
          <h2 className="venom-title">Revenue Engine</h2>
          <p className="venom-subtitle">Financial performance and efficiency</p>
        </div>
      </div>

      {loading ? <Card title="Loading"><div className="state-message">Loading revenue data…</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <div className="toolbar">
            <RangeToolbar rows={allRows} range={range} onChange={setRange} />
            <CompareToolbar mode={compareMode} onChange={setCompareMode} />
          </div>

          <VenomKpiStrip cards={kpiCards} />

          {/* Two-col breakdown */}
          <div className="two-col two-col-equal">
            <section className="card">
              <div className="venom-panel-head"><strong>Revenue Composition</strong></div>
              <div className="venom-breakdown-list">
                <div className="venom-breakdown-row"><span>Revenue</span><span className="venom-breakdown-val">{currency(rev)}</span><TruthBadge state="canonical" /></div>
                <div className="venom-breakdown-row"><span>Refunds</span><span className="venom-breakdown-val">{currency(refunds)}</span><TruthBadge state="canonical" /></div>
                <div className="venom-breakdown-row"><span>Discounts</span><span className="venom-breakdown-val">Missing data</span><TruthBadge state="unavailable" /></div>
                <div className="venom-breakdown-row"><span>Ad Spend</span><span className="venom-breakdown-val">{currency(adSpend)}</span><TruthBadge state="canonical" /></div>
                <div className="venom-breakdown-row"><span>Gross Profit Proxy</span><span className="venom-breakdown-val">{currency(grossProfit)}</span><TruthBadge state="proxy" /></div>
                <div className="venom-breakdown-row"><span>Contribution</span><span className="venom-breakdown-val">{currency(grossProfit)}</span><TruthBadge state="proxy" /></div>
              </div>
            </section>

            <section className="card">
              <div className="venom-panel-head"><strong>Traffic & Conversion</strong></div>
              <div className="venom-bar-list">
                <div className="venom-bar-row">
                  <span className="venom-bar-label">Sessions</span>
                  <BarIndicator value={sessions} max={Math.max(sessions, sessionsPrior) || 1} color="var(--blue)" />
                  <span className="venom-bar-value">{fmtInt(sessions)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">Orders</span>
                  <BarIndicator value={orders} max={Math.max(orders, ordersPrior) || 1} color="var(--green)" />
                  <span className="venom-bar-value">{fmtInt(orders)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">AOV</span>
                  <BarIndicator value={aovAvg} max={Math.max(aovAvg, aovPrior, 200) * 1.2} color="var(--orange)" />
                  <span className="venom-bar-value">{currency(aovAvg)}</span>
                </div>
                <div className="venom-bar-row">
                  <span className="venom-bar-label">Conversion</span>
                  <BarIndicator value={convAvg} max={10} color="var(--green)" />
                  <span className="venom-bar-value">{fmtPct(convAvg / 100, 2)}</span>
                </div>
              </div>
              <small className="venom-panel-footer">Prior period shown as bar max reference</small>
            </section>
          </div>

          {/* Trend Chart */}
          <section className="card">
            <div className="venom-panel-head">
              <strong>Revenue Trend</strong>
              <span className="venom-panel-hint">{currentRows.length} days</span>
            </div>
            {chartData.length > 0 ? (
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height={320}>
                  <ComposedChart data={chartData}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="date" stroke="#9fb0d4" tick={{ fontSize: 11 }} />
                    <YAxis yAxisId="left" stroke="#9fb0d4" tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
                    <YAxis yAxisId="right" orientation="right" stroke="#9fb0d4" />
                    <Tooltip />
                    <Legend />
                    <Area yAxisId="left" type="monotone" name="Revenue" dataKey="revenue" fill="rgba(110,168,255,0.12)" stroke="var(--blue)" strokeWidth={2} />
                    <Line yAxisId="left" type="monotone" name="Prior revenue" dataKey="prior_revenue" stroke="var(--blue)" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
                    <Line yAxisId="right" type="monotone" name="Sessions" dataKey="sessions" stroke="var(--orange)" strokeWidth={1.5} dot={false} />
                    <Line yAxisId="right" type="monotone" name="Orders" dataKey="orders" stroke="var(--green)" strokeWidth={1.5} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : <div className="state-message">No trend data available.</div>}
          </section>

          {/* Insight */}
          <section className="card">
            <div className="venom-panel-head"><strong>Insight</strong></div>
            <div className="stack-list compact">
              <div className="list-item status-muted">
                <p>{generateRevenueInsight(rev, revPrior, sessions, sessionsPrior, convAvg, convPrior, aovAvg, aovPrior)}</p>
              </div>
            </div>
          </section>

          {/* Channel Revenue — blocked */}
          <section className="card">
            <div className="venom-panel-head"><strong>Channel Revenue Breakdown</strong><TruthBadge state="unavailable" /></div>
            <div className="stack-list compact">
              <div className="list-item status-bad">
                <div className="item-head"><strong>Blocked</strong><span className="badge badge-bad">missing source</span></div>
                <p>Channel-level revenue feed is not yet connected. This requires backend integration to split revenue by acquisition channel.</p>
                <small>Owner: Joseph · Still trustworthy: total revenue, orders, sessions, conversion rate</small>
              </div>
            </div>
          </section>

          {/* Navigation */}
          <section className="card">
            <div className="venom-panel-head"><strong>Related</strong></div>
            <div className="venom-drill-grid">
              <Link to="/friction" className="venom-drill-tile"><div><strong>Friction Map</strong><small>Conversion friction analysis</small></div></Link>
              <Link to="/root-cause" className="venom-drill-tile"><div><strong>Root Cause</strong><small>Revenue diagnostic</small></div></Link>
              <Link to="/division/marketing" className="venom-drill-tile"><div><strong>Marketing</strong><small>Campaign performance</small></div></Link>
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
