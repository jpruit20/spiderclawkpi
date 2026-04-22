import { useEffect, useState } from 'react'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { ApiError, api } from '../lib/api'
import type { OrderAgingResponse } from '../lib/api'
import { currency, fmtInt, formatFreshness } from '../lib/format'
import { useAuth } from './AuthGate'

/**
 * Order aging report (Shopify) — how many currently-unfulfilled
 * orders sit in each age bucket, with a daily trend.
 *
 * Two variants:
 *   - variant="full"    (Operations): headline + full bucket table +
 *                        stacked-area trend chart + oldest-order list
 *                        + "refresh unfulfilled sync" button (owner).
 *   - variant="compact" (CX): single-line headline with per-bucket
 *                        chips, no chart, no admin actions. Sits next
 *                        to WISMO so the team sees whether fulfillment
 *                        delay is correlating with ticket volume.
 */

const BUCKET_COLORS: Record<string, string> = {
  '0-1d': '#39d08f',
  '1-3d': '#6ea8ff',
  '3-7d': '#ffb257',
  '7d+':  '#ff6d7a',
}

const BUCKET_STATE: Record<string, 'good' | 'warn' | 'bad' | 'neutral'> = {
  '0-1d': 'good',
  '1-3d': 'neutral',
  '3-7d': 'warn',
  '7d+':  'bad',
}

const OWNER_EMAIL = 'joseph@spidergrills.com'

export type OrderAgingVariant = 'full' | 'compact'

export function OrderAgingCard({
  variant = 'full',
  trendDays = 14,
  subtitle,
}: {
  variant?: OrderAgingVariant
  trendDays?: number
  subtitle?: string
}) {
  const [data, setData] = useState<OrderAgingResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)
  const { user } = useAuth()
  const isOwner = (user?.email ?? '').toLowerCase() === OWNER_EMAIL

  const load = () => {
    const ctl = new AbortController()
    setLoading(true)
    api.shopifyOrderAging(trendDays, ctl.signal)
      .then(r => { setData(r); setError(null) })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
      .finally(() => setLoading(false))
    return ctl
  }

  useEffect(() => {
    const ctl = load()
    return () => ctl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trendDays])

  const handleSync = async () => {
    if (!confirm('Pull every currently-unfulfilled order from Shopify? This re-fetches orders that haven\'t updated in a while.')) return
    setSyncing(true)
    setSyncMsg('Pulling unfulfilled orders from Shopify…')
    try {
      const r = await api.shopifySyncUnfulfilled()
      if (r.ok) {
        setSyncMsg(`✓ Pulled ${r.records_processed} unfulfilled orders · reloading…`)
        load()
        setTimeout(() => setSyncMsg(null), 4000)
      } else {
        setSyncMsg('✗ Sync failed — check backend logs')
      }
    } catch (e) {
      setSyncMsg(`✗ ${e instanceof ApiError ? e.message : String(e)}`)
    } finally {
      setSyncing(false)
    }
  }

  if (loading && !data) {
    return (
      <section className="card">
        <div className="state-message">Loading order aging…</div>
      </section>
    )
  }
  if (error && !data) {
    return (
      <section className="card">
        <div className="state-message" style={{ color: 'var(--red)' }}>
          Order aging error: {error}
        </div>
      </section>
    )
  }
  if (!data) return null

  const { current, trend } = data
  const worstBucketCount = Math.max(...current.buckets.map(b => b.count))
  const hasStale = (current.buckets.find(b => b.label === '7d+')?.count ?? 0) > 0

  /* ─── compact (CX embed) ──────────────────────────────────────────── */

  if (variant === 'compact') {
    return (
      <section
        className="card"
        style={{
          borderLeft: `3px solid ${hasStale ? 'var(--red)' : 'var(--blue)'}`,
          padding: '12px 14px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 1, fontWeight: 600 }}>
              Order fulfillment aging · FYI for WISMO context
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 2 }}>
              {fmtInt(current.total_unfulfilled)} unfulfilled
              <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 6 }}>
                · {currency(current.total_unfulfilled_value_usd)} open
              </span>
            </div>
            {subtitle ? (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>{subtitle}</div>
            ) : null}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {current.buckets.map(b => (
              <span
                key={b.label}
                style={{
                  padding: '3px 8px',
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 500,
                  background: b.count > 0 ? `${BUCKET_COLORS[b.label]}22` : 'rgba(255,255,255,0.03)',
                  color: b.count > 0 ? BUCKET_COLORS[b.label] : 'var(--muted)',
                  border: `1px solid ${b.count > 0 ? BUCKET_COLORS[b.label] : 'var(--border)'}`,
                }}
                title={`${b.label}: ${b.count} orders · oldest ${b.oldest_order_days.toFixed(1)}d · ${currency(b.total_value_usd)}`}
              >
                {b.label}: {b.count}
              </span>
            ))}
          </div>
        </div>
      </section>
    )
  }

  /* ─── full (Operations) ──────────────────────────────────────────── */

  const stackedData = trend.days.map((day, i) => {
    const row: Record<string, string | number> = { day }
    for (const s of trend.series) {
      row[s.label] = s.counts[i] ?? 0
    }
    return row
  })

  return (
    <section className="card" style={{ borderLeft: `3px solid ${hasStale ? 'var(--red)' : 'var(--blue)'}` }}>
      <div className="venom-panel-head">
        <div>
          <strong>Order fulfillment aging</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Shopify · currently-unfulfilled orders bucketed by age, with a {trend.days.length}-day trend.
            {current.newest_snapshot_at ? ` Latest snapshot ${formatFreshness(current.newest_snapshot_at)}.` : ''}
          </div>
        </div>
        {isOwner ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {syncMsg ? <span style={{ fontSize: 11, color: 'var(--muted)' }}>{syncMsg}</span> : null}
            <button className="range-button" onClick={handleSync} disabled={syncing}>
              {syncing ? 'Syncing…' : 'Refresh from Shopify'}
            </button>
          </div>
        ) : null}
      </div>

      {/* Headline strip */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
        gap: 10, marginBottom: 14,
      }}>
        <div style={{
          padding: 10, border: '1px solid var(--border)', borderRadius: 8,
          background: 'rgba(0,0,0,0.2)',
        }}>
          <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Unfulfilled total
          </div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>
            {fmtInt(current.total_unfulfilled)}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)' }}>
            {currency(current.total_unfulfilled_value_usd)} open
          </div>
        </div>
        {current.buckets.map(b => {
          const color = BUCKET_COLORS[b.label] || 'var(--muted)'
          return (
            <div
              key={b.label}
              style={{
                padding: 10,
                border: `1px solid ${b.count > 0 ? color : 'var(--border)'}`,
                borderLeft: `3px solid ${color}`,
                borderRadius: 8,
                background: b.count > 0 ? `${color}11` : 'rgba(0,0,0,0.2)',
              }}
            >
              <div style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                {b.label}
              </div>
              <div style={{ fontSize: 22, fontWeight: 700, color: b.count > 0 ? color : 'var(--muted)' }}>
                {fmtInt(b.count)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)' }}>
                {b.count > 0 ? `oldest ${b.oldest_order_days.toFixed(1)}d` : 'clear'}
                {b.total_value_usd > 0 ? ` · ${currency(b.total_value_usd)}` : ''}
              </div>
            </div>
          )
        })}
      </div>

      {/* Trend chart */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
          Daily unfulfilled count, stacked by age bucket (end-of-day state, reconstructed from order snapshots)
        </div>
        <div style={{ height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={stackedData} margin={{ top: 6, right: 20, left: 0, bottom: 20 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 10 }}
                stroke="var(--muted)"
                tickFormatter={(d: string) => d.slice(5)}
              />
              <YAxis tick={{ fontSize: 10 }} stroke="var(--muted)" allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }}
                labelFormatter={(d: string) => `Day ending ${d}`}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {trend.series.map(s => (
                <Area
                  key={s.label}
                  type="monotone"
                  dataKey={s.label}
                  stackId="1"
                  stroke={BUCKET_COLORS[s.label] || 'var(--muted)'}
                  fill={BUCKET_COLORS[s.label] || 'var(--muted)'}
                  fillOpacity={0.7}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Oldest orders preview */}
      {current.oldest_orders.length > 0 ? (
        <div>
          <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>
            5 oldest unfulfilled
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                  <th style={{ padding: '4px 8px' }}>Order</th>
                  <th>Age</th>
                  <th>Bucket</th>
                  <th>Status</th>
                  <th>Value</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {current.oldest_orders.map(o => (
                  <tr key={o.order_id} style={{ borderTop: '1px solid var(--border)' }}>
                    <td style={{ padding: '4px 8px', fontFamily: 'ui-monospace, monospace' }}>
                      #{o.order_id}
                    </td>
                    <td style={{ color: BUCKET_COLORS[o.bucket] }}>
                      {o.age_days.toFixed(1)}d
                    </td>
                    <td>
                      <span
                        className="badge"
                        style={{
                          fontSize: 10,
                          background: `${BUCKET_COLORS[o.bucket]}22`,
                          color: BUCKET_COLORS[o.bucket],
                          border: `1px solid ${BUCKET_COLORS[o.bucket]}`,
                        }}
                      >
                        {o.bucket}
                      </span>
                    </td>
                    <td>{o.fulfillment_status}</td>
                    <td>{currency(o.total_value_usd)}</td>
                    <td>{(o.tags || []).slice(0, 3).join(', ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 10 }}>
        {data.meta.notes}
      </div>
    </section>
  )
}
