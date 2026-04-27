import { useEffect, useMemo, useState } from 'react'
import {
  Bar, BarChart, Cell, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../lib/api'
import type {
  ShippingCarrierMix, ShippingGeographic, ShippingCostTrend,
  Shipping3plRoi, ShippingCxCorrelation,
} from '../lib/api'

/**
 * Shipping intelligence — visual operations dashboard backed by
 * /api/shipping/* endpoints. Five sections:
 *   1. Headline tiles (totals, avg cost, carrier count)
 *   2. Carrier mix donut + spend table
 *   3. Geographic distribution by state (US heatmap-style bar chart)
 *   4. Cost trend over time (weekly buckets)
 *   5. 3PL location ROI estimator (would-save-N-if-warehouse-near-X)
 *   6. CX correlation: WISMO tickets matched to shipments
 *
 * Every section is responsive + uses recharts for visuals so the
 * page reads in seconds, not paragraphs.
 */

const PIE_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#14b8a6']

function fmtUSD(n: number | null | undefined): string {
  if (n == null) return '—'
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (Math.abs(n) >= 10_000) return `$${(n / 1000).toFixed(1)}k`
  if (Math.abs(n) >= 1000) return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

const CARRIER_LABEL: Record<string, string> = {
  fedex: 'FedEx', ups: 'UPS', usps: 'USPS', dhl: 'DHL',
  ontrac: 'OnTrac', amazon: 'Amazon', stamps_com: 'Stamps.com',
  unknown: 'Unknown',
}

interface Props {
  defaultDays?: number
  showCxCorrelation?: boolean  // toggle to render WISMO panel (Operations + CX pages set this)
}

export function ShippingIntelligenceCard({ defaultDays = 90, showCxCorrelation = true }: Props) {
  const [days, setDays] = useState(defaultDays)
  const [mix, setMix] = useState<ShippingCarrierMix | null>(null)
  const [geo, setGeo] = useState<ShippingGeographic | null>(null)
  const [trend, setTrend] = useState<ShippingCostTrend | null>(null)
  const [roi, setRoi] = useState<Shipping3plRoi | null>(null)
  const [cx, setCx] = useState<ShippingCxCorrelation | null>(null)
  const [tab, setTab] = useState<'overview' | 'geographic' | '3pl' | 'cx'>('overview')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    setError(null)
    Promise.all([
      api.shippingCarrierMix(days, ctl.signal).then(setMix).catch(() => setMix(null)),
      api.shippingGeographic(days, ctl.signal).then(setGeo).catch(() => setGeo(null)),
      api.shippingCostTrend(days, 'week', ctl.signal).then(setTrend).catch(() => setTrend(null)),
      api.shipping3plRoi(Math.max(days, 90), ctl.signal).then(setRoi).catch(() => setRoi(null)),
      showCxCorrelation
        ? api.shippingCxCorrelation(Math.min(days, 90), ctl.signal).then(setCx).catch(() => setCx(null))
        : Promise.resolve(),
    ]).catch(() => undefined)
    return () => ctl.abort()
  }, [days, showCxCorrelation])

  const carrierData = useMemo(
    () => (mix?.carriers || []).map((c, i) => ({
      name: CARRIER_LABEL[c.carrier] || c.carrier,
      value: c.total_cost_usd,
      shipments: c.shipments,
      avg: c.avg_cost_usd,
      share: c.share_pct,
      color: PIE_COLORS[i % PIE_COLORS.length],
    })),
    [mix],
  )

  const stateData = useMemo(
    () => (geo?.by_state || [])
      .filter(s => s.country === 'US' && s.state !== '??')
      .slice(0, 15)
      .map((s, i) => ({
        name: s.state,
        shipments: s.shipments,
        cost: s.total_cost_usd,
        avg: s.avg_cost_usd,
        color: PIE_COLORS[i % PIE_COLORS.length],
      })),
    [geo],
  )

  const trendData = useMemo(
    () => (trend?.series || []).map(s => ({
      bucket: s.bucket.slice(5),  // MM-DD
      cost: s.cost_usd,
      shipments: s.shipments,
      avg: s.avg_cost_usd,
    })),
    [trend],
  )

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <strong>Shipping intelligence</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            ShipStation Spider stores (Amazon + Shopify + Manual). Carrier mix, geographic distribution, 3PL siting, CX correlation.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[30, 90, 180, 365].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              style={{
                background: days === d ? 'var(--blue)' : 'var(--panel-2)',
                border: '1px solid rgba(255,255,255,0.1)',
                color: days === d ? '#fff' : 'var(--muted)',
                padding: '3px 8px', borderRadius: 4, fontSize: 11, cursor: 'pointer',
              }}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Tab strip */}
      <div style={{ display: 'flex', gap: 16, marginTop: 12, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        {(['overview', 'geographic', '3pl', ...(showCxCorrelation ? ['cx' as const] : [])] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: 'none', border: 'none',
              padding: '6px 0',
              borderBottom: tab === t ? '2px solid var(--blue)' : '2px solid transparent',
              color: tab === t ? 'var(--text)' : 'var(--muted)',
              fontSize: 12, fontWeight: 600, letterSpacing: 0.3, cursor: 'pointer', textTransform: 'uppercase',
            }}
          >
            {t === 'overview' ? 'Carriers' : t === 'geographic' ? 'Geography' : t === '3pl' ? '3PL ROI' : 'CX correlation'}
          </button>
        ))}
      </div>

      {error && <div style={{ marginTop: 10, color: 'var(--red)', fontSize: 12 }}>{error}</div>}

      {/* OVERVIEW: headline tiles + carrier mix donut + carrier table */}
      {tab === 'overview' && mix && (
        <div style={{ marginTop: 12 }}>
          {/* Tiles */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8 }}>
            <Tile label="Total shipments" value={fmtInt(mix.totals.shipments)} accent="blue" />
            <Tile label="Total spend" value={fmtUSD(mix.totals.total_cost_usd)} accent="orange" />
            <Tile label="Avg cost / shipment" value={fmtUSD(mix.totals.avg_cost_per_shipment)} accent="neutral" />
            <Tile label="Active carriers" value={String(mix.carriers.length)} accent="neutral" />
          </div>

          {/* Donut + table */}
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 280px) 1fr', gap: 16, marginTop: 12 }}>
            <div style={{ width: '100%', height: 240 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>Carrier spend mix</div>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={carrierData} dataKey="value" nameKey="name" innerRadius={50} outerRadius={92} paddingAngle={1}>
                    {carrierData.map((d, i) => <Cell key={i} fill={d.color} stroke="var(--panel)" strokeWidth={1} />)}
                  </Pie>
                  <Tooltip
                    formatter={(v: number, _: string, p: any) => [`${fmtUSD(v)} · ${fmtInt(p.payload.shipments)} shipments · ${fmtUSD(p.payload.avg)} avg`, p.payload.name]}
                    contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', fontSize: 11 }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>Carrier breakdown</div>
              <table style={{ width: '100%', fontSize: 11, fontVariantNumeric: 'tabular-nums', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ color: 'var(--muted)', textAlign: 'left', fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    <th style={{ padding: '4px 6px' }}>Carrier</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Ships</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Spend</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Avg/Ship</th>
                    <th style={{ padding: '4px 6px', textAlign: 'right' }}>Share</th>
                  </tr>
                </thead>
                <tbody>
                  {carrierData.map(c => (
                    <tr key={c.name} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                      <td style={{ padding: '4px 6px' }}>
                        <span style={{ display: 'inline-block', width: 10, height: 10, background: c.color, borderRadius: 2, marginRight: 6, verticalAlign: 'middle' }} />
                        {c.name}
                      </td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtInt(c.shipments)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtUSD(c.value)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtUSD(c.avg)}</td>
                      <td style={{ padding: '4px 6px', textAlign: 'right', color: 'var(--muted)' }}>{c.share.toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Cost trend */}
          {trendData.length > 0 && (
            <div style={{ marginTop: 12, height: 180 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>Weekly shipping spend</div>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
                  <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: 'var(--muted)' }} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--muted)' }} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip
                    formatter={(v: number, name: string) => name === 'cost' ? fmtUSD(v) : fmtInt(v)}
                    contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', fontSize: 11 }}
                  />
                  <Line dataKey="cost" stroke="var(--blue)" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* GEOGRAPHIC */}
      {tab === 'geographic' && geo && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8 }}>
            <Tile label="Domestic ships" value={fmtInt(geo.totals.domestic_shipments)} accent="green" />
            <Tile label="International" value={fmtInt(geo.totals.international_shipments)} accent="blue" />
            <Tile label="States reached" value={String(geo.totals.states_seen)} accent="neutral" />
          </div>
          <div style={{ marginTop: 12, fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>
            Top 15 destination states (by shipment count)
          </div>
          <div style={{ height: Math.max(280, stateData.length * 22) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stateData} layout="vertical" margin={{ top: 4, right: 80, left: 4, bottom: 4 }}>
                <XAxis type="number" tick={{ fontSize: 10, fill: 'var(--muted)' }} tickFormatter={v => fmtInt(v)} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: 'var(--text)' }} width={50} />
                <Tooltip
                  formatter={(v: number, _: string, p: any) => [`${fmtInt(v)} shipments · ${fmtUSD(p.payload.cost)} total · ${fmtUSD(p.payload.avg)} avg`, p.payload.name]}
                  contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', fontSize: 11 }}
                />
                <Bar dataKey="shipments" radius={[0, 4, 4, 0]}>
                  {stateData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* 3PL ROI */}
      {tab === '3pl' && roi && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
            Estimates the per-year shipping savings if a second warehouse opened at each candidate location.
            Current hub: <strong>{roi.current_warehouse.city}, {roi.current_warehouse.state}</strong>.
            Method: haversine distance × carrier zone multiplier.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {roi.candidates.map((c, i) => (
              <div key={c.name} style={{
                padding: 10, background: 'var(--panel-2)', borderRadius: 6,
                borderLeft: `3px solid ${i === 0 ? 'var(--green)' : i === 1 ? 'var(--blue)' : 'var(--muted)'}`,
              }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 12, alignItems: 'baseline' }}>
                  <strong style={{ fontSize: 13 }}>{c.name}</strong>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>{fmtInt(c.shipments_better_served)} ships better served</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: c.estimated_annual_savings_usd > 1000 ? 'var(--green)' : 'var(--muted)' }}>
                    {fmtUSD(c.estimated_annual_savings_usd)}/yr
                  </span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
                  {c.savings_pct.toFixed(1)}% of current annualized shipping cost
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10, fontSize: 10, color: 'var(--muted)', fontStyle: 'italic' }}>{roi.method_note}</div>
        </div>
      )}

      {/* CX CORRELATION */}
      {tab === 'cx' && cx && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8 }}>
            <Tile label="WISMO tickets" value={fmtInt(cx.totals.wismo_tickets)} accent={cx.totals.wismo_ratio_pct > 15 ? 'orange' : 'blue'} sub={`${cx.totals.wismo_ratio_pct}% of all CX`} />
            <Tile label="Matched to ship" value={fmtInt(cx.totals.wismo_matched_to_shipment)} accent="green" sub={cx.totals.wismo_tickets > 0 ? `${(cx.totals.wismo_matched_to_shipment / cx.totals.wismo_tickets * 100).toFixed(0)}% match rate` : ''} />
            <Tile label="Unshipped at ticket" value={fmtInt(cx.totals.wismo_unshipped_at_ticket_time)} accent={cx.totals.wismo_unshipped_at_ticket_time > 0 ? 'red' : 'neutral'} sub="real fulfillment delay" />
            <Tile label="Median ship→ask" value={cx.totals.median_ship_to_wismo_hours != null ? `${cx.totals.median_ship_to_wismo_hours.toFixed(0)}h` : '—'} accent="neutral" sub="time from label to ticket" />
          </div>
          {cx.totals.late_tracking_signal_count > 0 && (
            <div style={{ marginTop: 10, padding: 10, background: 'rgba(243,156,18,0.10)', borderLeft: '3px solid var(--orange)', borderRadius: 4, fontSize: 12 }}>
              ⚠ <strong>{cx.totals.late_tracking_signal_count}</strong> WISMO tickets came in &gt;7 days after the order shipped — likely tracking-email never seen by customer. Investigate notification UX.
            </div>
          )}
          {cx.by_carrier.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>WISMO by carrier (which carriers generate the most "where is it?" tickets)</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {cx.by_carrier.map(c => (
                  <div key={c.carrier} style={{ padding: '4px 10px', background: 'var(--panel-2)', borderRadius: 4, fontSize: 12 }}>
                    <strong>{CARRIER_LABEL[c.carrier] || c.carrier}</strong>: {c.wismo_tickets}
                  </div>
                ))}
              </div>
            </div>
          )}
          {cx.wismo_tickets.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                WISMO tickets ({cx.wismo_tickets.length})
              </summary>
              <div style={{ maxHeight: 320, overflowY: 'auto', marginTop: 6 }}>
                {cx.wismo_tickets.map(t => (
                  <div key={t.ticket_id} style={{ padding: '6px 8px', borderTop: '1px solid rgba(255,255,255,0.04)', fontSize: 11 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 8, alignItems: 'baseline' }}>
                      <span style={{ fontWeight: 600 }}>{t.subject || `#${t.ticket_id}`}</span>
                      <span style={{ color: 'var(--muted)' }}>{t.created_at?.slice(0, 10)}</span>
                      <span style={{ color: t.shipped ? 'var(--green)' : 'var(--red)', fontSize: 10, fontWeight: 700, letterSpacing: 0.4 }}>
                        {t.shipped ? '✓ shipped' : t.extracted_order_number ? '✗ unshipped' : '— no order #'}
                      </span>
                    </div>
                    {t.matched_shipment && (
                      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>
                        order #{t.extracted_order_number} · {t.matched_shipment.carrier ?? 'unknown'} · ship_date {t.matched_shipment.ship_date ?? '—'} · ${t.matched_shipment.shipment_cost.toFixed(2)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  )
}


function Tile({ label, value, accent, sub }: { label: string; value: string; accent: 'green' | 'red' | 'orange' | 'blue' | 'neutral'; sub?: string }) {
  const tone = {
    green:   { fg: 'var(--green)',  bd: 'var(--green)',  bg: 'rgba(46,204,113,0.07)' },
    red:     { fg: 'var(--red)',    bd: 'var(--red)',    bg: 'rgba(231,76,60,0.10)' },
    orange:  { fg: 'var(--orange)', bd: 'var(--orange)', bg: 'rgba(243,156,18,0.08)' },
    blue:    { fg: 'var(--blue)',   bd: 'var(--blue)',   bg: 'rgba(110,168,255,0.06)' },
    neutral: { fg: 'var(--text)',   bd: 'var(--muted)',  bg: 'var(--panel-2)' },
  }[accent]
  return (
    <div style={{ padding: 10, background: tone.bg, borderLeft: `3px solid ${tone.bd}`, borderRadius: 4 }}>
      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: tone.fg, lineHeight: 1.1, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}
