import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { BarIndicator } from '../components/BarIndicator'
import { TruthBadge } from '../components/TruthBadge'
import { ProvenanceBanner } from '../components/ProvenanceBanner'
import { CollapsibleSection } from '../components/CollapsibleSection'
import { RangeToolbar } from '../components/RangeToolbar'
import { CompareToolbar } from '../components/CompareToolbar'
import { BaselineBand } from '../components/BaselineBand'
import { SeasonalContextBadge } from '../components/SeasonalContextBadge'
import { EventTimelineStrip } from '../components/EventTimelineStrip'
import { ChannelMixCard } from '../components/ChannelMixCard'
import { DivisionHero } from '../components/DivisionHero'
import { ApiError, api } from '../lib/api'
import type { FinancialsGrossProfit } from '../lib/api'
import { currency, deltaPct, deltaDirection, fmtPct, fmtInt } from '../lib/format'
import { KPIDaily } from '../lib/types'
import { buildPresetRange, filterRowsByRange, type RangeState } from '../lib/range'
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
        if (!cancelled) {
          setAllRows(rows)
          setRange(buildPresetRange('7d', rows))
        }
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

  // Pull canonical gross profit for the active window — same numbers
  // as Executive / Commercial / Marketing / Command Center pages.
  // SharePoint COGS + ShipStation shipping + ad spend folded in.
  const [gpCurrent, setGpCurrent] = useState<FinancialsGrossProfit | null>(null)
  const [gpPrior, setGpPrior] = useState<FinancialsGrossProfit | null>(null)
  useEffect(() => {
    if (!currentRows.length) return
    const ctl = new AbortController()
    const cStart = currentRows[0].business_date
    const cEnd = currentRows[currentRows.length - 1].business_date
    // /gross-profit treats end as exclusive — bump by 1 day
    const endDate = (() => { const d = new Date(cEnd); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10) })()
    api.financialsGrossProfit({ start: cStart, end: endDate }, ctl.signal).then(setGpCurrent).catch(() => setGpCurrent(null))
    if (priorRows.length) {
      const pStart = priorRows[0].business_date
      const pEnd = priorRows[priorRows.length - 1].business_date
      const pEndPlus = (() => { const d = new Date(pEnd); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10) })()
      api.financialsGrossProfit({ start: pStart, end: pEndPlus }, ctl.signal).then(setGpPrior).catch(() => setGpPrior(null))
    }
    return () => ctl.abort()
  }, [currentRows, priorRows])

  const rev = sum(currentRows, 'revenue')
  const revPrior = sum(priorRows, 'revenue')
  const grossRev = sum(currentRows, 'gross_revenue')
  const grossRevPrior = sum(priorRows, 'gross_revenue')
  const refunds = sum(currentRows, 'refunds')
  const discounts = sum(currentRows, 'total_discounts')
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
  // Canonical GP from /api/financials/gross-profit (SharePoint COGS +
  // ShipStation shipping subtracted). Falls back to revenue−refunds−adSpend
  // ONLY while the canonical fetch is in flight, never as steady state.
  const grossProfit = gpCurrent?.totals.gross_profit_usd ?? (rev - refunds - adSpend)
  const grossProfitPrior = gpPrior?.totals.gross_profit_usd ?? (revPrior - sum(priorRows, 'refunds') - sum(priorRows, 'ad_spend'))
  const grossMarginPct = gpCurrent?.totals.gross_margin_pct ?? (rev > 0 ? (grossProfit / rev) * 100 : 0)
  const contributionMargin = gpCurrent?.totals.contribution_margin_usd ?? null
  const contributionMarginPct = gpCurrent?.totals.contribution_margin_pct ?? null
  const appliedCogs = gpCurrent?.totals.applied_cogs_usd ?? 0
  const appliedShipping = gpCurrent?.totals.applied_shipping_usd ?? 0
  const isCanonicalGp = gpCurrent != null
  const discountRate = rev > 0 ? (discounts / (rev + discounts)) * 100 : 0

  // KPI strip removed — DivisionHero already shows revenue/GP/MER/conv.
  // Keep these locals available for the trend chart + composition card.

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
      {/* ── DIVISION HERO — signature: revenueDial ─────────────────
          Dual-arc dial: outer = revenue vs target (prior × 1.1 as an
          implicit growth goal), inner = margin %. The dial shape is
          unique to the Revenue Engine. */}
      {(() => {
        const target = revPrior * 1.1  // +10% growth as the implicit plan
        const revProgress = target > 0 ? rev / target : 0
        const marginPct = grossMarginPct / 100
        const revState: 'good' | 'warn' | 'bad' | 'neutral' =
          revProgress >= 1 ? 'good' : revProgress >= 0.85 ? 'warn' : revProgress > 0 ? 'bad' : 'neutral'
        const merState: 'good' | 'warn' | 'bad' | 'neutral' =
          mer >= 2.0 ? 'good' : mer >= 1.5 ? 'warn' : mer > 0 ? 'bad' : 'neutral'
        return (
          <DivisionHero
            accentColor="#f59e0b"
            accentColorSoft="#ec4899"
            signature="revenueDial"
            title="Revenue Engine"
            subtitle="Financial scoreboard — revenue, margin, MER, AOV, conversion. Gross profit pulls SharePoint-extracted CBOM COGS + ShipStation shipping from the canonical /api/financials/gross-profit endpoint."
            rightMeta={
              <div style={{ fontSize: 11, color: 'var(--muted)', textAlign: 'right' }}>
                <div>{range.preset ? `Range · ${range.preset}` : 'Custom range'}</div>
                <div>{currentRows.length} days in window</div>
              </div>
            }
            primary={{
              label: 'Revenue vs prior +10% target',
              value: currency(rev),
              sublabel: `target ${currency(target)}`,
              state: revState,
              progress: revProgress,
              progressSecondary: Math.max(0, marginPct),
            }}
            flanking={[
              {
                label: 'MER',
                value: mer > 0 ? mer.toFixed(2) : '—',
                sublabel: merPrior > 0 ? `vs ${merPrior.toFixed(2)} prior` : 'target 2.0',
                state: merState,
                progress: Math.min(1, mer / 3),
              },
              {
                label: 'Gross profit',
                value: currency(grossProfit),
                sublabel: isCanonicalGp
                  ? `${grossMarginPct.toFixed(1)}% margin${grossProfitPrior !== 0 ? ` · ${((grossProfit - grossProfitPrior) / Math.abs(grossProfitPrior) * 100).toFixed(0)}% vs prior` : ''}`
                  : 'loading canonical…',
                state: grossProfit >= grossProfitPrior ? 'good' : 'warn',
              },
            ]}
            tiles={[
              {
                label: 'Orders',
                value: fmtInt(orders),
                sublabel: ordersPrior > 0 ? `${((orders - ordersPrior) / ordersPrior * 100).toFixed(0)}%` : undefined,
                state: orders >= ordersPrior ? 'good' : 'warn',
              },
              {
                label: 'AOV',
                value: aovAvg > 0 ? currency(aovAvg) : '—',
                state: aovAvg >= aovPrior ? 'good' : 'warn',
              },
              {
                label: 'Sessions',
                value: fmtInt(sessions),
                state: sessions >= sessionsPrior ? 'good' : 'warn',
              },
              {
                label: 'Conversion',
                value: convAvg > 0 ? `${convAvg.toFixed(2)}%` : '—',
                state: convAvg >= convPrior ? 'good' : 'warn',
              },
              {
                label: 'Refunds',
                value: currency(refunds),
                state: 'neutral',
              },
              {
                label: 'Discount rate',
                value: `${discountRate.toFixed(1)}%`,
                state: discountRate <= 10 ? 'good' : discountRate <= 20 ? 'warn' : 'bad',
              },
            ]}
          />
        )
      })()}

      {loading ? <Card title="Loading"><div className="state-message">Loading revenue data…</div></Card> : null}
      {error ? <Card title="Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <div className="toolbar">
            <RangeToolbar rows={allRows} range={range} onChange={setRange} />
            <CompareToolbar mode={compareMode} onChange={setCompareMode} />
          </div>

          {/* Auto-generated revenue insight — single source of truth.
              The duplicate "Insight" card below was removed. */}
          {currentRows.length > 0 && priorRows.length > 0 ? (
            <div className="scope-note" style={{ fontSize: 12, color: 'var(--muted)', fontStyle: 'italic', padding: '6px 0' }}>
              💡 {generateRevenueInsight(rev, revPrior, sessions, sessionsPrior, convAvg, convPrior, aovAvg, aovPrior)}
            </div>
          ) : null}

          {/* Traffic & conversion bars stay above the fold.
              Composition breakdown folded — it's a 10-row reference table. */}
          <CollapsibleSection
            id="rev-composition"
            title="Revenue composition"
            subtitle="Line-by-line: gross sales → discounts → COGS → shipping → ad spend → GP → contribution margin"
            density="compact"
            meta={`${currency(grossProfit)} GP · ${grossMarginPct.toFixed(1)}% margin`}
          >
            <div className="venom-breakdown-list">
                <div className="venom-breakdown-row"><span>Gross Sales</span><span className="venom-breakdown-val">{currency(grossRev)}</span><TruthBadge state="canonical" /><span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>Shopify "Total sales"</span></div>
                <div className="venom-breakdown-row"><span>Net Sales</span><span className="venom-breakdown-val">{currency(rev)}</span><TruthBadge state="canonical" /><span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>post-refund</span></div>
                <div className="venom-breakdown-row"><span>Refunds</span><span className="venom-breakdown-val">{currency(refunds)}</span><TruthBadge state="canonical" /></div>
                <div className="venom-breakdown-row"><span>Discounts</span><span className="venom-breakdown-val">{discounts > 0 ? currency(discounts) : '$0.00'}</span><TruthBadge state={discounts > 0 ? 'canonical' : 'proxy'} />{discounts > 0 && <span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>({fmtPct(discountRate / 100, 1)} of gross)</span>}</div>
                <div className="venom-breakdown-row"><span>Product COGS</span><span className="venom-breakdown-val">{currency(gpCurrent?.totals.applied_cogs_classified_usd ?? 0)}</span><TruthBadge state={isCanonicalGp ? 'canonical' : 'proxy'} /><span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>SharePoint CBOMs</span></div>
                <div className="venom-breakdown-row"><span>Accessory COGS (est)</span><span className="venom-breakdown-val">{currency(gpCurrent?.totals.applied_cogs_accessory_estimate_usd ?? 0)}</span><TruthBadge state={isCanonicalGp ? 'estimated' : 'proxy'} /><span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>50% of accessory revenue</span></div>
                <div className="venom-breakdown-row"><span>Shipping</span><span className="venom-breakdown-val">{currency(appliedShipping)}</span><TruthBadge state={isCanonicalGp ? 'canonical' : 'proxy'} /><span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>ShipStation carrier cost</span></div>
                <div className="venom-breakdown-row"><span>Ad Spend</span><span className="venom-breakdown-val">{currency(adSpend)}</span><TruthBadge state="canonical" /></div>
                <div className="venom-breakdown-row"><span>Gross Profit</span><span className="venom-breakdown-val">{currency(grossProfit)}</span><TruthBadge state={isCanonicalGp ? 'canonical' : 'proxy'} /><span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>{isCanonicalGp ? `${grossMarginPct.toFixed(1)}% margin` : 'loading…'}</span></div>
                <div className="venom-breakdown-row"><span>Contribution Margin</span><span className="venom-breakdown-val">{contributionMargin != null ? currency(contributionMargin) : '—'}</span><TruthBadge state={isCanonicalGp ? 'canonical' : 'proxy'} /><span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 4 }}>{contributionMarginPct != null ? `${contributionMarginPct.toFixed(1)}% · GP − ad spend` : 'GP − ad spend'}</span></div>
            </div>
            <ProvenanceBanner
              compact
              truthState={isCanonicalGp ? 'canonical' : 'proxy'}
              lastUpdated={currentRows.length ? currentRows[currentRows.length - 1]?.business_date : undefined}
              scope={`${currentRows.length}-day window · Shopify + Triple Whale + SharePoint CBOMs + ShipStation`}
              caveat={
                isCanonicalGp
                  ? `Gross Profit = Net Revenue − ${currency(appliedCogs)} COGS (incl. ${currency(appliedShipping)} shipping) − applied accessory estimate. Same canonical figures as Executive / Commercial / Marketing pages.`
                  : 'Loading canonical /api/financials/gross-profit — temporary proxy displayed until response lands.'
              }
            />
          </CollapsibleSection>

          {/* Traffic & Conversion bars stay above the fold — fully visual. */}
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

          {/* Seasonal Context — folded by default; viewers drill in when curious. */}
          {currentRows.length >= 3 && (
            <CollapsibleSection
              id="rev-seasonal-context"
              title="Seasonal context"
              subtitle="Is today's revenue normal for this week of year?"
              density="compact"
              meta={
                <SeasonalContextBadge
                  metric="revenue"
                  onDate={currentRows[currentRows.length - 1].business_date}
                  value={currentRows[currentRows.length - 1].revenue}
                />
              }
            >
              <BaselineBand
                metric="revenue"
                start={currentRows[0].business_date}
                end={currentRows[currentRows.length - 1].business_date}
                currentSeries={currentRows.map((r) => ({ date: r.business_date, value: Number(r.revenue) || 0 }))}
                currentLabel="Revenue (current)"
                color="#6ea8ff"
                height={260}
                valueFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
              />
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                  Events during this window:
                </div>
                <EventTimelineStrip
                  start={currentRows[0].business_date}
                  end={currentRows[currentRows.length - 1].business_date}
                  division="commercial"
                  showStates={false}
                />
              </div>
            </CollapsibleSection>
          )}

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

          {/* Duplicate "Insight" card removed — same insight already
              renders inline above the composition fold. */}

          {/* Channel spend mix — Triple Whale */}
          {range.startDate && range.endDate ? (
            <ChannelMixCard range={{ startDate: range.startDate, endDate: range.endDate }} />
          ) : null}

          {/* Slim drill-down strip — folded by default. */}
          <CollapsibleSection
            id="rev-related"
            title="Related drill-downs"
            subtitle="Friction Map · Root Cause · Marketing"
            density="compact"
          >
            <div className="venom-drill-grid">
              <Link to="/friction" className="venom-drill-tile"><div><strong>Friction Map</strong><small>Conversion friction analysis</small></div></Link>
              <Link to="/root-cause" className="venom-drill-tile"><div><strong>Root Cause</strong><small>Revenue diagnostic</small></div></Link>
              <Link to="/division/marketing" className="venom-drill-tile"><div><strong>Marketing</strong><small>Campaign performance</small></div></Link>
            </div>
          </CollapsibleSection>
        </>
      ) : null}
    </div>
  )
}
