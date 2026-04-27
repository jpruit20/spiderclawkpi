import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api'
import type { FinancialsGrossProfit } from '../lib/api'

/**
 * Gross profit + gross margin tile, reusable across pages.
 *
 * Reads /api/financials/gross-profit so every page (Executive,
 * Commercial, Marketing, Revenue Engine, Command Center) shows the
 * same number. Per-unit COGS comes from the SharePoint synthesis;
 * unit counts come from Shopify line_items.
 *
 * Props:
 *   days — trailing window (defaults to 30). Pass null for lifetime.
 *   compact — render the tile-only view; otherwise render with the
 *     per-product breakdown bar chart.
 */
interface Props {
  days?: number | null
  compact?: boolean
  title?: string
}

const PRODUCT_COLORS: Record<string, string> = {
  'Huntsman': '#3b82f6',
  'Giant Huntsman': '#8b5cf6',
  'Venom': '#10b981',
  'Webcraft': '#f59e0b',
  'Giant Webcraft': '#ef4444',
}

function fmtUSD(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (Math.abs(n) >= 10_000) return `$${(n / 1000).toFixed(1)}k`
  if (Math.abs(n) >= 1000) return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  return `${n.toFixed(1)}%`
}

function fmtInt(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US')
}

function marginTone(pct: number | null): { color: string; label: string } {
  if (pct == null) return { color: 'var(--muted)', label: 'no data' }
  if (pct >= 40) return { color: 'var(--green)', label: 'healthy' }
  if (pct >= 20) return { color: 'var(--orange)', label: 'thin' }
  return { color: 'var(--red)', label: 'underwater' }
}

export function GrossProfitCard({ days = 30, compact = false, title }: Props) {
  const [data, setData] = useState<FinancialsGrossProfit | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.financialsGrossProfit({ days: days ?? undefined }, ctl.signal)
      .then(setData)
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [days])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>{title ?? 'Gross profit'}</strong></div>
        <div className="state-message" style={{ color: 'var(--red)', fontSize: 12 }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>{title ?? 'Gross profit'}</strong></div>
        <div className="state-message" style={{ fontSize: 12 }}>Loading…</div>
      </section>
    )
  }

  const t = data.totals
  const tone = marginTone(t.gross_margin_pct)
  const windowLabel = days ? `Trailing ${days}d` : 'Lifetime'

  // Per-product chart data (filter out zero-unit products)
  const chartData = data.by_product
    .filter(p => p.units_sold > 0)
    .map(p => ({
      name: p.product,
      gross_profit: p.gross_profit_usd,
      revenue: p.revenue_usd,
      units: p.units_sold,
      margin: p.gross_margin_pct,
      color: PRODUCT_COLORS[p.product] || '#64748b',
    }))

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <strong>{title ?? 'Gross profit'}</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            {windowLabel} · revenue × (1 − COGS/unit). COGS pulled from SharePoint synthesis.
          </div>
        </div>
        <span
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 0.5,
            padding: '3px 7px',
            borderRadius: 3,
            background: tone.color,
            color: '#fff',
            textTransform: 'uppercase',
          }}
        >
          margin {tone.label}
        </span>
      </div>

      {/* Headline tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8, marginTop: 10 }}>
        <div style={{ padding: 10, background: 'var(--panel-2)', borderLeft: `3px solid ${tone.color}`, borderRadius: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>Gross profit</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: tone.color, lineHeight: 1.1, marginTop: 4 }}>{fmtUSD(t.gross_profit_usd)}</div>
        </div>
        <div style={{ padding: 10, background: 'var(--panel-2)', borderLeft: `3px solid ${tone.color}`, borderRadius: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>Gross margin</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: tone.color, lineHeight: 1.1, marginTop: 4 }}>{fmtPct(t.gross_margin_pct)}</div>
        </div>
        <div style={{ padding: 10, background: 'var(--panel-2)', borderLeft: '3px solid var(--blue)', borderRadius: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>Revenue</div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, marginTop: 4 }}>{fmtUSD(t.revenue_usd)}</div>
        </div>
        <div style={{ padding: 10, background: 'var(--panel-2)', borderLeft: '3px solid var(--muted)', borderRadius: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>Units</div>
          <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1.1, marginTop: 4 }}>{fmtInt(t.units_sold)}</div>
        </div>
      </div>

      {/* Per-product bar chart */}
      {!compact && chartData.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600, marginBottom: 4 }}>
            Gross profit by product
          </div>
          <div style={{ height: Math.max(140, chartData.length * 26) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 80, left: 8, bottom: 4 }}>
                <XAxis type="number" tick={{ fontSize: 10, fill: 'var(--muted)' }} tickFormatter={v => fmtUSD(v)} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: 'var(--text)' }} width={120} />
                <Tooltip
                  formatter={(v: number, _: string, p: any) => {
                    const row = p.payload
                    return [`${fmtUSD(v)} · ${fmtInt(row.units)}u · ${fmtPct(row.margin)}`, 'Gross profit']
                  }}
                  contentStyle={{ background: 'var(--panel)', border: '1px solid rgba(255,255,255,0.1)', fontSize: 11 }}
                />
                <Bar dataKey="gross_profit" radius={[0, 4, 4, 0]}>
                  {chartData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Per-product table with COGS source links */}
      {!compact && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Per-product breakdown ({data.by_product.filter(p => p.units_sold > 0).length} active)
          </summary>
          <div style={{ marginTop: 6, fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ color: 'var(--muted)', textAlign: 'left', fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  <th style={{ padding: '4px 6px' }}>Product</th>
                  <th style={{ padding: '4px 6px', textAlign: 'right' }}>Units</th>
                  <th style={{ padding: '4px 6px', textAlign: 'right' }}>Revenue</th>
                  <th style={{ padding: '4px 6px', textAlign: 'right' }}>Unit COGS</th>
                  <th style={{ padding: '4px 6px', textAlign: 'right' }}>GP</th>
                  <th style={{ padding: '4px 6px', textAlign: 'right' }}>Margin</th>
                  <th style={{ padding: '4px 6px' }}>Conf</th>
                </tr>
              </thead>
              <tbody>
                {data.by_product.map(p => (
                  <tr key={p.product} style={{ borderTop: '1px solid rgba(255,255,255,0.04)', opacity: p.units_sold === 0 ? 0.4 : 1 }}>
                    <td style={{ padding: '4px 6px' }}>
                      {p.product}
                      {p.cogs_source_web_url && (
                        <a href={p.cogs_source_web_url} target="_blank" rel="noreferrer" title={p.cogs_source_doc_name ?? 'COGS source'} style={{ marginLeft: 4, color: 'var(--blue)', textDecoration: 'none' }}>📄</a>
                      )}
                    </td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtInt(p.units_sold)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtUSD(p.revenue_usd)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtUSD(p.unit_cogs_usd)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 600 }}>{fmtUSD(p.gross_profit_usd)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{fmtPct(p.gross_margin_pct)}</td>
                    <td style={{ padding: '4px 6px', fontSize: 9, color: 'var(--muted)', textTransform: 'uppercase' }}>{p.cogs_confidence ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {/* Data quality flags */}
      {data.data_quality_flags && data.data_quality_flags.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 11 }}>
          {data.data_quality_flags.map((f, i) => (
            <div key={i} style={{ color: f.severity === 'warn' ? 'var(--orange)' : 'var(--muted)', marginTop: 2 }}>
              ⚠ {f.issue}
            </div>
          ))}
        </div>
      )}

      {/* Methodology footnote — explicit so the number is auditable */}
      <div style={{ marginTop: 10, fontSize: 10, color: 'var(--muted)', lineHeight: 1.6 }}>
        <strong>How this is computed:</strong> net revenue after order + line discounts; cancelled and fully-refunded orders excluded.
        {' '}
        {data.totals.discounts_applied_usd != null && data.totals.discounts_applied_usd > 0 && (
          <>Discounts applied this window: {fmtUSD(data.totals.discounts_applied_usd)}. </>
        )}
        {data.excluded && (data.excluded.cancelled_orders + data.excluded.refunded_orders + data.excluded.partially_refunded_orders) > 0 && (
          <>Excluded: {data.excluded.cancelled_orders} cancelled, {data.excluded.refunded_orders} refunded ({fmtUSD(data.excluded.refunded_revenue_usd)}), {data.excluded.partially_refunded_orders} partially refunded. </>
        )}
        {data.accessory_assumption && data.totals.revenue_unclassified_usd > 0 && (
          <>Accessory revenue ({fmtUSD(data.totals.revenue_unclassified_usd)}) is NOT a core grill SKU and has no extracted CBOM — applying estimated COGS at <strong>{(data.accessory_assumption.ratio * 100).toFixed(0)}%</strong> of retail (={fmtUSD(data.totals.applied_cogs_accessory_estimate_usd ?? 0)}). Per-product margins above are exact; blended margin uses this estimate. </>
        )}
        {data.coverage.orders_total > 0 && (
          <>Coverage: {data.coverage.orders_with_line_items} / {data.coverage.orders_total} orders carry line-item data ({((data.coverage.orders_with_line_items / data.coverage.orders_total) * 100).toFixed(0)}%). </>
        )}
      </div>
    </section>
  )
}
