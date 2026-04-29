import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { ShippingFedexReconciliation } from '../lib/api'

/**
 * FedEx rate cross-check + invoice reconciliation for the Operations page.
 *
 * Three lenses, all on the same window:
 *
 *   1) HEADLINE — total contract savings vs LIST (annualized) and the
 *      ShipStation-vs-ACCOUNT alignment number. Big bold tiles since
 *      this is the "is the FedEx contract paying off, and is anyone
 *      sneaking surcharges past us" view.
 *
 *   2) BY SERVICE — per-FedEx-service breakdown so we know whether
 *      the savings are concentrated on Ground (volume play) or
 *      Express (premium services we use sparingly).
 *
 *   3) TOP OUTLIERS — single-shipment ACCOUNT deltas with the largest
 *      absolute value. These are the "what happened on this label?"
 *      candidates worth sending to ops for investigation.
 *
 * Empty-state behavior: shows a one-line "FedEx reconciliation hasn't
 * collected data yet" with a tip on the daily 07:30 ET sync. Keeps
 * Operations page calm if the cron didn't fire (e.g., the day after
 * a cred rotation).
 */

const WINDOWS: Array<{ label: string; days: number }> = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '180d', days: 180 },
]

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function fmtUsd2(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

/** Tier the alignment health avg-delta with operator-friendly thresholds.
 * Within ±$1: "calibrated" (green). Within ±$3: "minor drift" (yellow).
 * Beyond ±$3: "investigate" (orange). These are tuned for the typical
 * ground/home-delivery cost range ($15-25). */
function alignmentTier(avgDeltaUsd: number | null | undefined): 'calibrated' | 'minor' | 'drift' | 'unknown' {
  if (avgDeltaUsd == null) return 'unknown'
  const a = Math.abs(avgDeltaUsd)
  if (a <= 1) return 'calibrated'
  if (a <= 3) return 'minor'
  return 'drift'
}

const TIER_COLORS: Record<ReturnType<typeof alignmentTier>, string> = {
  calibrated: '#39d08f',
  minor: '#ffb257',
  drift: '#ff6d7a',
  unknown: 'var(--muted)',
}

const TIER_LABELS: Record<ReturnType<typeof alignmentTier>, string> = {
  calibrated: 'Calibrated',
  minor: 'Minor drift',
  drift: 'Investigate',
  unknown: 'No data',
}

export function FedexReconciliationCard() {
  const [days, setDays] = useState<number>(30)
  const [data, setData] = useState<ShippingFedexReconciliation | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    setError(null)
    const ctl = new AbortController()
    api.shippingFedexReconciliation(days, 10, ctl.signal)
      .then(setData)
      .catch(err => { if (!ctl.signal.aborted) setError(err instanceof Error ? err.message : String(err)) })
    return () => ctl.abort()
  }, [days])

  const tier = useMemo(() => alignmentTier(data?.alignment_health.avg_delta_usd), [data])

  const empty = data && data.totals.quoted_shipments === 0
  const noData = !data || empty

  return (
    <section className="card" style={{ borderLeft: '3px solid #6ea8ff' }}>
      <div className="venom-panel-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <strong>FedEx rate reconciliation</strong>
          <span className="venom-panel-hint" style={{ marginLeft: 8 }}>
            ShipStation actuals vs FedEx ACCOUNT/LIST quotes
          </span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {WINDOWS.map(w => (
            <button
              key={w.days}
              onClick={() => setDays(w.days)}
              className={`range-button${days === w.days ? ' active' : ''}`}
              style={{ fontSize: 11 }}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="state-message" style={{ color: 'var(--orange)' }}>Error: {error}</div>}

      {noData && !error && (
        <div className="state-message" style={{ fontSize: 13, color: 'var(--muted)' }}>
          {empty
            ? `No FedEx rate quotes in the last ${days}d. The cross-check job runs daily at 07:30 ET — try widening the window or wait for the next sync.`
            : 'Loading…'}
        </div>
      )}

      {data && !empty && (
        <>
          {/* ── Headline tiles ─────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
            <div style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Annualized contract savings</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#39d08f' }}>
                {fmtUsd(data.totals.annualized_savings_vs_list_usd)}
              </div>
              <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                vs FedEx LIST · {fmtUsd(data.totals.in_window_savings_vs_list_usd)} in {days}d
              </div>
            </div>

            <div style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Alignment health</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: TIER_COLORS[tier] }}>
                {TIER_LABELS[tier]}
              </div>
              <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                avg ACCOUNT Δ {fmtUsd2(data.alignment_health.avg_delta_usd)} · σ {fmtUsd2(data.alignment_health.stddev_usd)}
              </div>
            </div>

            <div style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.03)', borderRadius: 6 }}>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>Cross-checked shipments</div>
              <div style={{ fontSize: 22, fontWeight: 700 }}>
                {data.totals.quoted_shipments.toLocaleString()}
              </div>
              <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                {data.totals.account_quotes} ACCOUNT · {data.totals.list_quotes} LIST quotes
              </div>
            </div>
          </div>

          {/* ── Per-service breakdown ─────────────────────────────── */}
          {data.by_service.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                By FedEx service
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>Service</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>n</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }} title="Average per-shipment delta between FedEx ACCOUNT quote and ShipStation's billed cost. Near zero = healthy.">
                        Avg ACCOUNT Δ
                      </th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }} title="Average per-shipment savings vs list price (LIST − ShipStation).">
                        Avg LIST savings
                      </th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>Total LIST savings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_service.map(s => (
                      <tr key={s.service_type} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        <td style={{ padding: '6px 8px', fontFamily: 'monospace', fontSize: 11 }}>{s.service_type}</td>
                        <td style={{ textAlign: 'right', padding: '6px 8px' }}>{s.n}</td>
                        <td style={{ textAlign: 'right', padding: '6px 8px',
                          color: s.avg_account_delta_usd != null && Math.abs(s.avg_account_delta_usd) > 3 ? 'var(--orange)' : undefined
                        }}>
                          {fmtUsd2(s.avg_account_delta_usd)}
                        </td>
                        <td style={{ textAlign: 'right', padding: '6px 8px' }}>{fmtUsd2(s.avg_list_savings_usd)}</td>
                        <td style={{ textAlign: 'right', padding: '6px 8px', fontWeight: 600, color: '#39d08f' }}>
                          {fmtUsd(s.total_list_savings_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Top outliers ─────────────────────────────────────── */}
          {data.top_outliers.length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                Top {data.top_outliers.length} ACCOUNT delta outliers (worth investigating)
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>Tracking #</th>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>Service</th>
                      <th style={{ textAlign: 'left', padding: '4px 8px' }}>State</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>FedEx</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>ShipStation</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_outliers.map(o => (
                      <tr key={o.tracking_number} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        <td style={{ padding: '4px 8px', fontFamily: 'monospace', fontSize: 11 }}>{o.tracking_number}</td>
                        <td style={{ padding: '4px 8px', fontFamily: 'monospace', fontSize: 10, color: 'var(--muted)' }}>{o.service_type}</td>
                        <td style={{ padding: '4px 8px' }}>{o.ship_to_state || '—'}</td>
                        <td style={{ textAlign: 'right', padding: '4px 8px' }}>{fmtUsd2(o.quoted_charge_usd)}</td>
                        <td style={{ textAlign: 'right', padding: '4px 8px' }}>{fmtUsd2(o.shipstation_charge_usd)}</td>
                        <td style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600,
                          color: (o.delta_usd ?? 0) < 0 ? 'var(--orange)' : '#39d08f'
                        }}>
                          {fmtUsd2(o.delta_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Invoice-based truth (FBO ingest) ───────────────────
              When fedex_invoice_charges has data in this window, show
              actual billed amounts side-by-side with the rate-API
              estimate. The Δ between invoice and ShipStation is the
              "ShipStation overstatement" finding — labels priced
              higher than what FedEx actually charged. */}
          {data.invoice && data.invoice.spider_shipments > 0 && (
            <>
              <div style={{ marginTop: 24, marginBottom: 8, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>Actual invoiced cost (FBO)</div>
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                  {data.invoice.spider_shipments.toLocaleString()} Spider shipments · billed truth from FedEx invoice export
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
                <div style={{ padding: '8px 10px', background: 'rgba(57,208,143,0.06)', borderRadius: 6, borderLeft: '2px solid #39d08f' }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>Total invoiced</div>
                  <div style={{ fontSize: 22, fontWeight: 700 }}>{fmtUsd(data.invoice.total_invoiced_usd)}</div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                    avg {fmtUsd2(data.invoice.avg_per_ship_usd)} / shipment
                  </div>
                </div>
                <div style={{ padding: '8px 10px', background: 'rgba(57,208,143,0.06)', borderRadius: 6, borderLeft: '2px solid #39d08f' }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>Annualized savings vs LIST</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: '#39d08f' }}>
                    {fmtUsd(data.invoice.annualized_savings_vs_list_usd)}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                    from invoiced DISCOUNT lines (truth)
                  </div>
                </div>
                <div style={{ padding: '8px 10px', background: 'rgba(255,109,122,0.06)', borderRadius: 6, borderLeft: '2px solid #ff6d7a' }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>ShipStation vs invoice</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: data.invoice.two_way_reconciliation.avg_invoice_minus_ss_usd < 0 ? '#ff6d7a' : '#39d08f' }}>
                    {fmtUsd2(data.invoice.two_way_reconciliation.avg_invoice_minus_ss_usd)}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--muted)' }}>
                    avg per ship · {fmtUsd(data.invoice.two_way_reconciliation.total_invoice_minus_ss_usd)} total<br/>
                    {data.invoice.two_way_reconciliation.matched_shipments.toLocaleString()} shipments matched
                  </div>
                </div>
              </div>

              {/* Component breakdown — base / discount / surcharge / duty */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                  Invoice components ({data.window_days}d window)
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
                  <ComponentTile label="Base freight" amount={data.invoice.components.base_total_usd} />
                  <ComponentTile label="Discount" amount={data.invoice.components.discount_total_usd} negative />
                  <ComponentTile label="Surcharges" amount={data.invoice.components.surcharge_total_usd} />
                  <ComponentTile label="Duty / tax" amount={data.invoice.components.duty_tax_total_usd} dimWhenZero />
                </div>
              </div>

              {/* Top overstatement outliers */}
              {data.invoice.top_overstatement_outliers.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', marginBottom: 6 }}>
                    Top {data.invoice.top_overstatement_outliers.length} biggest ShipStation-vs-invoice gaps
                    <span style={{ fontWeight: 400, marginLeft: 6 }}>
                      (negative Δ = ShipStation overstated)
                    </span>
                  </div>
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.15)', color: 'var(--muted)' }}>
                          <th style={{ textAlign: 'left', padding: '4px 8px' }}>Tracking #</th>
                          <th style={{ textAlign: 'left', padding: '4px 8px' }}>Service</th>
                          <th style={{ textAlign: 'left', padding: '4px 8px' }}>State</th>
                          <th style={{ textAlign: 'left', padding: '4px 8px' }}>Ship date</th>
                          <th style={{ textAlign: 'right', padding: '4px 8px' }}>ShipStation</th>
                          <th style={{ textAlign: 'right', padding: '4px 8px' }}>Invoice</th>
                          <th style={{ textAlign: 'right', padding: '4px 8px' }}>Δ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.invoice.top_overstatement_outliers.map(o => (
                          <tr key={o.tracking_number} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                            <td style={{ padding: '4px 8px', fontFamily: 'monospace', fontSize: 11 }}>{o.tracking_number}</td>
                            <td style={{ padding: '4px 8px', fontFamily: 'monospace', fontSize: 10, color: 'var(--muted)' }}>{o.service_type || '—'}</td>
                            <td style={{ padding: '4px 8px' }}>{o.ship_to_state || '—'}</td>
                            <td style={{ padding: '4px 8px', color: 'var(--muted)', fontSize: 10 }}>{o.ship_date || '—'}</td>
                            <td style={{ textAlign: 'right', padding: '4px 8px' }}>{fmtUsd2(o.shipstation_cost_usd)}</td>
                            <td style={{ textAlign: 'right', padding: '4px 8px' }}>{fmtUsd2(o.invoice_cost_usd)}</td>
                            <td style={{ textAlign: 'right', padding: '4px 8px', fontWeight: 600,
                              color: o.delta_usd < 0 ? '#ff6d7a' : '#39d08f'
                            }}>
                              {fmtUsd2(o.delta_usd)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}

          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 12, lineHeight: 1.5 }}>
            {data.method_note}
          </div>
        </>
      )}
    </section>
  )
}

function ComponentTile({ label, amount, negative, dimWhenZero }: {
  label: string
  amount: number
  negative?: boolean
  dimWhenZero?: boolean
}) {
  const muted = dimWhenZero && (amount === 0 || Math.abs(amount) < 0.01)
  return (
    <div style={{
      padding: '6px 10px',
      background: 'rgba(255,255,255,0.02)',
      borderRadius: 4,
      opacity: muted ? 0.4 : 1,
    }}>
      <div style={{ fontSize: 10, color: 'var(--muted)' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: negative ? '#39d08f' : undefined }}>
        {fmtUsd(amount)}
      </div>
    </div>
  )
}
