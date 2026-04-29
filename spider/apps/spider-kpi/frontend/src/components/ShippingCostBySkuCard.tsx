import { useEffect, useMemo, useState } from 'react'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts'
import { api } from '../lib/api'
import type { ShippingCostBySku } from '../lib/api'

/**
 * Shipping cost drill-down: per-SKU spend + per-SKU carrier mix +
 * over-time trend by carrier. Joseph asked for this so Operations can
 * answer "is this SKU still profitable to ship?" and "which carrier
 * is eating the bundle costs on Huntsman accessories?"
 *
 * Three views toggled via header chips:
 *   • by-sku  — top SKUs by spend, with click-to-expand carrier rows
 *   • by-carrier — full carrier mix (all carriers, no top-N truncation)
 *   • trend — per-carrier weekly cost stack, the "is this getting more
 *             expensive over time?" view
 *
 * Window control: 30d / 90d / 180d / 365d.
 *
 * NOTE on Giant Huntsman: this card only shows what shipped through
 * ShipStation (parcel carriers). Giant Huntsman LTL freight is booked
 * outside ShipStation and isn't in this dataset — once that integration
 * lands, an "LTL freight" carrier slice will appear here automatically.
 */

const CARRIER_LABELS: Record<string, string> = {
  fedex: 'FedEx',
  fedex_walleted: 'FedEx (3PL)',
  ups: 'UPS',
  ups_walleted: 'UPS (3PL)',
  stamps_com: 'USPS (Stamps.com)',
  usps: 'USPS',
}

function carrierLabel(code: string): string {
  return CARRIER_LABELS[code] ?? code.replace(/_/g, ' ')
}

const CARRIER_COLORS: Record<string, string> = {
  fedex: '#5b21b6',
  fedex_walleted: '#7c3aed',
  ups: '#92400e',
  ups_walleted: '#b45309',
  stamps_com: '#0e7490',
  usps: '#0e7490',
}

function carrierColor(code: string, fallbackIdx: number): string {
  if (CARRIER_COLORS[code]) return CARRIER_COLORS[code]
  const palette = ['#6ea8ff', '#39d08f', '#ff6d7a', '#ffb257', '#b88bff', '#4ade80', '#f59e0b']
  return palette[fallbackIdx % palette.length]
}

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function fmtCurrency2(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

type View = 'by_sku' | 'by_carrier' | 'trend'
type Window = 30 | 90 | 180 | 365

export function ShippingCostBySkuCard() {
  const [data, setData] = useState<ShippingCostBySku | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('by_sku')
  const [days, setDays] = useState<Window>(90)
  const [bucket, setBucket] = useState<'week' | 'day' | 'month'>('week')
  const [expandedSku, setExpandedSku] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    const ctl = new AbortController()
    api.shippingCostBySku(days, bucket, 25, ctl.signal)
      .then(setData)
      .catch(err => { if (!ctl.signal.aborted) setError(err instanceof Error ? err.message : String(err)) })
    return () => ctl.abort()
  }, [days, bucket])

  // Trend chart data: pivot the per-bucket-per-carrier rows into one row
  // per bucket with a column per carrier, so Recharts can stack them.
  const trendChartData = useMemo(() => {
    if (!data) return [] as Array<Record<string, string | number>>
    const carriers = data.by_carrier.map(c => c.carrier_code)
    const buckets = new Map<string, Record<string, string | number>>()
    for (const t of data.trend) {
      const row = buckets.get(t.bucket) ?? { bucket: t.bucket }
      row[t.carrier_code] = (row[t.carrier_code] as number || 0) + t.attributed_cost_usd
      buckets.set(t.bucket, row)
    }
    // Ensure every row has every carrier key (Recharts stacks need this).
    const rows = Array.from(buckets.values()).sort((a, b) => String(a.bucket).localeCompare(String(b.bucket)))
    for (const r of rows) {
      for (const c of carriers) if (r[c] == null) r[c] = 0
    }
    return rows
  }, [data])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Shipping cost by SKU</strong></div>
        <div className="state-message error">{error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Shipping cost by SKU</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  const t = data.totals
  const carriers = data.by_carrier.map(c => c.carrier_code)

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ flexWrap: 'wrap', gap: 8 }}>
        <strong>Shipping cost by SKU</strong>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {([30, 90, 180, 365] as Window[]).map(d => (
            <button key={d} className={`range-button${days === d ? ' active' : ''}`} onClick={() => setDays(d)} style={{ fontSize: 11 }}>{d}d</button>
          ))}
          <span style={{ width: 8 }} />
          <button className={`range-button${view === 'by_sku' ? ' active' : ''}`} onClick={() => setView('by_sku')} style={{ fontSize: 11 }}>By SKU</button>
          <button className={`range-button${view === 'by_carrier' ? ' active' : ''}`} onClick={() => setView('by_carrier')} style={{ fontSize: 11 }}>By carrier</button>
          <button className={`range-button${view === 'trend' ? ' active' : ''}`} onClick={() => setView('trend')} style={{ fontSize: 11 }}>Over time</button>
          {view === 'trend' ? (
            <>
              <span style={{ width: 8 }} />
              <button className={`range-button${bucket === 'day' ? ' active' : ''}`} onClick={() => setBucket('day')} style={{ fontSize: 11 }}>day</button>
              <button className={`range-button${bucket === 'week' ? ' active' : ''}`} onClick={() => setBucket('week')} style={{ fontSize: 11 }}>week</button>
              <button className={`range-button${bucket === 'month' ? ' active' : ''}`} onClick={() => setBucket('month')} style={{ fontSize: 11 }}>month</button>
            </>
          ) : null}
        </div>
      </div>

      {/* Headline KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Total spend</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--orange)' }}>{fmtCurrency(t.total_shipping_cost_usd)}</div>
          <div style={{ fontSize: 10, color: 'var(--muted)' }}>{days}-day window</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Shipments</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{t.shipments.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>Units shipped</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{t.shipped_units.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>SKUs · carriers</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{t.skus_seen} <span style={{ fontSize: 13, color: 'var(--muted)' }}>· {t.carriers_seen}</span></div>
        </div>
      </div>

      {view === 'by_sku' ? (
        data.by_sku.length === 0 ? <div className="state-message">No paid shipments matched in this window.</div> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 720 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>SKU</th>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>Title</th>
                  <th style={{ textAlign: 'right', padding: '6px 8px' }}>Units</th>
                  <th style={{ textAlign: 'right', padding: '6px 8px' }}>Shipments</th>
                  <th style={{ textAlign: 'right', padding: '6px 8px' }}>Spend</th>
                  <th style={{ textAlign: 'right', padding: '6px 8px' }}>Avg / unit</th>
                </tr>
              </thead>
              <tbody>
                {data.by_sku.map(s => {
                  const isOpen = expandedSku === s.sku
                  return (
                    <>
                      <tr
                        key={s.sku}
                        style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', cursor: 'pointer' }}
                        onClick={() => setExpandedSku(isOpen ? null : s.sku)}
                      >
                        <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 12 }}>
                          <span style={{ marginRight: 4, color: 'var(--muted)' }}>{isOpen ? '▾' : '▸'}</span>
                          {s.sku}
                        </td>
                        <td style={{ padding: '6px 8px', maxWidth: 260, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.title || '—'}</td>
                        <td style={{ textAlign: 'right', padding: '6px 8px' }}>{s.units.toLocaleString()}</td>
                        <td style={{ textAlign: 'right', padding: '6px 8px' }}>{s.shipments.toLocaleString()}</td>
                        <td style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 600, color: 'var(--orange)' }}>{fmtCurrency(s.attributed_cost_usd)}</td>
                        <td style={{ textAlign: 'right', padding: '6px 8px' }}>{fmtCurrency2(s.avg_cost_per_unit_usd)}</td>
                      </tr>
                      {isOpen ? (
                        <tr key={`${s.sku}-detail`}>
                          <td colSpan={6} style={{ padding: '4px 8px 12px 28px', background: 'rgba(255,255,255,0.02)' }}>
                            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>Carrier mix for {s.sku}</div>
                            <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                              <thead>
                                <tr style={{ color: 'var(--muted)' }}>
                                  <th style={{ textAlign: 'left', padding: '4px 8px' }}>Carrier</th>
                                  <th style={{ textAlign: 'left', padding: '4px 8px' }}>Service</th>
                                  <th style={{ textAlign: 'right', padding: '4px 8px' }}>Units</th>
                                  <th style={{ textAlign: 'right', padding: '4px 8px' }}>Shipments</th>
                                  <th style={{ textAlign: 'right', padding: '4px 8px' }}>Spend</th>
                                </tr>
                              </thead>
                              <tbody>
                                {s.carriers.map((c, i) => (
                                  <tr key={i}>
                                    <td style={{ padding: '4px 8px' }}>{carrierLabel(c.carrier_code)}</td>
                                    <td style={{ padding: '4px 8px', color: 'var(--muted)', fontSize: 10 }}>{c.service_code || '—'}</td>
                                    <td style={{ textAlign: 'right', padding: '4px 8px' }}>{c.units}</td>
                                    <td style={{ textAlign: 'right', padding: '4px 8px' }}>{c.shipments}</td>
                                    <td style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600 }}>{fmtCurrency2(c.attributed_cost_usd)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      ) : null}
                    </>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      ) : view === 'by_carrier' ? (
        data.by_carrier.length === 0 ? <div className="state-message">No carriers seen in this window.</div> : (
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px' }}>Carrier</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Shipments</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Spend</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Share</th>
                <th style={{ textAlign: 'left', padding: '6px 8px' }}>Services seen</th>
              </tr>
            </thead>
            <tbody>
              {data.by_carrier.map(c => {
                const share = t.total_shipping_cost_usd > 0 ? (c.attributed_cost_usd / t.total_shipping_cost_usd) * 100 : 0
                return (
                  <tr key={c.carrier_code} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 500 }}>{carrierLabel(c.carrier_code)}</td>
                    <td style={{ textAlign: 'right', padding: '6px 8px' }}>{c.shipments.toLocaleString()}</td>
                    <td style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 600, color: 'var(--orange)' }}>{fmtCurrency(c.attributed_cost_usd)}</td>
                    <td style={{ textAlign: 'right', padding: '6px 8px' }}>{share.toFixed(1)}%</td>
                    <td style={{ padding: '6px 8px', fontSize: 10, color: 'var(--muted)', maxWidth: 320 }}>
                      {c.service_codes.slice(0, 4).join(' · ')}{c.service_codes.length > 4 ? ` · +${c.service_codes.length - 4}` : ''}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )
      ) : (
        trendChartData.length === 0 ? <div className="state-message">No trend data in this window.</div> : (
          <div className="chart-wrap-short">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={trendChartData} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="bucket" stroke="#9fb0d4" tick={{ fontSize: 10 }} />
                <YAxis stroke="#9fb0d4" tick={{ fontSize: 10 }} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)' }}
                  formatter={(v: number, name: string) => [fmtCurrency(v), carrierLabel(name)]}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} formatter={(value: string) => carrierLabel(value)} />
                {carriers.map((c, i) => (
                  <Bar key={c} dataKey={c} stackId="cost" fill={carrierColor(c, i)} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )
      )}

      <small style={{ color: 'var(--muted)', fontSize: 11, marginTop: 10, display: 'block', lineHeight: 1.5 }}>
        {data.method_note}
        {' '}<strong style={{ color: 'var(--text)' }}>LTL freight</strong> (Giant Huntsman full-grill shipments)
        is booked outside ShipStation and isn't in this dataset — those will appear once the LTL feed is wired in.
      </small>
    </section>
  )
}
