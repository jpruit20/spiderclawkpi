import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { FleetLifetimeResponse, FleetSizeResponse, FleetFamilyBreakdown } from '../lib/api'
import { fmtInt } from '../lib/format'

/**
 * Total lifetime unique devices, broken out by product family and by
 * data source. Three sources:
 *
 *   * AWS-registered — every device that has ever phoned home via
 *     telemetry. Authoritative for "how many units are out there
 *     provisioned right now." This is the live number.
 *   * Shopify units — unit count from Shopify line_items. Partially
 *     populated because `line_items` capture landed 2026-04-21;
 *     historical orders don't carry line-item data yet.
 *   * Amazon units — pending the SP-API Sales & Traffic Reports
 *     connector. Listings are synced; unit-level sales are not.
 *
 * The three numbers WILL disagree. A buyer who never provisions
 * skews Shopify up vs AWS; one physical grill re-provisioned under
 * multiple user accounts skews AWS up vs Shopify. Don't hide the gap.
 *
 * Also surfaces the "active 24mo" count from /api/fleet/size so the
 * split between "registered lifetime" and "still cooking" is obvious.
 */

const FAMILIES: Array<keyof FleetFamilyBreakdown> = [
  'Weber Kettle',
  'Huntsman',
  'Giant Huntsman',
  'Unknown',
]

const FAMILY_COLORS: Record<string, string> = {
  'Weber Kettle': '#6ea8ff',
  'Huntsman': '#ffb257',
  'Giant Huntsman': '#ec4899',
  'Unknown': '#9fb0d4',
}

type SourceTab = 'aws' | 'shopify' | 'amazon'

export function LifetimeFleetCard() {
  const [size, setSize] = useState<FleetSizeResponse | null>(null)
  const [lifetime, setLifetime] = useState<FleetLifetimeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<SourceTab>('aws')

  useEffect(() => {
    const ctl = new AbortController()
    Promise.all([api.fleetSize(ctl.signal), api.fleetLifetime(ctl.signal)])
      .then(([s, l]) => { setSize(s); setLifetime(l) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctl.abort()
  }, [])

  if (error) return <section className="card"><div className="state-message" style={{ color: 'var(--red)' }}>Fleet composition error: {error}</div></section>
  if (!size || !lifetime) return <section className="card"><div className="state-message">Loading fleet composition…</div></section>

  const sourceData = tab === 'aws'
    ? { total: lifetime.aws_registered.total, by_family: lifetime.aws_registered.by_family, note: lifetime.aws_registered.note, unavailable: false }
    : tab === 'shopify'
      ? { total: lifetime.shopify_units.total, by_family: lifetime.shopify_units.by_family, note: lifetime.shopify_units.note, unavailable: false }
      : { total: lifetime.amazon_units.total, by_family: lifetime.amazon_units.by_family, note: lifetime.amazon_units.note, unavailable: lifetime.amazon_units.total === null }

  const sourceBy = sourceData.by_family || { 'Weber Kettle': 0, 'Huntsman': 0, 'Giant Huntsman': 0, 'Unknown': 0 }
  const activeBy = size.active_24mo.by_family

  return (
    <section className="card">
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>Fleet composition</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Active fleet (24mo rolling) = canonical dashboard number. Lifetime totals reconcile three data sources — they will not agree.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4, background: 'var(--panel-2)', borderRadius: 8, padding: 2 }}>
          {(['aws', 'shopify', 'amazon'] as SourceTab[]).map(t => (
            <button
              key={t}
              className={`range-button${tab === t ? ' active' : ''}`}
              onClick={() => setTab(t)}
              style={{ fontSize: 11 }}
            >
              {t === 'aws' ? 'AWS registered' : t === 'shopify' ? 'Shopify units' : 'Amazon units'}
            </button>
          ))}
        </div>
      </div>

      {/* Headline: active 24mo vs lifetime */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 12,
        marginBottom: 14,
      }}>
        <div style={{
          padding: 14,
          border: '1px solid var(--border)',
          borderRadius: 10,
          background: 'rgba(57, 208, 143, 0.06)',
          borderLeft: '3px solid var(--green)',
        }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Active fleet · 24mo rolling
          </div>
          <div style={{ fontSize: 30, fontWeight: 700, lineHeight: 1 }}>
            {fmtInt(size.active_24mo.total)}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
            Canonical dashboard denominator (replaces old 13k placeholder).
          </div>
        </div>
        <div style={{
          padding: 14,
          border: '1px solid var(--border)',
          borderRadius: 10,
          background: sourceData.unavailable ? 'rgba(255,255,255,0.02)' : 'rgba(110, 168, 255, 0.05)',
          borderLeft: `3px solid ${sourceData.unavailable ? 'var(--muted)' : 'var(--blue)'}`,
        }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Lifetime · {tab === 'aws' ? 'AWS registered' : tab === 'shopify' ? 'Shopify units' : 'Amazon units'}
          </div>
          <div style={{
            fontSize: 30, fontWeight: 700, lineHeight: 1,
            color: sourceData.unavailable ? 'var(--muted)' : 'var(--text)',
          }}>
            {sourceData.unavailable ? '—' : fmtInt(sourceData.total ?? 0)}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
            {sourceData.note}
          </div>
          {tab === 'shopify' && !sourceData.unavailable && lifetime.shopify_units.coverage_orders_total > 0 ? (
            <div style={{ fontSize: 10, color: 'var(--orange)', marginTop: 4 }}>
              Coverage: {lifetime.shopify_units.coverage_orders_with_line_items}/{lifetime.shopify_units.coverage_orders_total} orders carry line-item data
              ({Math.round(100 * lifetime.shopify_units.coverage_orders_with_line_items / lifetime.shopify_units.coverage_orders_total)}%).
            </div>
          ) : null}
        </div>
      </div>

      {/* Per-family breakdown */}
      <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
        By product family — Active 24mo vs Lifetime ({tab === 'aws' ? 'AWS registered' : tab === 'shopify' ? 'Shopify units' : 'Amazon units'})
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse', minWidth: 500 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
              <th style={{ padding: '6px 8px' }}>Family</th>
              <th style={{ textAlign: 'right' }}>Active 24mo</th>
              <th style={{ textAlign: 'right' }}>Lifetime ({tab})</th>
              <th style={{ textAlign: 'right' }}>Dormant (ever-active − active)</th>
            </tr>
          </thead>
          <tbody>
            {FAMILIES
              // Giant Huntsman is currently consolidated into Huntsman on the
              // backend (see product_taxonomy.CONSOLIDATE_GIANT_HUNTSMAN) —
              // drop any family row that's empty across BOTH active and the
              // current source so we don't render a stale zero line. Self-heals
              // when Agustín's app integration lands and the flag flips.
              .filter(fam => {
                const act = activeBy[fam] ?? 0
                const life = sourceData.unavailable ? 0 : (sourceBy[fam] ?? 0)
                const aws = lifetime.aws_registered.by_family[fam] ?? 0
                // Always keep the core three; only hide when truly empty.
                if (fam === 'Weber Kettle' || fam === 'Huntsman' || fam === 'Unknown') return true
                return act + life + aws > 0
              })
              .map(fam => {
              const color = FAMILY_COLORS[fam]
              const active = activeBy[fam] ?? 0
              const lifetimeCount = sourceData.unavailable ? null : (sourceBy[fam] ?? 0)
              const awsLifetime = lifetime.aws_registered.by_family[fam] ?? 0
              const dormant = Math.max(0, awsLifetime - active)
              return (
                <tr key={fam} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px' }}>
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: color, marginRight: 6 }} />
                    {fam}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmtInt(active)}</td>
                  <td style={{ textAlign: 'right' }}>{lifetimeCount == null ? '—' : fmtInt(lifetimeCount)}</td>
                  <td style={{ textAlign: 'right', color: 'var(--muted)' }}>
                    {awsLifetime > 0 ? fmtInt(dormant) : '—'}
                  </td>
                </tr>
              )
            })}
            <tr style={{ borderTop: '1px solid var(--border)', fontWeight: 700 }}>
              <td style={{ padding: '6px 8px' }}>Total</td>
              <td style={{ textAlign: 'right' }}>{fmtInt(size.active_24mo.total)}</td>
              <td style={{ textAlign: 'right' }}>
                {sourceData.unavailable ? '—' : fmtInt(sourceData.total ?? 0)}
              </td>
              <td style={{ textAlign: 'right', color: 'var(--muted)' }}>
                {fmtInt(Math.max(0, lifetime.aws_registered.total - size.active_24mo.total))}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 10, lineHeight: 1.5 }}>
        <strong>Why the sources disagree:</strong> a buyer can purchase a grill and never provision it (Shopify sees the sale, AWS never sees the device);
        conversely an original owner can re-pair the grill with a new user account and AWS registers two separate <code>device_id</code> hashes for one physical unit.
        Dormant = registered lifetime on AWS but no telemetry in the last 24 months — these devices exist but aren't being used.
      </div>
    </section>
  )
}
