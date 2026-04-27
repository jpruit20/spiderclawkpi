import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { FinancialsGrossProfit } from '../lib/api'

/**
 * Marketing-side contribution-margin tile strip.
 *
 * Reads /api/financials/gross-profit so the same canonical numbers
 * (with SharePoint-extracted COGS + ShipStation shipping folded in)
 * flow into the Marketing page. Then surfaces the marketing-relevant
 * read: revenue → gross profit → minus ad spend → contribution margin.
 *
 * Replaces the orphan grossProfitProxy / contributionProxy that were
 * computed off raw revenue without COGS or shipping.
 */
interface Props {
  days?: number
}

function fmtUSD(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (Math.abs(n) >= 10_000) return `$${(n / 1000).toFixed(1)}k`
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  return `${n.toFixed(1)}%`
}

function tone(pct: number | null | undefined): { color: string; label: string } {
  if (pct == null) return { color: 'var(--muted)', label: 'no data' }
  if (pct >= 25) return { color: 'var(--green)', label: 'healthy' }
  if (pct >= 10) return { color: 'var(--orange)', label: 'thin' }
  return { color: 'var(--red)', label: 'underwater' }
}

export function MarketingContributionStrip({ days = 30 }: Props) {
  const [data, setData] = useState<FinancialsGrossProfit | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    api.financialsGrossProfit({ days }, ctl.signal).then(setData).catch(err => {
      if (err.name !== 'AbortError') setError(String(err.message || err))
    })
    return () => ctl.abort()
  }, [days])

  if (error) {
    return (
      <section className="card">
        <div className="state-message" style={{ color: 'var(--red)', fontSize: 12 }}>{error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="state-message" style={{ fontSize: 12 }}>Loading marketing contribution…</div>
      </section>
    )
  }

  const t = data.totals
  const contribTone = tone(t.contribution_margin_pct ?? null)
  const gmTone = tone(t.gross_margin_pct)

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Marketing contribution (last {days}d)</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Net revenue − product COGS − shipping − ad spend. Same canonical figures as Executive / Commercial pages.
          </div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8, marginTop: 10 }}>
        <Tile label="Net revenue" value={fmtUSD(t.revenue_usd)} accent="blue" />
        <Tile label="Gross profit" value={fmtUSD(t.gross_profit_usd)} accent={gmTone.color === 'var(--green)' ? 'green' : gmTone.color === 'var(--orange)' ? 'orange' : 'red'} sub={fmtPct(t.gross_margin_pct) + ' GM'} />
        <Tile label="Ad spend" value={fmtUSD(t.ad_spend_usd ?? 0)} accent="orange" />
        <Tile label="Contribution" value={fmtUSD(t.contribution_margin_usd ?? null)} accent={contribTone.color === 'var(--green)' ? 'green' : contribTone.color === 'var(--orange)' ? 'orange' : 'red'} sub={fmtPct(t.contribution_margin_pct ?? null) + ' margin · ' + contribTone.label} />
      </div>
      <div style={{ marginTop: 8, fontSize: 10, color: 'var(--muted)', lineHeight: 1.5 }}>
        Includes <strong>{fmtUSD(t.applied_cogs_classified_usd ?? 0)}</strong> product COGS (extracted CBOMs) +{' '}
        <strong>{fmtUSD(t.applied_cogs_accessory_estimate_usd ?? 0)}</strong> accessory estimate +{' '}
        <strong>{fmtUSD(t.applied_shipping_usd ?? 0)}</strong> ShipStation carrier cost +{' '}
        <strong>{fmtUSD(t.ad_spend_usd ?? 0)}</strong> ad spend = <strong>{fmtUSD((t.applied_cogs_usd ?? 0) + (t.ad_spend_usd ?? 0))}</strong> total deductions.
      </div>
    </section>
  )
}

function Tile({ label, value, accent, sub }: { label: string; value: string; accent: 'green' | 'red' | 'orange' | 'blue' | 'neutral'; sub?: string }) {
  const c = {
    green:   { fg: 'var(--green)',  bd: 'var(--green)',  bg: 'rgba(46,204,113,0.07)' },
    red:     { fg: 'var(--red)',    bd: 'var(--red)',    bg: 'rgba(231,76,60,0.10)' },
    orange:  { fg: 'var(--orange)', bd: 'var(--orange)', bg: 'rgba(243,156,18,0.08)' },
    blue:    { fg: 'var(--blue)',   bd: 'var(--blue)',   bg: 'rgba(110,168,255,0.06)' },
    neutral: { fg: 'var(--text)',   bd: 'var(--muted)',  bg: 'var(--panel-2)' },
  }[accent]
  return (
    <div style={{ padding: 10, background: c.bg, borderLeft: `3px solid ${c.bd}`, borderRadius: 4 }}>
      <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: c.fg, lineHeight: 1.1, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}
