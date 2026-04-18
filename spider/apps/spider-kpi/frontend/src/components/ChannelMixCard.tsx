import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { currency, fmtPct } from '../lib/format'
import type { MarketingChannelMixResponse, MarketingChannelRow } from '../lib/types'
import { TruthBadge } from './TruthBadge'

interface ChannelMixCardProps {
  range: { startDate: string; endDate: string }
}

// Fixed palette so channels are visually consistent across range
// changes — re-sort by spend, colors stick to the channel.
const CHANNEL_COLORS: Record<string, string> = {
  facebook_spend: '#1877F2',
  google_spend: '#EA4335',
  tiktok_spend: '#FF0050',
  amazon_ads_spend: '#FF9900',
  pinterest_spend: '#E60023',
  snapchat_spend: '#FFFC00',
  bing_spend: '#008373',
  twitter_spend: '#1DA1F2',
  reddit_spend: '#FF4500',
  linkedin_spend: '#0A66C2',
  smsbump_spend: '#7C3AED',
  omnisend_spend: '#FB923C',
  postscript_spend: '#22C55E',
  taboola_spend: '#0EA5E9',
  outbrain_spend: '#F97316',
  stackadapt_spend: '#14B8A6',
  adroll_spend: '#EAB308',
  impact_spend: '#8B5CF6',
  custom_spend: '#64748B',
}

function deltaClass(d: number | null): string {
  if (d == null) return 'badge-neutral'
  if (d > 5) return 'badge-good'
  if (d < -5) return 'badge-bad'
  return 'badge-neutral'
}

function formatDelta(d: number | null): string {
  if (d == null) return '—'
  const sign = d > 0 ? '+' : ''
  return `${sign}${d.toFixed(1)}%`
}

export function ChannelMixCard({ range }: ChannelMixCardProps) {
  const [data, setData] = useState<MarketingChannelMixResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!range.startDate || !range.endDate) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api.marketingChannelMix({ start: range.startDate, end: range.endDate, compare_prior: true })
      .then(r => { if (!cancelled) setData(r) })
      .catch(err => { if (!cancelled) setError(err?.message || 'failed to load channel mix') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [range.startDate, range.endDate])

  const visible: MarketingChannelRow[] = (data?.channels || []).filter(c => c.spend > 0)
  const totalSpend = data?.totals.ad_spend ?? 0
  const totalRevenue = data?.totals.revenue ?? 0
  const mer = data?.totals.mer ?? null
  const unmapped = data?.totals.unmapped_spend ?? 0

  return (
    <section className="card">
      <div className="venom-panel-head">
        <strong>Channel spend mix</strong>
        <TruthBadge state="canonical" />
        <span className="venom-panel-hint">
          {data?.window ? `${data.window.start} → ${data.window.end} (${data.window.days}d)` : '\u2014'}
        </span>
      </div>

      {loading && <div className="state-message">Loading…</div>}
      {error && <div className="state-message error">{error}</div>}

      {!loading && !error && data && (
        <>
          <div className="venom-breakdown-list" style={{ marginBottom: 8 }}>
            <div className="venom-breakdown-row">
              <span>Total ad spend</span>
              <span className="venom-breakdown-val">{currency(totalSpend)}</span>
            </div>
            <div className="venom-breakdown-row">
              <span>Blended MER (revenue / spend)</span>
              <span className="venom-breakdown-val">{mer != null ? `${mer.toFixed(2)}x` : '\u2014'}</span>
              <span className="badge badge-neutral">{currency(totalRevenue)} rev</span>
            </div>
          </div>

          {/* Stacked horizontal bar — spend mix at a glance */}
          {totalSpend > 0 && (
            <div
              style={{
                display: 'flex',
                height: 24,
                borderRadius: 4,
                overflow: 'hidden',
                marginBottom: 10,
                background: 'rgba(255,255,255,0.04)',
              }}
              aria-label="Channel spend mix"
            >
              {visible.map((ch) => (
                <div
                  key={ch.column}
                  title={`${ch.label}: ${currency(ch.spend)} (${ch.share_pct.toFixed(1)}%)`}
                  style={{
                    width: `${ch.share_pct}%`,
                    background: CHANNEL_COLORS[ch.column] || '#64748B',
                    minWidth: ch.share_pct > 0 ? 2 : 0,
                  }}
                />
              ))}
              {unmapped > 0 && (
                <div
                  title={`Unmapped: ${currency(unmapped)}`}
                  style={{
                    width: `${(unmapped / totalSpend) * 100}%`,
                    background: 'repeating-linear-gradient(45deg, #475569, #475569 4px, #334155 4px, #334155 8px)',
                  }}
                />
              )}
            </div>
          )}

          {/* Per-channel breakdown with delta */}
          <div className="venom-breakdown-list">
            {visible.length === 0 && (
              <div className="state-message">
                No channel-level spend captured for this window yet. Run
                <code style={{ margin: '0 4px' }}>tw_backfill_channel_spends.py</code>
                to re-derive from stored payloads.
              </div>
            )}
            {visible.map((ch) => (
              <div className="venom-breakdown-row" key={ch.column}>
                <span>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 10,
                      height: 10,
                      background: CHANNEL_COLORS[ch.column] || '#64748B',
                      borderRadius: 2,
                      marginRight: 6,
                      verticalAlign: 'middle',
                    }}
                  />
                  {ch.label}
                </span>
                <span className="venom-breakdown-val">{currency(ch.spend)}</span>
                <span className="badge badge-neutral">{fmtPct(ch.share_pct / 100)}</span>
                <span className={`badge ${deltaClass(ch.delta_pct)}`}>{formatDelta(ch.delta_pct)}</span>
              </div>
            ))}
            {unmapped > 0 && (
              <div className="venom-breakdown-row">
                <span style={{ color: 'var(--muted)' }}>Unmapped (blended total minus per-channel sum)</span>
                <span className="venom-breakdown-val">{currency(unmapped)}</span>
                <span className="badge badge-warn">alias missing</span>
              </div>
            )}
          </div>

          <small className="venom-panel-footer">
            Deltas compare to the prior {data.window.days}-day period
            {data.prior_window ? ` (${data.prior_window.start} → ${data.prior_window.end})` : ''}.
            Unmapped spend means TW's blended total is higher than the sum of
            per-channel columns we have mapped — add the alias in
            <code style={{ margin: '0 4px' }}>triplewhale.py · CHANNEL_SPEND_IDS</code>
            to resolve.
          </small>
        </>
      )}
    </section>
  )
}
